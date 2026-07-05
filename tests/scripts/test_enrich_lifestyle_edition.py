#!/usr/bin/env python3
"""Tests for deterministic weekend lifestyle enrichment."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

import enrich_lifestyle_edition as enrich_lifestyle  # noqa: E402


def _assembled(day: str = "saturday") -> dict:
    weekday = "Saturday" if day == "saturday" else "Sunday"
    return {
        "date": "2026-07-04" if day == "saturday" else "2026-07-05",
        "weekday": weekday,
        "kind": "lifestyle",
        "generatedAt": "2026-07-04T12:00:00+00:00",
        "zip": "63025",
        "location": {"label": "Eureka, MO", "lat": 38.5017, "lon": -90.6276},
        "rawInputs": {
            "rss": {
                "stories": [
                    {
                        "section": "mag7",
                        "title": "Microsoft launches new AI infrastructure product - Example Wire",
                        "url": "https://example.com/msft",
                        "source": "google_news_mag7",
                    },
                    {
                        "section": "ai",
                        "title": "OpenAI releases agent workflow update - Example AI",
                        "url": "https://example.com/openai",
                        "source": "google_news_ai",
                    },
                    {
                        "section": "crypto",
                        "title": "Bitcoin treasury companies expand collateral programs - Example Crypto",
                        "url": "https://example.com/btc",
                        "source": "cointelegraph",
                    },
                ]
            },
            "health": {
                "stories": [
                    {
                        "topic": "cardiac",
                        "title": "Polypill improves heart-failure adherence",
                        "url": "https://example.com/heart",
                        "source": "nature_medicine",
                    }
                ]
            },
        },
        "pillars": {
            "weather": {
                "today": {"temperature": 88, "shortForecast": "Chance Showers", "precipChance": 60},
                "tonight": {"temperature": 70, "shortForecast": "Showers"},
                "tomorrow": {"temperature": 84, "shortForecast": "Partly Sunny"} if day == "saturday" else None,
                "whatToWear": None,
            },
            "life": {
                "calendarToday": [],
                "oneThing": None,
                "oneThingToPlan": None,
                "localPicks": [
                    {
                        "title": "Soulard Farmers Market",
                        "url": "https://example.com/market",
                        "dateLabel": "Saturday mornings",
                        "venue": "Soulard",
                    }
                ],
                "localPicksNextWeekend": None,
                "rec": None,
            },
            "vacation": {
                "upcomingTravel": [],
                "driveDistanceIdeas": [
                    {"name": "Grafton, IL", "blurb": "50 min. River town."},
                    {"name": "Branson, MO", "blurb": "4 hr. Shows."},
                ],
            },
            "retirement": {"portfolioState": {}, "planningNote": None},
            "executiveSummary": {"opportunities": None, "summaryBullets": None, "actionItems": None, "funFact": None},
            "markets": {
                "indicators": [
                    {"label": "S&P 500", "current": 6200, "changeWtd": "+1.2%", "source": "S&P 500"},
                    {"label": "10Y Treasury", "current": "4.20%", "changeWtd": "+5 bps", "source": "home.treasury.gov"},
                ],
                "whyParagraph": None,
            },
            "investingThemes": {"themes": None, "noMeaningfulNews": None},
            "retirementWatch": {"items": None, "noMeaningfulNews": None, "planningNote": None, "weekEndReflection": None},
            "aiLandscape": {"entries": None, "noMeaningfulNews": None},
            "health": {"entries": None, "noMeaningfulNews": None},
            "worthReading": {"articles": None, "videos": None, "podcasts": None},
        },
    }


def test_saturday_enrichment_fills_source_backed_fields():
    enriched = enrich_lifestyle.enrich_edition(_assembled("saturday"), "saturday")
    pillars = enriched["pillars"]

    assert pillars["weather"]["whatToWear"]
    assert pillars["life"]["oneThing"].startswith("Do the easiest real-world thing")
    assert pillars["retirement"]["planningNote"]
    assert pillars["markets"]["whyParagraph"]
    assert pillars["investingThemes"]["themes"][0]["ticker"] == "MSFT"
    assert pillars["aiLandscape"]["entries"][0]["company"] == "OpenAI"
    assert pillars["health"]["entries"][0]["topic"] == "cardiac"
    assert pillars["worthReading"]["articles"]
    assert pillars["executiveSummary"]["opportunities"]
    assert enriched["enrichment"]["strategy"] == "deterministic-lifestyle-v1"


def test_sunday_enrichment_uses_planning_and_reflection_fields():
    enriched = enrich_lifestyle.enrich_edition(_assembled("sunday"), "sunday")
    pillars = enriched["pillars"]

    assert pillars["life"]["oneThingToPlan"]
    assert pillars["life"]["localPicksNextWeekend"]
    assert pillars["retirement"]["weekEndReflection"]
    assert pillars["retirementWatch"]["weekEndReflection"]
    assert "upcomingTravel14d" in pillars["vacation"]
