# Brief: Weekday Morning — Daily Financial Briefing (DFB)

**Workflow:** `recurring_publish`
**Schedule:** 7:00 AM America/Chicago, Monday through Friday
**Destination:** **Vercel only** (https://daily-brief-tau.vercel.app/)
**Audience:** John, single-reader morning-coffee brief (≤ 15 minutes).

---

## Objective

A single daily financial brief that replaces two old jobs:
- `daily-telegram-briefing` (07:00 — calendar + kanban + gmail)
- `market-brief-845am-weekdays` (08:45 — market RSS)

And expands them into the **7-section DFB chain** (Bitcoin, Strategy,
Institutional, Creator Intel, AI Race, Retirement, Health) so it
publishes cleanly to the Vercel DFB site.

**Length cap:** reads in **≤ 15 minutes** with morning coffee. Not an
all-day research dump. Each section compresses to what's *new* and
*actionable* — full data lives in source links, the brief surfaces
signals.

---

## Inputs (fetch all four, every run)

1. **Market news (RSS, 5 feeds, deduped)**
   `python3 scripts/fetch_market_brief_rss.py`
   Returns: `{ "stories": [{section, title, url, published, source,
   snippet}] }`. Sections in dedup order: crypto → ai → mag7 →
   movers → macro → analyst.

2. **Today's calendar + week ahead (iCal URL, Proton Calendar)**
   `python3 scripts/fetch_proton_calendar.py --days 7 --from-date $(date +%Y-%m-%d)`
   Returns events list. For TODAY section: events where `start` is
   today (CT). For INSTITUTIONAL/REGULATORY radar: surface any
   earnings/FOMC/CPI events as calendar-anchored context.

3. **Overnight inbox (Proton Mail, last 18h, max 10 unread)**
   `python3 scripts/fetch_proton_mail.py --folder INBOX --unseen-only --since-hours 18 --limit 10`
   Returns envelope list. Skip newsletters/promotional; surface
   personal/actionable items in HEALTH section ("personal items
   worth a glance" — health appointments, family emails).

4. **Portfolio snapshot (TWS/IB Gateway)**
   `python3 scripts/fetch_tws_portfolio.py --plain`
   Returns account summary + positions. Drives the RETIREMENT
   section directly.

---

## Sections (in order — matches `BriefingSections` in `Milo/website/src/lib/briefings-types.ts`)

### 1. Market Headlines (`MarketHeadlineSection`)
- 3–5 top overnight stories, deduped across RSS feeds.
- Each: headline + source pill + one-line "Why it matters."
- Compress: headline + 1 sentence of why. Don't paste full snippets.

### 2. Bitcoin & Strategy (`BitcoinSection` + `StrategySection`)
- **BitcoinSection** — BTC price, 24h change, dominance, market cap,
  fear & greed index, ETF flows (top 3 by inflow), funding signal,
  on-chain (LTH trend, exchange flow, realized vs spot).
- **StrategySection** — MSTR/STRK/STRF/STRD/STRC instrument quotes,
  btcHoldings. Each with price + 24h change.
- Sources: market RSS for the "what's moving" framing; the helper
  script `build_dfb_json.py` wires any live data source the model
  has access to (CoinGecko / Coinstats via fetch).

### 3. Institutional (`InstitutionalSection`)
- ETF league table (top 5 by flow), BlackRock/Fidelity note,
  regulatory radar (SEC/CFTC actions in RSS), sovereign news
  (when surfaced), TradFi note (bank earnings or notable moves).
- If RSS is sparse: 1-line "quiet institutional day."

### 4. Creator Intel (`CreatorIntelSection`)
- Top 2–3 videos from finance creators covering overnight moves.
  Source: RSS + (if available) YouTube transcript fetcher.
- Each video: title, creator, url, 1-sentence summary, 1-line "why
  it matters."
- Sentiment reading: 1-line synthesis of where the creator
  consensus sits.

### 5. AI Race (`AiRaceSection`)
- 2–4 moves from OpenAI/Anthropic/Google/xAI/Meta/Apple/Microsoft/
  Amazon/NVIDIA. Each: headline + company + 1-line why it matters.
- Compress ruthlessly — only the moves that change the picture.

### 6. Retirement (`RetirementSection`)
- **Portfolio state** — Net liquidation, buying power, day P&L.
- **Top 3 positions** — symbol, qty, avg cost, current P&L.
- **Rate watch** — 1-line on 10Y / 2Y / Fed funds if surfaced in RSS.
- **Supplement** — optional 1–2-line "things worth a glance" (fee
  changes, IRA contribution reminders, rebalance-quarter flag).

### 7. Health (`HealthSection`)
- **Sleep / recovery** — if HealthKit/Whoop data is wired, surface
  last night. If not: skip silently.
- **Personal items** — from inbox: appointments, family, anything
  personal. **Never** medical advice, never detailed health data.
- **Move** — 1-line nudge (stand up hourly, walk the dog, etc.).

---

## Length cap — "morning coffee, 15 minutes"

| Section | Word budget |
|---|---|
| Market Headlines | 200–250 |
| Bitcoin & Strategy | 250–350 |
| Institutional | 150–200 |
| Creator Intel | 150–200 |
| AI Race | 150–200 |
| Retirement | 100–150 |
| Health | 50–100 |
| **Total** | **~1,200–1,500 words** |

If a section exceeds its budget, the helper script trims the lowest-
signal entries. The Vercel page renders sections collapsed-by-default
for the longer sections; headlines stay expanded.

---

## Rules

- **No fabrication.** If a source returns nothing or errors, the
  helper script logs `null` for that section. The Vercel page
  renders "(source offline)" instead of inventing numbers.
- **Compress ruthlessly.** Hit the word budgets. If a section has
  nothing new, say "no notable moves" in 5 words.
- **Lead with the most actionable thing.** If portfolio is down
  significantly overnight, RETIREMENT's portfolio state surfaces
  that. If a critical inbox item arrived, HEALTH surfaces it.
- **Destination is Vercel only.** Do NOT call `send_message` /
  `notify` / `messaging` tools. The cron deliver target is the
  Vercel publish helper script — its success/failure IS the
  delivery.
- **Workdir:** `/Volumes/BotCentral/Users/milo/repos/dailybrief` so
  relative `scripts/` paths work.
- **If 5+ of 7 sections are `null` (all fetchers failed), respond
  with exactly `[SILENT]`.** Do not publish a half-empty brief.

---

## Output Schema (JSON, written to `out/dfb/<date>.json`)

Matches `Briefing` in `MiloTheAssistant/Milo/website/src/lib/briefings-types.ts`:

```json
{
  "date": "YYYY-MM-DD",
  "weekday": "Monday",
  "kind": "dfb",
  "title": "Daily Financial Briefing",
  "subtitle": "Mission Control · Market Intelligence · Daily",
  "generatedAt": "ISO-8601 UTC",
  "confidence": "high" | "medium" | "low",
  "zip": "63025",
  "sections": {
    "marketHeadlines": [...],
    "bitcoin": {...},
    "strategy": {...},
    "institutional": {...},
    "creatorIntel": {...},
    "aiRace": {...},
    "retirement": {...},
    "health": {...}
  }
}
```

Helper script `scripts/build_dfb_json.py` writes this and ships to
Vercel via `cd ~/repos/Milo/website && vercel deploy --prod --yes`.

---

## Edge cases

- **TWS offline:** RETIREMENT.portfolioState = null, page renders
  "(portfolio: TWS offline)" — brief proceeds.
- **Proton Bridge offline:** HEALTH.personalItems = null, others
  continue.
- **Calendar iCal URL revoked:** INSTITUTIONAL.calendarRadar +
  Bitcoin's earnings-anchored context use null, others continue.
- **All four fetchers offline:** `[SILENT]`. Do not publish.
- **First run after a holiday:** data may be sparse. Lean terse,
  use "low" confidence in the schema.

---

## Why 7:00 AM and not 8:45?

The old `market-brief-845am-weekdays` was scheduled for 8:45 to give
Proton's email + calendar a chance to settle before fire time. With
everything fetched in one job at 7:00, that's no longer a constraint.
Moving earlier means John can skim the brief before standups and the
8:45 slot is freed up.

If 7:00 turns out to be too early (data still stale, Proton Calendar
hasn't synced overnight events), move the schedule to 7:15 in this
spec, then `hermes cron edit <id> --schedule "15 7 * * 1-5"`.
