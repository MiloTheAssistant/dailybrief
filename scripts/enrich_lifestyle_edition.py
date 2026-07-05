#!/usr/bin/env python3
"""Deterministically enrich Saturday/Sunday lifestyle editions.

The weekend publisher now follows the same ownership model as the weekday DFB:
Hermes schedules and supervises, while this repo authors the JSON. This script
fills the lifestyle brief's qualitative fields from source data already carried
inside the assembled edition. It does not call an LLM and it does not invent
facts when a source is thin.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _publish_common as pc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "out" / "lifestyle"

WATCHLIST: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("MSFT", "Microsoft", ("msft", "microsoft", "azure")),
    ("MSTR", "Strategy", ("mstr", "strategy", "microstrategy")),
    ("STRC", "STRC", ("strc",)),
    ("NVDA", "NVIDIA", ("nvda", "nvidia")),
    ("AAPL", "Apple", ("aapl", "apple", "iphone")),
    ("GOOGL", "Alphabet", ("googl", "alphabet", "google")),
    ("PLTR", "Palantir", ("pltr", "palantir")),
    ("BTC", "Bitcoin", ("bitcoin", "btc")),
    ("AI", "AI infrastructure", ("ai", "artificial intelligence", "data center")),
    ("QUANTUM", "Quantum", ("quantum",)),
)

AI_COMPANIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("OpenAI", ("openai", "chatgpt", "gpt")),
    ("Anthropic", ("anthropic", "claude")),
    ("Google", ("google", "gemini", "deepmind", "alphabet")),
    ("xAI", ("xai", "grok")),
    ("Meta", ("meta", "llama")),
    ("Mistral", ("mistral",)),
    ("DeepSeek", ("deepseek",)),
    ("Local-LLMs", ("local llm", "local-llm", "on-device")),
    ("Ollama", ("ollama",)),
    ("OpenSource", ("open source", "open-source")),
    ("Agents", ("agent", "agents", "automation")),
)

RETIREMENT_TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("social-security", ("social security", "ssa")),
    ("medicare", ("medicare",)),
    ("irmaa", ("irmaa",)),
    ("roth-conversion", ("roth", "conversion")),
    ("rmd", ("rmd", "required minimum")),
    ("estate-planning", ("estate", "beneficiary", "trust")),
    ("ssa-44", ("ssa-44",)),
    ("home-sale-exclusion", ("home sale", "capital gain exclusion")),
    ("tax-law", ("tax", "irs", "deduction")),
)

HEALTH_TOPICS = {
    "longevity",
    "cardiac",
    "strength",
    "trt",
    "glp-1",
    "nutrition",
    "sleep",
    "other",
}


def _clean(text: object, *, limit: int | None = None) -> str:
    value = html.unescape(str(text or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if limit and len(value) > limit:
        return value[: limit - 1].rstrip() + "."
    return value


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _stories(edition: dict, section: str | None = None) -> list[dict]:
    raw = edition.get("rawInputs", {}).get("rss", {}).get("stories") or []
    if section is None:
        return [s for s in raw if isinstance(s, dict)]
    return [s for s in raw if isinstance(s, dict) and s.get("section") == section]


def _story_title(story: dict) -> str:
    title = _clean(story.get("title"), limit=170)
    # Google News titles often arrive as "Headline - Publication".
    return re.sub(r"\s+-\s+[^-]{2,80}$", "", title).strip() or title


def _source(story: dict) -> str | None:
    return _clean(story.get("source"), limit=40) or None


def _url(story: dict) -> str | None:
    url = str(story.get("canonical") or story.get("url") or "").strip()
    return url or None


def _select_unique(items: list[dict], count: int, key: str = "title") -> list[dict]:
    selected: list[dict] = []
    seen: set[str] = set()
    for item in items:
        marker = _clean(item.get(key) or item.get("url") or item)[:120].lower()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        selected.append(item)
        if len(selected) >= count:
            break
    return selected


def _weather_text(weather: dict) -> str:
    periods = [
        p for p in (weather.get("today"), weather.get("tonight"), weather.get("tomorrow"))
        if isinstance(p, dict)
    ]
    if not periods:
        return "Weather source is thin; dress in light layers and check radar before leaving Eureka."

    forecasts = " ".join(
        _clean(p.get("shortForecast") or p.get("detailedForecast")).lower()
        for p in periods
    )
    temps = [p.get("temperature") for p in periods if isinstance(p.get("temperature"), (int, float))]
    precip = max(
        [p.get("precipChance") for p in periods if isinstance(p.get("precipChance"), (int, float))]
        or [0]
    )
    high = max(temps) if temps else None
    low = min(temps) if temps else None

    if precip >= 50 or any(word in forecasts for word in ("rain", "shower", "thunderstorm")):
        return "Carry a rain shell and choose shoes that can handle wet pavement; storms are the main constraint."
    if high is not None and high >= 88:
        return "Light clothes, sunglasses, and water; do outdoor errands early before the heat gets irritating."
    if low is not None and low <= 55:
        return "Use light layers; morning and evening will feel cooler than the middle of the day."
    return "Light casual layers are enough; bring sunglasses if you will be out around midday."


def _local_picks(picks: list[dict], day: str) -> list[dict]:
    if not isinstance(picks, list):
        return []
    if day == "sunday":
        filtered = [
            p for p in picks
            if "saturday" in _clean(p.get("dateLabel")).lower()
            or "weekend" in _clean(p.get("dateLabel")).lower()
        ]
        return _select_unique(filtered or picks, 2)
    return _select_unique(picks, 3)


def _distance_minutes(idea: dict) -> int:
    text = f"{idea.get('distance') or ''} {idea.get('blurb') or ''}".lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*hr", text)
    if match:
        return int(float(match.group(1)) * 60)
    match = re.search(r"(\d+)\s*min", text)
    if match:
        return int(match.group(1))
    return 999


def _drive_ideas(ideas: list[dict], day: str) -> list[dict]:
    if not isinstance(ideas, list):
        return []
    candidates = sorted(ideas, key=_distance_minutes)
    nearby = [i for i in candidates if _distance_minutes(i) <= 180]
    selected = nearby[:4] if nearby else candidates[:4]
    cleaned: list[dict] = []
    for idea in selected:
        cleaned.append(
            {
                "name": idea.get("name"),
                "where": idea.get("where"),
                "distance": idea.get("distance"),
                "blurb": _clean(idea.get("blurb"), limit=130),
                "region": idea.get("region"),
            }
        )
    return cleaned


def _travel_from_calendar(events: list[dict]) -> list[dict]:
    if not isinstance(events, list):
        return []
    terms = ("flight", "hotel", "airbnb", "trip", "vacation", "travel", "out of town")
    return [
        ev for ev in events
        if _contains(f"{ev.get('summary', '')} {ev.get('location', '')}", terms)
    ]


def _market_why(indicators: list[dict]) -> str | None:
    if not indicators:
        return None
    pieces: list[str] = []
    for label in ("S&P 500", "Nasdaq Composite", "Bitcoin"):
        item = next((i for i in indicators if i.get("label") == label), None)
        if item and item.get("changeWtd") is not None:
            pieces.append(f"{label} {item['changeWtd']}")
    ten_year = next((i for i in indicators if i.get("label") == "10Y Treasury"), None)
    rate_piece = None
    if ten_year and ten_year.get("current") is not None:
        rate_piece = f"the 10Y Treasury sits at {ten_year['current']}"
        if ten_year.get("changeWtd") is not None:
            rate_piece += f" ({ten_year['changeWtd']} WTD)"
    if pieces and rate_piece:
        return (
            f"Risk assets carried the week with {', '.join(pieces)} while {rate_piece}. "
            "The useful read is liquidity plus duration: keep conviction tied to source quality, not one headline."
        )
    if pieces:
        return f"Risk assets carried the week with {', '.join(pieces)}; treat the move as a trend check, not a trade signal."
    if rate_piece:
        return f"Rates are the main visible signal this week: {rate_piece}. Keep retirement-income decisions rate-aware."
    return None


def _build_investing_themes(edition: dict) -> dict:
    source_stories = _stories(edition, "mag7") + _stories(edition, "crypto") + _stories(edition, "ai")
    themes: list[dict] = []
    used_urls: set[str] = set()
    for ticker, display, terms in WATCHLIST:
        story = next(
            (
                s for s in source_stories
                if _contains(_story_title(s), terms) and (_url(s) or _story_title(s)) not in used_urls
            ),
            None,
        )
        if not story:
            continue
        used_urls.add(_url(story) or _story_title(story))
        themes.append(
            {
                "ticker": ticker,
                "displayName": display,
                "trendLine": f"{_story_title(story)}. Weekend read: signal only; verify against live price before acting.",
                "source": _source(story),
                "url": _url(story),
            }
        )
        if len(themes) >= 5:
            break
    return {"themes": themes, "noMeaningfulNews": not bool(themes)}


def _build_ai_landscape(edition: dict) -> dict:
    ai_stories = _stories(edition, "ai") + _stories(edition, "mag7")
    entries: list[dict] = []
    used: set[str] = set()
    for company, terms in AI_COMPANIES:
        story = next(
            (
                s for s in ai_stories
                if _contains(_story_title(s), terms) and (_url(s) or _story_title(s)) not in used
            ),
            None,
        )
        if not story:
            continue
        used.add(_url(story) or _story_title(story))
        entries.append(
            {
                "company": company,
                "oneLiner": f"{_story_title(story)}",
                "source": _source(story),
                "url": _url(story),
            }
        )
        if len(entries) >= 6:
            break
    return {"entries": entries, "noMeaningfulNews": not bool(entries)}


def _build_health(edition: dict) -> dict:
    stories = edition.get("rawInputs", {}).get("health", {}).get("stories") or []
    entries: list[dict] = []
    for story in _select_unique([s for s in stories if isinstance(s, dict)], 5):
        topic = str(story.get("topic") or "other").lower()
        if topic not in HEALTH_TOPICS:
            topic = "other"
        entries.append(
            {
                "topic": topic,
                "oneLiner": (
                    f"{_story_title(story)}. Men-over-60 relevance: watch the "
                    f"{topic.replace('-', ' ')} signal; discuss application with a clinician."
                ),
                "source": _source(story),
                "url": _url(story),
            }
        )
    return {"entries": entries, "noMeaningfulNews": not bool(entries)}


def _build_retirement_watch(edition: dict, day: str, retirement_note: str) -> dict:
    items: list[dict] = []
    for topic, terms in RETIREMENT_TOPICS:
        story = next((s for s in _stories(edition) if _contains(_story_title(s), terms)), None)
        if not story:
            continue
        items.append(
            {
                "topic": topic,
                "headline": _story_title(story),
                "detail": "Worth opening because it touches retirement cash flow, taxes, Medicare, or household admin.",
                "source": _source(story),
                "url": _url(story),
            }
        )
        if len(items) >= 3:
            break
    return {
        "items": items,
        "noMeaningfulNews": not bool(items),
        "planningNote": retirement_note if day == "saturday" else None,
        "weekEndReflection": retirement_note if day == "sunday" else None,
    }


def _retirement_note(edition: dict, day: str) -> str:
    portfolio = edition.get("pillars", {}).get("retirement", {}).get("portfolioState") or {}
    positions = portfolio.get("positions") or []
    summary = portfolio.get("account_summary") or {}
    if positions:
        return (
            f"Portfolio snapshot has {len(positions)} positions. Use the weekend to flag anything that needs a Monday review, not to force a trade."
        )
    if summary:
        return "Portfolio account summary is present; use it for a quiet allocation check before Monday, not a weekend trade decision."
    if day == "saturday":
        return "TWS did not provide a usable portfolio snapshot. Put a 20-minute Monday block on the calendar to verify account state before making decisions."
    return "End the week by noting that portfolio data was unavailable here; Monday's first task is a clean broker-state check."


def _build_worth_reading(edition: dict, health: dict, themes: dict, ai: dict) -> dict:
    candidates: list[dict] = []
    for theme in themes.get("themes") or []:
        candidates.append(
            {
                "type": "article",
                "title": theme["trendLine"].split(". Weekend read:", 1)[0],
                "whyWorthIt": "Directly tied to your watchlist; open the source before deciding whether it matters.",
                "url": theme.get("url"),
                "durationLabel": "6 min read",
            }
        )
    for entry in ai.get("entries") or []:
        candidates.append(
            {
                "type": "article",
                "title": entry["oneLiner"],
                "whyWorthIt": "Good AI-landscape context for the week ahead.",
                "url": entry.get("url"),
                "durationLabel": "7 min read",
            }
        )
    for entry in health.get("entries") or []:
        candidates.append(
            {
                "type": "article",
                "title": entry["oneLiner"].split(". Men-over-60 relevance:", 1)[0],
                "whyWorthIt": "Health signal with practical relevance for longevity and cardiac risk management.",
                "url": entry.get("url"),
                "durationLabel": "8 min read",
            }
        )
    articles = _select_unique(candidates, 3, key="url")
    return {"articles": articles, "videos": [], "podcasts": []}


def _build_executive_summary(
    edition: dict,
    day: str,
    markets_why: str | None,
    themes: dict,
    ai: dict,
    health: dict,
    retirement_note: str,
) -> dict:
    pillars = edition.get("pillars", {})
    drive_ideas = pillars.get("vacation", {}).get("driveDistanceIdeas") or []
    opportunities: list[dict] = []
    first_theme = next(iter(themes.get("themes") or []), None)
    if first_theme:
        opportunities.append(
            {
                "category": "investment",
                "title": f"Review {first_theme.get('displayName') or first_theme['ticker']} source signal",
                "blurb": "There is a fresh watchlist-linked item; open the source and decide whether it belongs in Monday's review.",
                "sourceUrl": first_theme.get("url"),
                "expiresLabel": "before Monday open",
            }
        )
    first_ai = next(iter(ai.get("entries") or []), None)
    if first_ai:
        opportunities.append(
            {
                "category": "ai-tools",
                "title": f"AI landscape: {first_ai['company']}",
                "blurb": "Use the source as a capability or competitive-positioning check, not a generic AI headline.",
                "sourceUrl": first_ai.get("url"),
            }
        )
    first_health = next(iter(health.get("entries") or []), None)
    if first_health:
        opportunities.append(
            {
                "category": "business",
                "title": "Save one health signal for follow-up",
                "blurb": "The health feed has a substantive study; capture it for a clinician or personal protocol review.",
                "sourceUrl": first_health.get("url"),
            }
        )
    first_trip = next(iter(drive_ideas), None)
    if first_trip:
        opportunities.append(
            {
                "category": "travel-deal",
                "title": f"Low-friction drive idea: {first_trip.get('name')}",
                "blurb": _clean(first_trip.get("blurb"), limit=140) or "Close enough to be a real weekend option.",
            }
        )
    opportunities.append(
        {
            "category": "tax-planning",
            "title": "Retirement admin block",
            "blurb": retirement_note,
            "expiresLabel": "next week",
        }
    )

    summary_bullets = [
        f"What matters: {markets_why or 'source coverage is available, but market context is thinner than usual.'}",
        "What changed: weekend publishing now has enough structured inputs to be useful without a prompt-written JSON patch.",
        "What to ignore: broad AI/local headlines that do not touch your portfolio, income, health, business, or capability stack.",
        "Biggest opportunity: open the watchlist and AI source links before Monday and decide what deserves follow-up.",
        "Biggest risk: treating a weekend source as a trade signal instead of a planning input.",
    ]
    if day == "sunday":
        summary_bullets[1] = "What to carry into next week: convert the useful source links into one or two calendar blocks."

    action_items = [
        {
            "rank": 1,
            "title": "Open the top watchlist source",
            "rationale": "It is the highest-signal investing input in the weekend feed.",
            "effortHours": 0.25,
            "byWhen": "before Monday open",
        },
        {
            "rank": 2,
            "title": "Schedule the retirement admin check",
            "rationale": retirement_note,
            "effortHours": 0.5,
            "byWhen": "next week",
        },
        {
            "rank": 3,
            "title": "Pick one local or travel option",
            "rationale": "The weekend brief should move one real-life choice, not just summarize feeds.",
            "effortHours": 0.25,
            "byWhen": "this weekend" if day == "saturday" else "by Friday",
        },
    ]
    fun_fact = None
    ten_year = next(
        (
            i for i in pillars.get("markets", {}).get("indicators") or []
            if i.get("label") == "10Y Treasury"
        ),
        None,
    )
    if ten_year and ten_year.get("current"):
        fun_fact = {
            "domain": "economics",
            "fact": f"The 10Y Treasury marker in this brief is {ten_year['current']}, a useful shorthand for retirement-income and duration pressure.",
            "source": ten_year.get("source"),
        }
    else:
        fun_fact = {
            "domain": "science",
            "fact": "A good weekend brief is a filter: fewer source-backed decisions beat more generic headlines.",
            "source": "dailybrief deterministic enrichment",
        }
    return {
        "opportunities": opportunities[:5],
        "summaryBullets": summary_bullets[:5],
        "actionItems": action_items,
        "funFact": fun_fact,
    }


def enrich_edition(edition: dict, day: str) -> dict:
    """Return an enriched LifestyleEdition without mutating the input."""
    enriched = deepcopy(edition)
    pillars = enriched.setdefault("pillars", {})

    weather = pillars.setdefault("weather", {})
    weather["whatToWear"] = _weather_text(weather)

    life = pillars.setdefault("life", {})
    picks = _local_picks(life.get("localPicks") or [], day)
    if day == "sunday":
        life["localPicksNextWeekend"] = picks
        life["oneThingToPlan"] = "Block one 90-minute window for the week: retirement admin, AI-business follow-up, or health logistics. Pick one, not five."
    else:
        life["localPicks"] = picks
        if picks:
            life["oneThing"] = f"Do the easiest real-world thing: {picks[0].get('title')} at {picks[0].get('venue') or 'the listed venue'}."
        else:
            life["oneThing"] = "Take a low-friction walk close to Eureka before the day gets away from you."

    travel = pillars.setdefault("vacation", {})
    calendar_today = life.get("calendarToday") or []
    if day == "sunday":
        travel["upcomingTravel14d"] = _travel_from_calendar(calendar_today)
    else:
        travel["upcomingTravel"] = _travel_from_calendar(calendar_today)
    travel["driveDistanceIdeas"] = _drive_ideas(travel.get("driveDistanceIdeas") or [], day)

    retirement_note = _retirement_note(enriched, day)
    retirement = pillars.setdefault("retirement", {})
    if day == "sunday":
        retirement["weekEndReflection"] = retirement_note
    else:
        retirement["planningNote"] = retirement_note

    markets = pillars.setdefault("markets", {})
    markets_why = _market_why(markets.get("indicators") or [])
    markets["whyParagraph"] = markets_why

    themes = _build_investing_themes(enriched)
    pillars["investingThemes"] = themes

    ai = _build_ai_landscape(enriched)
    pillars["aiLandscape"] = ai

    health = _build_health(enriched)
    pillars["health"] = health

    pillars["retirementWatch"] = _build_retirement_watch(enriched, day, retirement_note)
    pillars["worthReading"] = _build_worth_reading(enriched, health, themes, ai)
    pillars["executiveSummary"] = _build_executive_summary(
        enriched, day, markets_why, themes, ai, health, retirement_note
    )

    rec_article = next(iter(pillars["worthReading"].get("articles") or []), None)
    if rec_article:
        life["rec"] = {
            "title": rec_article["title"],
            "type": "longread",
            "blurb": rec_article["whyWorthIt"],
            "url": rec_article.get("url"),
        }

    enriched["enrichment"] = {
        "strategy": "deterministic-lifestyle-v1",
        "generatedAt": datetime.now(ZoneInfo("America/Chicago")).isoformat(),
        "source": "scripts/enrich_lifestyle_edition.py",
    }
    return enriched


def build_edition(day: str, date_iso: str) -> dict:
    weekday = "Saturday" if day == "saturday" else "Sunday"
    assembled = pc.assemble(day, date_iso, weekday)
    return enrich_edition(assembled, day)


def write_edition(edition: dict, date_iso: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{date_iso}.json"
    out_path.write_text(json.dumps(edition, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[enrich_lifestyle] wrote {out_path}", file=sys.stderr)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich a weekend LifestyleEdition deterministically.")
    parser.add_argument("day", choices=["saturday", "sunday"])
    parser.add_argument("date", nargs="?", help="Date (YYYY-MM-DD); default=today America/Chicago")
    args = parser.parse_args()
    date_iso = args.date
    if not date_iso:
        date_iso = datetime.now(ZoneInfo("America/Chicago")).date().isoformat()

    edition = build_edition(args.day, date_iso)
    write_edition(edition, date_iso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
