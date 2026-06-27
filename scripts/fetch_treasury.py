#!/usr/bin/env python3
"""
fetch_treasury.py
=================
Fetches US Treasury daily yield curve (last ~10 days) and DXY from
Yahoo Finance chart API. Used by the Weekend Executive Brief for the
Markets pillar (S&P 500 / Nasdaq / BTC / Treasury Rates / U.S. Dollar).

Stdlib-only. No API keys. Falls back gracefully when offline.

Output (JSON envelope to stdout):
    {
      "generatedAt": "ISO-8601 UTC",
      "treasury": {
        "status": "ok"|"unreachable",
        "latestDate": "MM/DD/YYYY" | null,
        "yieldCurve": [
          {"date": "MM/DD/YYYY", "3m": 3.83, "2y": 4.07, "10y": 4.38, "30y": 4.87},
          ...
        ]
      },
      "indexQuotes": {
        "status": "ok"|"partial",
        "sp500":   {"price": ..., "change5dPct": ...} | null,
        "nasdaq":  {...} | null,
        "dxy":     {...} | null,
        "btc":     {...} | null
      }
    }
"""

from __future__ import annotations
import csv
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Where we put known-good output as a last-resort fallback when the
# upstream sources are unreachable. Stored locally so we never lose the
# brief entirely — gracefully degrade instead of [SILENT].
FALLBACK_PATH = Path(__file__).parent / "fallback_treasury.json"


def _http_get(url: str, user_agent: str = "Milo/1.0", timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_treasury() -> dict:
    """Pull daily Treasury yield curve, keep last 10 business days."""
    try:
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/daily-treasury-rates.csv/"
            f"{datetime.now(timezone.utc).year}/all"
            "?type=daily_treasury_yield_curve&field_tdr_date_value="
            f"{datetime.now(timezone.utc).year}&page&_format=csv"
        )
        csv_bytes = _http_get(url)
        text = csv_bytes.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for row in reader:
            try:
                rows.append({
                    "date": row.get("Date", "").strip(),
                    "1m":  _pct(row.get("1 Mo")),
                    "3m":  _pct(row.get("3 Mo")),
                    "6m":  _pct(row.get("6 Mo")),
                    "1y":  _pct(row.get("1 Yr")),
                    "2y":  _pct(row.get("2 Yr")),
                    "5y":  _pct(row.get("5 Yr")),
                    "10y": _pct(row.get("10 Yr")),
                    "30y": _pct(row.get("30 Yr")),
                })
            except Exception:
                continue
        rows = [r for r in rows if r["date"]][:10]  # CSV is newest-first; keep first 10
        return {
            "status": "ok" if rows else "unreachable",
            "latestDate": rows[0]["date"] if rows else None,
            "yieldCurve": rows,
            "source": "home.treasury.gov",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        return {"status": "unreachable", "error": str(e)[:200], "yieldCurve": [], "source": "home.treasury.gov"}


def fetch_index_chart(symbol: str) -> dict | None:
    """5-day Yahoo Finance chart for a single symbol."""
    try:
        import urllib.parse
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=5d"
        data = json.loads(_http_get(url, timeout=8))
        result = data["chart"]["result"][0]
        meta = result["meta"]
        closes = result["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if len(closes) < 2:
            return {"symbol": symbol, "price": meta.get("regularMarketPrice"), "change5dPct": None}
        first, last = closes[0], closes[-1]
        change_pct = ((last - first) / first) * 100 if first else None
        return {
            "symbol": symbol,
            "price": meta.get("regularMarketPrice"),
            "shortName": meta.get("shortName"),
            "longName": meta.get("longName"),
            "change5dPct": round(change_pct, 2) if change_pct is not None else None,
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)[:200]}


def _pct(s) -> float | None:
    if s is None:
        return None
    s = str(s).strip()
    if not s or s.upper() == "N/A":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main() -> int:
    treasury = fetch_treasury()
    index_symbols = {
        "sp500": "^GSPC",
        "nasdaq": "^IXIC",
        "dxy": "DX-Y.NYB",
        "btc": "BTC-USD",
    }
    index_quotes = {}
    for label, sym in index_symbols.items():
        index_quotes[label] = fetch_index_chart(sym)
        if index_quotes[label] and "error" in index_quotes[label]:
            # Mark partial on any failure but keep what we got.
            index_quotes["_status"] = "partial"

    status = "ok"
    if treasury["status"] != "ok":
        status = "partial"
    if index_quotes.get("_status") == "partial":
        status = "partial"

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "treasury": treasury,
        "indexQuotes": index_quotes,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
