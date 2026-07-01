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
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("/Volumes/BotCentral/Users/milo/repos/dailybrief")
SCRIPTS = REPO_ROOT / "scripts"
OUT_DIR = REPO_ROOT / "out" / "dfb"


def run_fetcher(name: str, *args: str) -> dict:
    """Run a fetcher subprocess and return {sources, data, error?}.

    Fetchers emit their payload at the top level (stories, events,
    envelopes, account_summary, ...). We wrap that payload as `data`
    so the rest of the pipeline can use a single uniform shape.
    """
    cmd = ["python3", str(SCRIPTS / name), *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {"sources": {}, "data": {}, "error": f"{name}: timeout"}
    if result.returncode != 0:
        return {"sources": {}, "data": {}, "error": f"{name}: exit {result.returncode}"}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {"sources": {}, "data": {}, "error": f"{name}: bad json: {e}"}
    # `feeds` and `sources` and metadata stay at the top; payload becomes `data`.
    sources = payload.get("feeds") or payload.get("sources") or {}
    return {"sources": sources, "data": payload, "error": None}


def group_stories_by_section(stories: list[dict]) -> dict[str, list[dict]]:
    """Map RSS 'section' values to the DFB's typed section buckets.

    The helper has to make judgment calls because RSS feeds don't split
    neatly across our DFB section schema. Default: a story goes to
    marketHeadlines unless it has a clearly crypto/ai home. Mag7 lives
    on the tech/market line AND feeds aiRace when AI-relevant.
    """
    buckets: dict[str, list] = {
        "marketHeadlines": [],
        "aiRace": [],
        "bitcoin": [],
    }
    # Mag7 keywords that signal an AI-company move (vs pure market story).
    ai_keywords = (
        "ai ", " ai,", " ai.", "gpt", "llm", "openai", "anthropic",
        "nvidia", "meta ", "google", "alphabet", "microsoft", "amazon",
        "agent", "model", "chip", "gpu", "data center", "ppa",
    )
    for s in stories:
        sec = s.get("section", "")
        title = (s.get("title") or "").lower()
        if sec == "crypto":
            target = "bitcoin"
        elif sec == "ai":
            target = "aiRace"
        elif sec == "mag7":
            target = "aiRace" if any(k in title for k in ai_keywords) else "marketHeadlines"
        else:
            # analyst / macro / movers / unknown → marketHeadlines
            target = "marketHeadlines"
        buckets[target].append({
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

    # Skip the commit/push if the on-disk JSON is already tracked and
    # byte-identical to what we're about to write. Avoids a no-op
    # commit+push on the --use-enriched path when the enriched file
    # was just produced by enrich_dfb_edition.py and didn't change.
    rel_path = str(out_path.relative_to(REPO_ROOT))
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel_path],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        tracked = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    is_tracked = tracked.returncode == 0
    if is_tracked:
        status = subprocess.run(
            ["git", "status", "--porcelain", rel_path],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
        if status.stdout.strip() == "":
            print(f"[build_dfb_json] {rel_path} unchanged — skipping commit/push",
                  file=sys.stderr)
            # Fall through to deploy step below if not --skip-deploy.
            if skip_deploy:
                return 0
            website_dir = Path(__file__).resolve().parent.parent.parent / "Milo" / "website"
            if not website_dir.exists():
                print(f"[build_dfb_json] website dir missing: {website_dir}",
                      file=sys.stderr)
                return 3
            return _vercel_deploy(website_dir)

    try:
        subprocess.run(["git", "add", "-f", rel_path],
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
        print("[build_dfb_json] SKIP DEPLOY — JSON pushed, Vercel pending",
              file=sys.stderr)
        return 0

    # Resolve website_dir relative to this file (so it works in any
    # workdir) with a fallback to the historical absolute path.
    website_dir = Path(__file__).resolve().parent.parent.parent / "Milo" / "website"
    if not website_dir.exists():
        website_dir = Path("/Volumes/BotCentral/Users/milo/repos/Milo/website")
    if not website_dir.exists():
        print(f"[build_dfb_json] website dir missing: {website_dir}",
              file=sys.stderr)
        return 3
    return _vercel_deploy(website_dir)


def _vercel_deploy(website_dir: Path) -> int:
    """Fire the Vercel deploy. Caller is responsible for path validation."""
    try:
        result = subprocess.run(
            ["vercel", "deploy", "--prod", "--yes"],
            cwd=website_dir, capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("[build_dfb_json] vercel deploy timeout", file=sys.stderr)
        return 4
    if result.returncode != 0:
        print(f"[build_dfb_json] vercel deploy failed: {result.stderr}",
              file=sys.stderr)
        return 5
    last = result.stdout.strip().splitlines()[-1] if result.stdout else "ok"
    print(f"[build_dfb_json] vercel deployed: {last}", file=sys.stderr)
    return 0


def check_deps() -> int:
    """Read-only preflight: verify the cron-time prerequisites are in place.

    Checks (and prints a status table for each):
      1. Proton Mail config: ~/.config/himalaya/config.toml exists + has credentials
      2. IB TWS port: 7497 reachable (lsof listener check)
      3. vercel CLI: on PATH + authenticated
      4. Website repo: exists + has public/briefings/ directory

    Returns 0 if all checks pass, 1 if any fail. No side effects.
    """
    checks: list[tuple[str, bool, str]] = []

    # 1. Proton Mail config (Himalaya CLI).
    himalaya = Path.home() / ".config" / "himalaya" / "config.toml"
    if himalaya.exists():
        text = himalaya.read_text(encoding="utf-8", errors="ignore")
        # Crude credential check: look for an account stanza with a
        # password-source or a non-empty password. Not airtight, but
        # catches the common "fresh install" case where the file
        # exists but no accounts are configured.
        has_account = "[accounts." in text or "password" in text
        if has_account:
            checks.append(("Proton Mail (Himalaya config)", True, str(himalaya)))
        else:
            checks.append((
                "Proton Mail (Himalaya config)",
                False, f"{himalaya} exists but no [accounts.*] stanza found",
            ))
    else:
        checks.append((
            "Proton Mail (Himalaya config)", False, f"{himalaya} not found",
        ))

    # 2. IB TWS port 7497 (live-paper-trading default).
    try:
        lsof = subprocess.run(
            ["lsof", "-iTCP:7497", "-sTCP:LISTEN", "-P", "-n"],
            capture_output=True, text=True, timeout=5,
        )
        listening = lsof.returncode == 0 and lsof.stdout.strip()
        checks.append((
            "IB TWS port 7497 (paper)",
            bool(listening),
            "listening" if listening else "no listener on 7497",
        ))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        checks.append(("IB TWS port 7497 (paper)", False, "lsof not available"))

    # 3. vercel CLI on PATH + authenticated.
    vercel = shutil.which("vercel")
    if vercel:
        # `vercel whoami` returns 0 if authenticated, non-zero otherwise.
        whoami = subprocess.run(
            [vercel, "whoami"], capture_output=True, text=True, timeout=10,
        )
        ok = whoami.returncode == 0
        detail = whoami.stdout.strip() or whoami.stderr.strip() or "unknown"
        checks.append(("vercel CLI authenticated", ok, detail[:80]))
    else:
        checks.append(("vercel CLI on PATH", False, "vercel not found"))

    # 4. Website repo exists + has public/briefings/.
    website = (
        Path(__file__).resolve().parent.parent.parent / "Milo" / "website"
    )
    if not website.exists():
        website = Path("/Volumes/BotCentral/Users/milo/repos/Milo/website")
    briefings = website / "public" / "briefings"
    if website.exists() and briefings.is_dir():
        checks.append((
            "Website repo + public/briefings/",
            True, str(website.relative_to(Path.home())),
        ))
    else:
        checks.append((
            "Website repo + public/briefings/",
            False, f"missing: {website}",
        ))

    # Render the table.
    print("[build_dfb_json] preflight — runtime dependencies", file=sys.stderr)
    all_ok = True
    for name, ok, detail in checks:
        marker = "✓" if ok else "✗"
        print(f"  {marker} {name}: {detail}", file=sys.stderr)
        all_ok = all_ok and ok
    if all_ok:
        print("[build_dfb_json] all checks passed", file=sys.stderr)
        return 0
    print("[build_dfb_json] one or more checks FAILED — fix above before cron run",
          file=sys.stderr)
    return 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Assemble + ship the Daily Financial Briefing to Vercel.")
    p.add_argument("--date", help="Override date (YYYY-MM-DD); default = today CT")
    p.add_argument("--dry-run", action="store_true", help="Write JSON only; skip git + Vercel")
    p.add_argument("--skip-deploy", action="store_true", help="Push JSON, skip Vercel deploy")
    p.add_argument("--use-enriched", action="store_true",
                   help="If out/dfb/<date>.json already exists, use it (skip re-fetch). "
                        "Lets the LLM-cron write qualitative enrichment first.")
    p.add_argument("--check-deps", action="store_true",
                   help="Preflight: verify cron-time prerequisites (Proton, TWS, "
                        "vercel CLI, website repo). Read-only; exits 0 if all OK, "
                        "1 if any check fails. Run BEFORE the cron job to catch "
                        "missing config / unreachable services.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.check_deps:
        return check_deps()
    today_iso = args.date or datetime.now(timezone.utc).astimezone().date().isoformat()
    weekday = datetime.fromisoformat(today_iso).strftime("%A")

    # If an enriched edition is already on disk, use it directly. This
    # lets the LLM-cron hand-write the qualitative fields and skip the
    # auto-assembly step (which would re-fetch and overwrite).
    out_path = OUT_DIR / f"{today_iso}.json"
    if args.use_enriched and out_path.exists():
        try:
            edition = json.loads(out_path.read_text(encoding="utf-8"))
            print(f"[build_dfb_json] using existing enriched file {out_path}", file=sys.stderr)
            print(json.dumps(edition, ensure_ascii=False, indent=2))
            return write_and_ship(edition, today_iso, args.dry_run, args.skip_deploy)
        except json.JSONDecodeError as e:
            print(f"[build_dfb_json] enriched file unreadable, re-assembling: {e}", file=sys.stderr)

    edition = assemble(today_iso, weekday)
    print(json.dumps(edition, ensure_ascii=False, indent=2))
    return write_and_ship(edition, today_iso, args.dry_run, args.skip_deploy)


if __name__ == "__main__":
    sys.exit(main())
