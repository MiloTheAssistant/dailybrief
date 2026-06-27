# dailybrief

Canonical specs + helper scripts for the **three Vercel-published daily
briefs** that run as Hermes cron jobs:

| Cron | Schedule | Brief |
|---|---|---|
| `brief-weekday-morning` | `0 7 * * 1-5` (07:00 CT Mon–Fri) | Daily Financial Briefing — 7 sections: market headlines, bitcoin/strategy, institutional, creator intel, AI race, retirement, health |
| `brief-saturday` | `0 9 * * 6` (09:00 CT Sat) | Saturday Lifestyle — 4 pillars: Life, Vacation, Retirement, Weather (Eureka, MO 63025) |
| `brief-sunday` | `0 9 * * 0` (09:00 CT Sun) | Sunday Lifestyle — same 4 pillars, reflective tone |

The Sunday Audit (`brief_sunday_audit`) is **not** in this repo — it's
local on each Mac, Telegram-only. See [`goals/manifest.md`](goals/manifest.md).

All three published briefs go to **Vercel only** (`https://daily-brief-tau.vercel.app/`).
The DFB lands on the home page; the lifestyle briefs land on
`/weekend/<date>`.

## Layout

```
dailybrief/
├── README.md
├── goals/
│   ├── manifest.md                       # canonical index, see above
│   ├── brief_weekday_morning.md          # 07:00 CT Mon–Fri DFB spec
│   ├── brief_saturday.md                 # 09:00 CT Sat Lifestyle spec
│   └── brief_sunday.md                   # 09:00 CT Sun Lifestyle spec
├── scripts/
│   ├── fetch_market_brief_rss.py         # DFB: RSS scan
│   ├── fetch_proton_calendar.py          # all 3: iCal → JSON
│   ├── fetch_proton_mail.py              # all 3: himalaya → JSON
│   ├── fetch_tws_portfolio.py            # all 3: IBAPI positions
│   ├── fetch_lifestyle_sources.py        # Sat + Sun: NWS Eureka MO 63025
│   ├── fetch_stl_events.py               # Sat + Sun: STL events (curated fallback)
│   ├── build_lifestyle_json.py           # Sat + Sun: assemble + ship to Vercel
│   ├── build_dfb_json.py                 # DFB: assemble + ship to Vercel
│   └── _publish_common.py                # shared git + Vercel deploy pipeline
├── references/
│   ├── top-travel-ideas.md               # Sat + Sun: drive-distance travel ideas
│   └── top-stl-events-curated.md         # Sat + Sun: fallback STL events
└── out/                                  # (gitignored — runtime artifacts)
    ├── dfb/<date>.json
    └── lifestyle/<date>.json
```

## Cron-mode contract

Every brief follows the **file-and-run pattern**:

- Helper scripts live in `scripts/` and are invoked with `python3 <path>`.
- No inline `python3 -c`, no `execute_code` (locked down in cron mode).
- The cron prompt runs `python3 scripts/build_<kind>_json.py` (the builder
  that fetches + assembles + writes JSON + commits + pushes + deploys to
  Vercel). Final response is the JSON envelope + a one-line "published"
  confirmation. **No Telegram, no Discord, no `send_message`.**
- If a fetcher can't reach its source, it returns a JSON envelope with
  `status: "unreachable"` or `"fallback"`. The helper script ships the
  brief with that source marked as offline; the Vercel page renders the
  gap honestly. **No fabrication.**
- If 5+ of 7 DFB sections are null, OR 3+ of 4 lifestyle pillars are
  empty, the helper script exits non-zero and the cron prompt should
  respond with `[SILENT]`.

## How the Vercel site reads this repo

The `Milo/website` repo (Next.js) has a prebuild step that pulls
`https://raw.githubusercontent.com/MiloTheAssistant/dailybrief/main/out/...`
for each published date, copying them into
`public/briefings/<date>.json` and `public/briefings/latest.json` before
the build runs. So:

1. Cron runs builder → writes `out/dfb/<date>.json` or
   `out/lifestyle/<date>.json` here → commits + pushes this repo.
2. Cron runs `cd ~/repos/Milo/website && vercel deploy --prod --yes`.
3. Vercel builds the site; prebuild step pulls the latest JSON from this
   repo; site renders.

## Sync model

This repo is the **canonical source**. Local working copies sync FROM
here:

```bash
cd ~/repos/dailybrief
git pull   # on every Mac that runs the cron jobs
```

To update a spec: edit here, commit, push, then `git pull` on the cron Mac.
