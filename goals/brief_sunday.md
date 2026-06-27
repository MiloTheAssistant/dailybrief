# Brief: Sunday — Lifestyle (Life, Vacation, Retirement, Weather)

**Workflow:** `recurring_publish`
**Schedule:** 9:00 AM America/Chicago, Sunday only
**Destination:** **Vercel only** (https://daily-brief-tau.vercel.app/weekend/<date>)
**Audience:** John, single-reader Sunday-morning lifestyle brief.

---

## Objective

A Sunday-morning lifestyle brief that mirrors Saturday's four-pillar
shape (Life, Vacation, Retirement, Weather) but with a **reflective,
week-closing tone** — Saturday leans forward into "go do this,"
Sunday leans into "wrap the weekend, look ahead to next."

Reads in 10–15 minutes — Sunday-morning coffee length. Distinct from
the weekday DFB (markets-only, M-F) and from Saturday (forward-leaning
present tense).

---

## Inputs (fetch every run)

1. **Weather — Eureka, MO 63025** (lat 38.5017, lon -90.6276)
   `python3 scripts/fetch_lifestyle_sources.py --lat 38.5017 --lon -90.6276 --label "Eureka, MO"`
   Surface: today + tonight. (No tomorrow — week's over.)

2. **St. Louis area local events** (today + next 7 days, lookahead)
   `python3 scripts/fetch_stl_events.py`
   Pick 1–2 events *for the next weekend* — Sunday's "life" pillar
   previews what's coming.

3. **Today's calendar (Sunday)** — Proton Calendar
   `python3 scripts/fetch_proton_calendar.py --from-date $(date +%Y-%m-%d) --to-date $(date +%Y-%m-%d)`
   Empty → "Open Sunday."

4. **Weekend inbox recap (last 48h, max 5 unread)** — Proton Mail
   `python3 scripts/fetch_proton_mail.py --folder INBOX --unseen-only --since-hours 48 --limit 5`
   On Sunday morning, "overnight" is really "since Saturday morning."

5. **Portfolio snapshot** — TWS/IB Gateway
   `python3 scripts/fetch_tws_portfolio.py --plain`
   Same one-line state as Saturday, framed for week-end reflection.
   If TWS offline: section reads "(portfolio: TWS offline)".

---

## Pillars (in order)

### 1. Weather (Eureka, MO 63025)
- Today: high/low, conditions, precip %, wind.
- Tonight: brief one-liner.
- **No tomorrow** — it's Sunday, week's over.
- One line on what to wear/bring for the day.

### 2. Life — Today's calendar + planning the week ahead
- **Today's calendar** (chronological). Empty → "Open Sunday."
- **One thing to plan this week** — a forward-looking nudge
  (schedule a coffee, block focus time Wed afternoon, sign up for
  the thing you keep meaning to). Different from Saturday's "do
  this today" — Sunday plans, Saturday does.
- **Local events coming up** — 1–2 picks for next weekend from
  `fetch_stl_events.py`, filtered to next-Sat/Sun window.
- **Weekend read** — one longread / book chapter / podcast episode
  for the week ahead. Different from Saturday's rec (which was for
  *now*).

### 3. Vacation — Look-ahead + drive-distance ideas
- **Upcoming travel in next 2 weeks** — anything from calendar with
  travel markers, expanded search window vs. Saturday (2 weeks vs.
  current week).
- **Drive-distance ideas** — from `references/top-travel-ideas.md`,
  filtered to "good for next weekend" framing.

### 4. Retirement — Portfolio state + week-end reflection
- **Portfolio state** — net liquidation + 1-line state (positions,
  week P&L if available, day P&L). Reflective frame: "where you
  ended the week" not "where you start Monday."
- **One quiet reflection** — a non-trade nudge for the week. Reading
  list update, beneficiary review reminder, rebalance-quarter
  check-in if applicable. Never financial advice.

---

## Rules

- **No fabrication.** Empty sources → say so in one line. Don't
  invent meetings, events, or travel.
- **Eureka, MO / St. Louis Metro specific.** Name places. No generic
  "visit a museum."
- **Tone:** quieter than Saturday. Reflective. Not chipper.
- **Length:** 500–800 words. Sunday morning = less screen time.
- **Destination is Vercel only.** Do NOT call `send_message` /
  `notify` / `messaging` tools. Helper script's success/failure IS
  the delivery.
- **Workdir:** `/Volumes/BotCentral/Users/milo/repos/dailybrief`.
- **If you cannot fill 3+ of the 4 pillars honestly, respond with
  exactly `[SILENT]`.** A Sunday brief without weather + life is
  worse than no brief.

---

## Output Schema (JSON, written to `out/lifestyle/<date>.json`)

```json
{
  "date": "YYYY-MM-DD",
  "weekday": "Sunday",
  "kind": "lifestyle",
  "generatedAt": "ISO-8601 UTC",
  "zip": "63025",
  "location": { "label": "Eureka, MO", "lat": 38.5017, "lon": -90.6276 },
  "pillars": {
    "weather": { "today": {...}, "tonight": {...}, "whatToWear": "..." },
    "life": { "calendarToday": [...], "oneThingToPlan": "...", "localPicksNextWeekend": [...], "rec": {...} },
    "vacation": { "upcomingTravel14d": [...], "driveDistanceIdeas": [...] },
    "retirement": { "portfolioState": {...}, "weekEndReflection": "..." }
  }
}
```

Must match `LifestyleEdition` in `MiloTheAssistant/Milo` website's
`src/lib/briefings-types.ts`. Helper script
`scripts/build_lifestyle_json.py` writes this and ships to Vercel.

---

## How this differs from Saturday

| | Saturday | Sunday |
|---|---|---|
| Frame | "Today + this weekend" | "Wrap-up + next weekend preview" |
| Weather | Today + tonight + tomorrow | Today + tonight (no tomorrow) |
| Life | Today's calendar + 1 thing to do | Today's calendar + 1 thing to plan |
| Vacation | Current-week travel + weekend drive ideas | 2-week travel lookahead + next-weekend drive ideas |
| Retirement | Portfolio state + planning note | Portfolio state + week-end reflection |
| Tone | Forward-leaning | Reflective |

If Sat + Sun briefs start to look the same, tighten the framing.
