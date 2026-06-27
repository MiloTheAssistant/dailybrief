# Brief: Sunday — Next-Week Preview (calendar + lifestyle forward-look)

**Workflow:** `recurring_publish`
**Schedule:** 9:00 AM America/Chicago, Sunday only
**Destination:** Telegram
**Audience:** John, single-reader Sunday-morning brief.

---

## Objective

A Sunday-morning brief that is structurally a *forward look*: next week's
calendar, week-ahead planning, and a quiet weekend-recap of the inbox.
Distinct from Saturday's present-tense brief.

If Saturday is "go do this today," Sunday is "here's the shape of the
week ahead." This is the brief John reads with coffee, not while
getting dressed.

---

## Inputs (fetch every run)

1. **Next-week calendar (Mon–Fri, 5 days starting tomorrow)**
   `python3 scripts/fetch_proton_calendar.py --days 5 --from-date $(date -v+1d +%Y-%m-%d)`
   (If `date -v+1d` doesn't work on this macOS, use
   `$(date -j -v+1d +%Y-%m-%d)` for BSD date or compute in Python.)
   This is the *primary* signal — the brief is built around it.

2. **Today's calendar (Sunday)**
   `python3 scripts/fetch_proton_calendar.py --from-date $(date +%Y-%m-%d) --to-date $(date +%Y-%m-%d)`

3. **Weekend inbox recap (last 48h, max 5 unread)**
   `python3 scripts/fetch_proton_mail.py --folder INBOX --unseen-only --since-hours 48 --limit 5`
   On Sunday morning, "overnight" is really "since Saturday morning."
   Surface anything actionable that arrived over the weekend.

---

## Sections (in order)

1. **THIS WEEK (Mon–Fri)** — the calendar at a glance:
   - Total meeting count
   - Busiest day (highest event count) — call it out
   - Open day(s) — if any weekday has zero events, that's a "use it"
     flag
   - First event of the week (day + time)
   - Last event of the week (day + time)
2. **ON THE CALENDAR TODAY** — Sunday's events. If empty: "Open
   Sunday." Don't pad.
3. **WEEKEND INBOX** — max 2 actionable emails from the weekend
   recap. Skip newsletters.
4. **ONE THING TO PLAN THIS WEEK** — a low-friction action that's
   *forward-looking* (schedule a coffee, block focus time on Wed
   afternoon, sign up for the thing you keep meaning to). Different
   from Saturday's present-tense "do this today."
5. **WEEKEND READ** — one longread / book chapter / podcast
   episode for the week ahead. Different from Saturday's rec
   (which was for *now*).

---

## Rules

- **No fabrication.** Empty sources → say so in one line. Don't
  invent meetings.
- **Tone:** quieter than Saturday. Reflective. Not chipper.
- **Length:** 400–600 words. Sunday morning = less screen time.
- **Telegram auto-delivery:** do NOT call `send_message` / `notify` /
  `messaging` tools.
- **Workdir:** `/Volumes/BotCentral/Users/milo/repos/dailybrief`.
- **If you cannot produce sections 1 + 4 honestly, respond with
  exactly `[SILENT]`.** A Sunday brief without a week preview is
  worse than no brief.

---

## Output Template

```
🌅 SUNDAY BRIEF — [MONTH DD, YYYY]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Delivered by Milo | 9:00 AM CT

📆  THIS WEEK (Mon–Fri)
• N meetings total across M weekdays
• Busiest: [Day] ([count] events)
• Open: [Day(s) with no events — "use it"]
• First: [Day] [Time] [Event]
• Last:  [Day] [Time] [Event]

📅  ON THE CALENDAR TODAY
• [Time] [Event]
[or "Open Sunday."]

📨  WEEKEND INBOX
• [Sender] — [Subject, 1 line]
[or "Inbox quiet all weekend."]

🎯  ONE THING TO PLAN THIS WEEK
[Forward-looking action — schedule, block, sign up]

📖  WEEKEND READ
[Title] — [Type] · [1 line on why it's right for this week]
```

---

## Edge Cases

- **Next-week calendar is fully empty:** the entire brief is just
  "Open week. Use it." That's a feature, not a bug — John has a clean
  week ahead and should know.
- **Next-week calendar is fully booked (15+ events):** surface the
  overload. Suggest a 30-min review block on the busiest day.
- **Both calendars empty:** section 1 says "Fully open week.
  Nothing scheduled Mon–Fri." Skip section 2 ("Open Sunday.").
  Still try to fill section 4 with a planning action.

---

## How this differs from Saturday

| | Saturday | Sunday |
|---|---|---|
| Frame | "Today + this weekend" | "Next week preview" |
| Calendar | Just today | Mon–Fri next week |
| Inbox | Overnight only | Weekend recap (48h) |
| Pick | "Do this today" | "Plan your week around this" |
| Rec | "Lazy Saturday morning" | "Sunday reading for the week" |

If Saturday and Sunday briefs start to look the same, re-read this
table and tighten the framing.
