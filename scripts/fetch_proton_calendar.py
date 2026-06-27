#!/usr/bin/env python3
"""
fetch_proton_calendar.py — pull events from a Proton Calendar iCal share URL.

Reads the .ics URL from ~/.config/hermes/proton-calendar-url (chmod 600)
and returns events overlapping a given date range as JSON.

Proton exposes calendar sharing as an iCal (.ics) feed at:
    https://calendar.proton.me/api/calendar/v1/url/<id>/<token>/calendar.ics
The URL itself IS the credential — anyone with it can read the calendar.
Store in a file with chmod 600, NEVER in committed code or .env.

Args:
    --from-date YYYY-MM-DD     Range start (default: today, local timezone)
    --to-date YYYY-MM-DD       Range end (default: --from-date + 1 day)
    --days N                   Range length in days (default: 1; ignored if --to-date set)
    --calendar-url-file PATH   Override the default URL file path
    --timezone TZ              IANA tz for output timestamps (default: America/Chicago)
    --plain                    Human-readable output (default: JSON)

Output JSON shape:
    {
      "fetched_at": "2026-06-27T...",
      "range": {"from": "2026-06-27", "to": "2026-06-28"},
      "calendar_name": "My calendar",
      "calendar_tz": "America/Chicago",
      "event_count": 0,
      "events": [
        {
          "uid": "...",
          "summary": "Lunch with Sarah",
          "description": "...",
          "location": "...",
          "start": "2026-06-27T12:00:00-05:00",
          "end": "2026-06-27T13:00:00-05:00",
          "all_day": false,
          "status": "CONFIRMED"
        }
      ]
    }

Exit codes:
    0 = success
    2 = URL file missing or unreadable
    3 = URL file contains no URL (or only comments)
    4 = iCal fetch failed (network / 4xx / 5xx)
    5 = iCal parse failed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import icalendar
from icalendar.prop import vDDDLists, vText


DEFAULT_URL_FILE = os.path.expanduser("~/.config/hermes/proton-calendar-url")
DEFAULT_TZ = "America/Chicago"


@dataclass
class CalEvent:
    uid: str
    summary: str
    description: str
    location: str
    start: str
    end: str
    all_day: bool
    status: str
    organizer: str = ""


def load_url(url_file: str) -> str:
    """Read the .ics URL from the configured file. Strips comments and whitespace."""
    if not os.path.exists(url_file):
        print(f"fetch_proton_calendar: URL file not found: {url_file}", file=sys.stderr)
        print(
            f"  Create one with: echo '<your_ics_url>' > {url_file} && chmod 600 {url_file}",
            file=sys.stderr,
        )
        sys.exit(2)
    if not os.access(url_file, os.R_OK):
        print(f"fetch_proton_calendar: URL file not readable: {url_file}", file=sys.stderr)
        sys.exit(2)

    with open(url_file) as f:
        for raw_line in f:
            line = raw_line.strip()
            # Skip blank lines and comments
            if not line or line.startswith("#"):
                continue
            return line

    print(f"fetch_proton_calendar: URL file is empty (or only comments): {url_file}", file=sys.stderr)
    sys.exit(3)


def fetch_ics(url: str) -> bytes:
    """GET the iCal feed via urllib. Timeout 30s."""
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-fetch-proton-calendar/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            if resp.status != 200:
                print(
                    f"fetch_proton_calendar: HTTP {resp.status} from Proton",
                    file=sys.stderr,
                )
                sys.exit(4)
            return body
    except urllib.error.HTTPError as e:
        print(f"fetch_proton_calendar: HTTP {e.code} {e.reason}", file=sys.stderr)
        print(f"  URL may be revoked — regenerate via calendar.proton.me → Share", file=sys.stderr)
        sys.exit(4)
    except urllib.error.URLError as e:
        print(f"fetch_proton_calendar: network error: {e.reason}", file=sys.stderr)
        sys.exit(4)


def parse_ics(raw: bytes) -> tuple[str, str, list[CalEvent]]:
    """Parse iCal bytes → (calendar_name, calendar_tz, [events])."""
    try:
        cal = icalendar.Calendar.from_ical(raw)
    except (ValueError, TypeError) as e:
        print(f"fetch_proton_calendar: iCal parse failed: {e}", file=sys.stderr)
        sys.exit(5)

    name = str(cal.get("X-WR-CALNAME", ""))
    tz_name = str(cal.get("X-WR-TIMEZONE", ""))

    events: list[CalEvent] = []
    for component in cal.walk("VEVENT"):
        events.append(_component_to_event(component))

    return name, tz_name, events


def _to_iso(value: Any) -> str:
    """Convert an icalendar date/datetime value to ISO 8601 string."""
    if isinstance(value, datetime):
        # icalendar gives us tz-aware or naive datetimes. Keep tz if present.
        if value.tzinfo is None:
            # Naive datetime — assume UTC and tag as Z
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()
    if isinstance(value, date):
        # All-day events: value is a `date`, not `datetime`
        return value.isoformat()
    return str(value)


def _component_to_event(comp: Any) -> CalEvent:
    """Convert a VEVENT component to a CalEvent dataclass."""
    summary = comp.get("SUMMARY")
    description = comp.get("DESCRIPTION")
    location = comp.get("LOCATION")
    status = comp.get("STATUS")
    uid = comp.get("UID")
    organizer = comp.get("ORGANIZER")

    # icalendar returns `vDDDTypes` wrappers for date-valued properties.
    # The `.dt` attribute is the underlying date/datetime, but Pyright can't
    # see it. Use getattr with a default to keep Pyright quiet AND to handle
    # the rare case where the wrapper exists but `.dt` is missing.
    dtstart_raw = comp.get("DTSTART")
    dtend_raw = comp.get("DTEND")
    duration_raw = comp.get("DURATION")

    def _dt(value: Any) -> Any:
        if value is None:
            return None
        return getattr(value, "dt", value)

    dtstart = _dt(dtstart_raw)
    dtend = _dt(dtend_raw)
    duration = _dt(duration_raw)

    # All-day events: DTSTART is a `date` (not `datetime`)
    is_all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)

    start_iso = _to_iso(dtstart) if dtstart else ""
    end_iso = _to_iso(dtend) if dtend else ""

    if not end_iso and duration:
        # Some events use DURATION instead of DTEND. Compute end from start+duration.
        try:
            if is_all_day and isinstance(dtstart, date):
                end_iso = (dtstart + duration).isoformat()
            elif isinstance(dtstart, datetime):
                end_iso = (dtstart + duration).isoformat()
        except (AttributeError, TypeError):
            end_iso = ""

    return CalEvent(
        uid=str(uid) if uid else "",
        summary=str(summary) if summary else "",
        description=str(description) if description else "",
        location=str(location) if location else "",
        start=start_iso,
        end=end_iso,
        all_day=is_all_day,
        status=str(status) if status else "",
        organizer=str(organizer) if organizer else "",
    )


def filter_by_range(events: list[CalEvent], from_d: date, to_d: date, tz: ZoneInfo) -> list[CalEvent]:
    """Keep events that overlap [from_d 00:00 local, to_d+1 00:00 local)."""
    # Inclusive end: events that start on to_d are included.
    range_start = datetime.combine(from_d, time.min, tzinfo=tz)
    range_end_exclusive = datetime.combine(to_d + timedelta(days=1), time.min, tzinfo=tz)

    out: list[CalEvent] = []
    for ev in events:
        try:
            start = datetime.fromisoformat(ev.start)
            end = datetime.fromisoformat(ev.end) if ev.end else start
        except ValueError:
            # Skip events with unparseable timestamps
            continue

        # Make timezone-aware if naive (treat as UTC, then convert to target tz)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        start_local = start.astimezone(tz)
        end_local = end.astimezone(tz)

        # Overlap test: event overlaps if start < range_end AND end > range_start
        if start_local < range_end_exclusive and end_local > range_start:
            # Re-render start/end in the requested tz for clean output
            ev_copy = CalEvent(**asdict(ev))
            ev_copy.start = start_local.isoformat()
            ev_copy.end = end_local.isoformat()
            out.append(ev_copy)

    # Sort by start time
    out.sort(key=lambda e: e.start)
    return out


def render_plain(result: dict[str, Any]) -> None:
    """Human-readable output for debugging."""
    print(f"# {result['calendar_name']} ({result['calendar_tz']})")
    print(f"# Range: {result['range']['from']} → {result['range']['to']}")
    print(f"# Fetched: {result['fetched_at']}")
    print(f"# Events: {result['event_count']}")
    for ev in result["events"]:
        day = ev["start"][:10]
        time_str = ev["start"][11:16] if "T" in ev["start"] else "(all day)"
        end_str = f"–{ev['end'][11:16]}" if ("T" in ev["end"] and ev["end"][11:16] != "00:00") else ""
        marker = "📅" if ev["all_day"] else "🕐"
        print(f"  {marker} {day} {time_str}{end_str}  {ev['summary']}")
        if ev["location"]:
            print(f"         📍 {ev['location']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pull events from Proton Calendar iCal share URL as JSON"
    )
    parser.add_argument("--from-date", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--to-date", default=None, help="YYYY-MM-DD (default: from + N days)")
    parser.add_argument("--days", type=int, default=1, help="Range length in days (default: 1)")
    parser.add_argument(
        "--calendar-url-file",
        default=DEFAULT_URL_FILE,
        help=f"Path to iCal URL file (default: {DEFAULT_URL_FILE})",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TZ,
        help=f"IANA timezone for output (default: {DEFAULT_TZ})",
    )
    parser.add_argument("--plain", action="store_true")
    args = parser.parse_args()

    try:
        tz = ZoneInfo(args.timezone)
    except Exception as e:
        print(f"fetch_proton_calendar: invalid timezone {args.timezone!r}: {e}", file=sys.stderr)
        return 1

    from_d = date.fromisoformat(args.from_date) if args.from_date else datetime.now(tz).date()
    to_d = date.fromisoformat(args.to_date) if args.to_date else from_d + timedelta(days=args.days - 1)

    url = load_url(args.calendar_url_file)
    raw = fetch_ics(url)
    cal_name, cal_tz, all_events = parse_ics(raw)
    in_range = filter_by_range(all_events, from_d, to_d, tz)

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "range": {"from": from_d.isoformat(), "to": to_d.isoformat()},
        "calendar_name": cal_name,
        "calendar_tz": cal_tz or args.timezone,
        "event_count": len(in_range),
        "events": [asdict(e) for e in in_range],
    }

    if args.plain:
        render_plain(result)
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
