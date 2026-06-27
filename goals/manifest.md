# Goals Manifest

> Canonical source for the **three Vercel-published daily briefs** that run
> as Hermes cron jobs. Saturday + Sunday are lifestyle (Life, Vacation,
> Retirement, Weather for Eureka, MO 63025). Weekday morning is the
> 7-section Daily Financial Briefing (DFB).
>
> **Local-only briefs:** `brief_sunday_audit.md` lives on this Mac only —
> Telegram delivery, not in this repo.

## Active Briefs (all Vercel-published)

| Cron | Schedule | Brief | Deliver | Source spec |
|---|---|---|---|---|
| `brief-weekday-morning` | `0 7 * * 1-5` (07:00 CT, Mon–Fri) | DFB — 7 sections: market headlines, bitcoin/strategy, institutional, creator intel, AI race, retirement, health | **Vercel only** (`https://daily-brief-tau.vercel.app/`) | [brief_weekday_morning.md](brief_weekday_morning.md) |
| `brief-saturday` | `0 9 * * 6` (09:00 CT, Sat) | Saturday Lifestyle — 4 pillars: Life, Vacation, Retirement, Weather (Eureka MO 63025) | **Vercel only** (`https://daily-brief-tau.vercel.app/weekend/<date>`) | [brief_saturday.md](brief_saturday.md) |
| `brief-sunday` | `0 9 * * 0` (09:00 CT, Sun) | Sunday Lifestyle — 4 pillars (reflective tone) | **Vercel only** (`https://daily-brief-tau.vercel.app/weekend/<date>`) | [brief_sunday.md](brief_sunday.md) |

All three were re-registered 2026-06-27 as part of the Vercel-only
redesign (DFB used to be Discord + Vercel; Sat/Sun used to be Telegram).
The lifestyle briefs went from one job (lifestyle-brief-9am-weekend) to
two jobs (Sat present-tense + Sun reflective) on the same date.

## Scripts

All scripts live in `scripts/` and are called by the cron prompt at fire
time (file-and-run pattern — no inline `python3 -c`, no `execute_code`).

| Script | Used by | Notes |
|---|---|---|
| `fetch_market_brief_rss.py` | DFB | RSS: SeekingAlpha + Yahoo Finance + Cointelegraph + Google News AI + Google News MAG7. Dedupes, JSON to stdout. |
| `fetch_proton_calendar.py` | DFB + Sat + Sun | iCal share URL → JSON events. |
| `fetch_proton_mail.py` | DFB + Sat + Sun | `himalaya envelope list` via Proton Bridge → JSON envelopes. |
| `fetch_tws_portfolio.py` | DFB + Sat + Sun | IBAPI to TWS/IB Gateway → account summary + positions. |
| `fetch_lifestyle_sources.py` | Sat + Sun | NWS forecast. Default Eureka MO 63025; override with `--lat/--lon/--label`. |
| `fetch_stl_events.py` | Sat + Sun | St. Louis area events via ExploreSTL list page; curated fallback when site is JS-only. |
| `build_lifestyle_json.py` | Sat + Sun | Assembles `LifestyleEdition` JSON, writes to `out/lifestyle/<date>.json`, commits + pushes + `vercel deploy --prod`. |
| `build_dfb_json.py` | DFB | Assembles `Briefing` JSON (7 sections), writes to `out/dfb/<date>.json`, commits + pushes + `vercel deploy --prod`. |
| `_publish_common.py` | helper | Shared assembler + ship pipeline (git + Vercel) used by both `build_*.py` scripts. |

## Reference data

| File | Used by | Notes |
|---|---|---|
| `references/top-travel-ideas.md` | Sat + Sun | Curated drive-distance travel ideas from 63025 (St. Louis region + within 3 hrs). Model filters per brief. |
| `references/top-stl-events-curated.md` | Sat + Sun | Fallback STL events list when `fetch_stl_events.py` can't parse live HTML. |

## Output artifacts (this repo, not the website)

```
dailybrief/
└── out/
    ├── dfb/
    │   └── <date>.json       # 7-section DFB, one per weekday
    └── lifestyle/
        └── <date>.json       # LifestyleEdition, one per Sat + Sun
```

These are the canonical published JSON files. They live in this repo so
`git log` shows the publication history. The `Milo/website` repo reads
them directly at Vercel build time (via a prebuild step that pulls
`https://raw.githubusercontent.com/MiloTheAssistant/dailybrief/main/out/...`).
No coupling between repos beyond that.

## Sunday Audit (local-only)

`brief_sunday_audit.md` (cron `brief-sunday-audit`, schedule `0 21 * * 0`,
21:00 CT Sunday) is intentionally **not** in this repo. System ops
checklist + week Proton recap. **Telegram delivery only.**

It lives on this Mac at `goals/brief_sunday_audit.md` and is not
intended for public review or upstream sync.

## Retired Specs (local-only, not pushed)

These are preserved on this Mac for history but are NOT in this repo.

| Spec | Local path | Why retired |
|---|---|---|
| Daily Financial Briefing (full 7-section chain spec) | `goals/daily_financial_briefing.md` | Superseded by `brief_weekday_morning.md`. The 7-section chain itself is preserved as the **shape** that `build_dfb_json.py` emits. |
| Daily Market Brief (old) | `goals/daily_market_brief.md` | Re-superseded by `brief_weekday_morning.md`. |
| Daily Lifestyle Brief (single-job weekend) | `goals/daily_lifestyle_briefing.md` | Replaced by `brief_saturday.md` + `brief_sunday.md`. |

## Source of Truth

This repo (`MiloTheAssistant/dailybrief`) is the **canonical source** for
the three active briefs + their helper scripts. Local working copies on
any Mac should sync FROM here.

To update a spec:
1. Edit the file in this repo, commit, push.
2. On each Mac that runs the cron, `git pull` in `~/repos/dailybrief`.

To add a new brief:
1. Add `goals/brief_<name>.md` here first.
2. Add the cron prompt that calls the helper script.
3. Add any new fetcher scripts to `scripts/`.
4. Update the `Milo/website` site repo to render the new JSON shape.
5. Update this manifest's Active table.
