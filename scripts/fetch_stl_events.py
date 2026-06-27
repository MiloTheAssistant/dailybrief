#!/usr/bin/env python3
"""
fetch_stl_events.py
===================
Fetches upcoming St. Louis-area events for the Saturday + Sunday
Lifestyle Briefs (see goals/brief_saturday.md, goals/brief_sunday.md).

Single source: ExploreStL.com (the official STL Convention &
Visitors Commission site). Lightweight HTML fetch + parse; no JS,
no scraping across multiple sites.

CLI:
    python3 scripts/fetch_stl_events.py
    python3 scripts/fetch_stl_events.py --limit 5
    python3 scripts/fetch_stl_events.py --offline   # curated fallback only

Output envelope (JSON to stdout):
    {
      "generatedAt": "ISO-8601 UTC",
      "sources": {
        "explorestl": {"status": "ok"|"unreachable"|"disabled", "elapsed_s": ...}
      },
      "data": {
        "events": [
          {"title": "...", "url": "...", "dateLabel": "Jun 27 – Jul 5", "venue": "..."}
        ]
      }
    }

Stdlib only. Soft-fails to curated list when offline.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timezone

USER_AGENT = "MiloLifestyleBrief/1.0 (+https://github.com/MiloTheAssistant/dailybrief)"

EXPLORESTL_LIST_URL = "https://www.explorestlouis.com/events/list/?eventDisplay=list"


def http_get(url: str) -> str | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"[fetch_stl_events] GET {url}: {e}", file=sys.stderr)
        return None


def parse_explorestl(html: str) -> list[dict]:
    """
    Pull events out of ExploreSTL list-page HTML. The Events Calendar
    plugin wraps each event in a `tribe-events-calendar-list__event`
    article tag. We grab title, URL, and any nearby date label.
    """
    events: list[dict] = []
    # Each event is wrapped in <article ... class="...tribe-events-calendar-list__event...">...</article>
    article_re = re.compile(
        r'<article[^>]*class="[^"]*tribe-events-calendar-list__event[^"]*"[^>]*>(.*?)</article>',
        re.DOTALL | re.IGNORECASE,
    )
    title_re = re.compile(
        r'<a[^>]*class="[^"]*tribe-events-calendar-list__event-title[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    venue_re = re.compile(
        r'<span[^>]*class="[^"]*tribe-venue[^"]*"[^>]*>(.*?)</span>',
        re.DOTALL | re.IGNORECASE,
    )
    date_re = re.compile(
        r'<time[^>]*datetime="([^"]+)"[^>]*>(.*?)</time>',
        re.DOTALL | re.IGNORECASE,
    )

    for article in article_re.findall(html):
        title_match = title_re.search(article)
        if not title_match:
            continue
        url = title_match.group(1)
        raw_title = title_match.group(2)
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        title = re.sub(r"\s+", " ", title)
        if not title:
            continue

        venue_match = venue_re.search(article)
        venue = ""
        if venue_match:
            venue = re.sub(r"<[^>]+>", "", venue_match.group(1)).strip()
            venue = re.sub(r"\s+", " ", venue)

        date_match = date_re.search(article)
        date_label = ""
        if date_match:
            # datetime attr is ISO; inner text is human-readable ("Jun 27 @ 7pm")
            inner = re.sub(r"<[^>]+>", "", date_match.group(2)).strip()
            inner = re.sub(r"\s+", " ", inner)
            date_label = inner

        events.append({
            "title": title,
            "url": url,
            "dateLabel": date_label,
            "venue": venue,
        })
    return events


def curated_fallback(limit: int) -> list[dict]:
    """Always-on STL picks, used when live fetcher is offline."""
    picks = [
        {
            "title": "St. Louis Art Museum",
            "url": "https://www.slam.org/",
            "dateLabel": "Always open",
            "venue": "Forest Park",
        },
        {
            "title": "Missouri Botanical Garden",
            "url": "https://www.missouribotanicalgarden.org/",
            "dateLabel": "Daily",
            "venue": "4344 Shaw Blvd",
        },
        {
            "title": "City Museum",
            "url": "https://www.citymuseum.org/",
            "dateLabel": "Daily",
            "venue": "750 N 16th St",
        },
        {
            "title": "Gateway Arch + Museum",
            "url": "https://www.gatewayarch.com/",
            "dateLabel": "Daily",
            "venue": "Downtown STL riverfront",
        },
        {
            "title": "Soulard Farmers Market",
            "url": "https://www.soulardmarket.com/",
            "dateLabel": "Saturday mornings",
            "venue": "730 Carroll St",
        },
        {
            "title": "Tower Grove Park Farmers Market",
            "url": "https://tgfarmersmarket.com/",
            "dateLabel": "Saturday mornings (Apr–Nov)",
            "venue": "Tower Grove Park",
        },
    ]
    return picks[:limit]


def fetch_events(limit: int) -> tuple[list[dict], str, float]:
    """
    Returns (events, status, elapsed_s).
    status is "ok", "unreachable", or "fallback".
    """
    t0 = time.monotonic()
    html = http_get(EXPLORESTL_LIST_URL)
    if html is None:
        return curated_fallback(limit), "unreachable", time.monotonic() - t0

    events = parse_explorestl(html)
    elapsed = time.monotonic() - t0
    if not events:
        return curated_fallback(limit), "fallback", elapsed

    return events[:limit], "ok", elapsed


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch St. Louis-area events.")
    p.add_argument("--limit", type=int, default=5,
                   help="Max events to return (default: 5)")
    p.add_argument("--offline", action="store_true",
                   help="Skip live fetch, return curated fallback only")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    now = datetime.now(timezone.utc)

    if args.offline:
        events = curated_fallback(args.limit)
        sources = {"explorestl": {"status": "disabled", "elapsed_s": 0.0}}
    else:
        events, status, elapsed = fetch_events(args.limit)
        sources = {"explorestl": {"status": status, "elapsed_s": round(elapsed, 2)}}

    envelope = {
        "generatedAt": now.isoformat(),
        "sources": sources,
        "data": {"events": events},
    }
    json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
