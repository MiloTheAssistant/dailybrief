#!/usr/bin/env python3
"""
build_lifestyle_json.py
=======================
Assembles a Saturday or Sunday lifestyle brief JSON from the dailybrief
fetchers + curated references, writes it to `out/lifestyle/<date>.json`,
commits + pushes the dailybrief repo, then triggers a Vercel deploy.

The JSON shape must match `LifestyleEdition` in
`MiloTheAssistant/Milo/website/src/lib/briefings-types.ts`.

CLI:
    python3 scripts/build_lifestyle_json.py saturday
    python3 scripts/build_lifestyle_json.py sunday
    python3 scripts/build_lifestyle_json.py saturday --dry-run
    python3 scripts/build_lifestyle_json.py saturday --skip-deploy

Stdout: the JSON envelope that would be written.
Exit: 0 on success, non-zero on a hard failure the brief should surface.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("/Volumes/BotCentral/Users/milo/repos/dailybrief")
SCRIPTS = REPO_ROOT / "scripts"
REFERENCES = REPO_ROOT / "references"
OUT_DIR = REPO_ROOT / "out" / "lifestyle"

EUREKA_LAT = 38.5017
EUREKA_LON = -90.6276
EUREKA_LABEL = "Eureka, MO"
EUREKA_ZIP = "63025"


def run_fetcher(name: str, *args: str) -> dict:
    """Run a dailybrief fetcher and return its parsed JSON envelope.
    On non-zero exit or parse failure, returns {'sources': {}, 'data': {}, 'error': ...}."""
    cmd = ["python3", str(SCRIPTS / name), *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {"sources": {}, "data": {}, "error": f"{name}: timeout"}
    except FileNotFoundError:
        return {"sources": {}, "data": {}, "error": f"{name}: not found"}
    if result.returncode != 0:
        return {"sources": {}, "data": {}, "error": f"{name}: exit {result.returncode}: {result.stderr.strip()}"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {"sources": {}, "data": {}, "error": f"{name}: invalid json: {e}"}


def read_curated_travel() -> list[dict]:
    """Pull a season-relevant subset of the curated travel list.

    The model doesn't write this — it picks from what's here.
    This helper returns the full curated list as structured JSON for
    the model to filter. We parse the markdown into a simpler shape:
    [{name, region, distance, blurb}, ...]
    """
    md = (REFERENCES / "top-travel-ideas.md").read_text(encoding="utf-8")
    ideas: list[dict] = []
    current_region = ""
    for line in md.splitlines():
        if line.startswith("### "):
            current_region = line[4:].strip()
        elif line.startswith("- **") and "** — " in line:
            # "- **Route 66 State Park** (Eureka, MO) — 0 min. Hiking..."
            head, tail = line[2:].split("** — ", 1)
            name = head.strip("*").strip()
            # Parse "(place)" and "X min/X hr" out of `tail`.
            blurb = tail
            # Crude distance extraction
            import re
            dm = re.match(r"^(.+?)\s+—\s+(\d[\d\.]*\s*(?:min|hr)(?:\s*\(borderline\s*\d+\s*hr\))?)\.\s*(.*)$", tail)
            if dm:
                where = dm.group(1).strip()
                dist = dm.group(2).strip()
                rest = dm.group(3).strip()
                ideas.append({"name": name, "where": where, "distance": dist, "blurb": rest, "region": current_region})
            else:
                ideas.append({"name": name, "where": "", "distance": "", "blurb": blurb, "region": current_region})
    return ideas


def assemble(day: str, today_iso: str, weekday: str) -> dict:
    """Pull fetchers, assemble LifestyleEdition JSON for the given day."""
    weather_env = run_fetcher("fetch_lifestyle_sources.py")
    events_env = run_fetcher("fetch_stl_events.py")
    calendar_env = run_fetcher(
        "fetch_proton_calendar.py",
        "--from-date", today_iso,
        "--to-date", today_iso,
    )
    if day == "saturday":
        mail_env = run_fetcher(
            "fetch_proton_mail.py",
            "--folder", "INBOX",
            "--unseen-only",
            "--since-hours", "18",
            "--limit", "5",
        )
    else:  # sunday
        mail_env = run_fetcher(
            "fetch_proton_mail.py",
            "--folder", "INBOX",
            "--unseen-only",
            "--since-hours", "48",
            "--limit", "5",
        )
    portfolio_env = run_fetcher("fetch_tws_portfolio.py", "--plain")

    # Executive Brief data: markets (treasury + index charts), health research,
    # and 7-day RSS rollup (the model filters by section + relevance to fill
    # InvestingThemes + AiLandscape pillars).
    treasury_env = run_fetcher("fetch_treasury.py")
    health_env = run_fetcher("fetch_health_research.py")
    rss_env = run_fetcher("fetch_market_brief_rss.py", "--window-hours", "168")

    weather = weather_env.get("data", {}).get("weather") or {}
    weather_sources = weather_env.get("sources", {}).get("weather", {})

    events = events_env.get("data", {}).get("events") or []

    calendar_today = []
    cal_data = calendar_env.get("data", {})
    if isinstance(cal_data, dict) and "events" in cal_data:
        calendar_today = cal_data["events"]
    elif isinstance(cal_data, list):
        calendar_today = cal_data

    inbox = []
    mail_data = mail_env.get("data", {})
    if isinstance(mail_data, dict) and "envelopes" in mail_data:
        inbox = mail_data["envelopes"]

    portfolio = portfolio_env.get("data") or {}

    travel_ideas = read_curated_travel()

    # Build the markets indicator list from treasury + index chart outputs.
    markets_indicators = _build_markets_indicators(treasury_env)
    markets_why = None  # model writes this from the brief's narrative

    # RSS: pass through the 7-day window for the model to filter into
    # InvestingThemes (mag7 stories) and AiLandscape (ai stories). Cap to
    # 60 to keep the brief file small but give the model enough signal.
    rss_stories = (rss_env.get("stories") or [])[:60]
    rss_sections_present = sorted({s.get("section", "?") for s in rss_stories})

    # Health research: pass through to the model so it can pick the top
    # 5-7 stories relevant to men-over-60 lens.
    health_stories = (health_env.get("stories") or [])[:30]

    now = datetime.now(timezone.utc)
    edition = {
        "date": today_iso,
        "weekday": weekday,
        "kind": "lifestyle",
        "generatedAt": now.isoformat(),
        "zip": EUREKA_ZIP,
        "location": {"label": EUREKA_LABEL, "lat": EUREKA_LAT, "lon": EUREKA_LON},
        "fetchers": {
            "weather": weather_sources,
            "stlEvents": events_env.get("sources", {}),
            "calendar": calendar_env.get("sources", {}),
            "mail": mail_env.get("sources", {}),
            "portfolio": portfolio_env.get("sources", {}),
            "treasury": treasury_env.get("status"),
            "health": health_env.get("status"),
            "rss": {
                "stories": len(rss_stories),
                "sections": rss_sections_present,
            },
        },
        # Raw fetcher payloads — model reads these when filling the
        # qualitative fields. Kept in the JSON so the brief is fully
        # reproducible from the file alone (no hidden fetcher state).
        "rawInputs": {
            "treasury": treasury_env,
            "health": {"stories": health_stories, "feeds": health_env.get("feeds", {})},
            "rss": {"stories": rss_stories, "feeds": rss_env.get("feeds", {})},
        },
        "pillars": {
            "weather": {
                "today": weather.get("today"),
                "tonight": weather.get("tonight"),
                "tomorrow": weather.get("tomorrow") if day == "saturday" else None,
                "whatToWear": None,  # filled by the model
                "source": weather_sources.get("status"),
            },
            "life": {
                "calendarToday": calendar_today,
                "oneThing": None,  # filled by the model (or oneThingToPlan for Sunday)
                "oneThingToPlan": None,  # Sunday only
                "localPicks": events,
                "localPicksNextWeekend": None,  # Sunday only
                "rec": None,  # filled by the model
            },
            "vacation": {
                "upcomingTravel": [],  # filled by the model from calendar text
                "driveDistanceIdeas": travel_ideas,  # full list, model filters
            },
            "retirement": {
                "portfolioState": portfolio,
                "planningNote": None,  # filled by the model
            },
            # Executive Brief pillars (Weekend_Executive_Brief_Prompt.md).
            # The model fills the qualitative fields; some (markets.indicators)
            # are pre-populated from the fetchers.
            "executiveSummary": {
                "opportunities": None,    # model fills
                "summaryBullets": None,   # model fills
                "actionItems": None,      # model fills
                "funFact": None,          # model fills
            },
            "markets": {
                "indicators": markets_indicators,  # pre-populated from treasury + index charts
                "whyParagraph": None,              # model writes 1-paragraph synthesis
            },
            "investingThemes": {
                "themes": None,            # model picks from rss.stories filtered by section=mag7
                "noMeaningfulNews": None,  # model sets true if no signal this week
            },
            "retirementWatch": {
                "items": None,             # model fills from web_search + RSS
                "noMeaningfulNews": None,
                "planningNote": None,
                "weekEndReflection": None,
            },
            "aiLandscape": {
                "entries": None,           # model picks from rss.stories filtered by section=ai
                "noMeaningfulNews": None,
            },
            "health": {
                "entries": None,           # model picks from rawInputs.health.stories
                "noMeaningfulNews": None,
            },
            "worthReading": {
                "articles": None,
                "videos": None,
                "podcasts": None,
            },
        },
    }
    return edition


def _build_markets_indicators(treasury_env: dict) -> list[dict]:
    """Translate fetch_treasury.py output into the MarketsPillar.indicators
    shape. Each indicator gets a label, current, week-to-date change, source.
    """
    indicators: list[dict] = []
    quotes = treasury_env.get("indexQuotes") or {}
    curve = (treasury_env.get("treasury") or {}).get("yieldCurve") or []

    def _quote(label: str, key: str) -> dict | None:
        q = quotes.get(key)
        if not q or q.get("error") or q.get("price") is None:
            return None
        return {
            "label": label,
            "current": q["price"],
            "changeWtd": f"{q['change5dPct']:+.2f}%" if q.get("change5dPct") is not None else None,
            "source": q.get("shortName") or q.get("longName") or key,
        }

    sp = _quote("S&P 500", "sp500")
    if sp: indicators.append(sp)
    nq = _quote("Nasdaq Composite", "nasdaq")
    if nq: indicators.append(nq)
    btc = _quote("Bitcoin", "btc")
    if btc: indicators.append(btc)
    dxy = _quote("U.S. Dollar (DXY)", "dxy")
    if dxy: indicators.append(dxy)

    # Treasury rates — show 3M, 2Y, 10Y, 30Y from the latest curve row.
    if curve:
        latest = curve[0]
        for label, key in [("3M Treasury", "3m"),
                           ("2Y Treasury", "2y"),
                           ("10Y Treasury", "10y"),
                           ("30Y Treasury", "30y")]:
            v = latest.get(key)
            if v is not None:
                # Calculate WTD change vs the oldest row in the 10-row window.
                if len(curve) >= 2:
                    oldest = curve[-1]
                    old_v = oldest.get(key)
                    bps_change = None
                    if old_v is not None:
                        bps_change = round((v - old_v) * 100, 0)  # pct -> bps
                        indicators.append({
                            "label": label,
                            "current": f"{v:.2f}%",
                            "changeWtd": f"{bps_change:+.0f} bps",
                            "source": "home.treasury.gov",
                        })
                    else:
                        indicators.append({"label": label, "current": f"{v:.2f}%", "source": "home.treasury.gov"})
                else:
                    indicators.append({"label": label, "current": f"{v:.2f}%", "source": "home.treasury.gov"})

    return indicators


def write_and_ship(edition: dict, day: str, today_iso: str, dry_run: bool, skip_deploy: bool) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{today_iso}.json"
    out_path.write_text(json.dumps(edition, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build_lifestyle_json] wrote {out_path}", file=sys.stderr)

    if dry_run:
        print(f"[build_lifestyle_json] DRY RUN — would commit + push + deploy", file=sys.stderr)
        return 0

    # Write manifest first (lists all dates), so the JSON commit can
    # include both the new edition and the updated manifest in one push.
    _write_manifest()

    # Git commit + push.
    try:
        subprocess.run(["git", "add",
                        str(out_path.relative_to(REPO_ROOT)),
                        "out/manifest.json"],
                       cwd=REPO_ROOT, check=True, timeout=15)
        subprocess.run(["git", "commit", "-m",
                        f"chore(lifestyle): {day} edition {today_iso}"],
                       cwd=REPO_ROOT, check=True, timeout=15)
        subprocess.run(["git", "push", "origin", "main"],
                       cwd=REPO_ROOT, check=True, timeout=60)
    except subprocess.CalledProcessError as e:
        print(f"[build_lifestyle_json] git push failed: {e}", file=sys.stderr)
        return 2

    if skip_deploy:
        print(f"[build_lifestyle_json] SKIP DEPLOY — JSON pushed, Vercel build pending", file=sys.stderr)
        return 0

    # Vercel deploy from the website repo.
    website_dir = Path("/Volumes/BotCentral/Users/milo/repos/Milo/website")
    if not website_dir.exists():
        print(f"[build_lifestyle_json] website dir missing: {website_dir}", file=sys.stderr)
        return 3
    try:
        result = subprocess.run(
            ["vercel", "deploy", "--prod", "--yes"],
            cwd=website_dir, capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("[build_lifestyle_json] vercel deploy timeout", file=sys.stderr)
        return 4
    if result.returncode != 0:
        print(f"[build_lifestyle_json] vercel deploy failed: {result.stderr}", file=sys.stderr)
        return 5
    print(f"[build_lifestyle_json] vercel deployed: {result.stdout.strip().splitlines()[-1] if result.stdout else 'ok'}", file=sys.stderr)
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Assemble + ship a lifestyle brief to Vercel.")
    p.add_argument("day", choices=["saturday", "sunday"], help="Which day to assemble for.")
    p.add_argument("--date", help="Override date (YYYY-MM-DD); default = today CT")
    p.add_argument("--dry-run", action="store_true", help="Write JSON + skip commit/push/deploy")
    p.add_argument("--skip-deploy", action="store_true", help="Commit + push, skip Vercel deploy")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today_iso = args.date or datetime.now(timezone.utc).astimezone().date().isoformat()
    weekday = "Saturday" if args.day == "saturday" else "Sunday"

    edition = assemble(args.day, today_iso, weekday)
    print(json.dumps(edition, ensure_ascii=False, indent=2))
    return write_and_ship(edition, args.day, today_iso, args.dry_run, args.skip_deploy)


def _write_manifest() -> None:
    """
    Scan out/dfb/ and out/lifestyle/, write out/manifest.json with the
    list of all published dates per kind. The website prebuild reads this
    one file instead of calling the rate-limited GH trees API.
    """
    dfb_dir = REPO_ROOT / "out" / "dfb"
    life_dir = REPO_ROOT / "out" / "lifestyle"
    manifest = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "dfb": sorted(p.stem for p in dfb_dir.glob("*.json") if p.stem != "latest"),
        "lifestyle": sorted(p.stem for p in life_dir.glob("*.json") if p.stem != "latest"),
    }
    out_path = REPO_ROOT / "out" / "manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[build_lifestyle_json] wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
