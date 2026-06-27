# Brief: Saturday — Lifestyle (Life, Vacation, Retirement, Weather)

**Workflow:** `recurring_publish`
**Schedule:** 9:00 AM America/Chicago, Saturday only
**Destination:** **Vercel only** (https://daily-brief-tau.vercel.app/weekend/<date>)
**Audience:** John, single-reader Saturday-morning lifestyle brief.

---

## Objective

A Saturday-morning lifestyle brief that leans into the *start* of the
weekend. Four pillars: **Life** (what's happening today + a rec),
**Vacation** (upcoming travel + St. Louis area day-trip ideas),
**Retirement** (portfolio glance + one planning note), and **Weather**
(Eureka, MO 63025 forecast + what to wear/bring).

Reads in 10–15 minutes — Saturday-morning coffee length. Not a wall of
financial data; the DFB covers that M-F.

---

## Inputs (fetch every run)

1. **Weather — Eureka, MO 63025** (lat 38.5017, lon -90.6276)
   `python3 scripts/fetch_lifestyle_sources.py --lat 38.5017 --lon -90.6276 --label "Eureka, MO"`
   Returns JSON envelope; NWS gridpoint LSX/80,68. Surface: today +
   tonight + tomorrow.

2. **St. Louis area local events** (weekend + next 7 days)
   `python3 scripts/fetch_stl_events.py`
   Returns JSON: top 3–5 events (festivals, markets, concerts, sports)
   within ~30 mi of 63025. If the fetcher is offline, the Life section
   uses `references/top-stl-events-curated.md` as a curated fallback.

3. **Today's calendar (Saturday)** — Proton Calendar
   `python3 scripts/fetch_proton_calendar.py --from-date $(date +%Y-%m-%d) --to-date $(date +%Y-%m-%d)`
   If empty: today is open. Lean into "go do something" framing.

4. **Overnight inbox (last 18h, max 5 unread)** — Proton Mail
   `python3 scripts/fetch_proton_mail.py --folder INBOX --unseen-only --since-hours 18 --limit 5`
   On weekends people expect less email. If empty, skip.

5. **Portfolio snapshot** — TWS/IB Gateway (one-line state, no deep dive)
   `python3 scripts/fetch_tws_portfolio.py --plain`
   If TWS offline: section reads "(portfolio: TWS offline)" — keep going.

---

## Pillars (in order)

### 1. Weather (Eureka, MO 63025)
- Today: high/low, conditions, precip %, wind.
- Tonight + tomorrow: brief one-liners.
- One line on what to wear/bring ("jacket by evening," "sunscreen if
  you're out past 4pm," etc.). Don't pad.

### 2. Life — What's happening + a rec
- **Today's calendar** (chronological). Empty → "Nothing on the books.
  Open day."
- **One thing to do today** — a single low-friction action slightly
  better than the default Saturday (walk the trails at Route 66 State
  Park, try a new brewery in Eureka, finish the chapter you're on).
  Not aspirational; not a chore.
- **Local events near you** — 1–2 picks from `fetch_stl_events.py`,
  filtered to weekend-window. One sentence on why now.
- **Read / Listen / Watch** — one rec with a one-line reason.

### 3. Vacation — Upcoming + drive-distance ideas
- **Upcoming travel** — anything from calendar with `category: travel`
  or detected from event text (keywords: flight, hotel, airbnb, trip,
  vacation, out of town). If none: section pivots to drive-distance
  weekend ideas.
- **Drive-distance ideas** — pulled from
  `references/top-travel-ideas.md`. Curated list of St. Louis–region
  + within-driving-distance destinations: Missouri State Parks
  (Ha Ha Tonka, Johnson Shut-Ins, Elephant Rocks), Illinois wine
  country, Hermann MO, Ozark National Scenic Riverways, etc. Pick
  one or two relevant to the season and surface.

### 4. Retirement — Portfolio glance + one quiet planning note
- **Portfolio state** — net liquidation + 1-line state (positions,
  day P&L). Same data as weekday DFB portfolio section, framed for
  Saturday reflection rather than trading.
- **One planning note** — a quiet forward-looking nudge for the week
  ahead (rebalance reminder if it's been a quarter, contribution
  check, beneficiary review on a non-finance topic — reading list
  update, etc.). Never financial advice; this is a nudge to *think*
  not a trade signal.

---

## Rules

- **No fabrication.** If a source is empty, say so in one short
  clause. Don't invent an event or restaurant.
- **Eureka, MO / St. Louis Metro specific.** Name places (Route 66
  State Park, the Muny, Grant's Farm, etc.). No generic "visit a
  museum."
- **Tone:** warm, dry, slightly opinionated. Like a friend who has
  opinions and respects your time. Not breathless. Not corporate.
- **Length:** 600–900 words. One phone screen on the Vercel page,
  slightly longer on Telegram if you skim.
- **Destination is Vercel only.** Do NOT call `send_message` /
  `notify` / `messaging` tools. The cron deliver target is the
  Vercel publish helper script — its success/failure IS the delivery.
- **Workdir:** `/Volumes/BotCentral/Users/milo/repos/dailybrief` so
  `scripts/` paths resolve.
- **If you cannot fill 3+ of the 4 pillars honestly, respond with
  exactly `[SILENT]`.** Do not post a half-empty brief.

---

## Output Schema (JSON, written to `out/lifestyle/<date>.json`)

```json
{
  "date": "YYYY-MM-DD",
  "weekday": "Saturday",
  "kind": "lifestyle",
  "generatedAt": "ISO-8601 UTC",
  "zip": "63025",
  "location": { "label": "Eureka, MO", "lat": 38.5017, "lon": -90.6276 },
  "pillars": {
    "weather": { "today": {...}, "tonight": {...}, "tomorrow": {...}, "whatToWear": "..." },
    "life": { "calendarToday": [...], "oneThingToDo": "...", "localPicks": [...], "rec": {...} },
    "vacation": { "upcomingTravel": [...], "driveDistanceIdeas": [...] },
    "retirement": { "portfolioState": {...}, "planningNote": "..." }
  }
}
```

Must match `LifestyleEdition` in `MiloTheAssistant/Milo` website's
`src/lib/briefings-types.ts`. Helper script
`scripts/build_lifestyle_json.py` writes this and ships to Vercel.

---

## How this differs from Sunday

| | Saturday | Sunday |
|---|---|---|
| Frame | "Today + this weekend" | "Wrap-up + next weekend preview" |
| Weather | Today + tonight + tomorrow | Today + tonight (no tomorrow, week's over) |
| Life | Today's calendar + 1 thing to do | Today's calendar + 1 thing to plan |
| Vacation | Drive-distance weekend ideas | Look-ahead: travel in next 2 weeks |
| Retirement | Portfolio state + planning note | Portfolio state + week-end reflection |
| Tone | Forward-leaning | Reflective |

If Sat + Sun briefs start to look the same, tighten the framing.

---

## Reference data

- `references/top-travel-ideas.md` — curated drive-distance travel
  ideas (St. Louis region + within 3 hours).
- `references/top-stl-events-curated.md` — fallback event list when
  `fetch_stl_events.py` can't reach live sources.
