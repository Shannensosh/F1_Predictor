"""
f1_replay.py — FastF1-based race replay builder.

Approach modelled on IAmTomShaw/f1-race-replay: pull official F1 live-timing
position data via the `fastf1` package, rotate everything by the circuit's
official map rotation (so the track looks like the F1 broadcast graphics),
and emit playback frames + the track outline + numbered corner markers.

Used to build the bundled live-timing sample; OpenF1 still supplies intervals,
tyres, pits, weather, race control and team radio for the same session.
"""

import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "ff1cache")


def _rotate(x, y, deg):
    a = math.radians(deg)
    return (x * math.cos(a) + y * math.sin(a),
            -x * math.sin(a) + y * math.cos(a))


def build(year, gp, window_utc, frame_hz=1.0):
    """Return {"track", "corners", "frames", "rotation"} or None on failure.

    window_utc: (iso_start, iso_end) naive-UTC strings, e.g.
                ("2024-12-01T16:00:00", "2024-12-01T16:13:00")
    """
    try:
        import fastf1
        import pandas as pd
    except ImportError:
        print("   ! fastf1 not installed — falling back to OpenF1 track")
        return None
    try:
        os.makedirs(CACHE, exist_ok=True)
        fastf1.Cache.enable_cache(CACHE)
        sess = fastf1.get_session(year, gp, "R")
        sess.load(telemetry=True, laps=True, weather=False, messages=False)

        ci = sess.get_circuit_info()
        rot = float(ci.rotation)

        # ── track outline: the fastest lap's GPS trace, officially rotated ──
        fl = sess.laps.pick_fastest()
        pos = fl.get_pos_data()
        track = []
        for _, r in pos.iterrows():
            x, y = _rotate(r["X"], r["Y"], rot)
            track.append([round(x), round(y)])
        track = track[::2]

        # ── numbered corners ────────────────────────────────────────────────
        corners = []
        for _, c in ci.corners.iterrows():
            x, y = _rotate(c["X"], c["Y"], rot)
            corners.append([round(x), round(y), int(c["Number"])])

        # ── playback frames (1 Hz) for every car across the window ──────────
        t0 = pd.Timestamp(window_utc[0])
        t1 = pd.Timestamp(window_utc[1])
        n_frames = int((t1 - t0).total_seconds() * frame_hz)

        conv = {}
        for num in sess.drivers:
            pdata = sess.pos_data.get(num)
            if pdata is None or pdata.empty:
                continue
            w = pdata[(pdata["Date"] >= t0) & (pdata["Date"] <= t1)]
            w = w[(w["X"] != 0) | (w["Y"] != 0)]
            seq = []
            for _, r in w.iterrows():
                x, y = _rotate(r["X"], r["Y"], rot)
                seq.append(((r["Date"] - t0).total_seconds(), x, y))
            if seq:
                conv[str(int(num))] = seq

        frames = []
        cursor = {n: 0 for n in conv}
        step = 1.0 / frame_hz
        for fi in range(n_frames):
            ft = fi * step
            cars = {}
            for n, seq in conv.items():
                i = cursor[n]
                while i + 1 < len(seq) and seq[i + 1][0] <= ft:
                    i += 1
                cursor[n] = i
                if seq[i][0] <= ft + 5:          # tolerate small gaps only
                    cars[n] = [round(seq[i][1]), round(seq[i][2])]
            frames.append(cars)

        print(f"   fastf1: {len(frames)} frames, {len(conv)} cars, "
              f"{len(track)} track pts, {len(corners)} corners, rot {rot:.0f}°")
        return {"track": track, "corners": corners, "frames": frames,
                "rotation": rot}
    except Exception as e:  # noqa: BLE001 — replay is best-effort
        print(f"   ! fastf1 replay failed ({e}) — falling back to OpenF1 track")
        return None
