# Hermes Handoff

This repo is the publisher package for the three public daily briefs. Hermes
owns scheduling, execution supervision, and final status delivery. The repo
owns source collection, JSON publishing, manifest refresh, and Vercel deploys.

## Active Jobs

| Hermes job | Schedule | Entrypoint | Public URL |
|---|---:|---|---|
| `brief-weekday-morning` | `0 7 * * 1-5` | `scripts/hermes_jobs/weekday_morning.py` | `https://daily-brief-tau.vercel.app/` |
| `brief-saturday` | `0 9 * * 6` | `scripts/hermes_jobs/saturday_lifestyle.py` | `https://daily-brief-tau.vercel.app/weekend/<date>` |
| `brief-sunday` | `0 9 * * 0` | `scripts/hermes_jobs/sunday_lifestyle.py` | `https://daily-brief-tau.vercel.app/weekend/<date>` |

The Sunday system audit is not public and is not part of this handoff package.

## Runtime Contract

Hermes should call one entrypoint per scheduled job and report only its final
JSON envelope, or `[SILENT]` when the entrypoint emits that exact value.

The entrypoints:

1. run from `/Volumes/BotCentral/Users/milo/repos/dailybrief`
2. sync the repo with `git pull --ff-only`
3. publish an existing enriched JSON artifact with `--use-enriched`
4. refresh `/Volumes/BotCentral/Users/milo/repos/Milo/website/public/briefings`
5. deploy Vercel production with `vercel deploy --prod --non-interactive`
6. print a machine-readable final status envelope

Example success envelope:

```json
{
  "status": "published",
  "job": "weekday",
  "kind": "dfb",
  "date": "2026-07-06",
  "url": "https://daily-brief-tau.vercel.app/",
  "deployed": true,
  "preflight": "ok"
}
```

## Cron Registration

Create or update the jobs from the cron Mac:

```bash
cd /Volumes/BotCentral/Users/milo/repos/dailybrief

hermes cron create "0 7 * * 1-5" \
  "Run scripts/hermes_jobs/weekday_morning.py. Report the final JSON envelope or [SILENT]." \
  --script /Volumes/BotCentral/Users/milo/repos/dailybrief/scripts/hermes_jobs/weekday_morning.py \
  --name "brief-weekday-morning"

hermes cron create "0 9 * * 6" \
  "Generate/enrich the Saturday lifestyle JSON, then run scripts/hermes_jobs/saturday_lifestyle.py. Report the final JSON envelope or [SILENT]." \
  --name "brief-saturday"

hermes cron create "0 9 * * 0" \
  "Generate/enrich the Sunday lifestyle JSON, then run scripts/hermes_jobs/sunday_lifestyle.py. Report the final JSON envelope or [SILENT]." \
  --name "brief-sunday"
```

The weekday job is deterministic today because `scripts/enrich_dfb_edition.py`
authors the qualitative fields. Weekend jobs still require the Hermes prompt to
fill the qualitative fields in `out/lifestyle/<date>.json` before calling the
publish entrypoint.

## Manual Runs

Safe plan check. This validates local paths and prints the exact command plan
without executing any command, commit, push, or deploy:

```bash
python3 scripts/hermes_jobs/weekday_morning.py --date 2026-07-06 --dry-run
python3 scripts/hermes_jobs/saturday_lifestyle.py --date 2026-07-04 --dry-run
python3 scripts/hermes_jobs/sunday_lifestyle.py --date 2026-07-05 --dry-run
```

Live run:

```bash
python3 scripts/hermes_jobs/weekday_morning.py --date 2026-07-06
python3 scripts/hermes_jobs/saturday_lifestyle.py --date 2026-07-04
python3 scripts/hermes_jobs/sunday_lifestyle.py --date 2026-07-05
```

Use `--skip-deploy` to commit/push JSON and manifest only:

```bash
python3 scripts/hermes_jobs/weekday_morning.py --date 2026-07-06 --skip-deploy
```

Use `--no-pull` only for local test runs where the branch is intentionally not
tracking remote state.

## Source Preconditions

- Proton Bridge IMAP must be listening on `127.0.0.1:1143`.
- Proton Bridge SMTP should be listening on `127.0.0.1:1025`.
- Bridge credentials file must exist at
  `/Volumes/BotCentral/Users/milo/.config/codex_skills/protonmail-bridge.env`
  with owner-only permissions.
- Himalaya must be configured for Proton Mail.
- TWS/IB Gateway should listen on `127.0.0.1:7497` for portfolio-backed
  retirement data. If it is down, the weekday job marks preflight degraded.
- Vercel CLI must be authenticated for the `digitalenergy` account.
- `/Volumes/BotCentral/Users/milo/repos/Milo/website` must exist and be linked
  to the correct Vercel project.

Read-only preflight:

```bash
python3 scripts/build_dfb_json.py --check-deps
```

## Recovery

Check scheduler state:

```bash
hermes cron list
hermes cron status
hermes cron run brief-weekday-morning
```

Check repo publication state:

```bash
git log --oneline -5
cat out/manifest.json
```

Check website pull/deploy locally:

```bash
cd /Volumes/BotCentral/Users/milo/repos/Milo/website
npm run fetch-briefs
vercel deploy --prod --non-interactive
```

If the repo JSON exists and the manifest contains the date but the live site is
stale, treat it as a website fetch/deploy/cache problem before regenerating the
brief.
