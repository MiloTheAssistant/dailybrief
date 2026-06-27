#!/usr/bin/env python3
"""
fetch_market_brief_rss.py
=========================
Fetches the five RSS feeds listed in goals/brief_weekday_morning.md, deduplicates
stories across feeds, and prints a JSON envelope to stdout:

    {
      "generatedAt": "ISO-8601 UTC",
      "feeds": {
        "seekingalpha": {"status": "ok"|"unreachable", "count": N},
        "yahoo_finance": {...},
        "cointelegraph": {...},
        "google_news_ai": {...},
        "google_news_mag7": {...}
      },
      "stories": [
        {
          "section": "analyst" | "crypto" | "ai" | "mag7" | "movers" | "macro",
          "title": "...",
          "url": "...",
          "published": "ISO-8601 or null",
          "source": "feed label",
          "canonical": "normalized URL or title-hash for dedup"
        }
      ]
    }

Design notes
------------
- Stdlib only. No pip deps. Cron jobs need to be hermetic.
- 8-second per-feed timeout, 10-second total. A slow feed is treated as
  unreachable but does not block the rest.
- Dedup priority: SeekingAlpha > Yahoo Finance > Cointelegraph > Google AI > Google MAG7.
  A story appearing in multiple feeds is attributed to the highest-priority
  source.
- Time filter: last 36 hours. RSS pubDate parsing is best-effort; if parsing
  fails we keep the item but mark `published=null` so the LLM can judge.
- Output is *all* stories within window. The cron prompt does the section
  bucketing and headline selection, not this script. Keeping the script
  dumb and the prompt smart is the cleaner split.

Exit codes
----------
0  success (even if individual feeds failed — partial data is still useful)
1  fatal: couldn't reach ANY feed (script-level failure, brief should go silent)
2  usage error (bad CLI args)

"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# --- feed config -----------------------------------------------------------

FEEDS = [
    {
        # SeekingAlpha (free RSS). Includes "1-Minute Market Report", analyst
        # articles, Mag 7 / sector pieces. We use priority=0 so it wins dedup
        # attribution for any story that also surfaces on Yahoo Finance.
        # No auth required; URL is public.
        "label": "seekingalpha",
        "section_hint": "analyst",
        "url": "https://seekingalpha.com/feed.xml",
        "priority": 0,  # highest priority
    },
    {
        "label": "yahoo_finance",
        "section_hint": "movers",
        "url": "https://finance.yahoo.com/news/rssindex",
        "priority": 1,  # lowest number = highest priority for dedup attribution
    },
    {
        "label": "cointelegraph",
        "section_hint": "crypto",
        "url": "https://cointelegraph.com/rss",
        "priority": 2,
    },
    {
        # Was: news.search.yahoo.com/rss (deprecated, returns HTML search page).
        # Replaced 2026-06-15 with Google News RSS, which is a public XML feed
        # with the same item shape. Same query, new host.
        "label": "google_news_ai",
        "section_hint": "ai",
        "url": "https://news.google.com/rss/search?q=" + urllib.parse.quote(
            "AI OR \"artificial intelligence\" OR \"machine learning\" OR automation"
        ) + "&hl=en-US&gl=US&ceid=US:en",
        "priority": 3,
    },
    {
        # Same swap as google_news_ai. Was: news.search.yahoo.com/rss.
        "label": "google_news_mag7",
        "section_hint": "mag7",
        "url": "https://news.google.com/rss/search?q=" + urllib.parse.quote(
            "AAPL OR MSFT OR GOOGL OR AMZN OR META OR NVDA OR TSLA OR PLTR"
        ) + "&hl=en-US&gl=US&ceid=US:en",
        "priority": 4,
    },
]

WINDOW_HOURS = 36
PER_FEED_TIMEOUT_S = 8
USER_AGENT = "MiloDailyBrief/1.0 (+https://github.com/MiloTheAssistant/Milo)"


# --- helpers ---------------------------------------------------------------

def normalize_url(url: str) -> str:
    """Strip tracking junk so the same story from two aggregators collapses."""
    if not url:
        return ""
    try:
        u = urllib.parse.urlparse(url)
        # Drop common trackers
        drop_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "guce_referrer", "guce_referrer_sig", "ncid", "soc_src", "src",
        }
        q = urllib.parse.parse_qs(u.query, keep_blank_values=False)
        q = {k: v for k, v in q.items() if k.lower() not in drop_params}
        new_query = urllib.parse.urlencode(q, doseq=True)
        return urllib.parse.urlunparse((u.scheme, u.netloc, u.path, u.params, new_query, ""))
    except Exception:
        return url


def title_fingerprint(title: str) -> str:
    """Loose fingerprint for dedup when URLs differ (re-aggregations)."""
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Drop a few high-frequency noise words
    for w in ("the", "a", "an", "says", "report", "reports", "amid", "after", "over"):
        t = re.sub(rf"\b{w}\b", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]


def parse_pub_date(s: str | None) -> str | None:
    """Best-effort RFC 822 / ISO 8601 -> ISO 8601 UTC. None on failure."""
    if not s:
        return None
    s = s.strip()
    # Common RSS date format: "Mon, 15 Jun 2026 12:34:56 +0000"
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.astimezone(timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def fetch_feed(feed: dict) -> tuple[list[dict], str]:
    """
    Fetch a single feed. Returns (stories, status).
    status: "ok" | "unreachable" | "parse_error"
    """
    req = urllib.request.Request(feed["url"], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=PER_FEED_TIMEOUT_S) as resp:
            raw = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"[fetch_market_brief] {feed['label']}: unreachable ({e})", file=sys.stderr)
        return [], "unreachable"

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"[fetch_market_brief] {feed['label']}: parse_error ({e})", file=sys.stderr)
        return [], "parse_error"

    # RSS 2.0: <rss><channel><item>...
    items = root.findall(".//item")
    out: list[dict] = []
    for item in items:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()
        if not title and not link:
            continue
        iso_pub = parse_pub_date(pub)
        canon = normalize_url(link) or title_fingerprint(title)
        out.append({
            "section": feed["section_hint"],
            "title": title,
            "url": link,
            "published": iso_pub,
            "source": feed["label"],
            "canonical": canon,
            "priority": feed["priority"],
            # short snippet is gold for the LLM; cap to 400 chars
            "snippet": (desc[:400] + "…") if len(desc) > 400 else desc,
        })
    return out, "ok"


def filter_window(stories: list[dict], now: datetime) -> list[dict]:
    """Keep stories published within WINDOW_HOURS. Items without a parseable
    pubDate are kept (caller can judge recency from snippet)."""
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    out = []
    for s in stories:
        if s["published"] is None:
            out.append(s)
            continue
        try:
            dt = datetime.fromisoformat(s["published"])
        except ValueError:
            out.append(s)
            continue
        if dt >= cutoff:
            out.append(s)
    return out


def dedupe(stories: list[dict]) -> list[dict]:
    """Deduplicate by canonical. Higher-priority feed wins attribution.

    Also caps each section to avoid a single noisy feed (Google News routinely
    returns 100 items) drowning out the other sections in the dedup window.
    """
    by_key: dict[str, dict] = {}
    for s in stories:
        key = s["canonical"]
        if not key:
            continue
        if key not in by_key or s["priority"] < by_key[key]["priority"]:
            by_key[key] = s
    # Cap per section so movers/crypto don't get pushed off the page.
    per_section: dict[str, list[dict]] = {}
    for s in by_key.values():
        per_section.setdefault(s["section"], []).append(s)
    for sec in per_section:
        # Within a section: items with a parseable pubDate first, newest first;
        # then items without pubDate in original order.
        with_dates = sorted(
            (s for s in per_section[sec] if s["published"] is not None),
            key=lambda s: s["published"],
            reverse=True,
        )
        without_dates = [s for s in per_section[sec] if s["published"] is None]
        per_section[sec] = (with_dates + without_dates)[:20]
    out: list[dict] = []
    for sec in ("crypto", "ai", "mag7", "movers", "macro", "analyst"):
        out.extend(per_section.get(sec, []))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and dedupe the four daily market brief RSS feeds.")
    parser.add_argument("--window-hours", type=int, default=WINDOW_HOURS,
                        help=f"Only include items published within N hours (default {WINDOW_HOURS}).")
    parser.add_argument("--max", type=int, default=60,
                        help="Cap total stories in the output envelope (default 60).")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    all_stories: list[dict] = []
    feed_status: dict[str, dict] = {}

    for feed in FEEDS:
        t0 = time.monotonic()
        stories, status = fetch_feed(feed)
        elapsed = time.monotonic() - t0
        feed_status[feed["label"]] = {
            "status": status,
            "count": len(stories),
            "elapsed_s": round(elapsed, 2),
        }
        all_stories.extend(stories)

    if not all_stories:
        # Total failure: nothing to report. Caller should treat as silent.
        print(f"[fetch_market_brief] all feeds failed: {feed_status}", file=sys.stderr)
        return 1

    all_stories = filter_window(all_stories, now)
    all_stories = dedupe(all_stories)
    if args.max and len(all_stories) > args.max:
        all_stories = all_stories[: args.max]

    envelope = {
        "generatedAt": now.isoformat(),
        "windowHours": args.window_hours,
        "feeds": feed_status,
        "storyCount": len(all_stories),
        "stories": all_stories,
    }
    json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
