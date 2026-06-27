#!/usr/bin/env python3
"""
fetch_proton_mail.py — list envelopes in a Proton folder via himalaya, output JSON.

Cron-mode safe (no execute_code, no inline python -c — file-and-run pattern).
The cron prompt invokes this script with `python3 <file>`.

Outputs JSON to stdout for downstream consumption by the brief-composing LLM.
Each envelope is shaped:
    {
        "id": "1528",
        "subject": "...",
        "from": "sender@example.com",
        "date": "2026-06-27 13:40+00:00",
        "flags": "*",        # * = unseen, blank = seen, R = replied, ! = flagged
        "size": null,        # himalaya 1.2.0 envelope list doesn't surface size by default
        "has_attachments": null
    }

Args:
    --folder FOLDER       Folder name (default: INBOX)
    --limit N             Max envelopes to return (default: 25)
    --unseen-only         Only return envelopes without the \\Seen flag
    --since-hours N       Only return envelopes newer than N hours (default: 24)
    --json                Output JSON (default; flag exists for clarity)
    --plain               Output human-readable plain text (for debugging)

Exit codes:
    0 = success
    1 = himalaya call failed
    2 = himalaya not on PATH
    3 = parse error (himalaya output didn't match expected table shape)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone


@dataclass
class Envelope:
    id: str
    subject: str
    sender: str
    date: str
    flags: str
    is_seen: bool


def call_himalaya(folder: str, page_size: int) -> str:
    """Run `himalaya envelope list --folder <folder> --page-size <page_size>`."""
    if not shutil_which("himalaya"):
        print("fetch_proton_mail: himalaya not on PATH", file=sys.stderr)
        sys.exit(2)

    # himalaya's STDOUT is the table; STDERR is warnings (e.g. imap_codec rectifications)
    cmd = [
        "himalaya",
        "envelope",
        "list",
        "--folder",
        folder,
        "--page-size",
        str(page_size),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=30
        )
    except subprocess.CalledProcessError as e:
        print(
            f"fetch_proton_mail: himalaya exited {e.returncode}: {e.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("fetch_proton_mail: himalaya timed out after 30s", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def shutil_which(cmd: str) -> str | None:
    """stdlib-free which; avoids importing shutil just for one call."""
    import shutil

    return shutil.which(cmd)


def parse_himalaya_table(raw: str) -> list[Envelope]:
    """
    Parse himalaya's envelope list output. himalaya 1.2.0 uses a comfy-table
    markdown preset by default:

        | ID   | FLAGS | SUBJECT     | FROM      | DATE                   |
        |------|-------|-------------|-----------|------------------------|
        | 1523 |  *    | Hello world | John      | 2025-05-03 20:30+00:00 |

    The first two lines are the header + separator; subsequent lines are rows.
    Rows whose first column starts with `|` are data rows. Lines starting with
    `2026-` or other timestamp prefixes (warn logs on STDERR, but himalaya
    sometimes leaks them to STDOUT in 1.2.0) are filtered.
    """
    envelopes: list[Envelope] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        # Skip the header (contains "ID") and the separator (contains "---")
        if "ID" in line and "FLAGS" in line:
            continue
        if re.match(r"^\|[\s\-:|]+\|$", line):
            continue

        # Split on `|` and strip each cell, BUT preserve empty cells (some
        # rows have empty SUBJECT — `[c.strip() for c in line.split("|") if c.strip()]`
        # would collapse them and shift every later column left by one).
        raw_cells = [c.strip() for c in line.split("|")]
        # The split produces ["", "1522", " * ", "Subject", "From", "Date", ""]
        # Drop the leading and trailing empties (the outer `|`s).
        if raw_cells and raw_cells[0] == "":
            raw_cells = raw_cells[1:]
        if raw_cells and raw_cells[-1] == "":
            raw_cells = raw_cells[:-1]
        cells = raw_cells

        if len(cells) < 4:
            continue

        # himalaya column order: ID | FLAGS | SUBJECT | FROM | DATE
        # DATE column may have a timezone suffix; we keep the raw string.
        # FLAGS may be empty (seen, no flag) or contain "*" (unseen),
        # "R" (replied), "!" (flagged), or any combination.
        envelope = Envelope(
            id=cells[0],
            flags=cells[1] if len(cells) > 1 else "",
            subject=cells[2] if len(cells) > 2 else "",
            sender=cells[3] if len(cells) > 3 else "",
            date=cells[4] if len(cells) > 4 else "",
            is_seen="*" not in cells[1] if len(cells) > 1 else True,
        )
        envelopes.append(envelope)

    if not envelopes and raw.strip():
        print(
            f"fetch_proton_mail: parsed 0 envelopes but himalaya returned "
            f"{len(raw.splitlines())} lines — schema may have changed. "
            f"First line: {raw.splitlines()[0][:80]!r}",
            file=sys.stderr,
        )
        sys.exit(3)

    return envelopes


def filter_envelopes(
    envelopes: list[Envelope], unseen_only: bool, since_hours: int
) -> list[Envelope]:
    """Apply --unseen-only and --since-hours filters."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    out: list[Envelope] = []
    for env in envelopes:
        if unseen_only and env.is_seen:
            # Email is read (is_seen=True); we want unseen only, so skip.
            continue
        # Parse date for since-hours filter. Format: "2026-06-27 13:40+00:00"
        try:
            ts = datetime.fromisoformat(env.date.replace(" ", "T"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        except ValueError:
            # Unparseable date — keep the envelope (don't silently drop)
            pass
        out.append(env)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--folder", default="INBOX", help="Folder name (default: INBOX)")
    parser.add_argument("--limit", type=int, default=25, help="Max envelopes (default: 25)")
    parser.add_argument(
        "--unseen-only",
        action="store_true",
        help="Only return envelopes without the \\Seen flag (i.e. unread)",
    )
    parser.add_argument(
        "--since-hours",
        type=int,
        default=24,
        help="Only envelopes newer than N hours (default: 24)",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Human-readable output (default: JSON)",
    )
    args = parser.parse_args()

    # Request slightly more than --limit from himalaya so filtering doesn't
    # truncate the result set. Cap at 250 to keep memory bounded.
    fetch_size = min(max(args.limit * 2, 50), 250)
    raw = call_himalaya(args.folder, fetch_size)
    envelopes = parse_himalaya_table(raw)
    envelopes = filter_envelopes(envelopes, args.unseen_only, args.since_hours)
    envelopes = envelopes[: args.limit]

    if args.plain:
        print(f"# {len(envelopes)} envelope(s) from {args.folder!r}")
        for e in envelopes:
            mark = "📩" if not e.is_seen else "  "
            print(f"{mark} [{e.id}] {e.subject} — {e.sender} ({e.date})")
    else:
        print(
            json.dumps(
                {
                    "folder": args.folder,
                    "count": len(envelopes),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "envelopes": [asdict(e) for e in envelopes],
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
