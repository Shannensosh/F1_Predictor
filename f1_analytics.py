"""
f1_analytics.py — per-race analytics for the Results tab, via FastF1.

For every completed 2026 round it extracts, into data/race_analytics.json:
  • fp           — FP1 / FP2 / FP3 classification (drivers ranked by fastest lap)
  • race[code]   — quick-lap times (s) for the pace/box charts,
                   position-per-lap for the race-positions chart, and
                   tyre stints (compound + lap range) for the strategy chart.

It is INCREMENTAL: rounds already present in the JSON are skipped, so the daily
CI build only loads FastF1 sessions for a newly-completed round. Each session
load is wrapped so one bad session never drops the rest.

Run:  python3 f1_analytics.py            (all completed rounds, skip cached)
      python3 f1_analytics.py --force     (re-extract every completed round)
"""

import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "race_analytics.json")
SEASON = 2026
FP_CODES = ["FP1", "FP2", "FP3"]


def _completed_rounds():
    with open(os.path.join(DATA, "results.json")) as f:
        res = json.load(f)
    return sorted(r["round"] for r in res.get(str(SEASON), []))


def _meta_by_round():
    with open(os.path.join(DATA, "schedule.json")) as f:
        sched = json.load(f)
    return {r["round"]: r for r in sched}


def _laps_df(session):
    session.load(telemetry=False, laps=True, weather=False, messages=False)
    return session.laps


def _fastest_ranking(laps):
    """[ [code, pos], ... ] ordered by each driver's fastest valid lap."""
    best = {}
    for code in laps["Driver"].dropna().unique():
        dl = laps[laps["Driver"] == code]
        t = dl["LapTime"].dropna()
        if len(t):
            best[code] = t.min().total_seconds()
    order = sorted(best, key=lambda c: best[c])
    return [[c, i + 1] for i, c in enumerate(order)]


def _race_detail(laps):
    """Per-driver quick-lap times, position-per-lap and tyre stints."""
    out = {}
    total = int(laps["LapNumber"].dropna().max()) if len(laps) else 0
    for code in laps["Driver"].dropna().unique():
        dl = laps[laps["Driver"] == code].sort_values("LapNumber")
        # ── representative racing laps (drop in/out + >107% of personal best) ──
        valid = dl[dl["LapTime"].notna()
                   & dl["PitInTime"].isna() & dl["PitOutTime"].isna()]
        lapseq = []
        if len(valid):
            cut = valid["LapTime"].dt.total_seconds().min() * 1.07
            for r in valid.itertuples():
                s = r.LapTime.total_seconds()
                if s <= cut:
                    lapseq.append([int(r.LapNumber), round(float(s), 3)])
        lap_times = [t for _, t in lapseq]
        # ── average sector times (s) ──
        sectors = []
        for col in ("Sector1Time", "Sector2Time", "Sector3Time"):
            v = valid[col].dropna() if col in valid.columns else []
            sectors.append(round(float(v.dt.total_seconds().mean()), 3) if len(v) else None)
        # ── top speed (speed trap, km/h) ──
        topspeed = None
        if "SpeedST" in dl.columns:
            sp = dl["SpeedST"].dropna()
            if len(sp):
                topspeed = round(float(sp.max()), 1)
        # ── position per lap ──
        pos = [[int(r.LapNumber), int(r.Position)]
               for r in dl.itertuples() if r.Position == r.Position]  # not NaN
        # ── tyre stints ──
        stints = []
        for sid, grp in dl.groupby("Stint"):
            comp = grp["Compound"].dropna()
            if not len(comp):
                continue
            stints.append([str(comp.iloc[0]),
                           int(grp["LapNumber"].min()), int(grp["LapNumber"].max())])
        stints.sort(key=lambda s: s[1])
        if not (lap_times or pos or stints):
            continue
        out[str(code)] = {"laps": lap_times, "lapseq": lapseq, "sectors": sectors,
                          "topspeed": topspeed, "pos": pos, "stints": stints}
    return out, total


def extract_round(rnd):
    import fastf1
    fastf1.Cache.enable_cache(os.path.join(DATA, "ff1cache"))
    bundle = {"round": rnd, "fp": {}, "race": {}, "total_laps": 0}
    # free practice classifications
    for code in FP_CODES:
        try:
            s = fastf1.get_session(SEASON, rnd, code)
            bundle["fp"][code] = _fastest_ranking(_laps_df(s))
            print(f"   · {code}: {len(bundle['fp'][code])} classified")
        except Exception as e:  # noqa: BLE001
            print(f"   ! {code} failed: {type(e).__name__}: {str(e)[:70]}")
    # race detail
    try:
        s = fastf1.get_session(SEASON, rnd, "R")
        race, total = _race_detail(_laps_df(s))
        bundle["race"], bundle["total_laps"] = race, total
        print(f"   · R: {len(race)} drivers, {total} laps")
    except Exception as e:  # noqa: BLE001
        print(f"   ! R failed: {type(e).__name__}: {str(e)[:70]}")
    return bundle


def main():
    force = "--force" in sys.argv
    existing = {}
    if os.path.exists(OUT) and not force:
        try:
            existing = json.load(open(OUT))
        except Exception:
            existing = {}
    meta = _meta_by_round()
    out = dict(existing)
    for rnd in _completed_rounds():
        if str(rnd) in out and not force:
            continue
        m = meta.get(rnd, {})
        print(f"» analytics round {rnd} — {m.get('name', '')}")
        b = extract_round(rnd)
        b["raceName"] = m.get("name", f"Round {rnd}")
        b["country"] = m.get("country", "")
        out[str(rnd)] = b
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    kb = os.path.getsize(OUT) / 1024
    print(f"✓ race_analytics.json — {len(out)} rounds ({kb:,.0f} KB)")


if __name__ == "__main__":
    main()
