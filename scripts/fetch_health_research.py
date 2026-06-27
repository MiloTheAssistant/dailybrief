#!/usr/bin/env python3
"""
fetch_health_research.py
========================
Pulls the last 14 days of RSS items from a curated set of medical
journals, then keyword-filters for men-over-60 relevant topics:
longevity, cardiac, strength training, TRT, GLP-1, nutrition, sleep.

Used by the Weekend Executive Brief for the Health pillar.

Stdlib-only. No API keys. Falls back gracefully when offline.

Output (JSON envelope to stdout):
    {
      "generatedAt": "ISO-8601 UTC",
      "feeds": {
        "lancet": {"status": "ok"|"unreachable", "fetched": N, "matched": N},
        "nature_medicine": {...},
        "jama": {...}
      },
      "stories": [
        {
          "topic": "cardiac"|"longevity"|"glp-1"|"sleep"|"strength"|"trt"|"nutrition"|"other",
          "title": "...",
          "url": "...",
          "published": "ISO-8601 or null",
          "source": "feed label",
          "summary": "..." | null
        }
      ]
    }
"""

from __future__ import annotations
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# Curated RSS sources — high signal for men-over-60 health.
FEEDS = [
    ("lancet", "https://www.thelancet.com/rssfeed/lancet_online.xml"),
    ("nature_medicine", "https://www.nature.com/nm.rss"),
    ("jama", "https://jamanetwork.com/rss/site_3/searchRss?Query=jamanetwork&ContentGroupKey=&allJournals=true&SortBy=0&StartPage=0&PageCount=50"),
]

# Topic keywords — map raw title to a topic bucket.
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "cardiac":   ["heart", "cardiac", "cardiovascular", "stroke", "statin", "cholesterol", "blood pressure", "hypertension", "myocardial", "atrial", "coronary"],
    "longevity": ["longevity", "lifespan", "life expectancy", "aging", "age-related", "senescence", "biological age", "frailty"],
    "glp-1":     ["glp-1", "glp1", "semaglutide", "tirzepatide", "ozempic", "wegovy", "mounjaro", "incretin"],
    "sleep":     ["sleep", "circadian", "insomnia", "rem sleep", "apnea"],
    "strength":  ["strength train", "resistance train", "muscle mass", "sarcopenia", "frailty", "weight train", "lean mass"],
    "trt":       ["testosterone", " trt ", "androgen", "low t"],
    "nutrition": ["diet", "nutrition", "protein", "mediterranean", "intermittent fast", "caloric restrict", "omega-3", "supplement"],
    "other":     [],
}


def _http_get(url: str, user_agent: str = "Milo/1.0", timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _parse_pub(entry: ET.Element) -> str | None:
    """Pull pubDate or dc:date from a feed entry."""
    for tag in ("pubDate", "published", "{http://purl.org/dc/elements/1.1/}date"):
        el = entry.find(tag)
        if el is not None and el.text:
            return el.text.strip()
    return None


def _classify(title: str, summary: str | None) -> str:
    haystack = (title + " " + (summary or "")).lower()
    best_topic = "other"
    best_count = 0
    for topic, kws in TOPIC_KEYWORDS.items():
        if topic == "other":
            continue
        cnt = sum(1 for k in kws if k in haystack)
        if cnt > best_count:
            best_count = cnt
            best_topic = topic
    return best_topic


def fetch_feed(name: str, url: str, cutoff: datetime) -> tuple[dict, list[dict]]:
    """Pull + parse one RSS feed. Returns (status_envelope, matched_items).

    Handles RSS 2.0 (<item>), Atom (<entry>), and RSS 1.0 / RDF
    (<rdf:RDF> root, items in default namespace).
    """
    try:
        raw = _http_get(url, timeout=8)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        return ({"status": "unreachable", "error": str(e)[:200]}, [])

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return ({"status": "unreachable", "error": f"parse: {e}"}, [])

    # RSS 2.0 <item>, Atom <entry>, RSS 1.0 default-namespace <item>.
    # `root.iter("{ns}item")` requires exact prefix match — combine the
    # candidates into one list to handle all three.
    candidates = list(root.iter("item"))
    candidates += list(root.iter("{http://purl.org/rss/1.0/}item"))
    candidates += list(root.iter("{http://www.w3.org/2005/Atom}entry"))
    # De-dupe (RDF feeds sometimes list the same item twice via rdf:li).
    seen_ids = set()
    items = []
    for el in candidates:
        key = id(el)
        if key in seen_ids:
            continue
        seen_ids.add(key)
        items.append(el)

    def _findtext(parent, *tags) -> str | None:
        for t in tags:
            el = parent.find(t)
            if el is not None and el.text:
                return el.text.strip()
        # Fallback: iter (handles nested namespace variants).
        for t in tags:
            for el in parent.iter(t):
                if el.text:
                    return el.text.strip()
        return None

    fetched = 0
    matched = []
    for entry in items:
        fetched += 1
        title = _findtext(entry, "title", "{http://purl.org/rss/1.0/}title",
                          "{http://www.w3.org/2005/Atom}title")
        if not title:
            continue
        title = re.sub(r"\s+", " ", title).strip()

        link = _findtext(entry, "link", "{http://purl.org/rss/1.0/}link")
        if not link:
            # Atom uses <link href="..."/>.
            for le in entry.iter("{http://www.w3.org/2005/Atom}link"):
                href = le.attrib.get("href")
                if href:
                    link = href.strip()
                    break

        pub = _findtext(entry, "pubDate", "date",
                        "{http://purl.org/dc/elements/1.1/}date",
                        "{http://www.w3.org/2005/Atom}published")
        # Try to parse pubDate; if unparseable, include anyway (no cutoff filter).
        pub_dt = None
        if pub:
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub)
            except Exception:
                pass

        summary = _findtext(entry, "description", "{http://purl.org/rss/1.0/}description",
                            "{http://www.w3.org/2005/Atom}summary",
                            "{http://purl.org/rss/1.0/modules/content/}encoded")
        if summary:
            summary = re.sub(r"<[^>]+>", "", summary)
            summary = re.sub(r"\s+", " ", summary).strip()[:300]

        topic = _classify(title, summary)
        if topic == "other":
            continue  # skip items that don't match any men-over-60 topic

        if pub_dt and pub_dt < cutoff:
            continue  # older than 14 days

        matched.append({
            "topic": topic,
            "title": title,
            "url": link or "",
            "published": pub,
            "source": name,
            "summary": summary or None,
        })

    return ({"status": "ok", "fetched": fetched, "matched": len(matched)}, matched)


def main() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    envelopes = {}
    stories: list[dict] = []
    seen_titles: set[str] = set()
    for name, url in FEEDS:
        env, matched = fetch_feed(name, url, cutoff)
        envelopes[name] = env
        for item in matched:
            # Dedup by normalized title prefix.
            key = re.sub(r"\W+", "", item["title"].lower())[:80]
            if key in seen_titles:
                continue
            seen_titles.add(key)
            stories.append(item)

    # Stable order: most recent first (best-effort; many feeds lack parseable dates).
    def _sort_key(s):
        return s.get("published") or ""
    stories.sort(key=_sort_key, reverse=True)

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "ok" if stories else "empty",
        "cutoffDate": cutoff.isoformat(),
        "feeds": envelopes,
        "stories": stories[:30],  # cap to top 30 — cron will pick best 5-7
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
