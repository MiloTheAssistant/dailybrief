# Goals Manifest

> Canonical source for the **three Proton-redesign daily briefs** that run as
> Hermes cron jobs (`brief-weekday-morning`, `brief-saturday`, `brief-sunday`).
>
> **Local-only briefs:** `brief_sunday_audit.md` lives on this Mac only — see
> the [Sunday Audit](#sunday-audit-local-only) section below. It is not
> published to GitHub on purpose.

## Active Briefs

| Cron | Schedule | Brief | Deliver | Source spec |
|---|---|---|---|---|
| `brief-weekday-morning` | `0 7 * * 1-5` (07:00 CT, Mon–Fri) | Weekday morning: market + calendar + inbox + portfolio | Telegram | [brief_weekday_morning.md](brief_weekday_morning.md) |
| `brief-saturday` | `0 9 * * 6` (09:00 CT, Sat) | Saturday lifestyle: weather, today's calendar, overnight inbox, one thing to do, weekend pick, read/listen/watch | Telegram | [brief_saturday.md](brief_saturday.md) |
| `brief-sunday` | `0 9 * * 0` (09:00 CT, Sun) | Sunday next-week preview: Mon–Fri calendar count + busiest day, weekend inbox recap, plan-this-week, weekend read | Telegram | [brief_sunday.md](brief_sunday.md) |

All three were registered on **2026-06-27** as part of the Proton redesign
(parallel-run with the 4 prior jobs until stable; the old jobs are being
retired in lockstep).

## Scripts

All scripts live in `scripts/` and are called by the cron prompt at fire time
(file-and-run pattern — no inline `python3 -c`, no `execute_code`).

| Script | Used by | Notes |
|---|---|---|
| `fetch_market_brief_rss.py` | weekday | RSS: SeekingAlpha + Yahoo Finance + Cointelegraph + Google News AI + Google News MAG7. Dedupes, JSON to stdout. |
| `fetch_proton_calendar.py` | weekday + saturday + sunday | Reads iCal share URL from `~/.config/hermes/proton-calendar-url`, parses with `icalendar`, JSON events to stdout. |
| `fetch_proton_mail.py` | weekday + saturday + sunday | Wraps `himalaya envelope list` against Proton Mail Bridge (127.0.0.1:1143). JSON envelopes to stdout. |
| `fetch_tws_portfolio.py` | weekday | IBAPI connection to TWS/IB Gateway. Account summary + positions + executions. |
| `fetch_lifestyle_sources.py` | saturday (legacy) | NWS Chicago forecast. Predecessor to the Proton redesign's lifestyle data; kept for reference while `brief-saturday` migration settles. |

## Sunday Audit (local-only)

`brief_sunday_audit.md` (cron `brief-sunday-audit`, schedule `0 21 * * 0`,
21:00 CT Sunday) is intentionally **not** in this repo. It covers system
ops (disk, Docker, gateway, backups) plus a quiet Proton week-in-review.

It lives on this Mac at `goals/brief_sunday_audit.md` and is **not** intended
for public review or upstream sync. If it ever needs to move, it gets its
own repo or stays in `~/memory/` as a private note — never the public
`dailybrief` repo.

## Retired Specs (local-only, not pushed)

These specs are preserved on this Mac for history but are NOT in this repo.
The README + manifest + active specs above are the canonical GitHub source.

| Spec | Local path | Why retired |
|---|---|---|
| Daily Financial Briefing (full DFB) | `goals/daily_financial_briefing.md` | Superseded by `brief_weekday_morning.md` which folds market + calendar + inbox + portfolio into one 07:00 CT brief. The 7-section DFB chain is preserved locally but has no live cron job. |
| Daily Market Brief (old) | `goals/daily_market_brief.md` | First superseded by `daily_financial_briefing.md`, reinstated as 8:45 AM quick-look, then re-superseded by `brief_weekday_morning.md`. |
| Daily Lifestyle Brief (single-job weekend) | `goals/daily_lifestyle_briefing.md` | Replaced by split: `brief_saturday.md` (present-tense) + `brief_sunday.md` (next-week-tense). The old job fired both days with the same content, which was the bug. |

## Source of Truth

This repo (`MiloTheAssistant/dailybrief`) is the **canonical source** for the
three active briefs. Local working copies on any Mac should sync FROM here —
not the other way around.

To update a spec:
1. Edit the file in this repo, commit, push.
2. On each Mac that runs the cron, `git pull` in `~/repos/dailybrief`.

To add a new brief:
1. Add `goals/brief_<name>.md` here first.
2. Register the cron job with `hermes cron create` using the spec as the prompt.
3. Add the script to `scripts/` if it needs a fetcher.
4. Update this manifest's Active table.
