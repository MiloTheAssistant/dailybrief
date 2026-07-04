#!/usr/bin/env python3
"""Tests for fetch_market_brief_rss.py CLI window handling."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

import fetch_market_brief_rss  # noqa: E402


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
        return fixed if tz is None else fixed.astimezone(tz)


def test_window_hours_argument_controls_recency_filter(monkeypatch, capsys):
    """--window-hours 168 should retain a story that is 100 hours old."""
    now = FixedDateTime.now(timezone.utc)
    story = {
        "section": "mag7",
        "title": "A 100-hour-old but still weekly-relevant story",
        "url": "https://example.com/story",
        "published": (now - timedelta(hours=100)).isoformat(),
        "source": "example",
        "canonical": "https://example.com/story",
        "priority": 0,
        "snippet": "weekly context",
    }

    monkeypatch.setattr(fetch_market_brief_rss, "FEEDS", [{"label": "example"}])
    monkeypatch.setattr(fetch_market_brief_rss, "datetime", FixedDateTime)
    monkeypatch.setattr(
        fetch_market_brief_rss,
        "fetch_feed",
        lambda _feed: ([story], "ok"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["fetch_market_brief_rss.py", "--window-hours", "168", "--max", "10"],
    )

    assert fetch_market_brief_rss.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["windowHours"] == 168
    assert payload["storyCount"] == 1
    assert payload["stories"][0]["title"] == story["title"]
