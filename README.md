# dailybrief

Canonical specs for the **three Proton-redesign daily briefs** that run as
Hermes cron jobs: weekday morning, Saturday, and Sunday.

The Sunday Audit (`brief_sunday_audit`) is **not** in this repo — it's local
on each Mac. See [`goals/manifest.md`](goals/manifest.md) for the full
breakdown of what's published here vs. kept locally.

## Active briefs

| Cron | Schedule | Brief |
|---|---|---|
| `brief-weekday-morning` | `0 7 * * 1-5` (07:00 CT Mon–Fri) | Market + calendar + inbox + portfolio, Telegram |
| `brief-saturday` | `0 9 * * 6` (09:00 CT Sat) | Lifestyle: weather, today's calendar, overnight inbox, one thing to do, weekend pick, read/listen/watch, Telegram |
| `brief-sunday` | `0 9 * * 0` (09:00 CT Sun) | Next-week preview: Mon–Fri calendar count + busiest day, weekend inbox recap, plan-this-week, weekend read, Telegram |

All three were registered 2026-06-27 as part of the Proton redesign.

## Layout

```
dailybrief/
├── README.md
├── goals/
│   ├── manifest.md                       # canonical index, see above
│   ├── brief_weekday_morning.md          # 07:00 CT Mon–Fri spec
│   ├── brief_saturday.md                 # 09:00 CT Sat spec
│   └── brief_sunday.md                   # 09:00 CT Sun spec
└── scripts/
    ├── fetch_market_brief_rss.py         # weekday: RSS scan
    ├── fetch_proton_calendar.py          # all 3: iCal → JSON
    ├── fetch_proton_mail.py              # all 3: himalaya → JSON
    ├── fetch_tws_portfolio.py            # weekday: IBAPI positions
    └── fetch_lifestyle_sources.py        # saturday legacy: NWS Chicago
```

Each spec lists which scripts it calls and the exact `python3 scripts/...`
invocations the cron prompt should use.

## Cron-mode contract

Every brief follows the **file-and-run pattern**:

- Scripts live in `scripts/` and are invoked with `python3 <path>`.
- No inline `python3 -c`, no `execute_code` (locked down in cron mode).
- If a fetcher can't reach its source, the script returns a JSON envelope with
  `status: "unreachable"` and the brief surfaces that gap honestly. **No
  fabrication.** If a brief can't fill 4+ of its sections honestly, the
  prompt is required to respond with exactly `[SILENT]` rather than post a
  half-empty brief.
- Final cron response IS the Telegram delivery. Don't call `send_message`,
  `notify`, or `messaging` tools inside the brief — the system routes it.

## Sync model

This repo is the **canonical source**. Local working copies sync FROM here:

```bash
cd ~/repos/dailybrief
git pull   # on every Mac that runs the cron jobs
```

To update a spec: edit here, commit, push, then `git pull` on the cron Mac.
