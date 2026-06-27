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
                "oneThing": None,  # filled by the model
                "localPicks": events,
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
        },
    }
    return edition


def write_and_ship(edition: dict, day: str, today_iso: str, dry_run: bool, skip_deploy: bool) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{today_iso}.json"
    out_path.write_text(json.dumps(edition, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build_lifestyle_json] wrote {out_path}", file=sys.stderr)

    if dry_run:
        print(f"[build_lifestyle_json] DRY RUN — would commit + push + deploy", file=sys.stderr)
        return 0

    # Git commit + push.
    try:
        subprocess.run(["git", "add", str(out_path.relative_to(REPO_ROOT))],
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


if __name__ == "__main__":
    sys.exit(main())
