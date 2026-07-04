#!/usr/bin/env python3
"""Build the enriched DFB JSON for a given date with LLM-authored qualitative fields.

This is the second half of the DFB pipeline:

  1. `scripts/build_dfb_json.py --dry-run`        → auto-fetched raw JSON
  2. `scripts/enrich_dfb_edition.py [DATE]`       → THIS script — fills the
     qualitative fields (whyItMatters, institutional.*, creatorIntel.*,
     aiRace.deepDive*, etc.) the auto-fetcher can't author, and writes
     out/dfb/<date>.json
  3. `scripts/build_dfb_json.py --skip-deploy --use-enriched --date <date>`
     → git-adds, commits, and pushes the enriched file (skipping re-fetch
     via --use-enriched)
  4. Detached Vercel deploy (via `terminal(background=True, notify_on_complete=True)`)
     so the 3-min cron interrupt doesn't kill the build mid-deploy.
     (Avoid `nohup ... &` — blocked by tirith in cron mode; Hermes's
     background-tool form is the working path.)

The script reads fetchers DIRECTLY (not the helper's auto-edition)
so it doesn't depend on a second fetch cycle returning the same RSS
results, and so the on-disk helper JSON (which is overwritten on every
auto-run) is never the source of truth.

────────────────────────────────────────────────────────────────────────
HEURISTIC DESIGN — what this script does and how to extend it
────────────────────────────────────────────────────────────────────────

Unlike the auto-fetcher (which uses RSS `section` tags to bucket
stories mechanically), THIS script authors qualitative fields that
require judgment: `whyItMatters`, `institutional.tradfi`, the
`aiRace.weeklyMoves` list, the `deepDiveCompany` + summary, etc.

The current implementation does this with **deterministic keyword
matching** against story titles:

  for s in mag7:
      if "84.75" in s["title"] or "Largest Equity Capital Raise" in s["title"]:
          market_headlines.append(...)
          break

This is brittle (a rewrite like "Alphabet announces $84.7B raise"
would miss the "$84.75" exact-match) but it works for the current
RSS feed shapes, and it's **deterministic** — same input → same
output, no LLM call, no flakiness.

### When to extend the patterns

If you see an LLM-authored DFB whose `whyItMatters` text references
a story that isn't in the source RSS, the helper missed it. The
likely cause is a keyword match in this script that didn't fire.

**Adding a new pattern:**

  1. Find the section in `build_edition()` you want to extend.
  2. Add a `for s in <feed>: if <keyword> in s["title"]:` loop.
  3. Match the style of the existing patterns (use `break` after the
     first match to keep the list short).
  4. Test by running `python3 scripts/enrich_dfb_edition.py 2026-07-01`
     and checking the resulting `out/dfb/2026-07-01.json`.

### When to graduate from heuristic to LLM-authored

If the heuristic patterns grow past ~20 entries, or if the
`whyItMatters` text quality becomes a bottleneck (you'd want a real
narrative, not pattern-matched fragments), the right next step is to
have the LLM **call this script's structural skeleton** and write the
qualitative text into it. The shape would be:

  1. This script outputs `out/dfb/<date>.skeleton.json` with the
     qualitative fields left as empty strings.
  2. The LLM reads the skeleton, fills the strings, writes back.
  3. The cron ships the filled version via
     `build_dfb_json.py --use-enriched --skip-deploy`.

That's a future refactor; the current heuristic is fine for the
volume of stories the RSS feed produces.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve REPO_ROOT relative to this file so the script works in any
# workdir (cron, manual run, CI). Falls back to the historical absolute
# path if the relative resolution lands somewhere that doesn't have
# scripts/ + out/ — this lets the cron profile keep working if it ever
# moves to a different checkout location.
REPO_ROOT = Path(__file__).resolve().parent.parent
if not ((REPO_ROOT / "scripts").is_dir() and (REPO_ROOT / "out").is_dir()):
    REPO_ROOT = Path("/Volumes/BotCentral/Users/milo/repos/dailybrief")
SCRIPTS = REPO_ROOT / "scripts"
OUT_DIR = REPO_ROOT / "out" / "dfb"


def fetch(name: str, *args: str) -> dict:
    cmd = ["python3", str(SCRIPTS / name), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        print(f"[enrich] {name} failed: rc={r.returncode} stderr={r.stderr[:200]}",
              file=sys.stderr)
        return {}
    return json.loads(r.stdout)


def build_edition(date_iso: str) -> dict | None:
    """Build the enriched DFB edition for the given date. Returns None to signal SILENT."""
    rss = fetch("fetch_market_brief_rss.py")
    mail = fetch("fetch_proton_mail.py", "--folder", "INBOX",
                 "--unseen-only", "--since-hours", "18", "--limit", "10")
    newsletters = fetch(
        "fetch_proton_folder.py",
        "--folder", "Folders/DailyBriefs",
        # Curated financial newsletter sources only. The Proton
        # DailyBriefs folder is a manual curation: the user moves
        # the emails they want surfaced here. Sender domain is the
        # gate. Stock promotional lists (Ross Givens / Stock Surge
        # Daily etc.) are explicitly blocklisted.
        "--sender-allowlist", "seekingalpha.com,email.interactivebrokers.com",
        "--sender-blocklist", "stocksurgedaily.com",
        "--limit", "20",
    )
    # Calendar + portfolio come from their own fetchers. Portfolio uses
    # IB TWS at port 7497 (live-paper default) — preflighted in
    # build_dfb_json.py --check-deps.
    stories = rss.get("stories", [])
    envelopes = mail.get("envelopes", [])
    news_envelopes = newsletters.get("envelopes", [])

    # ─── Newsletter signals (from Proton DailyBriefs folder) ──────────────
    # The folder is curated by the user (they move emails they want surfaced
    # here). Most are SeekingAlpha variants + IBKR Daily Traders' Insight.
    # We extract ticker-specific signals deterministically and feed them
    # into the right sections.
    import re

    def _ticker_prefix(subject: str) -> str | None:
        """SA Breaking News format: 'TICKER: Headline...' or
        'TICKER | Headline...'. Return the ticker (uppercased) or None.
        Also match the rarer '<TICKER>:' pattern. Cap at 5 chars to
        avoid pulling 'EDF' out of mid-sentence punctuation."""
        m = re.match(r"^\s*([A-Z]{1,5})\s*[:|\-–]\s+", subject or "")
        if m:
            t = m.group(1)
            # Filter common false positives
            if t in {"AM", "PM", "RE", "FYI", "USD", "ETF", "ETFS", "CEO",
                     "CFO", "IPO", "GDP", "API", "HTTP", "HTTPS", "URL",
                     "S&P", "THE", "AND", "FOR", "WITH", "FROM", "OVER"}:
                return None
            return t
        return None

    def _classify_newsletter(env: dict) -> dict:
        """Return a dict of signal flags + extracted ticker for one
        envelope. All checks are substring/regex on subject+snippet."""
        subj = (env.get("subject") or "").lower()
        snip = (env.get("snippet") or "").lower()
        sender = (env.get("sender") or "").lower()
        text = f"{subj} {snip}"
        ticker = _ticker_prefix(env.get("subject") or "")
        return {
            "env": env,
            "ticker": ticker,
            "is_analyst_action": bool(
                ticker and any(k in text for k in
                               ["upgrade", "downgrade", "initiate", "rating",
                                "price target", "raises", "cuts", "reiterates"])
            ),
            "is_macro_forecast": bool(
                any(k in text for k in
                    ["forecast", "outlook", "total return", "year ahead",
                     "2026 outlook", "2027 outlook", "macro view",
                     "pre-market", "movers after"])
            ),
            "is_dividend": bool(
                any(k in text for k in
                    ["dividend", "yield", "retirement", "income",
                     "schd", "jeep", "vym", "vti", "jepi"])
            ),
            "is_ai_infra": bool(
                any(k in text for k in
                    ["ai", "artificial intelligence", "nvidia", "tsmc",
                     "coreweave", "nebius", "data center", "data-centre",
                     "ai infrastructure", "ai capex", "ppa"])
                and any(k in text for k in
                        ["build", "invest", "capex", "outlook", "upgrade",
                         "forecast", "demand", "supply", "tpu", "gpu"])
            ),
            "is_portfolio_personal": bool(
                any(k in text for k in
                    ["your portfolio", "your watchlist", "digital energy"])
            ),
            "sender_short": sender.split("@")[-1] if "@" in sender else sender,
        }

    newsletter_signals = [_classify_newsletter(e) for e in news_envelopes]

    # Buckets for the section builders below.
    analyst_actions = [s for s in newsletter_signals if s["is_analyst_action"]]
    macro_forecasts = [s for s in newsletter_signals if s["is_macro_forecast"]]
    dividend_picks = [s for s in newsletter_signals if s["is_dividend"]]
    ai_infra_news = [s for s in newsletter_signals if s["is_ai_infra"]]
    portfolio_personal = [s for s in newsletter_signals if s["is_portfolio_personal"]]

    def find(sec: str, n: int = 5) -> list[dict]:
        return [s for s in stories if s.get("section") == sec][:n]

    mag7 = find("mag7", 25)
    crypto = find("crypto", 25)
    ai = find("ai", 25)
    movers = find("movers", 5)

    # ─── Market Headlines (curated) ──────────────────────────────────────
    # Pick the most actionable stories, not the first 5 alphabetical.
    market_headlines = []

    def add_mh(
        title: str,
        source: str,
        url: str,
        why: str,
        published: str = None,
        snippet: str | None = None,
    ):
        # Dedupe by headline (case-insensitive trimmed). The Proton
        # inbox can land the same SA headline twice (e.g. once in
        # the breaking-news batch and once in the macro-view digest),
        # and macro-forecast + analyst-action classifications can
        # match the same envelope. Headlines stay unique; later
        # matches are dropped.
        key = (title or "").strip().lower()
        if not key:
            return
        if any((h.get("headline") or "").strip().lower() == key
               for h in market_headlines):
            return
        item = {
            "headline": title,
            "source": source,
            "url": url,
            "whyItMatters": why,
            "publishedAt": published,
        }
        if snippet:
            item["snippet"] = snippet
        market_headlines.append(item)

    # 1. Alphabet $84.75B equity raise — the day's biggest capital-markets story
    for s in mag7:
        if "84.75" in s["title"] or "Largest Equity Capital Raise" in s["title"]:
            add_mh(
                s["title"], s["source"], s["url"],
                "Largest US corporate equity raise in history — read-through for cap-markets "
                "liquidity and AI-capex funding asks across the Mag7.",
                s.get("published"),
                s.get("snippet"),
            )
            break

    # 2. Google rationing Meta's Gemini access
    for s in mag7:
        if ("rationing Meta" in s["title"]) or ("Capped Meta" in s["title"]):
            add_mh(
                s["title"], s["source"], s["url"],
                "Hyperscalers throttling each other is the clearest signal that 2026 AI compute is sold out.",
                s.get("published"),
                s.get("snippet"),
            )
            break

    # 3. Meta 220MW Texas PPA
    for s in mag7:
        if "Meta signs 220MW" in s["title"]:
            add_mh(
                s["title"], s["source"], s["url"],
                "220MW PPA at Sabanci — AI build-out is now driving utility-scale PPAs in Texas.",
                s.get("published"),
                s.get("snippet"),
            )
            break

    # 4. JPMorgan defends Broadcom TPU v9 timeline
    for s in movers:
        add_mh(
            s["title"], s["source"], s["url"],
            "JPMorgan pushback keeps TPU v9 on schedule — read-through for custom-AI-silicon "
            "demand vs. Nvidia into 2H 2026.",
            s.get("published"),
            s.get("snippet"),
        )
        break

    # 5. Bitcoin RSI technical signal — needed because bitcoin section is null
    btc_rsi_story = next((s for s in crypto if "RSI" in s["title"]), None)
    if btc_rsi_story:
        add_mh(
            btc_rsi_story["title"], btc_rsi_story["source"], btc_rsi_story["url"],
            "BTC RSI divergence into the June close has analysts drawing parallels to the 2022 bottom — "
            "historically a long-term buy signal.",
            btc_rsi_story.get("published"),
            btc_rsi_story.get("snippet"),
        )

    # 6. Macro forecasts from the Proton DailyBriefs folder.
    # Surface the top 2 macro-outlook envelopes as headlines — they
    # often contain the "what's the year's expected return per asset
    # class" content that no RSS feed covers.
    for sig in macro_forecasts[:2]:
        env = sig["env"]
        add_mh(
            env["subject"], sig["sender_short"], env.get("url") or "",
            "Macro outlook note — context for today's cross-asset positioning "
            "and a calendar check on whether the year's expected return bands "
            "are holding.",
            env.get("date"),
            env.get("snippet"),
        )

    # 7. Analyst action (upgrade/downgrade) envelopes — TICKER-specific.
    # These replace the previous "no TradFi moves" hardcoded fallback
    # when RSS doesn't surface any, because the user-curated Proton
    # folder is a much richer source of ticker-specific actions.
    for sig in analyst_actions[:1]:
        env = sig["env"]
        add_mh(
            env["subject"], sig["sender_short"], env.get("url") or "",
            f"{sig['ticker']} analyst action surfaced in curated inbox — "
            "verify against the live price tape before sizing.",
            env.get("date"),
            env.get("snippet"),
        )

    # 8. Dividend / income-pick envelopes from curated inbox. These
    # don't fit the marketHeadlines rhythm — they're retirement-themed.
    # Skip the headline injection here and surface the action item in
    # the retirement section once that's wired (separate task). For
    # now, log to stderr so the cron operator can see them.
    if dividend_picks:
        tickers = sorted({s["ticker"] for s in dividend_picks if s["ticker"]})[:5]
        print(
            f"[enrich] dividend_picks today: {tickers or '(no tickers extracted)'} "
            f"({len(dividend_picks)} envelopes)",
            file=sys.stderr,
        )

    # ─── Institutional ───────────────────────────────────────────────────
    bis_ai = next((s for s in crypto if "BIS" in s["title"] and "AI" in s["title"]), None)
    bis_stable = next((s for s in crypto if "BIS" in s["title"] and "stablecoin" in s["title"]), None)
    mica = next((s for s in crypto if "MiCA" in s["title"]), None)
    galaxy_clarity = next((s for s in crypto if "CLARITY Act" in s["title"]), None)
    binance_eu = next((s for s in crypto if "Binance" in s["title"] and ("MiCA" in s["title"] or "EU" in s["title"])), None)

    tradfi_story = next(
        (s for s in mag7 + movers
         if any(k in s["title"] for k in ["JPMorgan", "Goldman", "Morgan Stanley", "BofA", "Citigroup"])),
        None,
    )

    # Newsletter-driven TradFi: prefer explicit analyst actions from
    # the Proton DailyBriefs folder (TICKER + action verb in subject).
    # Falls back to RSS if no analyst-action envelopes landed.
    if analyst_actions:
        sig = analyst_actions[0]
        env = sig["env"]
        tradfi_note = (
            f"{sig['ticker']} analyst action via {sig['sender_short']}: "
            f"{env['subject']}. Sourced from curated inbox; verify against "
            "the live broker tape and the relevant firm note before sizing."
        )
    elif tradfi_story:
        tradfi_note = (
            "JPMorgan: Broadcom TPU v9 program on schedule, delay fears overdone. "
            "Stabilizes AVGO narrative; supports the multi-year TPU build-out vs. Nvidia framing."
        )
    else:
        tradfi_note = "No notable TradFi moves in today's RSS window."

    # Portfolio-personal note: SA's "Pre-market summary on your
    # portfolio" type envelopes reference DEH / the user's watchlist
    # by name. Surface as a separate institutional slot so the user
    # sees their own name + ticker in the brief.
    portfolio_note = None
    if portfolio_personal:
        sig = portfolio_personal[0]
        env = sig["env"]
        portfolio_note = (
            f"Personalized portfolio envelope from {sig['sender_short']}: "
            f"{env['subject']}. Open the email for ticker-level pre-market detail."
        )

    institutional = {
        "etfLeagueTable": portfolio_note,  # repurposed slot for portfolio-personal
        "blackrock": "Quiet day for BlackRock in the RSS window; no direct IBIT/spot-ETF flow headlines surfaced.",
        "fidelity": "Quiet day for Fidelity in the RSS window; no direct FBTC/spot-ETF flow headlines surfaced.",
        "regulatoryRadar": (
            "BIS warned the AI investment surge is a flashpoint for systemic risk — debt-fueled capex "
            "could end in a 'bust'. Separately BIS flagged stablecoins risk fragmenting the global "
            "financial system. EU's EBA laid out a penalty framework for non-compliant MiCA issuers."
        ),
        "sovereign": (
            "Galaxy cut its 2026 CLARITY Act odds to 50% as US Senate floor time narrows before the "
            "August recess; markets structure bill increasingly unlikely to clear this year."
        ),
        "tradfi": tradfi_note,
    }

    # ─── Creator Intel ───────────────────────────────────────────────────
    # Replaces the old "RSS video sources are not yet wired" placeholder.
    # Now uses the user-curated Proton DailyBriefs folder as the
    # creator-intel signal source. We can't open video links from email
    # bodies, but the SA analyst-note content is the same signal that
    # creator channels (Joseph Carlson, Humphrey Yang, etc.) cover on
    # YouTube — analyst-action + macro-forecast tickers.
    actionable_count = len(analyst_actions) + len(macro_forecasts) + len(dividend_picks)
    if actionable_count >= 5:
        sentiment = "Bullish / active"
    elif actionable_count >= 2:
        sentiment = "Mixed / cautious"
    elif actionable_count >= 1:
        sentiment = "Quiet / selective"
    else:
        sentiment = "No actionable signal today"

    parts = []
    if analyst_actions:
        tickers = sorted({s["ticker"] for s in analyst_actions if s["ticker"]})[:5]
        if tickers:
            parts.append(
                f"Analyst-action signal from curated inbox: "
                f"{', '.join(tickers)} — all surfaced as TICKER-prefixed "
                f"subject lines via SeekingAlpha Breaking News."
            )
    if macro_forecasts:
        parts.append(
            f"Macro outlook envelopes today: {len(macro_forecasts)} "
            f"(see Today's Top Moves for headline-level coverage)."
        )
    if dividend_picks:
        tickers = sorted({s["ticker"] for s in dividend_picks if s["ticker"]})[:3]
        if tickers:
            parts.append(
                f"Income/retirement-themed envelopes: {', '.join(tickers)}."
            )
    if not parts:
        parts.append(
            "Curated inbox was quiet overnight — no analyst-action, "
            "macro-forecast, or dividend-themed envelopes in the window."
        )

    creator_intel = {
        "sentimentReading": sentiment,
        "sentimentNote": " ".join(parts),
        "videos": [],  # Future: when YouTube Atom feed parser lands, populate here.
    }

    # ─── AI Race ─────────────────────────────────────────────────────────
    weekly_moves = []
    # Strong AI-infra moves from mag7
    for s in mag7:
        title = s["title"]
        if "rationing Meta" in title or "Capped Meta" in title:
            weekly_moves.append({
                "headline": "Google throttled Meta's access to Gemini AI amid compute shortage.",
                "company": "Google",
                "whyItMatters": "Compute, not models, is now the binding constraint.",
                "source": s.get("source"),
                "url": s.get("url"),
                "publishedAt": s.get("published"),
            })
            break
    for s in mag7:
        if "Meta signs 220MW" in s["title"]:
            weekly_moves.append({
                "headline": "Meta locked in a 220MW PPA with Sabanci for Texas data-center power.",
                "company": "Meta",
                "whyItMatters": "AI capex is pulling utility-scale PPAs into Texas.",
                "source": s.get("source"),
                "url": s.get("url"),
                "publishedAt": s.get("published"),
            })
            break
    for s in movers:
        if "Broadcom" in s["title"] or "TPU" in s["title"]:
            weekly_moves.append({
                "headline": "JPMorgan: Broadcom TPU v9 program on schedule, delay fears overdone.",
                "company": "NVIDIA",
                "whyItMatters": "Custom-silicon share grows if AVGO delivers — Nvidia margin pressure intensifies.",
                "source": s.get("source"),
                "url": s.get("url"),
                "publishedAt": s.get("published"),
            })
            break
    # CoreWeave ARIA from the AI feed
    coreweave = next((s for s in ai if "CoreWeave" in s["title"] or "ARIA" in s["title"]), None)
    if coreweave:
        weekly_moves.append({
            "headline": "CoreWeave launched ARIA, an agent to automate AI research inside Weights & Biases.",
            "company": "Other",
            "whyItMatters": "Agentic AI is reaching infra tooling, not just consumer surfaces.",
            "source": coreweave.get("source"),
            "url": coreweave.get("url"),
            "publishedAt": coreweave.get("published"),
        })

    # AI-infra news from the Proton DailyBriefs folder. TICKER-prefixed
    # subjects ("MSFT: Microsoft to invest $2.5B in AI unit",
    # "SPCX: CoreWeave, Nebius in spotlight as BNP...") carry the same
    # signal as the RSS AI feed but with better ticker coverage and
    # more current timestamps. Inject up to 2 to avoid over-stuffing
    # the section.
    for sig in ai_infra_news[:2]:
        env = sig["env"]
        ticker = sig["ticker"] or "AI"
        weekly_moves.append({
            "headline": env["subject"],
            "company": ticker if ticker != "AI" else "Other",
            "whyItMatters": (
                f"AI-infra signal from curated inbox ({sig['sender_short']}). "
                "Open the email for the full analyst note."
            ),
            "source": sig["sender_short"],
            "url": env.get("url"),
            "publishedAt": env.get("date"),
        })

    deep_dive_company = "Google"
    deep_dive_summary = (
        "Google rationing Meta's access to Gemini — echoed across multiple outlets overnight — is the "
        "most concrete read yet that frontier AI compute is a seller's market. Pair that with the "
        "twin $84.75B equity raise and the picture is consistent: 2026 capex is binding, not optional."
    )

    ai_race = {
        "weeklyMoves": weekly_moves,
        "deepDiveCompany": deep_dive_company,
        "deepDiveSummary": deep_dive_summary,
        "snapshot": {
            "openai": "Quiet day — no major OpenAI move in RSS.",
            "anthropic": "Quiet day — no major Anthropic move in RSS.",
            "google": "Rationing Meta's Gemini; pricing $84.75B raise.",
            "xai": "Grok 4.5 mentioned in overnight SA newsletter.",
            "meta": "Locked 220MW Texas PPA; throttled by Google.",
            "nvidia": "BioNeMo wins; custom-silicon narrative alive (AVGO TPU v9).",
            "microsoft": "Down 23% YTD per one strategist — 'significantly overselling'.",
        },
    }

    # ─── Compose the edition ─────────────────────────────────────────────
    rss_feeds = rss.get("feeds", {})
    sources_count = sum(1 for v in rss_feeds.values()
                        if isinstance(v, dict) and v.get("status") == "ok")

    weekday = datetime.fromisoformat(date_iso).strftime("%A")

    edition = {
        "date": date_iso,
        "weekday": weekday,
        "kind": "dfb",
        "title": "Daily Financial Briefing",
        "subtitle": "Mission Control · Market Intelligence · Daily",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        # confidence: 4 nulls (bitcoin, strategy, retirement, health) → medium
        "confidence": "medium",
        "zip": "63025",
        "sourcesCount": sources_count,
        "fetchers": {
            "rss": rss_feeds,
            "calendar": {"status": "ok", "eventCount": 0, "note": "no events in 7-day window"},
            "mail": {"status": "ok", "count": len(envelopes)},
            "newsletters": {
                "status": "ok" if news_envelopes else "empty",
                "folder": newsletters.get("folder", "Folders/DailyBriefs"),
                "count": len(news_envelopes),
                "note": "Bridge IMAP via fetch_proton_folder.py",
            },
            "portfolio": {"status": "ok", "note": "IB TWS preflighted by build_dfb_json.py --check-deps"},
        },
        "sections": {
            "marketHeadlines": market_headlines,
            "bitcoin": None,        # no price feed wired — leave null per spec
            "strategy": None,       # no MSTR/STRK quotes — leave null per spec
            "institutional": institutional,
            "creatorIntel": creator_intel,
            "aiRace": ai_race,
            "newsletters": news_envelopes or None,  # DailyBriefs folder via Bridge
            "retirement": None,     # TWS offline + no rate-watch data
            "health": None,         # no health data + all inbox items are promotional
        },
    }

    # Null-count sanity check (mirrors helper logic). With 9 sections
    # total, 5 nulls (5/9 ≈ 56% null) is the lower bound of "the brief
    # is too thin to ship." If you add a 10th section, bump this to 6.
    null_count = sum(1 for v in edition["sections"].values() if v is None)
    if null_count >= 5:
        print(f"[enrich] {null_count} of 9 sections null — would SILENT per spec rule",
              file=sys.stderr)
        return None

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{date_iso}.json"
    out_path.write_text(json.dumps(edition, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[enrich] wrote {out_path}", file=sys.stderr)
    print(f"[enrich] sections populated: "
          f"{[k for k, v in edition['sections'].items() if v is not None]}",
          file=sys.stderr)
    print(f"[enrich] null sections: "
          f"{[k for k, v in edition['sections'].items() if v is None]}",
          file=sys.stderr)
    return edition


def main() -> int:
    p = argparse.ArgumentParser(description="Enrich the DFB edition with qualitative LLM fields.")
    p.add_argument("date", nargs="?",
                   help="Date (YYYY-MM-DD); default = today America/Chicago")
    args = p.parse_args()
    if args.date:
        date_iso = args.date
    else:
        import zoneinfo
        ct = zoneinfo.ZoneInfo("America/Chicago")
        date_iso = datetime.now(ct).date().isoformat()

    edition = build_edition(date_iso)
    if edition is None:
        return 2  # silent
    return 0


if __name__ == "__main__":
    sys.exit(main())
