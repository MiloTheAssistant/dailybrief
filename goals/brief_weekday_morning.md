# Brief: Weekday Morning — Market + Calendar + Mail (combined)

**Workflow:** `recurring_publish`
**Schedule:** 7:00 AM America/Chicago, Monday through Friday
**Destination:** Telegram
**Audience:** John, single-reader morning brief before market open.

---

## Objective

Produce a single, newsletter-style morning brief that replaces two old jobs:
- `daily-telegram-briefing` (old, 07:00 — calendar + kanban + gmail)
- `market-brief-845am-weekdays` (old, 08:45 — market RSS)

This brief is one page on a phone: markets + today's calendar + overnight inbox
highlights + portfolio snapshot. If something critical is happening, surface
it; otherwise be terse.

---

## Inputs (fetch all four, every run)

1. **Market news (RSS, 5 feeds, deduped)**
   `python3 scripts/fetch_market_brief_rss.py`
   Returns JSON: `{ "stories": [ { "section": "analyst|movers|crypto|ai|mag7", "title", "url", "published", "source", "snippet" } ] }`
   Sections in dedup order: `crypto → ai → mag7 → movers → macro → analyst`.

2. **Today's calendar events (iCal URL)**
   `python3 scripts/fetch_proton_calendar.py --from-date $(date +%Y-%m-%d) --to-date $(date +%Y-%m-%d) --plain`
   Returns JSON: `{ "events": [ { "summary", "start", "end", "location", "all_day" } ] }`
   **All-day events** should be displayed by date, not by the raw start time
   (iCal stores them as UTC midnight which renders as 7pm the prior day in CT).

3. **Overnight inbox (Proton Mail, last 18 hours, max 10 unread)**
   `python3 scripts/fetch_proton_mail.py --folder INBOX --unseen-only --since-hours 18 --limit 10`
   Returns JSON: `{ "envelopes": [ { "id", "subject", "sender", "date", "is_seen" } ] }`
   If zero unread, say "no overnight email" and stop.

4. **Portfolio snapshot (TWS, account summary + open positions)**
   `python3 scripts/fetch_tws_portfolio.py --plain`
   Returns JSON: `{ "account_summary": { "NetLiquidation", "BuyingPower", "AvailableFunds", "TotalCashValue", "UnrealizedPnL", "RealizedPnL" }, "positions": [ { "symbol", "qty", "avg_cost", "currency" } ] }`
   If TWS is not running, the script exits 2 with a clear stderr message — the
   brief should note "(portfolio: TWS offline)" in the Portfolio section and
   continue without it.

---

## Sections (in order)

1. **MARKETS** — 2–4 analyst/macro headlines from SeekingAlpha + Yahoo Finance.
   Lead with the 1-Minute Market Report or top overnight story. Each headline
   gets a one-line "why it matters."
2. **CRYPTO / AI / MAG7** — one line each, only if a story is notable.
3. **PORTFOLIO** — Net liquidation + 1-line state (positions, P&L). No deep
   analysis — the brief is for awareness, not trading.
4. **TODAY** — calendar events in chronological order. If empty: "No
   meetings today." If all-day only: list the dates.
5. **INBOX** — max 3 unread emails worth a glance. Skip promotional/newsletter
   content; surface personal or actionable items only.
6. **WEEK AHEAD** — one line: "N meetings this week" + first one is on DAY at
   TIME. Pulled from `fetch_proton_calendar.py --days 7` (already ran for
   the TODAY section, just count + sort).

---

## Rules

- **No fabrication.** If a source returns nothing or errors, say so in one
  short clause and move on. Never invent a market number, a meeting, or an
  email.
- **Compress ruthlessly.** Whole brief ≤ 600 words, fits on one phone screen.
- **Lead with the most actionable thing.** If portfolio is down significantly
  overnight, that's the lead. If the inbox has a critical email, that's the
  lead. Don't bury the lede.
- **Telegram auto-delivery:** do NOT call `send_message` / `notify` /
  `messaging` tools. Your final response IS the delivery.
- **Workdir:** this job runs in `/Volumes/BotCentral/Users/milo/repos/dailybrief`
  so the relative `scripts/` paths work. Do not `cd` elsewhere.
- **Self-checks before composing:**
  - Each fetch script's exit code — if non-zero, the section should say
    "(source: offline)" and continue.
  - The system prompt for cron-mode says "deliver final response, do not
    call send_message" — honor that.
- **If you cannot produce any of sections 1–6** (e.g. all four fetchers
  failed simultaneously), respond with exactly `[SILENT]`. Do not post a
  half-empty brief.

---

## Output Template

```
MARKET BRIEF — [WEEKDAY], [MMM DD] 7:00 AM CT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📈 MARKETS
• [Top headline] — [why it matters in 1 line]
• [2nd headline] — [why it matters]
• [3rd headline] — [why it matters]

💼 PORTFOLIO  (or: "PORTFOLIO: TWS offline")
NetLiq $X,XXX  |  BP $X,XXX  |  Day P&L $±XXX
• [Top position]: X shares @ avg $XX.XX
• [2nd position if material]

📅 TODAY — [Day, MMM DD]
• [Time] [Event] — [location if any]
• [Time] [Event]
[or "No meetings today."]

📨 INBOX
• [Sender] — [Subject, one line summary]
• [Sender] — [Subject]
[or "No overnight email."]

📆 WEEK AHEAD
N meetings Mon–Fri. First: [Day] [Time] [Event].
```

---

## Edge Cases

- **TWS offline:** portfolio section reads "PORTFOLIO: TWS offline" in
  bold, brief proceeds without it.
- **Proton Bridge offline:** today/inbox sections say "(mail: Bridge
  offline)" — the other three sections still deliver.
- **Calendar iCal URL revoked:** today/week sections say "(calendar:
  share revoked — regenerate in Proton web)" — the other sections still
  deliver.
- **All four offline:** `[SILENT]`. Do not post a 3-line brief with all
  the error messages — that's worse than silence.
- **First run after a holiday:** data may be sparse. Lean terse. Don't
  pad with generic market commentary.

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
