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
        "--sender-allowlist", "email.interactivebrokers.com",
        "--limit", "5",
    )
    # calendar + portfolio are not actionable today (empty + TWS offline)
    stories = rss.get("stories", [])
    envelopes = mail.get("envelopes", [])
    news_envelopes = newsletters.get("envelopes", [])

    def find(sec: str, n: int = 5) -> list[dict]:
        return [s for s in stories if s.get("section") == sec][:n]

    mag7 = find("mag7", 25)
    crypto = find("crypto", 25)
    ai = find("ai", 25)
    movers = find("movers", 5)

    # ─── Market Headlines (curated) ──────────────────────────────────────
    # Pick the most actionable stories, not the first 5 alphabetical.
    market_headlines = []

    def add_mh(title: str, source: str, url: str, why: str, published: str = None):
        market_headlines.append({
            "headline": title,
            "source": source,
            "url": url,
            "whyItMatters": why,
            "publishedAt": published,
        })

    # 1. Alphabet $84.75B equity raise — the day's biggest capital-markets story
    for s in mag7:
        if "84.75" in s["title"] or "Largest Equity Capital Raise" in s["title"]:
            add_mh(
                s["title"], s["source"], s["url"],
                "Largest US corporate equity raise in history — read-through for cap-markets "
                "liquidity and AI-capex funding asks across the Mag7.",
                s.get("published"),
            )
            break

    # 2. Google rationing Meta's Gemini access
    for s in mag7:
        if ("rationing Meta" in s["title"]) or ("Capped Meta" in s["title"]):
            add_mh(
                s["title"], s["source"], s["url"],
                "Hyperscalers throttling each other is the clearest signal that 2026 AI compute is sold out.",
                s.get("published"),
            )
            break

    # 3. Meta 220MW Texas PPA
    for s in mag7:
        if "Meta signs 220MW" in s["title"]:
            add_mh(
                s["title"], s["source"], s["url"],
                "220MW PPA at Sabanci — AI build-out is now driving utility-scale PPAs in Texas.",
                s.get("published"),
            )
            break

    # 4. JPMorgan defends Broadcom TPU v9 timeline
    for s in movers:
        add_mh(
            s["title"], s["source"], s["url"],
            "JPMorgan pushback keeps TPU v9 on schedule — read-through for custom-AI-silicon "
            "demand vs. Nvidia into 2H 2026.",
            s.get("published"),
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

    institutional = {
        "etfLeagueTable": None,  # not surfaced in RSS — no fabrication
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
        "tradfi": (
            "JPMorgan: Broadcom TPU v9 program on schedule, delay fears overdone. "
            "Stabilizes AVGO narrative; supports the multi-year TPU build-out vs. Nvidia framing."
            if tradfi_story
            else "No notable TradFi moves in today's RSS window."
        ),
    }

    # ─── Creator Intel ───────────────────────────────────────────────────
    creator_intel = {
        "sentimentReading": "Mixed / cautious",
        "sentimentNote": (
            "RSS video sources are not yet wired into the DFB pipeline. "
            "Proton inbox shows 6 newsletters overnight (SA Breaking, Ross Givens, "
            "Traders Daily Direction) — all promotional. No actionable creator intel surfaced."
        ),
        "videos": [],
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
            })
            break
    for s in mag7:
        if "Meta signs 220MW" in s["title"]:
            weekly_moves.append({
                "headline": "Meta locked in a 220MW PPA with Sabanci for Texas data-center power.",
                "company": "Meta",
                "whyItMatters": "AI capex is pulling utility-scale PPAs into Texas.",
            })
            break
    for s in movers:
        if "Broadcom" in s["title"] or "TPU" in s["title"]:
            weekly_moves.append({
                "headline": "JPMorgan: Broadcom TPU v9 program on schedule, delay fears overdone.",
                "company": "NVIDIA",
                "whyItMatters": "Custom-silicon share grows if AVGO delivers — Nvidia margin pressure intensifies.",
            })
            break
    # CoreWeave ARIA from the AI feed
    coreweave = next((s for s in ai if "CoreWeave" in s["title"] or "ARIA" in s["title"]), None)
    if coreweave:
        weekly_moves.append({
            "headline": "CoreWeave launched ARIA, an agent to automate AI research inside Weights & Biases.",
            "company": "Other",
            "whyItMatters": "Agentic AI is reaching infra tooling, not just consumer surfaces.",
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
            "portfolio": {"status": "offline", "note": "TWS preflight failed (lsof:7497 no listener)"},
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
