# St. Louis Area Events — Curated Fallback

Used by `scripts/fetch_stl_events.py` and the lifestyle brief when the
live fetcher is offline. **Check dates before recommending** — these
are recurring, but specific instances change year-to-year.

---

## Always-on (no specific date needed)

- **St. Louis Art Museum** (Forest Park) — Free, always open. Stieglitz,
  Picasso, German Expressionists.
- **City Museum** — Open daily, kid-and-adult-friendly. Multi-story
  repurposed industrial space. Half museum, half jungle gym.
- **Missouri Botanical Garden** — Open daily. Climatron geodesic dome,
  Japanese garden. Best April–October.
- **Forest Park** (St. Louis) — Larger than Central Park. Free
  zoo, art museum, history museum, science center. The Muny
  (outdoor theater) runs June–August.
- **Gateway Arch + museum** — Open daily. Trams up the arch (book
  ahead). Mississippi riverfront.
- **Grant's Farm** (free with parking pass) — Open seasonally
  April–October. Anheuser-Busch estate, deer + bison + Clydesdales.

## Recurring weekly

- **Soulard Farmers Market** — Saturday mornings year-round. The big
  one.
- **Tower Grove Park** — Saturday mornings, Tower Grove Farmers
  Market (April–November).
- **Schlafly Farmers Market** (Maplewood) — Wednesday afternoons,
  seasonal.

## Recurring monthly

- **First Fridays** (various galleries, Cherokee Street + Grand
  Center) — monthly art walks.
- **Third Fridays** — similar, different neighborhoods.

## Seasonal (no specific dates)

- **Cicada-summer music festivals** — Gather STL area lineup changes
  year-to-year. Check lineup before recommending.

---

## What this list is NOT

- A replacement for live event scraping. `fetch_stl_events.py` should
  hit Eventbrite ST. Louis + ExploreSTL + the city's official
  tourism site.
- A specific-date calendar. Don't tell John an event is on
  2026-07-15 unless you actually verified it.
- A recommendation to buy tickets. Always link to the official
  source.

---

## Notes for the model

- When `fetch_stl_events.py` returns successfully, prefer its data
  over this list.
- When it fails, fall back to one or two always-on picks (City
  Museum, Art Museum, Botanical Garden) plus one seasonal pick.
- Never fabricate specific events, lineups, dates, or prices.
