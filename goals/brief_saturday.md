# Brief: Saturday — Lifestyle + Calendar + Mail (weekend start)

**Workflow:** `recurring_publish`
**Schedule:** 9:00 AM America/Chicago, Saturday only
**Destination:** Telegram
**Audience:** John, single-reader weekend-morning brief.

---

## Objective

A Saturday-morning lifestyle brief that leans into the *start* of the
weekend: what's happening today, what to do today, and a couple of
forward-looking recs. Distinct from Sunday's brief, which is a
*next-week preview*.

Replaces the old `lifestyle-brief-9am-weekend` (which fired both Sat and
Sun with the same content — that was the bug: Saturday should be
*present-tense* and Sunday should be *next-week-tense*).

---

## Inputs (fetch every run)

1. **Today's calendar (Saturday)**
   `python3 scripts/fetch_proton_calendar.py --from-date $(date +%Y-%m-%d) --to-date $(date +%Y-%m-%d)`
   If empty: today is open. Lean into the "go-do-something" framing.

2. **Lifestyle sources (Chicago weather + weekend events)**
   `python3 scripts/fetch_lifestyle_sources.py`
   Already in the dailybrief repo; returns weather + Chicago weekend
   events. See `goals/daily_lifestyle_briefing.md` for the source spec.

3. **Overnight inbox (last 18h, max 5 unread)**
   `python3 scripts/fetch_proton_mail.py --folder INBOX --unseen-only --since-hours 18 --limit 5`
   On weekends people expect less email. If empty, just say so and move on.

---

## Sections (in order)

1. **TODAY'S SKY** — Chicago weather (from lifestyle source) + one
   line on what to wear.
2. **ON THE CALENDAR** — today's events. If empty: "Nothing on the
   books. Open day."
3. **OVERNIGHT INBOX** — max 2 unread emails. Skip newsletters.
4. **ONE THING TO DO TODAY** — a single low-friction action that's
   *slightly* better than the default Saturday (walk the 606, try a
   new restaurant, finish the chapter you're on). Not aspirational;
   not a chore.
5. **WEEKEND PICK** — restaurant, cultural thing, or local event for
   either today (Sat) or tomorrow (Sun). One sentence on why now.
6. **READ / LISTEN / WATCH** — one rec, with a one-line reason it's
   right for a Saturday morning.

---

## Rules

- **No fabrication.** If a source is empty, say so in one short
  clause. Don't invent a restaurant or event.
- **Chicago-specific.** Name places. No generic "visit a museum."
- **Tone:** warm, dry, slightly opinionated. Like a friend who has
  opinions and respects your time. Not breathless. Not corporate.
- **Length:** 500–800 words, fits one phone screen with short
  paragraphs.
- **Telegram auto-delivery:** do NOT call `send_message` / `notify` /
  `messaging` tools. Final response IS the delivery.
- **Workdir:** `/Volumes/BotCentral/Users/milo/repos/dailybrief`.
- **If you cannot fill 4+ of sections 1–6 honestly, respond with
  exactly `[SILENT]`.** Do not post a half-empty brief.

---

## Output Template

```
🌇 SATURDAY BRIEF — [MONTH DD, YYYY]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Delivered by Milo | 9:00 AM CT

☀️  TODAY'S SKY
[Temp, conditions, what to wear/bring]

📅  ON THE CALENDAR
• [Time] [Event] — [location if any]
[or "Nothing on the books. Open day."]

📨  OVERNIGHT INBOX
• [Sender] — [Subject, 1 line]
[or "Inbox quiet."]

🎯  ONE THING TO DO TODAY
[Single low-friction action — slightly better than the default]

🍽️  WEEKEND PICK
[Name] — [Neighborhood] · [Why now]

📚  READ / LISTEN / WATCH
[Title] — [Type] · [1 line on why]
```

---

## Edge Cases

- **Lifestyle fetcher returns nothing:** run `web_search` for Chicago
  weather + weekend events. Fall back gracefully.
- **Calendar is empty:** emphasize the open-day framing in section 4.
- **Inbox is empty:** skip section 3 entirely (or one line:
  "Inbox quiet."). Don't pad.

---

## How this differs from Sunday

| | Saturday | Sunday |
|---|---|---|
| Frame | "Today + this weekend" | "Next week preview" |
| Calendar | Just today | Mon–Fri next week |
| Inbox | Overnight only | Weekend recap |
| Pick | "Do this today" | "Plan your week around this" |
| Rec | "Lazy Saturday morning" | "Sunday reading for the week" |

If Saturday and Sunday briefs start to look the same, re-read this
table and tighten the framing.
