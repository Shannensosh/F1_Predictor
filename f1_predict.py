"""
f1_predict.py — transparent 2026 win-probability engine.

Same philosophy as the FIFA "Predict·26" model: no black box. A per-driver
**Power Rating** is built from real, recency-weighted data, nudged by curated
circuit-fit, then turned into probabilities via a Plackett–Luce / Gumbel race
simulator (Monte-Carlo).

Outputs (consumed by build.py → prediction.html):
  • next race  : per-driver win % and podium %
  • 2026 title : per-driver and per-constructor championship %
  • a transparent factor breakdown for every driver

Rating = 0.40·form + 0.20·quali + 0.15·reliability + 0.25·car
  form        recency-weighted points-per-race  (2026 ≫ 2025 ≫ 2024)
  quali       recency-weighted grid position
  reliability 1 − DNF rate (weighted)
  car         2026 constructor strength + curated package
Per race the rating is multiplied by circuit_fit(constructor, circuit).
"""

import json
import os
import numpy as np

import f1_circuits as C

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# ── transparent model constants ──────────────────────────────────────────────
# Base Power Rating weights (sum to 1.0). Applied to normalised 0..1 features.
W_FORM, W_QUALI, W_REL, W_CAR = 0.38, 0.19, 0.14, 0.29
SEASON_WEIGHT = {"2024": 0.25, "2025": 0.55, "2026": 1.00}   # recency emphasis
RECENCY_HALFLIFE = 6.0     # within-season: races' weight halves every N races back
# Per-race multipliers applied on top of the base rating (each ~±0.12):
#   circuit_fit  — how the car suits the track (aero, power, tyre, weight, balance)
#   track_factor — the driver's own past finishing record at that circuit
TRACK_FACTOR_MAX = 0.12    # max ± nudge from a driver's track history
WET_GAIN = 0.55            # how strongly wet-weather skill swings next-race odds when it rains
WET_PIVOT = 75             # neutral wet-skill level (above gains in rain, below loses)
BETA = 7.2                 # decisiveness of the race simulator (higher = favourite stronger)
DNF_SCALE = 1.00           # multiplies (1−reliability) into a per-race retirement chance


def track_factor(track_avg, circuit_id):
    """Multiplier ~[0.88 … 1.12] from a driver's weighted average finishing
    position at this circuit. Strong history (low avg) → boost; poor → penalty;
    no history → neutral 1.0. P1 avg ≈ +0.11, P10.5 ≈ 0, P20 ≈ −0.10."""
    avg = track_avg.get(circuit_id)
    if avg is None:
        return 1.0
    raw = (10.5 - avg) / 10.5 * TRACK_FACTOR_MAX
    return round(1.0 + max(-TRACK_FACTOR_MAX, min(TRACK_FACTOR_MAX, raw)), 4)
# Season-long form uncertainty: each sim draws a constant per-driver strength
# shock (car upgrades, mid-season form swings). Keeps next-race odds ~unchanged
# but stops the points leader from being a near-certainty — a realistic tail.
SEASON_SHOCK = 1.6
N_SIMS = 20000

RACE_POINTS   = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}
SPRINT_POINTS = {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}


def _load(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


def _is_dnf(status):
    """A car is a DNF only if it didn't take the chequered flag. 'Finished',
    '+N Laps' and 'Lapped' are all classified finishers."""
    if not status:
        return False
    return not (status == "Finished" or status.startswith("+") or status == "Lapped")


# ─────────────────────────────────────────────────────────────────────────────
# Feature engineering from real results
# ─────────────────────────────────────────────────────────────────────────────
def build_features():
    results = _load("results.json")
    quali   = _load("qualifying.json")
    standings = _load("standings.json")
    schedule = _load("schedule.json")

    grid = standings["drivers"]                 # 2026 grid (driverId → info)
    driver_ids = [d["driverId"] for d in grid]
    cons_of = {d["driverId"]: d["constructorId"] for d in grid}
    name_of = {d["driverId"]: f'{d["given"]} {d["family"]}' for d in grid}
    code_of = {d["driverId"]: d["code"] for d in grid}
    num_of  = {d["driverId"]: d.get("num") for d in grid}
    colour_of = {d["driverId"]: standings["colours"].get(str(d.get("num"))) for d in grid}

    # accumulate weighted form / reliability across seasons (most-recent first)
    acc = {d: {"pts_w": 0.0, "w": 0.0, "fin_w": 0.0, "tot_w": 0.0,
               "grid_w": 0.0, "gw": 0.0} for d in driver_ids}
    # per-driver, per-circuit finishing-position history (track record)
    hist = {d: {} for d in driver_ids}   # hist[did][circuitId] = {"sum": w·pos, "w": w}

    for season in ("2024", "2025", "2026"):
        sw = SEASON_WEIGHT[season]
        races = results.get(season, [])
        n = len(races)
        for ri, race in enumerate(races):
            # recency within season: latest race weight 1, older decays
            races_ago = (n - 1 - ri)
            rw = sw * 0.5 ** (races_ago / RECENCY_HALFLIFE)
            circ = race.get("circuitId")
            for res in race["results"]:
                did = res["driverId"]
                if did not in acc:
                    continue
                a = acc[did]
                a["pts_w"] += res["points"] * rw
                a["w"]     += rw
                a["tot_w"] += rw
                if not _is_dnf(res["status"]):
                    a["fin_w"] += rw
                    if isinstance(res["pos"], int) and circ:
                        h = hist[did].setdefault(circ, {"sum": 0.0, "w": 0.0})
                        h["sum"] += res["pos"] * sw    # season-weighted (circuits recur yearly)
                        h["w"]   += sw
        # qualifying grid pace
        for race in quali.get(season, []):
            races_ago = max(0, n - 1 - race["round"] + 1)
            rw = sw * 0.5 ** (races_ago / RECENCY_HALFLIFE)
            for q in race["results"]:
                did = q["driverId"]
                if did not in acc:
                    continue
                acc[did]["grid_w"] += q["pos"] * rw
                acc[did]["gw"]     += rw

    # constructor 2026 strength (real) + curated package
    cmax = max((c["points"] for c in standings["constructors"]), default=1) or 1
    cpts = {c["constructorId"]: c["points"] / cmax for c in standings["constructors"]}

    feats = {}
    for did in driver_ids:
        a = acc[did]
        ppr  = a["pts_w"] / a["w"] if a["w"] else 0.0          # weighted points/race
        rel  = a["fin_w"] / a["tot_w"] if a["tot_w"] else 0.85  # finish rate
        rel  = min(0.99, max(0.55, rel))
        gpos = a["grid_w"] / a["gw"] if a["gw"] else 12.0       # weighted avg grid
        quali_score = max(0.0, (21 - gpos) / 20.0)
        cid = cons_of[did]
        cur = (C.car(cid)["downforce_bias"] + C.car(cid)["straightline"]) / 200.0
        car_idx = 0.8 * cpts.get(cid, 0.3) + 0.2 * cur
        # per-circuit average finish (weighted), for the track-history factor
        track_avg = {c: h["sum"] / h["w"] for c, h in hist[did].items() if h["w"]}
        feats[did] = {"ppr": ppr, "rel": rel, "gpos": gpos,
                      "quali": quali_score, "car": car_idx, "track_avg": track_avg}

    # normalise form & quali to 0..1 across the grid
    pmax = max((f["ppr"] for f in feats.values()), default=1) or 1
    for did, f in feats.items():
        f["form_n"]  = f["ppr"] / pmax
        f["quali_n"] = f["quali"]      # already 0..1
        f["car_n"]   = f["car"]
        f["rating"]  = (W_FORM * f["form_n"] + W_QUALI * f["quali_n"]
                        + W_REL * f["rel"] + W_CAR * f["car_n"])

    # find next race + remaining schedule (rounds after last completed 2026 race)
    completed = max((r["round"] for r in results.get("2026", [])), default=0)
    remaining = [r for r in schedule if r["round"] > completed]
    next_race = remaining[0] if remaining else schedule[-1]

    meta = {
        "driver_ids": driver_ids, "cons_of": cons_of, "name_of": name_of,
        "code_of": code_of, "num_of": num_of, "colour_of": colour_of,
        "completed_round": completed, "remaining": remaining,
        "next_race": next_race,
        "current_points": {d["driverId"]: d["points"] for d in grid},
        "cons_points": {c["constructorId"]: c["points"] for c in standings["constructors"]},
        "cons_name": {c["constructorId"]: c["name"] for c in standings["constructors"]},
    }
    return feats, meta


# ─────────────────────────────────────────────────────────────────────────────
# Monte-Carlo race + season simulation (vectorised)
# ─────────────────────────────────────────────────────────────────────────────
def _points_vector(order, table):
    """order: (N, D) array of driver indices by finishing position (best first).
    Returns (N, D) points indexed by driver."""
    N, D = order.shape
    pts = np.zeros((N, D))
    for pos, p in table.items():
        if pos <= D:
            idx = order[:, pos - 1]
            pts[np.arange(N), idx] += p
    return pts


def simulate(feats, meta, n_sims=N_SIMS, seed=20260101, wet_mult=None):
    rng = np.random.default_rng(seed)
    dids = meta["driver_ids"]
    D = len(dids)
    ratings = np.array([feats[d]["rating"] for d in dids])
    rel = np.array([feats[d]["rel"] for d in dids])
    cons = [meta["cons_of"][d] for d in dids]

    track_avgs = [feats[d].get("track_avg", {}) for d in dids]

    # per-remaining-race log-strength (rating × circuit fit × track history)
    races = meta["remaining"]
    strength_by_race, is_sprint = [], []
    for r in races:
        cid = r["circuitId"]
        fit = np.array([C.circuit_fit(cons[i], cid) for i in range(D)])
        trk = np.array([track_factor(track_avgs[i], cid) for i in range(D)])
        strength_by_race.append(ratings * fit * trk * BETA)
        is_sprint.append(bool(r.get("isSprint")))

    # weather only forecast for the NEXT race → wet multiplier on race 0 only
    if wet_mult is not None and strength_by_race:
        strength_by_race[0] = strength_by_race[0] * np.asarray(wet_mult)

    # accumulators
    season_pts = np.tile(np.array([meta["current_points"][d] for d in dids], float),
                         (n_sims, 1))
    champ_count = np.zeros(D)
    next_p1 = np.zeros(D)
    next_top3 = np.zeros(D)
    next_pts_sum = np.zeros(D)

    # one constant strength shock per (sim, driver), held across the whole season
    shock = rng.normal(0.0, SEASON_SHOCK, size=(n_sims, D))

    for ridx, logS in enumerate(strength_by_race):
        # Plackett–Luce ordering via Gumbel-max trick
        gumbel = rng.gumbel(size=(n_sims, D))
        scores = logS[None, :] + shock + gumbel
        # retirements: drivers who DNF get pushed to the back
        dnf = rng.random((n_sims, D)) < (1 - rel)[None, :] * DNF_SCALE
        scores = np.where(dnf, -1e6 - rng.random((n_sims, D)), scores)
        order = np.argsort(-scores, axis=1)             # (N, D) best→worst

        pts = _points_vector(order, RACE_POINTS)
        if is_sprint[ridx]:
            pts = pts + _points_vector(order, SPRINT_POINTS)
        season_pts += pts

        if ridx == 0:   # the *next* race → win / podium stats
            winners = order[:, 0]
            np.add.at(next_p1, winners, 1)
            for k in range(3):
                np.add.at(next_top3, order[:, k], 1)
            next_pts_sum += pts.sum(axis=0)

    champs = np.argmax(season_pts, axis=1)
    np.add.at(champ_count, champs, 1)

    win_pct   = {dids[i]: 100 * next_p1[i] / n_sims for i in range(D)}
    podium    = {dids[i]: 100 * next_top3[i] / n_sims for i in range(D)}
    title_pct = {dids[i]: 100 * champ_count[i] / n_sims for i in range(D)}
    exp_pts   = {dids[i]: next_pts_sum[i] / n_sims for i in range(D)}

    # constructor title %: champion's constructor per sim
    cons_title = {}
    cons_arr = np.array([meta["cons_of"][d] for d in dids])
    # accumulate constructor season points to find constructor champion per sim
    uniq_cons = sorted(set(cons_arr))
    cidx = {c: i for i, c in enumerate(uniq_cons)}
    cons_season = np.zeros((n_sims, len(uniq_cons)))
    for i in range(D):
        cons_season[:, cidx[cons_arr[i]]] += season_pts[:, i]
    cons_champ = np.argmax(cons_season, axis=1)
    cc = np.zeros(len(uniq_cons)); np.add.at(cc, cons_champ, 1)
    for c in uniq_cons:
        cons_title[c] = 100 * cc[cidx[c]] / n_sims

    return {"win_pct": win_pct, "podium": podium, "title_pct": title_pct,
            "exp_pts": exp_pts, "cons_title": cons_title}


# ─────────────────────────────────────────────────────────────────────────────
# Assemble the prediction payload
# ─────────────────────────────────────────────────────────────────────────────
def run(n_sims=N_SIMS, verbose=False):
    feats, meta = build_features()
    nr = meta["next_race"]
    nrc = nr["circuitId"]

    # ── weather forecast for the next race → per-driver wet multiplier ───────
    forecast, wet_mult = None, None
    try:
        import f1_fetch
        forecast = f1_fetch.fetch_forecast(nr.get("lat"), nr.get("long"), nr.get("date"))
    except Exception:  # noqa: BLE001 — forecast is best-effort
        forecast = None
    rain_weight = 0.0
    if forecast and forecast.get("in_range") and forecast.get("precip_prob") is not None:
        rain_weight = max(0.0, (forecast["precip_prob"] - 20) / 80.0)   # <20% → no effect
    wet_factor = {}
    for did in meta["driver_ids"]:
        ws = C.wet_skill(did)
        wf = 1.0 + (ws - WET_PIVOT) / 100.0 * WET_GAIN * rain_weight
        wet_factor[did] = round(wf, 4)
    if rain_weight > 0:
        wet_mult = [wet_factor[d] for d in meta["driver_ids"]]

    sim = simulate(feats, meta, n_sims=n_sims, wet_mult=wet_mult)

    drivers = []
    for did in meta["driver_ids"]:
        f = feats[did]
        cid = meta["cons_of"][did]
        trk_avg = f.get("track_avg", {}).get(nrc)
        trk_f = track_factor(f.get("track_avg", {}), nrc)
        base = f["rating"]
        # final per-race strength = base × circuit_fit × track_factor
        fit = C.circuit_fit(cid, nrc)
        drivers.append({
            "driverId": did, "name": meta["name_of"][did],
            "code": meta["code_of"][did], "num": meta["num_of"][did],
            "constructorId": cid, "constructor": meta["cons_name"].get(cid, cid),
            "colour": meta["colour_of"][did],
            "rating": round(base, 4),
            # weighted contributions of each base factor (for a stacked breakdown)
            "contrib": {
                "form": round(W_FORM * f["form_n"], 4),
                "quali": round(W_QUALI * f["quali_n"], 4),
                "reliability": round(W_REL * f["rel"], 4),
                "car": round(W_CAR * f["car_n"], 4),
            },
            "form_n": round(f["form_n"], 4), "quali_n": round(f["quali_n"], 4),
            "rel": round(f["rel"], 4), "car_n": round(f["car_n"], 4),
            "avg_grid": round(f["gpos"], 1),
            "fit": fit,
            "fit_parts": C.fit_breakdown(cid, nrc),
            "track_factor": trk_f,
            "track_avg_finish": round(trk_avg, 1) if trk_avg is not None else None,
            "race_strength": round(base * fit * trk_f, 4),
            "balance": C.balance_label(cid),
            "weight_kg": C.car(cid)["weight_kg"],
            "wet_skill": C.wet_skill(did),
            "wet_factor": wet_factor[did],
            "current_points": meta["current_points"][did],
            "win_pct": round(sim["win_pct"][did], 2),
            "podium_pct": round(sim["podium"][did], 2),
            "title_pct": round(sim["title_pct"][did], 2),
            "exp_next_pts": round(sim["exp_pts"][did], 2),
        })
    drivers.sort(key=lambda d: d["win_pct"], reverse=True)

    constructors = sorted(
        [{"constructorId": c, "name": meta["cons_name"].get(c, c),
          "title_pct": round(sim["cons_title"][c], 2),
          "current_points": meta["cons_points"].get(c, 0)}
         for c in sim["cons_title"]],
        key=lambda c: c["title_pct"], reverse=True)

    payload = {
        "next_race": {
            "round": nr["round"], "name": nr["name"], "circuitId": nr["circuitId"],
            "circuitName": nr["circuitName"], "country": nr["country"],
            "date": nr["date"], "circuit_traits": C.circuit(nr["circuitId"]),
        },
        "forecast": forecast,
        "rain_weight": round(rain_weight, 3),
        "completed_round": meta["completed_round"],
        "remaining_count": len(meta["remaining"]),
        "drivers": drivers,
        "constructors": constructors,
        "model": {
            "weights": {"form": W_FORM, "quali": W_QUALI,
                        "reliability": W_REL, "car": W_CAR},
            "season_weight": SEASON_WEIGHT, "recency_halflife": RECENCY_HALFLIFE,
            "beta": BETA, "n_sims": n_sims, "season_shock": SEASON_SHOCK,
            "track_factor_max": TRACK_FACTOR_MAX,
            "race_points": RACE_POINTS, "sprint_points": SPRINT_POINTS,
            # full, self-documenting factor catalogue for the explainability UI
            "factors": [
                {"key": "form", "label": "Form", "kind": "base", "weight": W_FORM,
                 "source": "real", "data": "Race results 2024–26",
                 "desc": "Recency-weighted championship points per race. 2026 counts most; "
                         "older seasons fade and within a season weight halves every 6 races."},
                {"key": "quali", "label": "Qualifying pace", "kind": "base", "weight": W_QUALI,
                 "source": "real", "data": "Qualifying / grid 2024–26",
                 "desc": "Recency-weighted average grid position — one-lap speed, separate from race pace."},
                {"key": "reliability", "label": "Reliability", "kind": "base", "weight": W_REL,
                 "source": "real", "data": "DNFs in results 2024–26",
                 "desc": "1 − DNF rate (weighted). Also sets each car's per-race retirement chance in the sim."},
                {"key": "car", "label": "Car index", "kind": "base", "weight": W_CAR,
                 "source": "mixed", "data": "Constructor standings + curated package",
                 "desc": "80% live 2026 constructor strength, 20% curated package (downforce + straight-line)."},
                {"key": "circuit_fit", "label": "Circuit fit", "kind": "multiplier", "weight": None,
                 "source": "curated", "data": "Curated car ↔ circuit traits",
                 "desc": "Per-race ×0.88–1.12. Matches the car's downforce, straight-line speed, tyre "
                         "management, weight and over/understeer balance to the circuit's demands "
                         "(curves vs straights, tyre stress)."},
                {"key": "track_factor", "label": "Track history", "kind": "multiplier", "weight": None,
                 "source": "real", "data": "Driver's finishes at this circuit 2024–26",
                 "desc": "Per-race ×0.88–1.12 from the driver's own average finishing position at that "
                         "specific circuit. Strong history boosts; weak history penalises; none = neutral."},
                {"key": "weather", "label": "Weather (wet pace)", "kind": "multiplier", "weight": None,
                 "source": "mixed", "data": "Open-Meteo forecast + curated wet skill",
                 "desc": "If rain is forecast for the next race, a curated driver wet-weather skill "
                         "swings the odds — strong wet drivers (e.g. Verstappen, Hamilton, Alonso) gain, "
                         "weaker ones lose. Scales with the rain probability; no effect on a dry forecast."},
                {"key": "season_shock", "label": "Form uncertainty", "kind": "sim", "weight": None,
                 "source": "model", "data": "Per-simulation random shock",
                 "desc": "Each of the 20k simulated seasons draws a constant per-driver strength shock "
                         "(upgrades, slumps) so the points leader isn't a near-certainty."},
            ],
        },
    }
    if verbose:
        print(f"Next race: R{nr['round']} {nr['name']} ({nr['circuitName']})")
        print(f"Remaining races: {len(meta['remaining'])}  ·  sims: {n_sims:,}")
        print("\nNext-race win %:")
        for d in drivers[:8]:
            print(f"  {d['win_pct']:5.1f}%  {d['name']:22} {d['constructor']:13} "
                  f"(rating {d['rating']:.3f}, fit {d['fit']})")
        print("\n2026 title %:")
        for d in sorted(drivers, key=lambda x: -x['title_pct'])[:8]:
            print(f"  {d['title_pct']:5.1f}%  {d['name']:22} {d['current_points']:.0f} pts")
        print("\nConstructor title %:")
        for c in constructors[:6]:
            print(f"  {c['title_pct']:5.1f}%  {c['name']:14} {c['current_points']:.0f} pts")
    return payload


if __name__ == "__main__":
    p = run(verbose=True)
    out = os.path.join(DATA, "predictions.json")
    with open(out, "w") as f:
        json.dump(p, f, separators=(",", ":"))
    print(f"\n→ wrote {out}")
