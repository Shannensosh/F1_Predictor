"""
f1_tune.py — backtest, ablation & weight tuning for the prediction factors.

Walk-forward validation: for every completed 2025–26 race, rebuild each driver's
features from PRIOR races only, compute a per-driver race strength, and score it
against the actual finishing order. Reports:
  • baseline accuracy (Kendall τ vs finishing order, top-1 winner hit, winner log-loss)
  • leave-one-out ablation for every back-testable factor (does removing it help/hurt?)
  • a random search over the four base-rating weights

Factors that have NO historical signal to backtest (weather forecast, news upgrades,
news sentiment/penalties) and the pure-simulation shock are reported separately —
they can't be empirically validated here, only reasoned about.
"""
import json
import os
import numpy as np

import f1_circuits as C

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

def _load(n):
    with open(os.path.join(DATA, n)) as f:
        return json.load(f)

RESULTS = _load("results.json")
QUALI = _load("qualifying.json")
STAND = _load("standings.json")
GRID = [d["driverId"] for d in STAND["drivers"]]
CONS_OF = {d["driverId"]: d["constructorId"] for d in STAND["drivers"]}

SEASON_W = {"2024": 0.25, "2025": 0.55, "2026": 1.00}
HALFLIFE = 6.0
BETA = 7.2
DEFAULT_W = (0.38, 0.19, 0.14, 0.29)   # form, quali, rel, car (current model)

BASE = ["form", "quali", "rel", "car"]
MULT = ["circuit_fit", "track_factor", "momentum"]
BACKTESTABLE = BASE + MULT


def _flat(src):
    out = []
    for s in ("2024", "2025", "2026"):
        for r in sorted(src.get(s, []), key=lambda x: x["round"]):
            out.append((s, r["round"], r))
    return out

RACE_SEQ = _flat(RESULTS)
GIDX = {(s, rnd): i for i, (s, rnd, _) in enumerate(RACE_SEQ)}
QUALI_BY = {(s, q["round"]): q for s in QUALI for q in QUALI.get(s, [])}


def _dnf(st):
    return not (st == "Finished" or (st or "").startswith("+") or st == "Lapped")


def _car_index(ts, tr):
    """Constructor strength = season-to-date points (fallback prior season)."""
    pts = {}
    for s, rnd, race in RACE_SEQ:
        if s == ts and rnd < tr:
            for res in race["results"]:
                c = res.get("constructorId") or CONS_OF.get(res["driverId"])
                if c:
                    pts[c] = pts.get(c, 0) + res["points"]
    if not pts or max(pts.values()) == 0:
        ps = str(int(ts) - 1)
        for s, rnd, race in RACE_SEQ:
            if s == ps:
                for res in race["results"]:
                    c = res.get("constructorId") or CONS_OF.get(res["driverId"])
                    if c:
                        pts[c] = pts.get(c, 0) + res["points"]
    mx = max(pts.values()) if pts else 1
    return {c: v / mx for c, v in pts.items()} if mx else {}


def _precompute():
    """Per target race (2025–26): raw per-driver features from prior races only,
    plus the actual finishing order for the grid drivers who were classified."""
    pre = []
    for ti, (ts, tr, race) in enumerate(RACE_SEQ):
        if ts == "2024":
            continue
        circ = race.get("circuitId")
        acc = {d: {"pw": 0.0, "w": 0.0, "fin": 0.0, "tot": 0.0} for d in GRID}
        hist = {d: {} for d in GRID}
        qacc = {d: [0.0, 0.0] for d in GRID}
        for gi in range(ti):
            s, rnd, prace = RACE_SEQ[gi]
            dist = ti - gi
            w = SEASON_W[s] * 0.5 ** ((dist - 1) / HALFLIFE)
            pc = prace.get("circuitId")
            for res in prace["results"]:
                d = res["driverId"]
                if d not in acc:
                    continue
                a = acc[d]; a["pw"] += res["points"] * w; a["w"] += w; a["tot"] += w
                if not _dnf(res["status"]):
                    a["fin"] += w
                    if isinstance(res["pos"], int) and pc:
                        h = hist[d].setdefault(pc, [0.0, 0.0])
                        h[0] += res["pos"] * SEASON_W[s]; h[1] += SEASON_W[s]
            q = QUALI_BY.get((s, rnd))
            if q:
                for qr in q["results"]:
                    if qr["driverId"] in qacc:
                        qacc[qr["driverId"]][0] += qr["pos"] * w
                        qacc[qr["driverId"]][1] += w
        # momentum: last ≤3 in-season races before target
        srace = [pr for s, rnd, pr in RACE_SEQ if s == ts and rnd < tr]
        last3 = srace[-3:]; nseas = max(1, len(srace)); rn = max(1, len(last3))
        spts = {d: 0.0 for d in GRID}; rpts = {d: 0.0 for d in GRID}
        for pr in srace:
            for res in pr["results"]:
                if res["driverId"] in spts:
                    spts[res["driverId"]] += res["points"]
        for pr in last3:
            for res in pr["results"]:
                if res["driverId"] in rpts:
                    rpts[res["driverId"]] += res["points"]
        car = _car_index(ts, tr)
        feats = {}
        ppr_raw = {}
        for d in GRID:
            a = acc[d]
            ppr_raw[d] = a["pw"] / a["w"] if a["w"] else 0.0
        pmax = max(ppr_raw.values()) or 1
        for d in GRID:
            a = acc[d]
            rel = a["fin"] / a["tot"] if a["tot"] else 0.85
            rel = min(0.99, max(0.55, rel))
            gpos = qacc[d][0] / qacc[d][1] if qacc[d][1] else 12.0
            cid = CONS_OF[d]
            cur = (C.car(cid)["downforce_bias"] + C.car(cid)["straightline"]) / 200.0
            car_n = 0.8 * car.get(cid, 0.3) + 0.2 * cur
            ta = {c: h[0] / h[1] for c, h in hist[d].items() if h[1]}
            delta = rpts[d] / rn - spts[d] / nseas
            mom = 1.0 + max(-0.08, min(0.08, delta / 100.0))
            feats[d] = {
                "form": ppr_raw[d] / pmax, "quali": max(0.0, (21 - gpos) / 20.0),
                "rel": rel, "car": car_n,
                "fit": C.circuit_fit(cid, circ),
                "trk": _track_factor(ta.get(circ)),
                "mom": mom, "has_form": a["w"] > 0,
            }
        # actual order for grid finishers
        actual = {}
        for res in race["results"]:
            d = res["driverId"]
            if d in GRID and isinstance(res["pos"], int) and not _dnf(res["status"]):
                actual[d] = res["pos"]
        if len(actual) >= 5:
            pre.append({"feats": feats, "actual": actual, "circ": circ,
                        "season": ts, "round": tr})
    return pre


def _track_factor(avg):
    if avg is None:
        return 1.0
    raw = (10.5 - avg) / 10.5 * 0.12
    return 1.0 + max(-0.12, min(0.12, raw))


def _kendall(a, b):
    """τ between two equal-length sequences (manual, no scipy dependency)."""
    n = len(a); conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (a[i] - a[j]) * (b[i] - b[j])
            if s > 0: conc += 1
            elif s < 0: disc += 1
    tot = conc + disc
    return (conc - disc) / tot if tot else 0.0


def _strength(feats, d, weights, use):
    wF, wQ, wR, wC = weights
    bw = {"form": wF, "quali": wQ, "rel": wR, "car": wC}
    act = {k: bw[k] for k in BASE if k in use}
    tot = sum(act.values()) or 1.0
    f = feats[d]
    rating = sum(act.get(k, 0) / tot * f[k] for k in BASE)
    s = rating
    if "circuit_fit" in use: s *= f["fit"]
    if "track_factor" in use: s *= f["trk"]
    if "momentum" in use: s *= f["mom"]
    return s


def evaluate(pre, weights=DEFAULT_W, use=None):
    if use is None:
        use = set(BACKTESTABLE)
    taus, top1, ll = [], [], []
    for race in pre:
        ds = list(race["actual"].keys())
        if len(ds) < 5:
            continue
        st = np.array([_strength(race["feats"], d, weights, use) for d in ds])
        pos = np.array([race["actual"][d] for d in ds])
        taus.append(_kendall(list(-st), list(pos)))          # higher strength ↔ lower (better) pos
        winner = ds[int(np.argmin(pos))]
        top1.append(1.0 if ds[int(np.argmax(st))] == winner else 0.0)
        p = np.exp(BETA * (st - st.max())); p /= p.sum()
        ll.append(-np.log(max(1e-9, p[ds.index(winner)])))
    return {"tau": float(np.mean(taus)), "top1": float(np.mean(top1)),
            "logloss": float(np.mean(ll)), "n": len(taus)}


def main():
    pre = _precompute()
    base = evaluate(pre)
    print(f"Backtest set: {base['n']} races (2025–26), grid finishers per race.\n")
    print(f"BASELINE (current model)  τ={base['tau']:+.3f}  top1={base['top1']*100:4.1f}%  "
          f"winner-logloss={base['logloss']:.3f}\n")

    print("LEAVE-ONE-OUT ABLATION (drop one factor; Δτ>0 ⇒ factor HELPS):")
    rows = []
    for fa in BACKTESTABLE:
        e = evaluate(pre, use=set(BACKTESTABLE) - {fa})
        rows.append((fa, base["tau"] - e["tau"], base["top1"] - e["top1"],
                     e["logloss"] - base["logloss"]))
    for fa, dt, d1, dll in sorted(rows, key=lambda r: -r[1]):
        verdict = "keep (helps)" if dt > 0.002 else ("DROP? (no/neg value)" if dt <= 0 else "marginal")
        print(f"  {fa:13} Δτ={dt:+.4f}  Δtop1={d1*100:+5.1f}%  Δlogloss={dll:+.4f}   {verdict}")

    print("\nRANDOM SEARCH over base weights (form, quali, rel, car), all multipliers on:")
    rng = np.random.default_rng(7)
    best = (base["tau"], DEFAULT_W)
    for _ in range(4000):
        w = rng.dirichlet([4, 2, 1.5, 3])      # prior centred near current weights
        e = evaluate(pre, weights=tuple(w))
        if e["tau"] > best[0]:
            best = (e["tau"], tuple(w))
    bw = best[1]
    bestfull = evaluate(pre, weights=bw)
    print(f"  current  weights=({DEFAULT_W[0]:.2f},{DEFAULT_W[1]:.2f},{DEFAULT_W[2]:.2f},{DEFAULT_W[3]:.2f})"
          f"  τ={base['tau']:+.3f} top1={base['top1']*100:.1f}%")
    print(f"  tuned    weights=({bw[0]:.2f},{bw[1]:.2f},{bw[2]:.2f},{bw[3]:.2f})"
          f"  τ={bestfull['tau']:+.3f} top1={bestfull['top1']*100:.1f}% logloss={bestfull['logloss']:.3f}")
    print("\n  (form, quali, rel, car)")
    print("\nNOT backtestable here (no historical forecast/news; sim-only):")
    print("  weather, car_dev, news, season_shock — kept as small, capped priors.")


if __name__ == "__main__":
    main()
