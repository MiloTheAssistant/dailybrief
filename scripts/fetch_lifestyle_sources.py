#!/usr/bin/env python3
"""
fetch_lifestyle_sources.py
==========================
Fetches lifestyle data for the Saturday + Sunday Lifestyle Briefs
(see goals/brief_saturday.md, goals/brief_sunday.md).

Currently sources:
- National Weather Service forecast for any US lat/lon.

Default location is Eureka, MO 63025 (lat 38.5017, lon -90.6276)
which lands in NWS gridpoint LSX/80,68 (St. Louis office). Pass
--lat/--lon/--label to override.

CLI:
    python3 scripts/fetch_lifestyle_sources.py
    python3 scripts/fetch_lifestyle_sources.py --lat 41.8781 --lon -87.6298 --label "Chicago, IL"

Output envelope (JSON to stdout):
    {
      "generatedAt": "ISO-8601 UTC",
      "location": {"label": "Eureka, MO", "lat": 38.5017, "lon": -90.6276},
      "sources": {
        "weather": {"status": "ok"|"unreachable", "elapsed_s": null}
      },
      "data": {
        "weather": {
          "city": "Eureka, MO",
          "gridpoint": "LSX/80,68",
          "today": {
            "name": "Today",
            "temperature": 78,
            "temperatureUnit": "F",
            "windSpeed": "5 mph",
            "windDirection": "NW",
            "shortForecast": "Partly Sunny",
            "detailedForecast": "...",
            "precipChance": 20
          },
          "tonight": {...},
          "tomorrow": {...}
        }
      }
    }

Stdlib only. NWS endpoints are public, no auth.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

NWS_API = "https://api.weather.gov"
USER_AGENT = "MiloLifestyleBrief/2.0 (+https://github.com/MiloTheAssistant/dailybrief)"

# Defaults: Eureka, MO 63025 (St. Louis metro). NWS gridpoint LSX/80,68.
DEFAULT_LAT = 38.5017
DEFAULT_LON = -90.6276
DEFAULT_LABEL = "Eureka, MO"


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


def fetch_weather(lat: float, lon: float, label: str) -> tuple[dict | None, str, float]:
    """Returns (weather_data_or_none, status_string, elapsed_seconds)."""
    t0 = time.monotonic()

    points_url = f"{NWS_API}/points/{lat},{lon}"
    points = http_get(points_url)
    if not points or "properties" not in points:
        return None, "unreachable", time.monotonic() - t0

    props = points["properties"]
    forecast_url = props.get("forecast")
    if not forecast_url:
        return None, "no_forecast_url", time.monotonic() - t0

    forecast = http_get(forecast_url)
    if not forecast or "properties" not in forecast:
        return None, "unreachable", time.monotonic() - t0

    periods = forecast["properties"].get("periods", [])
    if not periods:
        return None, "no_periods", time.monotonic() - t0

    # Bucket periods into today/tonight/tomorrow buckets.
    today = None
    tonight = None
    tomorrow = None
    for p in periods[:6]:
        name = p.get("name", "")
        bucket = None
        if re.match(r"^(this\s+afternoon|today)$", name, re.IGNORECASE):
            bucket = "today"
        elif re.match(r"^(tonight|this\s+evening)$", name, re.IGNORECASE):
            bucket = "tonight"
        elif re.match(r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$", name, re.IGNORECASE):
            bucket = "tomorrow" if tomorrow is None else None
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
        "city": label,
        "gridpoint": f"{props.get('gridId', '')}/{props.get('gridX', '')},{props.get('gridY', '')}",
        "today": today,
        "tonight": tonight,
        "tomorrow": tomorrow,
        "rawPeriodCount": len(periods),
    }, "ok", time.monotonic() - t0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch lifestyle sources (weather) for the lifestyle brief.")
    p.add_argument("--lat", type=float, default=DEFAULT_LAT,
                   help=f"Latitude (default: {DEFAULT_LAT} for Eureka, MO 63025)")
    p.add_argument("--lon", type=float, default=DEFAULT_LON,
                   help=f"Longitude (default: {DEFAULT_LON} for Eureka, MO 63025)")
    p.add_argument("--label", default=DEFAULT_LABEL,
                   help=f"Display label for the location (default: '{DEFAULT_LABEL}')")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    now = datetime.now(timezone.utc)

    sources: dict[str, dict] = {}
    data: dict = {}

    weather, status, elapsed = fetch_weather(args.lat, args.lon, args.label)
    sources["weather"] = {"status": status, "elapsed_s": round(elapsed, 2)}
    if status == "ok":
        data["weather"] = weather

    envelope = {
        "generatedAt": now.isoformat(),
        "location": {"label": args.label, "lat": args.lat, "lon": args.lon},
        "sources": sources,
        "data": data,
    }
    json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    # Soft-fail: weather unreachable returns 0 — the LLM prompt falls back to
    # web_search gracefully. Hard-failing would block the whole brief.
    return 0


if __name__ == "__main__":
    sys.exit(main())
