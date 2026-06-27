#!/usr/bin/env python3
"""
fetch_lifestyle_sources.py
==========================
Fetches lifestyle data for the Daily Lifestyle Briefing
(see goals/daily_lifestyle_briefing.md).

Currently sources:
- National Weather Service forecast for Chicago (lat 41.8781, lon -87.6298)

Future sources (not yet wired — see open questions in the spec):
- Chicago weekend events (Do312 / Choose Chicago / etc.)
- Restaurant picks (Eater Chicago / Infatuation / etc.)

Output envelope (JSON to stdout):
    {
      "generatedAt": "ISO-8601 UTC",
      "sources": {
        "weather": {"status": "ok"|"unreachable", "data": {...} | null}
      },
      "data": {
        "weather": {
          "city": "Chicago, IL",
          "today": {
            "high_f": 78,
            "low_f": 62,
            "shortForecast": "Partly Sunny",
            "detailedForecast": "...",
            "precipChance": 20,
            "windSpeed": "5 mph",
            "windDirection": "NW"
          },
          "tonight": {...},
          "tomorrow": {...}
        }
      }
    }

Stdlib only. NWS endpoints are public, no auth.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

CHICAGO_LAT = 41.8781
CHICAGO_LON = -87.6298
NWS_API = "https://api.weather.gov"
USER_AGENT = "MiloLifestyleBrief/1.0 (+https://github.com/MiloTheAssistant/Milo)"


def http_get(url: str, accept: str = "application/geo+json") -> dict | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": accept,
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as e:
        print(f"[fetch_lifestyle] GET {url}: {e}", file=sys.stderr)
        return None


def fetch_chicago_weather() -> tuple[dict | None, str]:
    """Returns (weather_data_or_none, status_string)."""
    # Step 1: get the gridpoint for Chicago.
    points_url = f"{NWS_API}/points/{CHICAGO_LAT},{CHICAGO_LON}"
    points = http_get(points_url)
    if not points or "properties" not in points:
        return None, "unreachable"

    props = points["properties"]
    forecast_url = props.get("forecast")
    forecast_hourly_url = props.get("forecastHourly")
    if not forecast_url:
        return None, "no_forecast_url"

    forecast = http_get(forecast_url)
    if not forecast or "properties" not in forecast:
        return None, "unreachable"

    periods = forecast["properties"].get("periods", [])
    if not periods:
        return None, "no_periods"

    # Bucket periods into today/tonight/tomorrow buckets.
    today = None
    tonight = None
    tomorrow = None
    for p in periods[:6]:  # plenty of headroom; the API usually returns 14
        name = p.get("name", "")
        bucket = None
        if re.match(r"^(this\s+afternoon|today)$", name, re.IGNORECASE):
            bucket = "today"
        elif re.match(r"^(tonight|this\s+evening)$", name, re.IGNORECASE):
            bucket = "tonight"
        elif re.match(r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$", name, re.IGNORECASE):
            bucket = "tomorrow" if tomorrow is None else None  # only first
        if bucket is None:
            continue
        entry = {
            "name": name,
            "temperature": p.get("temperature"),
            "temperatureUnit": p.get("temperatureUnit", "F"),
            "windSpeed": p.get("windSpeed"),
            "windDirection": p.get("windDirection"),
            "shortForecast": p.get("shortForecast"),
            "detailedForecast": p.get("detailedForecast"),
            "precipChance": p.get("probabilityOfPrecipitation", {}).get("value") if isinstance(p.get("probabilityOfPrecipitation"), dict) else None,
        }
        if bucket == "today" and today is None:
            today = entry
        elif bucket == "tonight" and tonight is None:
            tonight = entry
        elif bucket == "tomorrow" and tomorrow is None:
            tomorrow = entry

    return {
        "city": "Chicago, IL",
        "gridpoint": props.get("gridId", "") + "/" + str(props.get("gridX", "")) + "," + str(props.get("gridY", "")),
        "today": today,
        "tonight": tonight,
        "tomorrow": tomorrow,
        "rawPeriodCount": len(periods),
    }, "ok"


def main() -> int:
    now = datetime.now(timezone.utc)
    sources: dict[str, dict] = {}
    data: dict = {}

    weather, status = fetch_chicago_weather()
    sources["weather"] = {"status": status, "elapsed_s": None}
    if status == "ok":
        data["weather"] = weather

    envelope = {
        "generatedAt": now.isoformat(),
        "sources": sources,
        "data": data,
    }
    json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    # Soft failure: if weather failed, return 0 anyway — the LLM prompt is
    # designed to gracefully fall back to web_search when fetcher data is
    # missing. Hard-failing on weather would prevent the brief from running
    # at all, which is worse than running with a hole.
    return 0


if __name__ == "__main__":
    sys.exit(main())
