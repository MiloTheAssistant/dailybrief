#!/usr/bin/env python3
"""
build_dfb_json.py
=================
Assembles the 7-section Daily Financial Briefing JSON from the dailybrief
fetchers (market RSS, calendar, mail, TWS portfolio), writes it to
`out/dfb/<date>.json`, commits + pushes the dailybrief repo, then
triggers a Vercel deploy from the website repo.

Output JSON shape must match `Briefing` in
`MiloTheAssistant/Milo/website/src/lib/briefings-types.ts`.

CLI:
    python3 scripts/build_dfb_json.py
    python3 scripts/build_dfb_json.py --dry-run
    python3 scripts/build_dfb_json.py --skip-deploy
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
OUT_DIR = REPO_ROOT / "out" / "dfb"


def run_fetcher(name: str, *args: str) -> dict:
    cmd = ["python3", str(SCRIPTS / name), *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {"sources": {}, "data": {}, "error": f"{name}: timeout"}
    if result.returncode != 0:
        return {"sources": {}, "data": {}, "error": f"{name}: exit {result.returncode}"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {"sources": {}, "data": {}, "error": f"{name}: bad json: {e}"}


def group_stories_by_section(stories: list[dict]) -> dict[str, list[dict]]:
    """Map RSS 'section' values to the DFB's typed section buckets."""
    buckets: dict[str, list] = {
        "marketHeadlines": [],
        "aiRace": [],
        "bitcoin": [],
    }
    section_map = {
        "analyst": "marketHeadlines",
        "macro": "marketHeadlines",
        "movers": "marketHeadlines",
        "crypto": "bitcoin",
        "ai": "aiRace",
        "mag7": "aiRace",  # AI-adjacent — Mag7 = mostly tech
    }
    for s in stories:
        bucket = section_map.get(s.get("section", ""), "marketHeadlines")
        buckets[bucket].append({
            "headline": s.get("title"),
            "source": s.get("source"),
            "url": s.get("url"),
            "whyItMatters": None,  # filled by the LLM
            "publishedAt": s.get("published"),
        })
    return buckets


def build_sections(rss_env: dict, calendar_env: dict, mail_env: dict, portfolio_env: dict) -> dict:
    stories = rss_env.get("data", {}).get("stories", [])
    buckets = group_stories_by_section(stories)

    portfolio = portfolio_env.get("data") or {}
    account = portfolio.get("account_summary", {}) or {}
    positions = portfolio.get("positions", []) or []

    mail_data = mail_env.get("data", {})
    inbox = mail_data.get("envelopes", []) if isinstance(mail_data, dict) else []

    return {
        "marketHeadlines": buckets["marketHeadlines"][:5],
        "bitcoin": None,  # filled by the LLM using fetch_dfb_market_data if available
        "strategy": None,  # ditto
        "institutional": {
            "etfLeagueTable": None,
            "blackrock": None,
            "fidelity": None,
            "regulatoryRadar": None,
            "sovereign": None,
            "tradfi": None,
        },
        "creatorIntel": {
            "videos": [],
            "sentimentReading": None,
            "sentimentNote": None,
        },
        "aiRace": buckets["aiRace"][:4],
        "retirement": {
            "netLiquidation": account.get("NetLiquidation"),
            "buyingPower": account.get("BuyingPower"),
            "availableFunds": account.get("AvailableFunds"),
            "totalCashValue": account.get("TotalCashValue"),
            "unrealizedPnL": account.get("UnrealizedPnL"),
            "realizedPnL": account.get("RealizedPnL"),
            "topPositions": positions[:3],
            "rateWatch": None,
            "supplement": [],
        },
        "health": {
            "personalInbox": [e for e in inbox if not e.get("is_seen", True)][:3],
            "move": None,
        },
    }


def assemble(today_iso: str, weekday: str) -> dict:
    rss_env = run_fetcher("fetch_market_brief_rss.py")
    calendar_env = run_fetcher(
        "fetch_proton_calendar.py",
        "--days", "7",
        "--from-date", today_iso,
    )
    mail_env = run_fetcher(
        "fetch_proton_mail.py",
        "--folder", "INBOX",
        "--unseen-only",
        "--since-hours", "18",
        "--limit", "10",
    )
    portfolio_env = run_fetcher("fetch_tws_portfolio.py", "--plain")

    sections = build_sections(rss_env, calendar_env, mail_env, portfolio_env)
    null_count = sum(1 for v in sections.values() if v is None)
    confidence = "high" if null_count <= 2 else "medium" if null_count <= 4 else "low"

    now = datetime.now(timezone.utc)
    return {
        "date": today_iso,
        "weekday": weekday,
        "kind": "dfb",
        "title": "Daily Financial Briefing",
        "subtitle": "Mission Control · Market Intelligence · Daily",
        "generatedAt": now.isoformat(),
        "confidence": confidence,
        "zip": "63025",
        "fetchers": {
            "rss": rss_env.get("sources", {}),
            "calendar": calendar_env.get("sources", {}),
            "mail": mail_env.get("sources", {}),
            "portfolio": portfolio_env.get("sources", {}),
        },
        "sections": sections,
    }


def write_and_ship(edition: dict, today_iso: str, dry_run: bool, skip_deploy: bool) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{today_iso}.json"
    out_path.write_text(json.dumps(edition, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build_dfb_json] wrote {out_path}", file=sys.stderr)

    if dry_run:
        print("[build_dfb_json] DRY RUN — skipping commit/push/deploy", file=sys.stderr)
        return 0

    try:
        subprocess.run(["git", "add", str(out_path.relative_to(REPO_ROOT))],
                       cwd=REPO_ROOT, check=True, timeout=15)
        subprocess.run(["git", "commit", "-m",
                        f"chore(dfb): edition {today_iso}"],
                       cwd=REPO_ROOT, check=True, timeout=15)
        subprocess.run(["git", "push", "origin", "main"],
                       cwd=REPO_ROOT, check=True, timeout=60)
    except subprocess.CalledProcessError as e:
        print(f"[build_dfb_json] git push failed: {e}", file=sys.stderr)
        return 2

    if skip_deploy:
        print("[build_dfb_json] SKIP DEPLOY — JSON pushed, Vercel pending", file=sys.stderr)
        return 0

    website_dir = Path("/Volumes/BotCentral/Users/milo/repos/Milo/website")
    if not website_dir.exists():
        print(f"[build_dfb_json] website dir missing: {website_dir}", file=sys.stderr)
        return 3
    try:
        result = subprocess.run(
            ["vercel", "deploy", "--prod", "--yes"],
            cwd=website_dir, capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("[build_dfb_json] vercel deploy timeout", file=sys.stderr)
        return 4
    if result.returncode != 0:
        print(f"[build_dfb_json] vercel deploy failed: {result.stderr}", file=sys.stderr)
        return 5
    print(f"[build_dfb_json] vercel deployed: {result.stdout.strip().splitlines()[-1] if result.stdout else 'ok'}", file=sys.stderr)
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Assemble + ship the Daily Financial Briefing to Vercel.")
    p.add_argument("--date", help="Override date (YYYY-MM-DD); default = today CT")
    p.add_argument("--dry-run", action="store_true", help="Write JSON only; skip git + Vercel")
    p.add_argument("--skip-deploy", action="store_true", help="Push JSON, skip Vercel deploy")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today_iso = args.date or datetime.now(timezone.utc).astimezone().date().isoformat()
    weekday = datetime.fromisoformat(today_iso).strftime("%A")

    edition = assemble(today_iso, weekday)
    print(json.dumps(edition, ensure_ascii=False, indent=2))
    return write_and_ship(edition, today_iso, args.dry_run, args.skip_deploy)


if __name__ == "__main__":
    sys.exit(main())
