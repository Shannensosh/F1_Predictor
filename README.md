# 🏎️ PITWALL — Formula 1 2026 Live Dashboard

A real-data Formula 1 dashboard for the **2026 season**, styled with the
**formula1.com-inspired PITWALL theme** (F1 Red on carbon dark, Titillium Web) and built with the same
pattern as the FIFA predictor: a **Python pipeline that fetches live data + runs a
model, then renders self-contained interactive HTML pages**.

```bash
cd "F1 2026 Dashboard"
python3 build.py          # fetch (first run) → predict → render 8 pages
open site/index.html      # or serve: python3 -m http.server --directory site 4178
```

Requirements: **Python 3.9+**, **NumPy**, **requests** (all in Anaconda), plus **fastf1**
(`pip install fastf1`) for the official-telemetry replay sample (optional — falls back to
OpenF1 tracing without it). The first build needs internet; afterwards everything is cached
under `data/` and pages open offline. Live-timing pulls fresh OpenF1 telemetry in the browser.

---

## Data sources (real)

| API | Provides |
|---|---|
| **Jolpica / Ergast** (`api.jolpi.ca`) | 2026 schedule (+ circuit lat/long), race / qualifying / sprint results, driver & constructor standings, driver info. History 2024–26. |
| **OpenF1** (`api.openf1.org`) | Live-timing telemetry — car GPS position, intervals, tyre stints, pit stops, race-control (flags / safety car), weather (wind = "air flow", air & track temp). Also single-lap circuit outlines (from the `laps` endpoint). |
| **Open-Meteo** (`api.open-meteo.com`) | Free, keyless daily **weather forecast** for the next circuit (rain probability, temps, wind) → wet-pace adjustment. |
| **Motorsport.com RSS** | Latest **F1 news** headlines, scraped at build time for the Overview. |

The 2026 season is **live mid-season** (currently after Round 5 — Antonelli leads).

---

## The 8 pages

| Page | What it shows |
|---|---|
| **Overview** (`index.html`) | Next-GP countdown, championship leader, last winner, mini standings, next-race win-% strip, predicted champion, **latest F1 news** (scraped) and a **reliability/incidents** panel (real DNF causes). |
| **Live Timing** | A **faithful browser port of [IAmTomShaw/f1-race-replay](https://github.com/IAmTomShaw/f1-race-replay)** running the **latest Grand Prix**, baked at build time by `f1_prebake.py` via FastF1 (the repo's own data schema: per-frame positions, tyres, pits, track statuses, official rotation). Same interface as the desktop window: black canvas, twin track-boundary strips that recolour with the flags, checkered finish line, DRS zones, car dots with normal-offset labels, LAP/TIME/STATUS top-left, 240px leaderboard with tyre rings / PIT tags / gap seconds / OUT, weather panel, controls legend, bottom progress bar with SC / red-flag markers, centre transport buttons, and the app's keymap (SPACE ←/→ ↑/↓ 1–4 R D L B, click to select drivers, speeds 0.1×–256×). Fully local playback — never stalls. If a race's GPS feed truncates (2026 Monaco ends at the red flag — no source publishes the rest), the replay continues **timing-only to the chequered flag** with a clear notice. Re-run `python3 build.py` after a race weekend to bake the newest GP. |
| **Schedule** | All 22 rounds on an **interactive street & satellite map** (Leaflet — Carto dark + Esri World Imagery toggle). Click a pin or card and the map **flies to the circuit and draws its exactly-georeferenced track** (f1-circuits dataset, incl. the new Madrid layout) on the real tarmac, with prev/next round arrows and an overlay panel: turns, DRS zones, longest straight, Sector 1/2/3, circuit traits. |
| **Results** | Filter by round and category — **Qualifying / Sprint / Race** — with grids, gaps, points, fastest laps; driver text filter. |
| **Standings** | Drivers' & Constructors' tables + **points-evolution line chart** (cumulative points per round, top 8). |
| **Drivers** | The 2026 grid as number-on-team-colour badge cards (photos aren't in the open APIs). |
| **Driver Stats** | Completion %, wins, podiums, poles, DNFs, avg finish, points/race — sortable, toggle **2026 / 2024–26**. |
| **Prediction** | Next-race **win %** + podium %, 2026 **driver & constructor title %**, a self-documenting **factor catalogue** (each factor's source, weight & formula), per-driver breakdown showing base contributions and the two per-race multipliers, full methodology + disclaimer. |

---

## Prediction model — transparent, recency-weighted

Same philosophy as the FIFA "Predict·26" engine: no black box.

**Base Power Rating** = `0.38·form + 0.19·qualifying + 0.14·reliability + 0.29·car`,
then per race ×**circuit fit** ×**track history**.

| Factor | Type | Source |
|---|---|---|
| **Form** | base | Recency-weighted points-per-race. 2026 ×1.0, 2025 ×0.55, 2024 ×0.25; within a season weight halves every 6 races. |
| **Qualifying** | base | Recency-weighted average grid position. |
| **Reliability** | base | 1 − DNF rate (weighted); also sets each car's per-race retirement chance. |
| **Car index** | base | 2026 constructor strength (real) + curated package. |
| **Circuit fit** | ×0.88–1.12 | How the car's downforce, straight-line speed, tyre management, **weight** and **over/understeer balance** suit the circuit's demands (curves vs straights, tyre stress). |
| **Track history** | ×0.88–1.12 | The driver's own weighted average **finishing position at that specific circuit** across 2024–26. |
| **Weather (wet pace)** | next race only | If the **Open-Meteo forecast** predicts rain, a curated driver wet-skill swings the odds — strong wet drivers (Verstappen, Hamilton, Alonso) gain, scaled by rain probability. No effect on a dry forecast. |

A **Plackett–Luce / Gumbel** race simulator runs **20,000 Monte-Carlo seasons** over the
remaining rounds (with per-race retirements and a season-long form shock) to produce next-race
win/podium % and 2026 title %.

⚠️ **Curated estimates, labelled as such:** car downforce, weight and handling balance
(over/understeer) are **not exposed by any public F1 API** — they're informed approximations in
`f1_circuits.py`, used only to *nudge* the data-driven ratings. Circuit characteristics
(downforce/power/tyre demand) are likewise curated.

---

## Files

| File | Purpose |
|---|---|
| `f1_fetch.py` | Fetch + cache Jolpica + OpenF1 → normalised `data/*.json`. Builds the sample-race telemetry bundle. |
| `f1_circuits.py` | Curated 2026 circuit traits + per-constructor car/handling traits + `circuit_fit()`. |
| `f1_predict.py` | Power Rating + Monte-Carlo simulator → `data/predictions.json`. |
| `build.py` | Orchestrates the pipeline and renders the overview / schedule / drivers pages. |
| `pages_more.py` | Renders results / standings / driver-stats / prediction pages. |
| `pages_live.py` | Renders the live-timing page (track playback + telemetry panels). |
| `f1_replay.py` | FastF1-based replay builder — official telemetry, rotated track, numbered corners (sample). |
| `site/assets/theme.css` | PITWALL design system (formula1.com-inspired). |
| `site/assets/app.js` | Shared nav / formatters / projection helpers. |
| `data/` | Cached JSON (schedule, results, standings, predictions, sample race, …). |

### Tuning

Model constants sit at the top of `f1_predict.py` (`W_FORM…W_CAR`, `SEASON_WEIGHT`,
`BETA`, `SEASON_SHOCK`, `N_SIMS`). Curated traits live in `f1_circuits.py`. Re-run
`python3 build.py` after any change — the model retrains/resimulates and pages re-render.

---

## ⚠️ Disclaimer

Educational / entertainment dashboard. Not affiliated with Formula 1, the FIA, or any team.
Probabilities are statistical model outputs, not predictions of fact. Car/handling figures are
curated approximations. **Not betting advice.**
