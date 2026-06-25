"""
f1_fetch.py — real-data layer for the F1 2026 dashboard.

Pulls from two free, public APIs and writes normalised JSON into ./data:

  • Jolpica/Ergast  (api.jolpi.ca)  — schedule, results, qualifying, sprint,
    driver & constructor standings, driver info. History 2024–2026.
  • OpenF1          (api.openf1.org) — live-timing telemetry. We build ONE
    bundled "sample race" (a real, completed Grand Prix with full telemetry)
    so the live-timing page always has something to play back offline.

Everything is cached on disk under ./data/cache so re-runs are fast and the
rest of the pipeline can rebuild with no network.

Run directly to (re)fetch everything:
    python3 f1_fetch.py
"""

import json
import os
import time
import urllib.parse
import urllib.request

HERE      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(HERE, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

JOLPICA = "https://api.jolpi.ca/ergast/f1"
OPENF1  = "https://api.openf1.org/v1"

# Seasons we pull. 2026 is the live season; 2024–25 feed stats + the predictor.
SEASONS      = [2024, 2025, 2026]
LIVE_SEASON  = 2026

# Bundled sample race for live-timing playback: a real GP with complete
# telemetry AND an early safety car so the flag colouring is visible.
# 2024 Qatar GP @ Lusail — session_key 9655. Window starts at LIGHTS OUT
# (lap 1 began 16:03:33 UTC) so playback opens with cars racing, not on the grid.
SAMPLE_SESSION_KEY = 9655
# Playback window (UTC) and target frame rate after downsampling.
SAMPLE_WINDOW   = ("2024-12-01T16:03:20", "2024-12-01T16:16:20")
SAMPLE_FRAME_HZ = 1.0   # one playback frame per second of real time

UA = {"User-Agent": "f1-2026-dashboard/1.0 (educational project)"}


# ─────────────────────────────────────────────────────────────────────────────
# HTTP + cache helpers
# ─────────────────────────────────────────────────────────────────────────────
def _ensure_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(key):
    safe = key.replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "-")
    safe = safe.replace(">", "gt").replace("<", "lt").replace("%", "")
    return os.path.join(CACHE_DIR, safe[:180] + ".json")


def _get(url, cache_key=None, retries=4, pause=1.5):
    """GET JSON with on-disk cache + polite retry/back-off."""
    _ensure_dirs()
    cp = _cache_path(cache_key or url)
    if os.path.exists(cp):
        try:
            with open(cp) as f:
                return json.load(f)
        except (ValueError, OSError):
            pass  # corrupt cache → refetch

    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.load(r)
            with open(cp, "w") as f:
                json.dump(data, f)
            return data
        except Exception as e:  # noqa: BLE001 — network is best-effort
            last = e
            code = getattr(e, "code", None)
            if code in (404, 422):       # genuinely no data → don't hammer
                return None
            time.sleep(pause * (attempt + 1))
    print(f"   ! giving up on {url}: {last}")
    return None


def _save(name, obj):
    path = os.path.join(DATA_DIR, name)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    kb = os.path.getsize(path) / 1024
    print(f"   → data/{name}  ({kb:,.0f} KB)")


# ─────────────────────────────────────────────────────────────────────────────
# Jolpica / Ergast
# ─────────────────────────────────────────────────────────────────────────────
def _ergast_paged(path, table_key, list_key):
    """Fetch every page of an Ergast resource and concat the inner list."""
    out, offset, limit, total = [], 0, 100, None
    while True:
        url = f"{JOLPICA}/{path}.json?limit={limit}&offset={offset}"
        d = _get(url, cache_key=f"{path}_{offset}")
        if not d:
            break
        mr = d["MRData"]
        table = mr.get(table_key, {})
        rows = table.get(list_key, [])
        out.extend(rows)
        total = int(mr.get("total", len(out)))
        offset += limit
        if offset >= total or not rows:
            break
        time.sleep(0.3)
    return out


def fetch_schedule(season):
    races = _ergast_paged(f"{season}", "RaceTable", "Races")
    out = []
    for r in races:
        c = r["Circuit"]; loc = c["Location"]
        sessions = {}
        for k, label in [("FirstPractice", "fp1"), ("SecondPractice", "fp2"),
                         ("ThirdPractice", "fp3"), ("Qualifying", "quali"),
                         ("Sprint", "sprint"), ("SprintQualifying", "sprint_quali")]:
            if k in r:
                sessions[label] = {"date": r[k].get("date"), "time": r[k].get("time")}
        out.append({
            "round": int(r["round"]),
            "name": r["raceName"],
            "circuitId": c["circuitId"],
            "circuitName": c["circuitName"],
            "locality": loc.get("locality"),
            "country": loc.get("country"),
            "lat": float(loc["lat"]), "long": float(loc["long"]),
            "date": r.get("date"), "time": r.get("time"),
            "url": r.get("url"),
            "sessions": sessions,
            "isSprint": "Sprint" in r,
        })
    return out


def _merge_by_round(races, list_field):
    """Ergast paginates by result-rows (100/page), so a race can appear on two
    pages with partial inner lists. Merge entries by round, concatenating the
    inner list and de-duplicating by driverId."""
    by_round = {}
    for r in races:
        rd = r["round"]
        if rd not in by_round:
            by_round[rd] = {k: v for k, v in r.items() if k != list_field}
            by_round[rd][list_field] = []
        by_round[rd][list_field].extend(r.get(list_field, []))
    for r in by_round.values():
        seen, merged = set(), []
        for row in r[list_field]:
            key = row.get("driverId")
            if key in seen:
                continue
            seen.add(key); merged.append(row)
        r[list_field] = merged
    return [by_round[k] for k in sorted(by_round)]


def _norm_result(res):
    drv = res["Driver"]; con = res["Constructor"]
    fl = res.get("FastestLap", {})
    return {
        "pos": int(res["positionText"]) if res["positionText"].isdigit() else res["positionText"],
        "posText": res["positionText"],
        "driverId": drv["driverId"],
        "code": drv.get("code", drv["familyName"][:3].upper()),
        "num": drv.get("permanentNumber"),
        "given": drv["givenName"], "family": drv["familyName"],
        "nationality": drv.get("nationality"),
        "constructorId": con["constructorId"], "constructor": con["name"],
        "grid": int(res["grid"]) if res.get("grid", "").lstrip("-").isdigit() else None,
        "laps": int(res["laps"]) if res.get("laps", "").isdigit() else None,
        "status": res.get("status"),
        "points": float(res.get("points", 0)),
        "time": res.get("Time", {}).get("time"),
        "fastestLap": fl.get("Time", {}).get("time") if fl else None,
        "fastestRank": fl.get("rank") if fl else None,
    }


def fetch_results(season):
    races = _ergast_paged(f"{season}/results", "RaceTable", "Races")
    out = []
    for r in races:
        out.append({
            "round": int(r["round"]), "raceName": r["raceName"],
            "date": r.get("date"),
            "circuitId": r["Circuit"]["circuitId"],
            "country": r["Circuit"]["Location"].get("country"),
            "results": [_norm_result(x) for x in r.get("Results", [])],
        })
    return _merge_by_round(out, "results")


def fetch_qualifying(season):
    races = _ergast_paged(f"{season}/qualifying", "RaceTable", "Races")
    out = []
    for r in races:
        rows = []
        for q in r.get("QualifyingResults", []):
            drv = q["Driver"]
            rows.append({
                "pos": int(q["position"]),
                "driverId": drv["driverId"],
                "code": drv.get("code", drv["familyName"][:3].upper()),
                "num": drv.get("permanentNumber"),
                "given": drv["givenName"], "family": drv["familyName"],
                "constructorId": q["Constructor"]["constructorId"],
                "constructor": q["Constructor"]["name"],
                "q1": q.get("Q1"), "q2": q.get("Q2"), "q3": q.get("Q3"),
            })
        out.append({"round": int(r["round"]), "raceName": r["raceName"],
                    "date": r.get("date"), "results": rows})
    return _merge_by_round(out, "results")


def fetch_sprint(season):
    races = _ergast_paged(f"{season}/sprint", "RaceTable", "Races")
    out = []
    for r in races:
        out.append({
            "round": int(r["round"]), "raceName": r["raceName"],
            "date": r.get("date"),
            "results": [_norm_result(x) for x in r.get("SprintResults", [])],
        })
    return _merge_by_round(out, "results")


def fetch_driver_standings(season, rnd=None):
    url = (f"{JOLPICA}/{season}/{rnd}/driverStandings.json" if rnd
           else f"{JOLPICA}/{season}/driverStandings.json")
    ck = f"{season}_r{rnd}_dstand" if rnd else f"{season}_dstand"
    d = _get(url, cache_key=ck)
    if not d:
        return []
    lists = d["MRData"]["StandingsTable"]["StandingsLists"]
    if not lists:
        return []
    out = []
    for s in lists[0]["DriverStandings"]:
        drv = s["Driver"]; con = s["Constructors"][0] if s.get("Constructors") else {}
        out.append({
            "pos": int(s["position"]), "points": float(s["points"]),
            "wins": int(s["wins"]),
            "driverId": drv["driverId"],
            "code": drv.get("code", drv["familyName"][:3].upper()),
            "num": drv.get("permanentNumber"),
            "given": drv["givenName"], "family": drv["familyName"],
            "nationality": drv.get("nationality"),
            "constructorId": con.get("constructorId"), "constructor": con.get("name"),
        })
    return out


def fetch_constructor_standings(season, rnd=None):
    url = (f"{JOLPICA}/{season}/{rnd}/constructorStandings.json" if rnd
           else f"{JOLPICA}/{season}/constructorStandings.json")
    ck = f"{season}_r{rnd}_cstand" if rnd else f"{season}_cstand"
    d = _get(url, cache_key=ck)
    if not d:
        return []
    lists = d["MRData"]["StandingsTable"]["StandingsLists"]
    if not lists:
        return []
    out = []
    for s in lists[0]["ConstructorStandings"]:
        con = s["Constructor"]
        out.append({
            "pos": int(s["position"]), "points": float(s["points"]),
            "wins": int(s["wins"]),
            "constructorId": con["constructorId"], "name": con["name"],
            "nationality": con.get("nationality"),
        })
    return out


def fetch_driver_careers(drivers, hist_max=2025):
    """Per-driver HISTORICAL career totals (seasons ≤ hist_max) from Jolpica:
    debut/last season, GPs, points, wins, podiums, poles, top-10s. Static history →
    cached hard (NOT busted by refresh_live); build.py adds the live 2026 numbers on
    top so totals stay current without re-paginating every veteran's career daily."""
    out = {}
    for drv in drivers:
        did = drv["driverId"]
        # ── all race results (≤ hist_max) → GPs, points, wins, podiums, top-10s, seasons.
        #    (Jolpica has no per-driver driverStandings endpoint, so totals come straight
        #     from the result list; points are race points, sprints excluded.) ──
        gps = pod = top10 = wins = 0
        pts = 0.0
        seasons = set()
        offset, total = 0, None
        while offset < 4000:
            r = _get(f"{JOLPICA}/drivers/{did}/results.json?limit=100&offset={offset}",
                     cache_key=f"car_{did}_res_{offset}")
            races = (((r or {}).get("MRData") or {}).get("RaceTable") or {}).get("Races") or []
            if not races:
                break
            total = int(r["MRData"]["total"])
            for race in races:
                if int(race["season"]) > hist_max or not race.get("Results"):
                    continue
                res = race["Results"][0]
                seasons.add(int(race["season"]))
                gps += 1
                pts += float(res.get("points", 0) or 0)
                try:
                    p = int(res["position"])
                except (KeyError, ValueError, TypeError):
                    p = None
                if p == 1:
                    wins += 1
                if p and p <= 3:
                    pod += 1
                if p and p <= 10:
                    top10 += 1
            offset += 100
            if offset >= total:
                break
        seasons = sorted(seasons)
        # ── poles: qualifying P1 (≤ hist_max) ──
        poles, offset, total = 0, 0, None
        while offset < 4000:
            q = _get(f"{JOLPICA}/drivers/{did}/qualifying/1.json?limit=100&offset={offset}",
                     cache_key=f"car_{did}_pole_{offset}")
            races = (((q or {}).get("MRData") or {}).get("RaceTable") or {}).get("Races") or []
            total = int((((q or {}).get("MRData") or {}).get("total")) or 0)
            for race in races:
                if int(race["season"]) <= hist_max:
                    poles += 1
            offset += 100
            if not races or offset >= total:
                break
        out[did] = {"debut": min(seasons) if seasons else None,
                    "last": max(seasons) if seasons else None,
                    "gps": gps, "points": round(pts), "wins": wins,
                    "podiums": pod, "poles": poles, "top10s": top10}
        time.sleep(0.15)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# OpenF1 — bundled sample race for live-timing playback
# ─────────────────────────────────────────────────────────────────────────────
def _openf1(ep, **params):
    qs = urllib.parse.urlencode(params)
    url = f"{OPENF1}/{ep}?{qs}"
    return _get(url, cache_key=f"of1_{ep}_{qs}") or []


def _team_colours(drivers):
    return {d["driver_number"]: ("#" + d["team_colour"]) if d.get("team_colour") else "#888888"
            for d in drivers}


def clean_lap_outline(sk, driver_number, dur_lo=55, dur_hi=140, downsample=2):
    """One clean racing lap's GPS path → an ordered, closed [[x,y]] outline.
    Uses the `laps` endpoint to pick a median-duration green lap (no pit in/out),
    then pulls that lap's location only — giving a correct single-lap circuit shape
    instead of a messy multi-lap time window."""
    from datetime import datetime, timedelta
    laps = _openf1("laps", session_key=sk, driver_number=driver_number)
    cand = [l for l in laps if l.get("lap_duration") and l.get("date_start")
            and not l.get("is_pit_out_lap") and dur_lo < l["lap_duration"] < dur_hi]
    if not cand:
        return []
    cand.sort(key=lambda l: l["lap_duration"])
    lap = cand[len(cand) // 2]                        # median-pace clean lap
    t0 = datetime.fromisoformat(lap["date_start"])
    t1 = t0 + timedelta(seconds=lap["lap_duration"] + 1.5)
    pts = _openf1("location", session_key=sk, driver_number=driver_number,
                  **{"date>": t0.isoformat(), "date<": t1.isoformat()})
    seq = [(p["x"], p["y"]) for p in pts if p.get("x") is not None]
    seq = seq[::downsample]
    return [[round(x), round(y)] for (x, y) in seq]


def build_sample_race():
    sk = SAMPLE_SESSION_KEY
    sess = _openf1("sessions", session_key=sk)
    meeting = _openf1("meetings", session_key=sk)
    sess = sess[0] if sess else {}
    meeting = meeting[0] if meeting else {}

    drivers = _openf1("drivers", session_key=sk)
    dmeta = [{
        "num": d["driver_number"], "acr": d.get("name_acronym"),
        "name": d.get("full_name"), "team": d.get("team_name"),
        "colour": ("#" + d["team_colour"]) if d.get("team_colour") else "#888888",
    } for d in drivers]
    nums = [d["driver_number"] for d in drivers]

    # ── location → playback frames + track outline ──────────────────────────
    w0, w1 = SAMPLE_WINDOW
    per_driver = {}
    for n in nums:
        pts = _openf1("location", session_key=sk, driver_number=n,
                      **{"date>": w0, "date<": w1})
        # keep only moving samples; parse epoch seconds
        seq = []
        for p in pts:
            if p.get("x") is None:
                continue
            seq.append((p["date"], p["x"], p["y"]))
        per_driver[n] = seq

    # common 1 Hz time grid across the window
    def _epoch(iso):
        # 2024-05-19T13:00:00.064000+00:00 → seconds since window start
        from datetime import datetime
        return datetime.fromisoformat(iso).timestamp()

    t0 = _epoch(w0 + "+00:00") if "+" not in w0 else _epoch(w0)
    t1 = _epoch(w1 + "+00:00") if "+" not in w1 else _epoch(w1)
    step = 1.0 / SAMPLE_FRAME_HZ
    n_frames = int((t1 - t0) / step)

    # pre-convert each driver's samples to (sec_offset, x, y)
    conv = {}
    for n, seq in per_driver.items():
        conv[n] = [(_epoch(d) - t0, x, y) for (d, x, y) in seq]

    frames = []
    cursor = {n: 0 for n in nums}
    for fi in range(n_frames):
        ft = fi * step
        cars = {}
        for n in nums:
            s = conv[n]
            if not s:
                continue
            i = cursor[n]
            while i + 1 < len(s) and s[i + 1][0] <= ft:
                i += 1
            cursor[n] = i
            cars[str(n)] = [round(s[i][1]), round(s[i][2])]
        frames.append(cars)

    # track outline from ONE clean lap (correct circuit shape); fall back to the
    # windowed path only if no lap data is available.
    track = []
    for n in nums[:6]:
        track = clean_lap_outline(sk, n)
        if len(track) > 60:
            break
    if len(track) <= 60:
        best = max(conv.values(), key=len) if conv else []
        track = [[round(x), round(y)] for (_, x, y) in best[::3]]

    # ── intervals (downsampled per driver) for the live leaderboard ─────────
    iv = _openf1("intervals", session_key=sk)
    # bucket to one row per driver per ~30s for a compact gap timeline
    iv_series = {}
    for r in iv:
        n = r["driver_number"]
        iv_series.setdefault(str(n), []).append({
            "t": r["date"], "gap": r.get("gap_to_leader"),
            "int": r.get("interval"),
        })
    for n in iv_series:
        iv_series[n] = iv_series[n][::20]  # thin it out

    # ── stints (tyres), pit, weather, race_control ──────────────────────────
    stints = [{
        "num": s["driver_number"], "compound": s.get("compound"),
        "start": s.get("lap_start"), "end": s.get("lap_end"),
        "age": s.get("tyre_age_at_start"), "stint": s.get("stint_number"),
    } for s in _openf1("stints", session_key=sk)]

    pits = [{
        "num": p["driver_number"], "lap": p.get("lap_number"),
        "duration": p.get("pit_duration"), "date": p.get("date"),
    } for p in _openf1("pit", session_key=sk)]

    weather = [{
        "date": w["date"], "air": w.get("air_temperature"),
        "track": w.get("track_temperature"), "humidity": w.get("humidity"),
        "wind_speed": w.get("wind_speed"), "wind_dir": w.get("wind_direction"),
        "rain": w.get("rainfall"), "pressure": w.get("pressure"),
    } for w in _openf1("weather", session_key=sk)]

    rc = [{
        "date": r["date"], "lap": r.get("lap_number"),
        "category": r.get("category"), "flag": r.get("flag"),
        "scope": r.get("scope"), "message": r.get("message"),
    } for r in _openf1("race_control", session_key=sk)]

    # ── team radio (real broadcast clips, mp3 URLs) ──────────────────────────
    radio = [{
        "num": t["driver_number"], "date": t.get("date"),
        "url": t.get("recording_url"),
    } for t in _openf1("team_radio", session_key=sk) if t.get("recording_url")]

    # ── per-driver lap starts (for the LAP x/y counter) ──────────────────────
    laps = [{
        "num": l["driver_number"], "n": l.get("lap_number"),
        "date": l.get("date_start"),
    } for l in _openf1("laps", session_key=sk) if l.get("lap_number")]

    # ── FastF1 overlay: official rotated track + corners + frames ───────────
    corners, rotation = [], None
    try:
        import f1_replay
        ff = f1_replay.build(2024, "Qatar", SAMPLE_WINDOW, SAMPLE_FRAME_HZ)
        if ff and ff["frames"]:
            track, frames = ff["track"], ff["frames"]
            corners, rotation = ff["corners"], ff["rotation"]
    except Exception as e:  # noqa: BLE001
        print("   ! fastf1 overlay skipped:", e)

    return {
        "session": {
            "key": sk, "name": sess.get("session_name"),
            "country": sess.get("country_name"), "location": sess.get("location"),
            "circuit": sess.get("circuit_short_name"),
            "year": sess.get("year"), "date_start": sess.get("date_start"),
            "meeting": meeting.get("meeting_official_name"),
        },
        "drivers": dmeta,
        "track": track,
        "corners": corners,
        "rotation": rotation,
        "frames": frames,
        "frame_hz": SAMPLE_FRAME_HZ,
        "window": list(SAMPLE_WINDOW),
        "intervals": iv_series,
        "stints": stints,
        "pit": pits,
        "weather": weather,
        "race_control": rc,
        "radio": radio,
        "laps": laps,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Driver index (2026 grid) with team colours from OpenF1 where available
# ─────────────────────────────────────────────────────────────────────────────
def build_driver_index(dstand_2026):
    """Merge 2026 standings with OpenF1 team colours + official headshots
    (by driver number)."""
    colour_by_num, photo_by_num = {}, {}
    sessions = _openf1("sessions", year=LIVE_SEASON, session_name="Race")
    if sessions:
        sk = sessions[-1]["session_key"]
        for d in _openf1("drivers", session_key=sk):
            num = str(d["driver_number"])
            if d.get("team_colour"):
                colour_by_num[num] = "#" + d["team_colour"]
            hs = d.get("headshot_url")
            if hs:
                # request a high-res crop (997×997) instead of the 1col thumbnail
                photo_by_num[num] = hs.replace("/1col/", "/9col/")
    out = []
    for s in dstand_2026:
        num = str(s.get("num"))
        out.append({**s, "colour": colour_by_num.get(num),
                    "photo": photo_by_num.get(num)})
    return out, colour_by_num, photo_by_num


# ─────────────────────────────────────────────────────────────────────────────
# Latest F1 news (RSS), weather forecast (Open-Meteo), per-circuit outlines
# ─────────────────────────────────────────────────────────────────────────────
def fetch_news(limit=20):
    import re
    import html as _html
    try:
        req = urllib.request.Request("https://www.motorsport.com/rss/f1/news/",
                                     headers={"User-Agent": "Mozilla/5.0 (f1-dashboard)"})
        xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        print("   ! news fetch failed:", e)
        return []
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)[:limit]
    out = []
    for it in items:
        def g(tag, blk=it):
            m = re.search(r"<%s>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</%s>" % (tag, tag), blk, re.S)
            return _html.unescape(re.sub("<.*?>", "", m.group(1)).strip()) if m else ""
        em = re.search(r'<enclosure[^>]*url="([^"]+\.(?:jpg|jpeg|png))"', it, re.I)
        if not em:
            em = re.search(r'(https?://[^\s"\'<>]+\.(?:jpg|jpeg|png))', it, re.I)
        out.append({"title": g("title"), "link": g("link"), "date": g("pubDate"),
                    "image": em.group(1) if em else None})
    return [x for x in out if x["title"]]


def fetch_forecast(lat, lon, date_iso):
    """Open-Meteo daily forecast (free, no key) for a circuit on race day."""
    u = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
         "&daily=precipitation_probability_max,temperature_2m_max,temperature_2m_min,"
         "weathercode,wind_speed_10m_max&forecast_days=16&timezone=UTC")
    d = _get(u, cache_key=f"forecast_{lat}_{lon}_{date_iso}")
    if not d:
        return None
    days = d.get("daily", {})
    times = days.get("time", [])
    if date_iso in times:
        i = times.index(date_iso)
        return {"date": date_iso, "in_range": True,
                "precip_prob": days["precipitation_probability_max"][i],
                "tmax": days["temperature_2m_max"][i], "tmin": days["temperature_2m_min"][i],
                "wcode": days["weathercode"][i], "wind": days["wind_speed_10m_max"][i]}
    return {"date": date_iso, "in_range": False}


# Ergast circuitId → bacinger/f1-circuits GeoJSON feature id (REAL georeferenced
# track geometry — lat/lng polylines that overlay correctly on map tiles)
CIRCUIT_GEOJSON_ID = {
    "albert_park": "au-1953", "shanghai": "cn-2004", "suzuka": "jp-1962",
    "miami": "us-2022", "villeneuve": "ca-1978", "monaco": "mc-1929",
    "catalunya": "es-1991", "red_bull_ring": "at-1969", "silverstone": "gb-1948",
    "spa": "be-1925", "hungaroring": "hu-1986", "zandvoort": "nl-1948",
    "monza": "it-1922", "madring": "es-2026", "baku": "az-2016",
    "marina_bay": "sg-2008", "americas": "us-2012", "rodriguez": "mx-1962",
    "interlagos": "br-1940", "vegas": "us-2023", "losail": "qa-2004",
    "yas_marina": "ae-2009",
}
GEOJSON_URL = "https://raw.githubusercontent.com/bacinger/f1-circuits/master/f1-circuits.geojson"


def fetch_circuit_geo(schedule):
    """Real lat/lng track polylines from the open f1-circuits dataset,
    keyed by Ergast circuitId. Coordinates converted to [lat, lng]."""
    d = _get(GEOJSON_URL, cache_key="f1_circuits_geojson")
    if not d:
        return {}
    by_id = {f["properties"].get("id"): f for f in d.get("features", [])}
    out = {}
    for r in schedule:
        cid = r["circuitId"]
        f = by_id.get(CIRCUIT_GEOJSON_ID.get(cid))
        if not f:
            continue
        coords = f["geometry"]["coordinates"]
        if f["geometry"]["type"] == "MultiLineString":
            coords = max(coords, key=len)
        out[cid] = [[round(lat, 6), round(lng, 6)] for lng, lat in coords]
    return out


# Ergast circuitId → OpenF1 `location` keyword (for finding a real lap to trace)
CIRCUIT_OF1_LOC = {
    "albert_park": "Melbourne", "shanghai": "Shanghai", "suzuka": "Suzuka",
    "miami": "Miami", "villeneuve": "Montréal", "monaco": "Monaco",
    "catalunya": "Barcelona", "red_bull_ring": "Spielberg", "silverstone": "Silverstone",
    "spa": "Spa", "hungaroring": "Budapest", "zandvoort": "Zandvoort", "monza": "Monza",
    "baku": "Baku", "marina_bay": "Marina Bay", "americas": "Austin",
    "rodriguez": "Mexico City", "interlagos": "Paulo", "vegas": "Las Vegas",
    "losail": "Lusail", "yas_marina": "Yas Island",
    # madring (Madrid) is new for 2026 — no historical telemetry.
}


# Per-circuit Commons search queries (representative aerial / track photos)
CIRCUIT_PHOTO_QUERY = {
    "albert_park": "Albert Park Circuit Melbourne", "shanghai": "Shanghai International Circuit aerial",
    "suzuka": "Suzuka Circuit aerial", "miami": "Miami International Autodrome",
    "villeneuve": "Circuit Gilles Villeneuve Montreal", "monaco": "Circuit de Monaco aerial",
    "catalunya": "Circuit de Barcelona-Catalunya aerial", "red_bull_ring": "Red Bull Ring Spielberg aerial",
    "silverstone": "Silverstone Circuit aerial", "spa": "Spa-Francorchamps circuit aerial",
    "hungaroring": "Hungaroring aerial", "zandvoort": "Circuit Zandvoort aerial",
    "monza": "Monza circuit aerial", "madring": "Madrid Spain skyline",
    "baku": "Baku City Circuit", "marina_bay": "Marina Bay Street Circuit Singapore night",
    "americas": "Circuit of the Americas aerial", "rodriguez": "Autodromo Hermanos Rodriguez",
    "interlagos": "Interlagos circuit aerial", "vegas": "Las Vegas Strip night",
    "losail": "Lusail International Circuit", "yas_marina": "Yas Marina Circuit aerial",
}


# Per-constructor Commons search → a representative on-track car photo (2024 chassis)
# 2025-spec (current) liveries from Wikimedia Commons; Cadillac uses its 2026 car.
CONSTRUCTOR_CAR_QUERY = {
    "ferrari": "Ferrari SF-25 2025", "mercedes": "Mercedes W16 2025 Formula One",
    "red_bull": "Red Bull RB21 2025", "mclaren": "McLaren MCL39 2025",
    "aston_martin": "FIA F1 Imola 2025 Alonso Aston Martin", "alpine": "FIA F1 Imola 2025 Gasly Alpine",
    "williams": "FIA F1 Imola 2025 Albon Williams", "rb": "FIA F1 Imola 2025 No. 6 Hadjar",
    "haas": "FIA F1 Imola 2025 Haas", "audi": "FIA F1 Imola 2025 Sauber",
    "cadillac": "Cadillac Formula 1 2026 car",
}
_CAR_BAD = ("logo", "helmet", "map", "garage", "pit", "1932", "typ ", "classic",
            "gala", "road", "amg gt", "concept", "museum", "retro", "show car")


def fetch_constructor_cars(constructors):
    """One CC-licensed on-track car photo per 2026 constructor (Commons), carried forward."""
    prev = {}
    sf = os.path.join(DATA_DIR, "standings.json")
    if os.path.exists(sf):
        try:
            prev = {k: v for k, v in (json.load(open(sf)).get("cars") or {}).items() if v}
        except Exception:
            pass
    out = dict(prev)
    for c in constructors:
        cid = c["constructorId"]
        if out.get(cid):
            continue
        d = _commons_search(CONSTRUCTOR_CAR_QUERY.get(cid, f'{c["name"]} 2024 Formula One car'))
        pages = sorted(d.get("query", {}).get("pages", {}).values(),
                       key=lambda p: -(p.get("imageinfo", [{}])[0].get("width", 0)))
        for p in pages:
            ii = (p.get("imageinfo") or [{}])[0]
            w, h, t = ii.get("width", 0), ii.get("height", 0), p.get("title", "")
            if w >= 1200 and w > h and t.lower().endswith((".jpg", ".jpeg")) \
                    and not any(k in t.lower() for k in _CAR_BAD):
                out[cid] = ii.get("thumburl"); break
        time.sleep(0.15)
    return out


# Per-driver Commons search → a free landscape photo of the driver
DRIVER_PHOTO_QUERY = {
    "antonelli": "Andrea Kimi Antonelli", "hamilton": "Lewis Hamilton 2023 Mercedes driver",
    "russell": "George Russell 2023 driver", "leclerc": "Charles Leclerc 2023 driver",
    "norris": "Lando Norris 2023 driver", "piastri": "Oscar Piastri 2023 driver",
    "max_verstappen": "Max Verstappen 2023 driver", "verstappen": "Max Verstappen 2023 driver",
    "gasly": "Pierre Gasly 2023 driver", "alonso": "Fernando Alonso 2023 driver",
    "sainz": "Carlos Sainz 2023 driver", "hulkenberg": "Nico Hülkenberg 2023 driver",
    "stroll": "Lance Stroll 2023 driver", "tsunoda": "Yuki Tsunoda 2023 driver",
    "albon": "Alexander Albon 2023 driver", "ocon": "Esteban Ocon 2023 driver",
    "bearman": "Oliver Bearman driver", "hadjar": "Isack Hadjar", "lawson": "Liam Lawson driver",
    "colapinto": "Franco Colapinto driver", "bortoleto": "Gabriel Bortoleto", "perez": "Sergio Pérez 2023 driver",
}
_DRV_BAD = ("helmet", "logo", "map", "steering", "trophy", "grid ahead", "podium",
            "nr.", "nr ", " no.", "car", "garage", "pit lane")


def fetch_driver_photos(drivers):
    """One CC-licensed landscape photo of each driver (Commons), carried forward.
    Two-pass: prefer a solo person shot (surname in title, no car keywords),
    then relax to any landscape with the surname."""
    prev = {}
    sf = os.path.join(DATA_DIR, "standings.json")
    if os.path.exists(sf):
        try:
            prev = {k: v for k, v in (json.load(open(sf)).get("driver_photos") or {}).items() if v}
        except Exception:
            pass
    out = dict(prev)
    for d in drivers:
        did = d["driverId"]
        if out.get(did):
            continue
        fam = d["family"].split()[-1].lower()
        res = _commons_search(DRIVER_PHOTO_QUERY.get(did, f'{d["given"]} {d["family"]} driver'))
        pages = sorted(res.get("query", {}).get("pages", {}).values(),
                       key=lambda p: -(p.get("imageinfo", [{}])[0].get("width", 0)))
        def pick(strict):
            for p in pages:
                ii = (p.get("imageinfo") or [{}])[0]
                w, h, t = ii.get("width", 0), ii.get("height", 0), p.get("title", "").lower()
                if w < 1000 or w < h or not t.endswith((".jpg", ".jpeg")):
                    continue
                if fam not in t:
                    continue
                if strict and any(k in t for k in _DRV_BAD):
                    continue
                if not strict and any(k in t for k in ("helmet", "logo", "map")):
                    continue
                return ii.get("thumburl")
            return None
        out[did] = pick(True) or pick(False)
        time.sleep(0.15)
    return {k: v for k, v in out.items() if v}


def _commons_search(query, limit=18):
    u = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": query, "gsrlimit": limit, "prop": "imageinfo",
        "iiprop": "url|size|extmetadata", "iiurlwidth": 1920})
    return _get(u, cache_key=f"commons_{query}") or {}


def fetch_circuit_photos(schedule):
    """One representative CC-licensed landscape photo per 2026 circuit (Commons).
    Carries forward previously-found photos so a rate-limited CI run never loses
    images it already had."""
    import re as _re
    bad = ("map", "logo", "diagram", "podium", "helmet", "trophy", "plan", "layout",
           "signature", "seating")
    prev = {}
    pf = os.path.join(DATA_DIR, "circuits_geo.json")
    if os.path.exists(pf):
        try:
            with open(pf) as f:
                old = json.load(f)
            prev = {c: {"photo": v["photo"], "credit": v.get("photo_credit", "")}
                    for c, v in old.items() if v.get("photo")}
        except Exception:
            pass
    out = dict(prev)
    for r in schedule:
        cid = r["circuitId"]
        if out.get(cid):            # already have a good photo from a prior run
            continue
        q = CIRCUIT_PHOTO_QUERY.get(cid, f'{r["circuitName"]}')
        d = _commons_search(q)
        cands = []
        for p in d.get("query", {}).get("pages", {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            w, h, t = ii.get("width", 0), ii.get("height", 0), p.get("title", "")
            if w >= 1400 and w > h * 1.25 and t.lower().endswith((".jpg", ".jpeg")) \
                    and not any(k in t.lower() for k in bad):
                meta = ii.get("extmetadata", {})
                art = _re.sub("<.*?>", "", meta.get("Artist", {}).get("value", "")).strip()[:40]
                lic = meta.get("LicenseShortName", {}).get("value", "")
                # prefer clean aerials
                score = w + (4000 if "skysat" in t.lower() or "aerial" in t.lower() else 0)
                cands.append((score, ii.get("thumburl"), f"{art} · {lic}".strip(" ·")))
        cands.sort(reverse=True)
        if cands:
            out[cid] = {"photo": cands[0][1], "credit": cands[0][2]}
        time.sleep(0.15)
    return out


def build_circuit_outlines(schedule):
    """For each 2026 circuit, trace a real single-lap outline from the most recent
    matching OpenF1 race session. New circuits with no history get an empty outline."""
    races = []
    for yr in (2025, 2024, 2023):
        races.extend(_openf1("sessions", year=yr, session_name="Race"))
    outlines = {}
    for r in schedule:
        cid = r["circuitId"]
        kw = CIRCUIT_OF1_LOC.get(cid)
        # match ONLY by circuit location keyword — never by country, or a new
        # circuit (e.g. Madrid) would borrow another race's shape from the same country.
        match = [s for s in races
                 if kw and kw.lower() in (s.get("location") or "").lower()]
        if not match:
            outlines[cid] = {"outline": [], "source": None}
            continue
        match.sort(key=lambda s: s.get("date_start") or "", reverse=True)
        sess = match[0]; sk = sess["session_key"]
        nums = [d["driver_number"] for d in _openf1("drivers", session_key=sk)][:6] \
            or [1, 4, 16, 44, 81, 63]
        ol = []
        for n in nums:
            ol = clean_lap_outline(sk, n)
            if len(ol) > 60:
                break
        outlines[cid] = {"outline": ol if len(ol) > 60 else [],
                         "source": (f"{sess.get('year')} {sess.get('location')}" if len(ol) > 60 else None)}
        time.sleep(0.2)
    return outlines


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def fetch_all():
    _ensure_dirs()
    print("» Schedule (2026)")
    schedule = fetch_schedule(LIVE_SEASON)
    _save("schedule.json", schedule)

    print("» Results / qualifying / sprint (2024–2026)")
    results, quali, sprint = {}, {}, {}
    for yr in SEASONS:
        print(f"   · {yr}")
        results[str(yr)] = fetch_results(yr)
        quali[str(yr)]   = fetch_qualifying(yr)
        sprint[str(yr)]  = fetch_sprint(yr)
    _save("results.json", results)
    _save("qualifying.json", quali)
    _save("sprint.json", sprint)

    print("» Standings (2026)")
    dstand = fetch_driver_standings(LIVE_SEASON)
    cstand = fetch_constructor_standings(LIVE_SEASON)
    # previous-round standings → race-on-race position movement
    completed = max((r.get("round", 0) for r in results.get(str(LIVE_SEASON), [])), default=0)
    prev_drivers, prev_constructors = {}, {}
    if completed > 1:
        print(f"   · previous-round standings (after round {completed-1})")
        prev_drivers = {x["driverId"]: x["pos"]
                        for x in fetch_driver_standings(LIVE_SEASON, completed - 1)}
        prev_constructors = {x["constructorId"]: x["pos"]
                             for x in fetch_constructor_standings(LIVE_SEASON, completed - 1)}
    drivers_idx, colour_by_num, photo_by_num = build_driver_index(dstand)
    print("   · constructor car photos")
    cars = fetch_constructor_cars(cstand)
    print("   · driver photos (Commons)")
    driver_photos = fetch_driver_photos(dstand)
    _save("standings.json", {"drivers": dstand, "constructors": cstand,
                              "colours": colour_by_num, "photos": photo_by_num,
                              "cars": cars, "driver_photos": driver_photos,
                              "prev_drivers": prev_drivers,
                              "prev_constructors": prev_constructors})
    _save("drivers.json", drivers_idx)
    print("   · driver career history (Jolpica, ≤2025)")
    _save("driver_careers.json", fetch_driver_careers(dstand))

    print("» Sample race telemetry (OpenF1)")
    sample = build_sample_race()
    _save("sample_race.json", sample)
    print(f"   sample: {len(sample['frames'])} frames, "
          f"{len(sample['drivers'])} cars, {len(sample['track'])} track pts, "
          f"{len(sample['race_control'])} RC msgs")

    print("» Circuit outlines (OpenF1 history)")
    outlines = build_circuit_outlines(schedule)
    got = sum(1 for v in outlines.values() if v["outline"])
    print(f"   traced {got}/{len(outlines)} circuits")
    print("» Georeferenced circuit geometry (f1-circuits)")
    geo_real = fetch_circuit_geo(schedule)
    for cid, coords in geo_real.items():
        outlines.setdefault(cid, {"outline": [], "source": None})
        outlines[cid]["geo"] = coords
        outlines[cid]["geo_source"] = "f1-circuits (bacinger) — georeferenced"
    print("» Circuit hero photos (Wikimedia Commons)")
    photos = fetch_circuit_photos(schedule)
    for cid, ph in photos.items():
        outlines.setdefault(cid, {"outline": [], "source": None})
        outlines[cid]["photo"] = ph["photo"]
        outlines[cid]["photo_credit"] = ph["credit"]
    _save("circuits_geo.json", outlines)
    print(f"   geo {len(geo_real)} · photos {len(photos)} / {len(schedule)} circuits")

    print("» Latest F1 news (RSS)")
    news = fetch_news()
    _save("news.json", news)
    print(f"   {len(news)} headlines")

    print("✓ fetch complete")


def refresh_live():
    """Bust every cache tied to the live season (results, standings, news,
    forecast, OpenF1 session lists) so a re-fetch pulls today's data. Static
    history (2024/25, sample telemetry, circuit geometry) stays cached."""
    import glob
    patterns = ["*2026*", "*news*", "*forecast*", "*dstand*", "*cstand*",
                "of1_sessions_*"]
    n = 0
    for pat in patterns:
        for f in glob.glob(os.path.join(CACHE_DIR, pat)):
            os.remove(f); n += 1
    print(f"» refresh: cleared {n} live-season cache files")


if __name__ == "__main__":
    import sys as _sys
    if "--refresh" in _sys.argv:
        refresh_live()
    fetch_all()
