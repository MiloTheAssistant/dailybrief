# Brief: Saturday — Weekend Executive Brief (Coffee Edition)

**Workflow:** `recurring_publish`
**Schedule:** 9:00 AM America/Chicago, Saturday only
**Destination:** **Vercel only** (https://daily-brief-tau.vercel.app/weekend/<date>)

---

## What this brief is

A calm, intelligent weekend briefing the reader can finish over coffee
in ~10 minutes. Modeled on the `Weekend_Executive_Brief_Prompt.md` spec
(see `references/weekend-executive-brief-spec.md` for the canonical
section structure).

The Saturday tone is **forward-leaning**: opportunities are surfaced
up top, action items emphasize "set up Monday."

The Sunday tone is **reflective**: week-closing, "what I learned / what
to carry into next week."

---

## Reader profile

60-year-old Microsoft executive preparing for semi-retirement around
age 63. Priorities, in order:

1. Preserve and grow wealth.
2. Build retirement income.
3. Reduce taxes legally.
4. Build AI businesses.
5. Build Bitcoin and digital asset income.
6. Maintain excellent health.
7. Continue learning.

The decision filter for inclusion: **does this improve retirement,
income, taxes, health, business, or AI capability?** If no — leave it out.

---

## Pillars (in render order)

The LifestyleEdition JSON has 11 pillars. The helper pre-populates the
data sides; the LLM fills the qualitative fields.

| # | Pillar | Data source | Model fills |
|---|---|---|---|
| 01 | Weather | `fetch_lifestyle_sources.py` (NWS) | `whatToWear` |
| 02 | Life | `fetch_proton_calendar.py` + `fetch_stl_events.py` | `oneThing`, `rec` |
| 03 | Vacation | curated `references/top-travel-ideas.md` + calendar | filters `driveDistanceIdeas` |
| 04 | Retirement | `fetch_tws_portfolio.py` | `planningNote` (Sat tone) |
| 05 | Executive Summary | (model only) | opportunities / summaryBullets / actionItems / funFact |
| 06 | Markets | `fetch_treasury.py` (Treasury CSV + Yahoo index charts) | `whyParagraph` |
| 07 | Investing Themes | `fetch_market_brief_rss.py` (Mag7 RSS, 7-day window) | `themes` filtered to MSFT / MSTR / STRC / AI / NVDA / AAPL / GOOGL / PLTR / Quantum / BTC |
| 08 | Retirement Watch | web_search at cron time + RSS | `items` for SS / Medicare / IRMAA / Roth / RMDs / estate / SSA-44 / home-sale exclusion |
| 09 | AI Landscape | `fetch_market_brief_rss.py` (AI RSS) | `entries` for OpenAI / Anthropic / Google / xAI / Local LLMs / Ollama / Open-source / Agents |
| 10 | Health (60+) | `fetch_health_research.py` (Lancet + Nature Medicine + JAMA) | `entries` for cardiac / longevity / GLP-1 / sleep / strength / TRT / nutrition |
| 11 | Worth Reading | (model only — picks from current week's substantive pieces) | articles (3) + videos (2) + podcast (1) |

---

## Section structure (from the executive-brief spec)

The Executive Brief spec defines 11 sections. They map onto the 11 pillars
1:1 in most cases; pillars 5 (Executive Summary) consolidates 4 of the
spec's sections (Opportunities, Summary, Action Items, Fun Section) and
pillars 1-4 (Weather / Life / Vacation / Retirement) are the lifestyle
overlays added by this brief.

| Spec section | Brief pillar |
|---|---|
| ☕ Header / Date | masthead only |
| 🎯 This Week's Opportunities | 05 Executive Summary |
| Executive Summary | 05 Executive Summary |
| Markets (S&P / Nasdaq / BTC / Treasury / DXY) | 06 Markets |
| My Investing Themes | 07 Investing Themes |
| Retirement Watch (SS / Medicare / IRMAA / Roth / RMDs / estate / SSA-44) | 08 Retirement Watch |
| AI Landscape | 09 AI Landscape |
| Bitcoin & Crypto | 07 Investing Themes (Bitcoin theme) |
| Technology | 09 AI Landscape (absorbs) |
| Health (60+ lens) | 10 Health |
| Worth Reading (3 articles + 2 YT + 1 podcast) | 11 Worth Reading |
| Action Items | 05 Executive Summary |
| Fun Section | 05 Executive Summary |

---

## Helper pipeline

`scripts/build_lifestyle_json.py saturday --date <YYYY-MM-DD> [--dry-run] [--skip-deploy]`

What the helper does, in order:

1. **Run fetchers** (all in parallel via sequential `subprocess.run`):
   - `fetch_lifestyle_sources.py` — Eureka 63025 weather from NWS.
   - `fetch_stl_events.py` — STL events (ExploreSTL + curated fallback).
   - `fetch_proton_calendar.py --from-date <today> --to-date <today>`.
   - `fetch_proton_mail.py --folder INBOX --unseen-only --since-hours 18 --limit 5`.
   - `fetch_tws_portfolio.py --plain` — current positions.
   - `fetch_treasury.py` — Treasury yield curve (10 rows) + S&P / Nasdaq / DXY / BTC.
   - `fetch_health_research.py` — 14-day window from Lancet + Nature Med + JAMA.
   - `fetch_market_brief_rss.py --window-hours 168` — 7-day RSS rollup.

2. **Assemble the LifestyleEdition JSON** with 11 pillars. Markets
   indicators are pre-populated from treasury + index charts. Other
   pillars have their data fields filled (calendar, events, RSS list)
   but qualitative fields (`*Plan*`, `*Note*`, `whyParagraph`, etc.)
   are set to `null` for the model to fill.

3. **Write JSON** to `out/lifestyle/<date>.json`.

4. **Write manifest** `out/manifest.json` (lists all published dates
   per kind — website prebuild reads this).

5. **Git commit + push** to `MiloTheAssistant/dailybrief` @ `main`.

6. **Vercel deploy** — runs `vercel deploy --prod --yes` from
   `Milo/website` (unless `--skip-deploy` is set, in which case the
   cron must trigger the deploy in detached background).

---

## Cron prompt

`prompts/brief-saturday-prompt.txt` (canonical, tracked in GH).

The prompt instructs the LLM to:

1. Run the helper in `--dry-run` mode.
2. Read the spec files (`goals/brief_saturday.md` and
   `~/Downloads/Weekend_Executive_Brief_Prompt.md`).
3. Apply the decision filter to each inclusion.
4. Enrich qualitative fields via `patch` on the raw JSON.
5. Write enriched JSON, run helper `--skip-deploy` for git push.
6. Trigger detached Vercel deploy via `nohup ... &`.
7. Return one-line confirmation.

---

## Self-checks (in the prompt)

- Helper exit code 0 → proceed.
- Helper exit non-zero → `[SILENT]`.
- 5+ of 11 pillars null after enrichment → `[SILENT]`.

## Hard rules

- No fabrication. If a section has nothing meaningful, set
  `noMeaningfulNews: true` or write "no notable moves" in 5 words.
- Total brief ≤ 2,000 words. Spec is "coffee length," not all-day.
- Decision filter applies to EVERY inclusion.
- No Telegram, no Discord, no send_message. The Vercel URL is the delivery.

## Reference

- Spec: `references/weekend-executive-brief-spec.md` (this repo).
- Source spec: `~/Downloads/Weekend_Executive_Brief_Prompt.md`.
- Cron prompt: `prompts/brief-saturday-prompt.txt`.
- JSON shape: `MiloTheAssistant/Milo/website/src/lib/briefings-types.ts` → `LifestyleEdition`.
