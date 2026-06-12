"""
f1_prebake.py — bake the latest Grand Prix into data/replay_race.json in the
exact frame schema the f1-race-replay desktop app renders.

The repo's own get_race_telemetry() needs per-lap car_data (speed/gear), which
the 2026 feed doesn't populate — so frames are assembled here from the healthy
channels (pos_data, laps, track_status, weather, race control) using the same
maths the app uses: cars projected onto the fastest-lap reference line, race
order = sort by (lap, distance), tyres/pits from the lap table, official
circuit rotation, DRS zones from the example lap's DRS channel.

Run:  python3 f1_prebake.py            (auto-picks the latest completed round)
      python3 f1_prebake.py 2026 6     (explicit year/round)
"""

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "f1-race-replay")
DATA = os.path.join(HERE, "data")
sys.path.insert(0, REPO)

FPS_OUT = 1.0            # baked frame rate (the browser port interpolates)
WEATHER_EVERY = 30       # attach weather every N frames
TYRE_INT = {"SOFT": 0, "MEDIUM": 1, "HARD": 2, "INTERMEDIATE": 3, "WET": 4}


def latest_round():
    with open(os.path.join(DATA, "results.json")) as f:
        results = json.load(f)
    rounds = [r["round"] for r in results.get("2026", [])]
    return 2026, (max(rounds) if rounds else 1)


def main():
    year, rnd = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else latest_round()
    print(f"» prebaking {year} round {rnd} (f1-race-replay schema)")

    import fastf1
    from scipy.spatial import cKDTree
    fastf1.Cache.enable_cache(os.path.join(DATA, "ff1cache"))

    # corner-marker pass can't merge this dataset's reference lap — only the
    # rotation is needed, so let it fail soft
    from fastf1.mvapi.data import CircuitInfo as _CI
    _orig_amd = _CI.add_marker_distance
    def _safe_amd(self, *a, **k):
        try:
            return _orig_amd(self, *a, **k)
        except Exception:
            return None
    _CI.add_marker_distance = _safe_amd

    sess = fastf1.get_session(year, rnd, "R")
    sess.load(telemetry=True, laps=True, weather=True, messages=True)
    rotation = float(sess.get_circuit_info().rotation)

    nums = list(sess.drivers)
    code_of = {n: sess.get_driver(n)["Abbreviation"] for n in nums}
    pos = sess.pos_data
    laps_df = sess.laps

    # ── example lap: quickest lap whose telemetry merges AND has real X/Y ───
    X = Y = DRS = None
    circuit_len = None
    for _, lap in laps_df.dropna(subset=["LapTime"]).sort_values("LapTime").iterrows():
        try:
            tel = lap.get_telemetry()
            if (len(tel) > 200 and {"X", "Y", "DRS", "Distance"}.issubset(tel.columns)
                    and (tel["X"].max() - tel["X"].min()) > 1000
                    and (tel["Y"].max() - tel["Y"].min()) > 1000):
                X = tel["X"].to_numpy(); Y = tel["Y"].to_numpy()
                DRS = tel["DRS"].to_numpy()
                circuit_len = float(tel["Distance"].max())
                print(f"   example lap: {lap['Driver']}  {lap['LapTime']}")
                break
        except Exception:
            continue
    if X is None:
        # car_data X/Y are zeroed in this dataset — trace the reference lap
        # straight from the position stream (fastest green lap of any driver)
        print("   ! no usable lap telemetry — tracing reference lap from position data")
        for _, lap in laps_df.dropna(subset=["LapTime"]).sort_values("LapTime").iterrows():
            num = next((n for n in nums if code_of[n] == lap["Driver"]), None)
            p = pos.get(num)
            if p is None or not len(p):
                continue
            ts = p["SessionTime"].dt.total_seconds().to_numpy()
            t0 = lap["LapStartTime"].total_seconds()
            t1 = t0 + lap["LapTime"].total_seconds()
            m = (ts >= t0) & (ts <= t1)
            if m.sum() > 100:
                Xc = p["X"].to_numpy()[m]; Yc = p["Y"].to_numpy()[m]
                if (Xc.max() - Xc.min()) > 1000 and (Yc.max() - Yc.min()) > 1000:
                    X, Y = Xc, Yc
                    DRS = np.zeros(len(X))
                    print(f"   reference lap: {lap['Driver']} lap {int(lap['LapNumber'])}  {lap['LapTime']}")
                    break
    if X is None:
        raise RuntimeError("no usable reference lap found")

    # track boundaries — identical to build_track_from_example_lap(width=200)
    dx = np.gradient(X); dy = np.gradient(Y)
    norm = np.sqrt(dx**2 + dy**2); norm[norm == 0] = 1.0
    nx, ny = -dy / norm, dx / norm
    HW = 100.0
    inner = np.column_stack((X - nx * HW, Y - ny * HW))
    outer = np.column_stack((X + nx * HW, Y + ny * HW))
    drs_zones, zstart = [], None
    for i, v in enumerate(DRS):
        if v in (10, 12, 14):
            if zstart is None:
                zstart = i
        elif zstart is not None:
            drs_zones.append([int(zstart), int(i - 1)]); zstart = None
    if zstart is not None:
        drs_zones.append([int(zstart), int(len(DRS) - 1)])

    # dense reference line for distance projection (app: 4000 pts + cumdist)
    t_old = np.linspace(0, 1, len(X)); t_new = np.linspace(0, 1, 4000)
    rx = np.interp(t_new, t_old, X); ry = np.interp(t_new, t_old, Y)
    seg = np.sqrt(np.diff(rx)**2 + np.diff(ry)**2)
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    ref_total = float(cum[-1])
    tree = cKDTree(np.column_stack((rx, ry)))

    # ── per-driver series on a 1 Hz session-time grid ────────────────────────
    # GENUINE GPS extent: this dataset pads the position stream with sparse
    # (0,0) placeholder rows long after the real feed dies — only rows with
    # real coordinates count.
    def _valid_ts(p):
        ts = p["SessionTime"].dt.total_seconds().to_numpy()
        ok = (np.abs(p["X"].to_numpy()) + np.abs(p["Y"].to_numpy())) > 10
        return ts[ok]
    pos_tmax = max((_valid_ts(p).max() for p in pos.values()
                    if len(p) and _valid_ts(p).size), default=0.0)

    # start at lights-out, run to the chequered flag (session_status clock ==
    # SessionTime — verified against lap-1 start). If the GPS stream truncates
    # early (it does for 2026 Monaco: red flag, feed never resumed), frames
    # after pos_tmax are flagged "np" and the renderer switches to timing-only.
    lap1 = float(sess.laps["LapStartTime"].dt.total_seconds().min())
    ss = sess.session_status
    fin = ss[ss["Status"] == "Finished"]
    finish_t = float(fin["Time"].iloc[-1].total_seconds()) if len(fin) else pos_tmax
    t_start = lap1 - 20.0
    t_end = max(finish_t + 30.0, pos_tmax)
    tmin = t_start
    timeline = np.arange(t_start, t_end, 1.0 / FPS_OUT)
    n_frames = len(timeline)
    print(f"   timeline: {n_frames} frames ({(t_end-t_start)/60:.0f} min), "
          f"GPS available for the first {(pos_tmax-t_start)/60:.0f} min")

    laps = sess.laps
    series = {}
    for n in nums:
        p = pos.get(n)
        if p is None or not len(p):
            continue
        code = code_of[n]
        ts_all = p["SessionTime"].dt.total_seconds().to_numpy()
        xa = p["X"].to_numpy(); ya = p["Y"].to_numpy()
        ok = (np.abs(xa) + np.abs(ya)) > 10          # drop (0,0) placeholder rows
        if ok.sum() < 20:
            continue
        ts, xa, ya = ts_all[ok], xa[ok], ya[ok]
        order = np.argsort(ts)
        xi = np.interp(timeline, ts[order], xa[order])
        yi = np.interp(timeline, ts[order], ya[order])

        dl = laps[laps["Driver"] == code]
        lap_starts = dl["LapStartTime"].dt.total_seconds().to_numpy()
        lap_nums = dl["LapNumber"].to_numpy()
        lap_i = np.searchsorted(lap_starts, timeline, side="right")
        lap_arr = np.where(lap_i > 0, lap_nums[np.clip(lap_i - 1, 0, len(lap_nums) - 1)], 1).astype(int) \
            if len(lap_nums) else np.ones(n_frames, int)

        tyre_by_lap, life_by_lap = {}, {}
        for _, lp in dl.iterrows():
            tyre_by_lap[int(lp["LapNumber"])] = TYRE_INT.get(str(lp["Compound"]).upper(), -1)
            life_by_lap[int(lp["LapNumber"])] = int(lp["TyreLife"]) if np.isfinite(lp["TyreLife"]) else 0

        pit_windows = []
        for _, lp in dl.iterrows():
            if not (lp["PitInTime"] is None or (isinstance(lp["PitInTime"], float) and np.isnan(lp["PitInTime"]))):
                try:
                    start = lp["PitInTime"].total_seconds()
                    end = lp["PitOutTime"].total_seconds() if lp["PitOutTime"] == lp["PitOutTime"] else start + 40
                    pit_windows.append((start, end))
                except Exception:
                    pass

        # along-track distance via KD-tree projection (the app's approach)
        _, idxs = tree.query(np.column_stack((xi, yi)))
        proj = cum[idxs]
        dist = (np.maximum(lap_arr, 1) - 1) * ref_total + proj

        # when does THIS car's GPS stop moving (retirement / feed cut)?
        sx, sy, st_ = xa[order], ya[order], ts[order]
        mv = (np.abs(np.diff(sx)) + np.abs(np.diff(sy))) > 5
        gps_end = float(st_[1:][mv].max()) if mv.any() else float(st_.min())

        series[code] = {"x": xi, "y": yi, "lap": lap_arr, "dist": dist,
                        "tyre_by_lap": tyre_by_lap, "life_by_lap": life_by_lap,
                        "pits": pit_windows, "gps_end": gps_end,
                        "max_lap": int(lap_nums.max()) if len(lap_nums) else 1}

    total_laps = int(sess.total_laps) if getattr(sess, "total_laps", None) \
        else max(s["max_lap"] for s in series.values())

    # ── track statuses + race control on the same clock ─────────────────────
    statuses = []
    for st in sess.track_status.to_dict("records"):
        t0s = st["Time"].total_seconds() - tmin
        if statuses:
            statuses[-1][2] = round(t0s, 1)
        statuses.append([str(st["Status"]), round(t0s, 1), None])

    rc = []
    rcm = getattr(sess, "race_control_messages", None)
    if rcm is not None and len(rcm):
        for m in rcm.to_dict("records"):
            tv = m.get("Time")
            secs = tv.total_seconds() if hasattr(tv, "total_seconds") \
                else (tv - sess.t0_date).total_seconds()
            t_rel = secs - tmin
            if t_rel > 0:
                rc.append({"time": round(t_rel, 1),
                           "category": str(m.get("Category") or ""),
                           "message": str(m.get("Message") or ""),
                           "flag": str(m.get("Flag") or "")})
        rc.sort(key=lambda m: m["time"])

    wdf = sess.weather_data
    wt = wdf["Time"].dt.total_seconds().to_numpy() - tmin if wdf is not None and len(wdf) else None

    # ── frames in the app's schema ───────────────────────────────────────────
    frames = []
    for i in range(n_frames):
        t = timeline[i] - tmin
        snap = []
        for code, s in series.items():
            snap.append((code, int(s["lap"][i]), float(s["dist"][i])))
        snap.sort(key=lambda r: (r[1], r[2]), reverse=True)
        d = {}
        for posn, (code, lapn, dist) in enumerate(snap, start=1):
            s = series[code]
            in_pit = any(a <= timeline[i] <= b for a, b in s["pits"])
            d[code] = [round(float(s["x"][i])), round(float(s["y"][i])), lapn, posn,
                       s["tyre_by_lap"].get(lapn, -1), s["life_by_lap"].get(lapn, 0),
                       1 if in_pit else 0, 0, 0, 0, round(dist)]
        fr = {"t": round(t, 1), "lap": snap[0][1] if snap else 1, "d": d}
        if timeline[i] > pos_tmax + 5:
            fr["np"] = 1                      # GPS feed has ended — timing only
        if wt is not None and i % WEATHER_EVERY == 0:
            j = int(np.clip(np.searchsorted(wt, t), 0, len(wt) - 1))
            row = wdf.iloc[j]
            fr["w"] = [float(row["AirTemp"]), float(row["TrackTemp"]), float(row["Humidity"]),
                       float(row["WindSpeed"]), float(row["WindDirection"]),
                       1 if bool(row["Rainfall"]) else 0]
        frames.append(fr)

    # ── driver colours via the repo's own helper ─────────────────────────────
    try:
        from src.f1_data import get_driver_colors
        colors = {c: "#{:02X}{:02X}{:02X}".format(*rgb)
                  for c, rgb in get_driver_colors(sess).items()}
    except Exception as e:
        print("   ! repo colour helper failed, using fastf1.plotting:", e)
        import fastf1.plotting as fp
        colors = {}
        for code in series:
            try:
                colors[code] = fp.get_driver_color(code, session=sess)
            except Exception:
                colors[code] = "#FFFFFF"

    # GPS coverage check — recomputed at every bake so the page can warn when
    # the upstream feed is partial (e.g. cut by a red flag)
    gps_last_lap = total_laps
    for fr_ in frames:
        if fr_.get("np"):
            gps_last_lap = max(1, fr_["lap"] - 1)
            break
    if gps_last_lap < total_laps:
        print(f"   ⚠ GPS covers laps 1–{gps_last_lap} of {total_laps} (feed cut upstream)")

    ev = sess.event
    payload = {
        "meta": {"event": str(ev.get("EventName", "")), "circuit": str(ev.get("Location", "")),
                 "country": str(ev.get("Country", "")), "year": year, "round": rnd,
                 "date": str(ev.get("EventDate", ""))[:10], "total_laps": total_laps,
                 "gps_last_lap": gps_last_lap, "rotation": rotation,
                 "circuit_length_m": circuit_len if circuit_len else round(ref_total / 10.0, 1)},
        "fps": FPS_OUT,
        "codes": sorted(series.keys()),
        "colors": colors,
        "track": {"ref":   [[round(a), round(b)] for a, b in zip(X[::2], Y[::2])],
                  "inner": [[round(a), round(b)] for a, b in inner[::2]],
                  "outer": [[round(a), round(b)] for a, b in outer[::2]],
                  "drs":   [[z[0] // 2, z[1] // 2] for z in drs_zones]},
        "statuses": statuses,
        "rc": rc,
        "gps_end": {c: round(s["gps_end"] - tmin, 1) for c, s in series.items()},
        "frames": frames,
    }
    out = os.path.join(DATA, "replay_race.json")
    with open(out, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"✓ {len(frames)} frames, {len(series)} drivers, {total_laps} laps, "
          f"{len(drs_zones)} DRS zones, rot {rotation:.0f}° → replay_race.json "
          f"({os.path.getsize(out)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
