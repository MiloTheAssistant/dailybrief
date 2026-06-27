#!/usr/bin/env python3
"""
build_lifestyle_json.py
=======================
CLI wrapper — assemble + ship a Saturday or Sunday lifestyle brief.
See `_publish_common.py` for the assembler logic.

CLI:
    python3 scripts/build_lifestyle_json.py saturday [--dry-run] [--skip-deploy]
    python3 scripts/build_lifestyle_json.py sunday   [--dry-run] [--skip-deploy]
"""

from __future__ import annotations

import argparse
import sys

# Local helper import.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import _publish_common as pc  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Build a lifestyle brief + ship to Vercel.")
    p.add_argument("day", choices=["saturday", "sunday"])
    p.add_argument("--date", help="Override date (YYYY-MM-DD); default = today CT")
    p.add_argument("--dry-run", action="store_true", help="Write JSON only; skip git + Vercel")
    p.add_argument("--skip-deploy", action="store_true", help="Push JSON, skip Vercel deploy")
    args = p.parse_args()

    from datetime import datetime, timezone
    today_iso = args.date or datetime.now(timezone.utc).astimezone().date().isoformat()
    weekday = "Saturday" if args.day == "saturday" else "Sunday"

    edition = pc.assemble(args.day, today_iso, weekday)
    import json
    print(json.dumps(edition, ensure_ascii=False, indent=2))
    return pc.write_and_ship(edition, args.day, today_iso, args.dry_run, args.skip_deploy)


if __name__ == "__main__":
    sys.exit(main())
