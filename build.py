#!/usr/bin/env python3
"""
build.py — render the F1·26 dashboard (8 self-contained pages).

Pipeline:
  1. ensure data exists (run f1_fetch if needed)
  2. run the prediction engine (f1_predict) → data/predictions.json
  3. compute derived metrics (standings evolution, driver stats)
  4. render site/*.html with build-time data inlined as <script id="DATA">

Pages: index · live-timing · schedule · results · standings · drivers ·
       driver-stats · prediction
"""

import html
import json
import os
import sys
import datetime

import f1_fetch
import f1_predict
import f1_circuits as C
from pages_live import live_timing_body, LIVE_JS   # live-timing is large → own module

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SITE = os.path.join(HERE, "site")

TODAY = datetime.date(2026, 6, 5)   # pinned "now" so the live season is reproducible

# ── consistent 2026 team colours (used for dots, badges, charts) ─────────────
TEAM_COLORS = {
    "mercedes": "#00D7B6", "ferrari": "#E8002D", "mclaren": "#FF8000",
    "red_bull": "#3671C6", "aston_martin": "#229971", "alpine": "#0093CC",
    "williams": "#64C4FF", "rb": "#6692FF", "haas": "#B6BABD",
    "audi": "#00C752", "cadillac": "#C8A24A",
}
def team_color(cid): return TEAM_COLORS.get(cid, "#8E8E93")

NAV = [
    ("dashboard.html", "Overview"), ("live-timing.html", "Live Timing"),
    ("schedule.html", "Schedule"), ("results.html", "Results"),
    ("drivers.html", "Drivers"),
    ("driver-stats.html", "Stats"), ("prediction.html", "Prediction"),
]

# editorial splash hero image — CC BY-SA 4.0, Lukas Raich (Wikimedia Commons):
# Ferrari (Sainz, #55) at the 2023 Austrian Grand Prix
HERO_IMG = ("https://upload.wikimedia.org/wikipedia/commons/thumb/9/9f/"
            "FIA_F1_Austria_2023_Nr._55_%281%29.jpg/3840px-FIA_F1_Austria_2023_Nr._55_%281%29.jpg")
HERO_CREDIT = 'Photo: Lukas Raich · CC BY-SA 4.0'

# ── flag emoji for countries + driver nationalities ──────────────────────────
_ISO = {
    "Australia": "AU", "China": "CN", "Japan": "JP", "USA": "US", "United States": "US",
    "Canada": "CA", "Monaco": "MC", "Spain": "ES", "Austria": "AT", "UK": "GB",
    "United Kingdom": "GB", "Belgium": "BE", "Hungary": "HU", "Netherlands": "NL",
    "Italy": "IT", "Azerbaijan": "AZ", "Singapore": "SG", "Mexico": "MX",
    "Brazil": "BR", "Qatar": "QA", "UAE": "AE", "United Arab Emirates": "AE",
    "Saudi Arabia": "SA", "Bahrain": "BH",
    # nationalities (demonyms)
    "British": "GB", "German": "DE", "Italian": "IT", "Dutch": "NL", "Spanish": "ES",
    "Monegasque": "MC", "Mexican": "MX", "Australian": "AU", "Canadian": "CA",
    "French": "FR", "Finnish": "FI", "Danish": "DK", "Thai": "TH", "Japanese": "JP",
    "Chinese": "CN", "American": "US", "Brazilian": "BR", "Argentine": "AR",
    "Argentinian": "AR", "New Zealander": "NZ", "Belgian": "BE", "Austrian": "AT",
}
def flag(name):
    iso = _ISO.get(name)
    if not iso:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso)


def esc(s):
    return html.escape(str(s if s is not None else ""))


def _load(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


def _load_opt(name, default):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    with open(p) as f:
        return json.load(f)


def _is_dnf(status):
    """A car is a DNF only if it didn't take the chequered flag. 'Finished',
    '+N Laps' and 'Lapped' are all classified finishers."""
    if not status:
        return False
    return not (status == "Finished" or status.startswith("+") or status == "Lapped")


# ═════════════════════════════════════════════════════════════════════════════
# Derived metrics
# ═════════════════════════════════════════════════════════════════════════════
def compute_evolution(results, sprint, standings):
    """Cumulative championship points per round per driver (2026)."""
    grid = [d["driverId"] for d in standings["drivers"]]
    races = sorted(results.get("2026", []), key=lambda r: r["round"])
    sprints = {s["round"]: s for s in sprint.get("2026", [])}
    rounds = [r["round"] for r in races]
    cum = {d: 0.0 for d in grid}
    series = {d: [] for d in grid}
    for r in races:
        pts = {res["driverId"]: res["points"] for res in r["results"]}
        sp = sprints.get(r["round"])
        if sp:
            for res in sp["results"]:
                pts[res["driverId"]] = pts.get(res["driverId"], 0) + res["points"]
        for d in grid:
            cum[d] += pts.get(d, 0)
            series[d].append(round(cum[d], 1))
    return rounds, series


def compute_stats(results, quali, sprint, standings):
    """Per-driver completion / wins / podiums / poles / DNFs / avg-finish, for
    2026 and the 2024–26 aggregate. Points include sprint points so totals
    reconcile with the championship standings."""
    grid = standings["drivers"]
    def blank():
        return {"races": 0, "wins": 0, "podiums": 0, "poles": 0, "dnf": 0,
                "fin": 0, "finish_sum": 0, "points": 0.0}
    out = {}
    poles_by_season = {}
    for season in ("2024", "2025", "2026"):
        pb = {}
        for race in quali.get(season, []):
            for q in race["results"]:
                if q["pos"] == 1:
                    pb.setdefault(q["driverId"], 0)
                    pb[q["driverId"]] += 1
        poles_by_season[season] = pb

    # sprint points per (season, round, driver)
    sprint_pts = {}
    for season in ("2024", "2025", "2026"):
        for race in sprint.get(season, []):
            for res in race["results"]:
                sprint_pts[(season, res["driverId"])] = \
                    sprint_pts.get((season, res["driverId"]), 0) + res["points"]

    for d in grid:
        did = d["driverId"]
        s26, sall = blank(), blank()
        for season in ("2024", "2025", "2026"):
            for race in results.get(season, []):
                res = next((x for x in race["results"] if x["driverId"] == did), None)
                if not res:
                    continue
                for bucket in ([sall] + ([s26] if season == "2026" else [])):
                    bucket["races"] += 1
                    bucket["points"] += res["points"]
                    if isinstance(res["pos"], int):
                        if res["pos"] == 1: bucket["wins"] += 1
                        if res["pos"] <= 3: bucket["podiums"] += 1
                    if _is_dnf(res["status"]):
                        bucket["dnf"] += 1
                    else:
                        bucket["fin"] += 1
                        if isinstance(res["pos"], int):
                            bucket["finish_sum"] += res["pos"]
        s26["points"] += sprint_pts.get(("2026", did), 0)
        sall["points"] += sum(sprint_pts.get((s, did), 0) for s in ("2024", "2025", "2026"))
        s26["poles"] = poles_by_season["2026"].get(did, 0)
        sall["poles"] = sum(poles_by_season[s].get(did, 0) for s in ("2024", "2025", "2026"))
        for b in (s26, sall):
            b["completion"] = round(100 * b["fin"] / b["races"], 1) if b["races"] else 0.0
            b["avg_finish"] = round(b["finish_sum"] / b["fin"], 1) if b["fin"] else None
            b["ppr"] = round(b["points"] / b["races"], 1) if b["races"] else 0.0
        out[did] = {"d": d, "y2026": s26, "all": sall}
    return out


_CRASH = ("Accident", "Collision", "Spun", "Damage", "Crash", "Puncture")
_MECH = ("Engine", "Gearbox", "Hydraulic", "Power Unit", "Transmission", "Brakes",
         "Suspension", "Electrical", "Cooling", "Water", "Oil", "Fuel", "Turbo",
         "Wheel", "Driveshaft", "Clutch", "Overheating", "Mechanical", "Retired")


def _dnf_type(status):
    s = (status or "")
    if any(k.lower() in s.lower() for k in _CRASH):
        return "crash"
    if any(k.lower() in s.lower() for k in _MECH):
        return "mech"
    return "other"


# Official result statuses → reader-friendly explanations
_STATUS_HUMAN = {
    "Retired": "Retired — withdrew from the race (cause unreported)",
    "Accident": "Crashed — accident",
    "Collision": "Crash damage — collision with another car",
    "Collision damage": "Crash damage — collision with another car",
    "Spun off": "Spun off track",
    "Engine": "Engine failure", "Gearbox": "Gearbox failure",
    "Hydraulics": "Hydraulics failure", "Power Unit": "Power-unit failure",
    "Brakes": "Brake failure", "Suspension": "Suspension failure",
    "Electrical": "Electrical failure", "Overheating": "Overheating",
    "Puncture": "Tyre puncture", "Wheel": "Wheel problem",
    "Disqualified": "Disqualified", "Withdrew": "Withdrew",
    "Illness": "Driver unwell", "Did not start": "Did not start",
}


def compute_incidents(results, standings):
    """DNFs from real result statuses (2026 season). Lapped/+N-lap cars are
    finishers and are excluded — only true retirements appear here."""
    recent, by_cause, by_cons = [], {}, {}
    for race in sorted(results.get("2026", []), key=lambda r: r["round"], reverse=True):
        for res in race["results"]:
            st = res.get("status")
            if not _is_dnf(st):
                continue
            typ = _dnf_type(st)
            by_cause[st] = by_cause.get(st, 0) + 1
            cid = res.get("constructorId")
            by_cons[cid] = by_cons.get(cid, 0) + 1
            recent.append({
                "round": race["round"], "raceName": race["raceName"],
                "driver": res["family"], "code": res["code"],
                "constructorId": cid, "status": st,
                "human": _STATUS_HUMAN.get(st, st), "type": typ,
            })
    crashes = sum(1 for r in recent if r["type"] == "crash")
    mech = sum(1 for r in recent if r["type"] == "mech")
    return {"recent": recent[:14], "total": len(recent), "crashes": crashes,
            "mech": mech, "by_cause": by_cause,
            "by_cons": sorted(by_cons.items(), key=lambda x: -x[1])}


# ═════════════════════════════════════════════════════════════════════════════
# Shared HTML scaffolding
# ═════════════════════════════════════════════════════════════════════════════
def page(title, active, body, data=None, js="", live_badge=None, head_extra=""):
    nav = "".join(
        f'<a href="{href}"{" class=\"active\"" if label == active else ""}>{label}</a>'
        for href, label in NAV)
    badge = f'<span class="live-badge">{esc(live_badge)}</span>' if live_badge else ""
    data_blob = ""
    if data is not None:
        data_blob = ('<script id="DATA" type="application/json">'
                     + json.dumps(data, separators=(",", ":")) + "</script>")
    extra_js = f"<script>{js}</script>" if js else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Titillium+Web:wght@400;600;700;900&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="assets/theme.css">
{head_extra}
</head>
<body>
<header><div class="wrap hbar">
  <a class="logo" href="dashboard.html"><span class="sq"></span>PITWALL<span class="mk">·F1 2026</span></a>
  {badge}
  <button class="menu-btn" onclick="toggleMenu()">≡</button>
  <nav class="tabs">{nav}</nav>
</div></header>
<main><div class="wrap">
{body}
</div></main>
<footer><div class="wrap">
  Data: <span class="mono">Jolpica/Ergast</span> + <span class="mono">OpenF1</span> ·
  PITWALL · Educational / entertainment only — not affiliated with Formula 1.
  Built {datetime.date.today().isoformat()}.
</div></footer>
{data_blob}
<script src="assets/app.js"></script>
{extra_js}
</body>
</html>"""


def dbadge(num, color, size=""):
    cls = "dbadge" + (f" {size}" if size else "")
    return (f'<div class="{cls}" style="--c:{color}"><span class="bar"></span>'
            f'{esc(num if num is not None else "–")}</div>')


def bar_row(label, frac, val, cls=""):
    pct = max(0, min(100, frac * 100))
    return (f'<div class="barrow"><span class="blabel">{esc(label)}</span>'
            f'<span class="bar {cls}"><i style="width:{pct:.0f}%"></i></span>'
            f'<span class="bval">{esc(val)}</span></div>')


def team_dot(cid):
    return f'<span class="teamdot" style="--c:{team_color(cid)}"></span>'


# ═════════════════════════════════════════════════════════════════════════════
# SVG charts (server-side)
# ═════════════════════════════════════════════════════════════════════════════
def line_chart(rounds, series_list, w=860, h=320):
    """series_list: [{name,color,pts:[...]}]. x = round index, y = cumulative pts."""
    if not rounds:
        return '<div class="note">No completed rounds yet.</div>'
    padL, padR, padT, padB = 38, 120, 16, 26
    iw, ih = w - padL - padR, h - padT - padB
    ymax = max((max(s["pts"]) for s in series_list if s["pts"]), default=1) or 1
    ymax = (int(ymax / 25) + 1) * 25
    n = len(rounds)
    def X(i): return padL + (iw * (i / (n - 1)) if n > 1 else iw / 2)
    def Y(v): return padT + ih - ih * (v / ymax)
    parts = [f'<svg viewBox="0 0 {w} {h}" class="linechart" preserveAspectRatio="xMidYMid meet">']
    # gridlines + y labels
    for g in range(0, ymax + 1, max(25, ymax // 6 // 25 * 25 or 25)):
        y = Y(g)
        parts.append(f'<line class="lc-grid" x1="{padL}" y1="{y:.0f}" x2="{padL+iw}" y2="{y:.0f}"/>')
        parts.append(f'<text class="lc-label" x="{padL-6}" y="{y+3:.0f}" text-anchor="end">{g}</text>')
    # x labels
    for i, rd in enumerate(rounds):
        if n <= 12 or i % 2 == 0 or i == n - 1:
            parts.append(f'<text class="lc-label" x="{X(i):.0f}" y="{h-8}" text-anchor="middle">R{rd}</text>')
    # lines + end labels
    for s in series_list:
        pts = s["pts"]
        d = "M" + "L".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(pts))
        parts.append(f'<path d="{d}" fill="none" stroke="{s["color"]}" stroke-width="2" '
                     f'stroke-linejoin="round" opacity=".95"/>')
        ex, ey = X(len(pts) - 1), Y(pts[-1])
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="2.6" fill="{s["color"]}"/>')
        parts.append(f'<text class="lc-label" x="{ex+7:.0f}" y="{ey+3:.0f}" '
                     f'fill="{s["color"]}" style="font-weight:700">{esc(s["name"])} {pts[-1]:.0f}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ═════════════════════════════════════════════════════════════════════════════
# Pages
# ═════════════════════════════════════════════════════════════════════════════
def _hero_track_svg(d, cid):
    """Large faded circuit outline used as hero background art."""
    g = d.get("geo", {}).get(cid, {})
    pts = g.get("geo")
    if pts:                                   # lat/lng → x=lng, y=-lat
        xs = [p[1] for p in pts]; ys = [-p[0] for p in pts]
    else:
        ol = g.get("outline") or []
        if len(ol) < 10:
            return ""
        xs = [p[0] for p in ol]; ys = [-p[1] for p in ol]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    sx, sy = (maxx - minx) or 1, (maxy - miny) or 1
    W, H, pad = 440, 300, 24
    sc = min((W - 2 * pad) / sx, (H - 2 * pad) / sy)
    ox, oy = (W - sc * sx) / 2, (H - sc * sy) / 2
    dd = "M" + "L".join(f"{ox+(x-minx)*sc:.1f},{oy+(y-miny)*sc:.1f}" for x, y in zip(xs, ys)) + "Z"
    return (f'<svg class="hero-track" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">'
            f'<path d="{dd}"/></svg>')


def build_splash(d):
    """Editorial intro landing — full-bleed Ferrari hero that swipes up into
    the dashboard on 'Start Racing'."""
    nr = d["preds"]["next_race"]
    total = len(d["sched"])
    try:
        nice = datetime.datetime.strptime(nr["date"], "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        nice = nr["date"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PITWALL · F1 2026</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Titillium+Web:wght@400;600;700;900&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="assets/theme.css">
</head>
<body style="background:#0a0a0e">
<div class="splash" id="splash">
  <img class="splash-bg" src="{HERO_IMG}" alt="Ferrari Formula 1 car">
  <div class="splash-scrim"></div>
  <div class="splash-grid"></div>
  <div class="splash-wrap">
    <div class="splash-head">
      <a class="logo" href="dashboard.html" style="font-size:19px"><span class="sq"></span>PITWALL<span class="mk">·F1 2026</span></a>
    </div>
    <div class="splash-mid">
      <div class="splash-stat">2026 SEASON</div>
      <h1 class="splash-h1">Lights Out,<br><span class="ghost">Full Data.</span></h1>
      <p class="splash-sub">The entire 2026 Formula 1 grid in one place — live race replays,
      championship standings, circuit maps, and a transparent win-probability engine.</p>
      <div class="splash-actions">
        <button class="splash-go" onclick="enter()">Start Racing
          <span style="font-size:18px">↗</span></button>
      </div>
    </div>
    <div class="splash-foot">
      <div class="splash-credit">{HERO_CREDIT} · via Wikimedia Commons</div>
      <a class="splash-next" href="dashboard.html" onclick="enter();return false;">
        <div class="caps">Next Grand Prix · Round {nr['round']} / {total}</div>
        <div class="nx-name">{flag(nr['country'])} {esc(nr['name'])}</div>
        <div class="nx-meta">{esc(nr['circuitName'])} · {esc(nice)}</div>
      </a>
    </div>
  </div>
</div>
<script>
function enter(){{var s=document.getElementById('splash');s.classList.add('lift');
  setTimeout(function(){{location.href='dashboard.html';}},720);}}
// keyboard: Enter / Space / ↓ also proceeds
document.addEventListener('keydown',function(e){{
  if(e.key==='Enter'||e.key===' '||e.key==='ArrowDown'){{e.preventDefault();enter();}}}});
// preload the dashboard so it appears instantly after the swipe
var l=document.createElement('link');l.rel='prefetch';l.href='dashboard.html';document.head.appendChild(l);
</script>
</body>
</html>"""


def build_overview(d):
    sched, results, standings, preds = d["sched"], d["results"], d["standings"], d["preds"]
    dr = standings["drivers"]; cons = standings["constructors"]
    photos = standings.get("photos", {})
    def photo(num): return photos.get(str(num))
    completed = max((r["round"] for r in results.get("2026", [])), default=0)
    total = len(sched)
    nr = preds["next_race"]
    last = max(results.get("2026", []), key=lambda r: r["round"], default=None)
    last_win = last["results"][0] if last and last["results"] else None
    leader = dr[0] if dr else None
    pred_champ = max(preds["drivers"], key=lambda x: x["title_pct"])
    tr = nr["circuit_traits"]

    try:
        nice_date = datetime.datetime.strptime(nr["date"], "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        nice_date = nr["date"]
    # split race name onto two display lines (drop trailing "Grand Prix")
    base = nr["name"].replace(" Grand Prix", "")
    title_html = f'{esc(base)}<br><span style="-webkit-text-stroke:1px #fff;color:transparent">Grand Prix</span>' \
        if "Grand Prix" in nr["name"] else esc(nr["name"])

    cgeo = d.get("geo", {}).get(nr["circuitId"], {})
    cphoto = cgeo.get("photo")
    ccredit = cgeo.get("photo_credit", "")
    hero_bg = (f'<img class="hero-photo" src="{esc(cphoto)}" alt="" loading="eager" onerror="this.remove()">'
               if cphoto else "")
    hero = f"""
    <section class="hero-race{' has-photo' if cphoto else ''}">
      {hero_bg}{_hero_track_svg(d, nr["circuitId"])}
      <div class="hero-scrim"></div>
      <div class="hero-inner">
        <div class="hero-eyebrow"><span class="chip lime">ROUND {nr['round']} / {total}</span>
          <span class="caps" style="margin:0">2026 Season · Next Up</span></div>
        <div class="hero-flag">{flag(nr['country'])}</div>
        <h1 class="hero-title">{title_html}</h1>
        <div class="hero-sub">{esc(nr['circuitName'])} · {esc(nr['country'])} · {esc(nice_date)}</div>
        <div class="hero-chips">
          <span class="chip">{tr['type'].title()}</span>
          <span class="chip">DF {tr['downforce']}</span>
          <span class="chip">PWR {tr['power']}</span>
          <span class="chip">Tyre {tr['tyre_stress']}</span>
          <span class="chip dim">{C.layout(nr['circuitId'])['drs']} DRS · {tr['corners']} turns</span>
        </div>
        <div class="hero-cta">
          <a class="btn primary" href="prediction.html">Race-day prediction →</a>
          <a class="btn ghost" href="live-timing.html">Watch replay</a>
          <a class="btn ghost" href="schedule.html">Circuit map</a>
        </div>
      </div>
      <div class="hero-side">
        <div class="caps" style="margin-bottom:8px">Lights out in</div>
        <div class="countdown" id="cd"></div>
      </div>
      {f'<div class="hero-credit">{esc(ccredit)} · Wikimedia</div>' if ccredit else ''}
    </section>"""

    # ── headshot stat cards: centred portrait + frosted info banner ─────────
    def shot_img(num):
        u = photo(num)
        return f'<img class="shot" src="{esc(u)}" alt="" loading="lazy" onerror="this.remove()">' if u else ""

    def lead_card(num, cid, label, delta, big, unit, name, nat):
        delta_html = f'<span class="delta {delta[0]}">{delta[1]}</span>' if delta else ""
        return f"""
        <div class="lead-card" style="--c:{team_color(cid)}">
          <div class="lead-photo">{shot_img(num)}</div>
          <div class="lead-banner">
            <div class="lead-top">{esc(label)} {delta_html}</div>
            <div class="lead-big">{big}<span class="unit">{esc(unit)}</span></div>
          </div>
          <div class="lead-foot"><span class="fl">{flag(nat)}</span> <span>{esc(name)}</span></div>
        </div>"""

    cards = []
    if leader:
        cards.append(lead_card(leader.get("num"), leader["constructorId"], "Championship Leader",
                               ("up", "▲"), f'{leader["points"]:.0f}', "POINTS",
                               f'{leader["given"]} {leader["family"]}', leader["nationality"]))
    if last_win:
        lw = next((x for x in dr if x["driverId"] == last_win["driverId"]), last_win)
        lw_wins = sum(1 for r in results.get("2026", []) for res in r["results"]
                      if res["driverId"] == last_win["driverId"] and res["pos"] == 1)
        cards.append(lead_card(lw.get("num"), last_win["constructorId"],
                               f'Last Winner · {last["raceName"].replace(" Grand Prix","") if last else ""}',
                               ("up", "▲"), f'{lw_wins}', "WINS '26",
                               f'{last_win["given"]} {last_win["family"]}', last_win.get("nationality")))
    pc_d = next((x for x in dr if x["driverId"] == pred_champ["driverId"]), None)
    cards.append(lead_card(pred_champ.get("num"), pred_champ["constructorId"], "Predicted Champion",
                           None, f'{pred_champ["title_pct"]:.0f}<span class="pct">%</span>', "TITLE PROBABILITY",
                           esc(pred_champ["name"]), pc_d["nationality"] if pc_d else None))
    lead = f'<div class="lead-grid">{"".join(cards)}</div>'

    cars = standings.get("cars", {})
    PLACE = {1: "1ST PLACE", 2: "2ND PLACE", 3: "3RD PLACE"}

    # ── drivers' championship: FINALISTS-style image-back cards + rest ───────
    def fin_driver(x):
        u = photo(x.get("num"))
        bg = f'<img class="fin-bg shot" src="{esc(u)}" alt="" loading="lazy" onerror="this.remove()">' if u else ""
        return f"""
        <div class="fin-card driver{' lead' if x['pos']==1 else ''}" style="--c:{team_color(x['constructorId'])}">
          {bg}<div class="fin-scrim"></div><div class="fin-bar"></div>
          <div class="fin-place">{PLACE.get(x['pos'], 'P'+str(x['pos']))}</div>
          <div class="fin-top">{team_dot(x['constructorId'])}{esc(x['constructor'])}</div>
          <div class="fin-pts">{x['points']:.0f}<span>PTS</span></div>
          <div class="fin-name">{flag(x['nationality'])} {esc(x['given'])} {esc(x['family'])}</div>
        </div>"""
    drest = "".join(
        f'<div class="srow"><span class="pos">{x["pos"]}</span>'
        f'{team_dot(x["constructorId"])}'
        f'<span><b>{esc(x["code"])}</b> {esc(x["family"])} '
        f'<span class="muted" style="font-size:11px">{esc(x["constructor"])}</span></span>'
        f'<span class="mono">{x["points"]:.0f}</span></div>'
        for x in dr[3:])
    drivers_sec = f"""
    <div class="sec-head"><h2>Drivers' Championship</h2>
      <div class="sec-sub">Top three on the road · after {completed} rounds</div></div>
    <div class="fin-grid">{"".join(fin_driver(x) for x in dr[:3])}</div>
    <details class="standings-more"><summary>Show all {len(dr)} drivers · standings &amp; results →</summary>
      {drest}</details>"""

    # ── constructors' championship: car-photo image-back cards + rest ───────
    def fin_team(x):
        u = cars.get(x["constructorId"])
        bg = f'<img class="fin-bg" src="{esc(u)}" alt="" loading="lazy" onerror="this.remove()">' if u else ""
        return f"""
        <div class="fin-card team{' lead' if x['pos']==1 else ''}" style="--c:{team_color(x['constructorId'])}">
          {bg}<div class="fin-scrim"></div><div class="fin-bar"></div>
          <div class="fin-place">{PLACE.get(x['pos'], 'P'+str(x['pos']))}</div>
          <div class="fin-top">{team_dot(x['constructorId'])}{x['wins']} wins '26</div>
          <div class="fin-pts">{x['points']:.0f}<span>PTS</span></div>
          <div class="fin-name">{esc(x['name'])}</div>
        </div>"""
    crest = "".join(
        f'<div class="srow"><span class="pos">{x["pos"]}</span>'
        f'{team_dot(x["constructorId"])}<span><b>{esc(x["name"])}</b></span>'
        f'<span class="mono">{x["points"]:.0f}</span></div>'
        for x in cons[3:])
    cons_sec = f"""
    <div class="sec-head"><h2>Constructors' Championship</h2>
      <div class="sec-sub">The teams' title fight</div></div>
    <div class="fin-grid">{"".join(fin_team(x) for x in cons[:3])}</div>
    <details class="standings-more"><summary>Show all {len(cons)} teams →</summary>{crest}</details>"""

    # ── one photo-led news feed (latest news first, then 2026 retirements) ──
    news = d.get("news", [])
    inc = d.get("incidents", {"recent": []})
    ticon = {"crash": "💥", "mech": "🔧", "other": "⚠️"}
    feed = []
    for n in news[:12]:
        img = n.get("image")
        imgdiv = (f'<div class="nf-img" style="background-image:url(\'{esc(img)}\')"></div>'
                  if img else '<div class="nf-img nf-noimg"><span>PITWALL</span></div>')
        feed.append(
            f'<a class="nf-card" href="{esc(n["link"])}" target="_blank" rel="noopener noreferrer">'
            f'{imgdiv}<div class="nf-body"><span class="nf-cat">F1 News</span>'
            f'<div class="nf-title">{esc(n["title"])}</div>'
            f'<div class="nf-date">{esc((n.get("date") or "")[:16])} · motorsport.com ↗</div></div></a>')
    for r in inc.get("recent", [])[:8]:
        tcls = "crash" if r["type"] == "crash" else "mech" if r["type"] == "mech" else "other"
        feed.append(
            f'<div class="nf-card inc">'
            f'<div class="nf-img inc-{tcls}"><span>{ticon.get(r["type"],"⚠️")}</span></div>'
            f'<div class="nf-body"><span class="nf-cat red">Retirement · R{r["round"]}</span>'
            f'<div class="nf-title">{esc(r["code"])} {esc(r["driver"])} — {esc(r.get("human", r["status"]))}</div>'
            f'<div class="nf-date">{esc(r["raceName"].replace(" Grand Prix",""))} Grand Prix</div></div></div>')
    news_feed = (f'<div class="sec-head"><h2>From the Paddock</h2>'
                 f'<div class="sec-sub">Latest F1 headlines &amp; 2026 retirements · scroll for more →</div></div>'
                 f'<div class="news-feed">{"".join(feed)}</div>')

    body = (hero + lead + drivers_sec + cons_sec + news_feed)
    cd_data = {"target": nr["date"] + "T" + (sched and "00:00:00") }
    # find next race time from schedule
    nr_full = next((r for r in sched if r["round"] == nr["round"]), None)
    iso = nr["date"] + "T" + ((nr_full or {}).get("time") or "13:00:00Z").replace("Z", "+00:00")
    js = ("var T=Date.parse('%s');function tick(){var c=document.getElementById('cd');if(!c)return;"
          "var s=(T-Date.now())/1000;"
          "if(s<=0){c.innerHTML='<div class=\\'cd-live\\'>RACE WEEKEND UNDERWAY</div>';return;}"
          "var dd=Math.floor(s/86400),h=Math.floor(s%%86400/3600),m=Math.floor(s%%3600/60),"
          "ss=Math.floor(s%%60);"
          "c.innerHTML=[['Days',dd],['Hrs',h],['Min',m],['Sec',ss]].map(function(x){"
          "return '<div class=\\'cd-cell\\'><div class=\\'v\\'>'+x[1]+'</div>"
          "<div class=\\'l\\'>'+x[0]+'</div></div>'}).join('');}tick();setInterval(tick,1000);"
          % iso)
    return page("PITWALL F1 · Dashboard", "Overview", body, js=js, live_badge="2026 Season Live")


def build_schedule(d):
    sched, results = d["sched"], d["results"]
    win_by_round = {}
    for r in results.get("2026", []):
        if r["results"]:
            win_by_round[r["round"]] = r["results"][0]
    completed = max(win_by_round, default=0)
    next_round = completed + 1

    # interactive street/satellite map (Leaflet) with race pins + circuit overlays
    geo = d.get("geo", {})
    races_geo, circ_detail = [], {}
    for r in sorted(sched, key=lambda r: r["round"]):
        status = "done" if r["round"] in win_by_round else ("next" if r["round"] == next_round else "up")
        races_geo.append({
            "round": r["round"], "name": r["name"], "country": r["country"],
            "date": r["date"], "lat": r["lat"], "lng": r["long"], "status": status,
        })
        cid = r["circuitId"]; tr = C.circuit(cid); lay = C.layout(cid)
        g = geo.get(cid, {})
        circ_detail[str(r["round"])] = {
            "round": r["round"], "name": r["name"], "circuitName": r["circuitName"],
            "country": r["country"], "locality": r["locality"], "date": r["date"],
            "lat": r["lat"], "lng": r["long"],
            "outline": g.get("outline", []), "source": g.get("source"),
            "geo": g.get("geo", []), "geo_source": g.get("geo_source"),
            "turns": tr["corners"], "drs": lay["drs"], "straight_m": lay["straight_m"],
            "s1": lay["s1"], "s2": lay["s2"], "s3": lay["s3"],
            "downforce": tr["downforce"], "power": tr["power"], "tyre": tr["tyre_stress"],
            "overtaking": tr["overtaking"], "type": tr["type"],
        }
    page_data = {"races": races_geo, "circuits": circ_detail, "next": next_round}
    worldmap = f"""
    <div class="mapbox" style="position:relative" id="circuitCard">
      <div id="lmap" style="width:100%;height:620px;border-radius:6px"></div>
      <div id="circuitInfo" class="card" style="position:absolute;top:14px;right:14px;width:330px;
        max-height:580px;overflow-y:auto;background:rgba(21,21,30,.94);backdrop-filter:blur(10px);
        border:1px solid var(--outline);z-index:900"></div>
      <div style="position:absolute;left:14px;bottom:24px;z-index:900" class="flex gap8">
        <button class="btn icon" onclick="stepRound(-1)" title="Previous round">‹</button>
        <button class="btn icon" onclick="stepRound(1)" title="Next round">›</button>
        <button class="btn" onclick="worldView()">World view</button>
      </div>
    </div>
    <div class="flex gap16 wrap-f" style="margin:10px 0 4px;font-size:12px">
      <span class="flex ac gap8"><span class="teamdot" style="--c:#9b9ba8"></span>Completed</span>
      <span class="flex ac gap8"><span class="teamdot" style="--c:#27D45F"></span>Next race</span>
      <span class="flex ac gap8"><span class="teamdot" style="--c:#E10600"></span>Upcoming</span>
      <span class="muted">Click a pin or race card to fly to the circuit — the real track outline is drawn
      on real streets/terrain. Use the layer switcher (top-right of the map) for Satellite view.</span>
    </div>"""

    # race cards
    cards = []
    for r in sorted(sched, key=lambda r: r["round"]):
        tr = C.circuit(r["circuitId"])
        win = win_by_round.get(r["round"])
        if r["round"] in win_by_round:
            badge = '<span class="chip green">Completed</span>'
        elif r["round"] == next_round:
            badge = '<span class="chip lime">Next</span>'
        else:
            badge = '<span class="chip dim">Upcoming</span>'
        winhtml = (f'<div class="muted" style="font-size:12px;margin-top:8px">🏆 '
                   f'{esc(win["given"][0])}. {esc(win["family"])}</div>') if win else ""
        cards.append(f"""
        <div class="card" id="r{r['round']}" onclick="showCircuit({r['round']},true)" style="cursor:pointer">
          <div class="flex jb ac"><span class="caps">R{r['round']}</span>{badge}</div>
          <div style="font-family:'Titillium Web';font-weight:700;font-size:16px;margin:6px 0 2px">
            {flag(r['country'])} {esc(r['name'])}</div>
          <div class="muted" style="font-size:12px">{esc(r['circuitName'])}</div>
          <div class="muted mono" style="font-size:12px;margin-top:4px">{esc(r['date'])} · {esc(r['locality'])}</div>
          <div class="flex gap8 wrap-f" style="margin-top:10px">
            <span class="chip">DF {tr['downforce']}</span>
            <span class="chip">PWR {tr['power']}</span>
            <span class="chip dim">{esc(tr['corners'])} cnr</span>
          </div>{winhtml}
        </div>""")

    body = ('<div class="page-head"><div><h1>2026 Calendar</h1>'
            f'<p>{len(sched)} Grands Prix across the globe — every circuit positioned by real '
            'latitude / longitude on an interactive street &amp; satellite map.</p></div>'
            f'<div class="chip lime">{len(sched)} ROUNDS</div></div>'
            + worldmap
            + '<div class="sec-title">All Rounds</div>'
            + '<div class="grid g4">' + "".join(cards) + "</div>")
    js = r"""
var PD=PAGE_DATA(), RACES=PD.races, CIRC=PD.circuits;
var COL={done:'#9b9ba8',next:'#27D45F',up:'#E10600'};
var MAP=null, trackLayer=null, currentRound=null;
function jumpTo(rnd){var el=document.getElementById('r'+rnd);if(el)el.scrollIntoView({behavior:'smooth',block:'center'});}

// Circuit overlay coordinates. Preferred: REAL georeferenced lat/lng geometry
// (f1-circuits dataset) — overlays the actual tarmac exactly. Fallback:
// telemetry x/y centred on the circuit's lat/lng (approximate placement).
function outlineLatLng(c){
  if(c.geo && c.geo.length>10){
    var g=c.geo.slice(); g.push(g[0]); return g;     // exact, close the loop
  }
  var ol=c.outline||[]; if(ol.length<10) return null;
  var n=ol.length, cx=0, cy=0;
  ol.forEach(function(p){cx+=p[0];cy+=p[1];}); cx/=n; cy/=n;
  var k=0.1/111320;                                  // deg latitude per unit
  var cosl=Math.cos(c.lat*Math.PI/180)||0.2;
  var coords=ol.map(function(p){
    return [c.lat+(p[1]-cy)*k, c.lng+(p[0]-cx)*k/cosl];
  });
  coords.push(coords[0]);
  return coords;
}

function showCircuit(rnd, fly){
  var c=CIRC[rnd]; if(!c) return;
  currentRound=+rnd;
  var coords=outlineLatLng(c);
  if(MAP){
    trackLayer.clearLayers();
    if(coords){
      L.polyline(coords,{color:'#15151E',weight:9,opacity:.85}).addTo(trackLayer);   // casing
      L.polyline(coords,{color:'#E10600',weight:4,opacity:1}).addTo(trackLayer);     // track
      L.circleMarker(coords[0],{radius:5,color:'#fff',weight:2,fillColor:'#27D45F',
        fillOpacity:1}).addTo(trackLayer);                                            // start/finish
    }
    if(fly!==false){
      if(coords) MAP.flyToBounds(L.latLngBounds(coords).pad(0.35), {duration:1.6});
      else MAP.flyTo([c.lat,c.lng], 11, {duration:1.6});
    }
  }
  var mapNote=coords?''
    :'<div class="note" style="margin:8px 0">New circuit — no telemetry yet to trace its shape.</div>';
  document.getElementById('circuitInfo').innerHTML=mapNote+
    '<div class="caps">Round '+c.round+' · '+(c.date||'')+'</div>'
    +'<div style="font-weight:800;font-size:20px;margin:4px 0 2px">'+c.name+'</div>'
    +'<div class="muted" style="font-size:12px">'+c.circuitName+' · '+(c.locality||'')+', '+c.country+'</div>'
    +'<div class="flex gap8 wrap-f" style="margin:12px 0">'
    +'<span class="chip lime">'+c.turns+' turns</span>'
    +'<span class="chip">'+c.drs+' DRS zone'+(c.drs>1?'s':'')+'</span>'
    +'<span class="chip">Longest straight ~'+c.straight_m+' m</span>'
    +'<span class="chip dim">'+c.type.charAt(0).toUpperCase()+c.type.slice(1)+'</span></div>'
    +'<div class="caps" style="margin-bottom:6px">Sectors</div>'
    +['s1','s2','s3'].map(function(s,i){return '<div style="display:grid;grid-template-columns:30px 1fr;gap:8px;margin:5px 0;font-size:12.5px">'
        +'<span class="chip lime" style="justify-content:center">S'+(i+1)+'</span><span>'+c[s]+'</span></div>';}).join('')
    +'<div class="divider"></div>'
    +'<div class="flex gap8 wrap-f"><span class="chip">Downforce '+c.downforce+'</span>'
    +'<span class="chip">Power '+c.power+'</span><span class="chip">Tyre stress '+c.tyre+'</span>'
    +'<span class="chip dim">Overtaking '+c.overtaking+'</span></div>'
    +((c.geo&&c.geo.length)?'<div class="muted" style="font-size:10px;margin-top:8px">Georeferenced track geometry (f1-circuits dataset) — exact position on the map.</div>'
       :(c.source?'<div class="muted" style="font-size:10px;margin-top:8px">Track traced from real '+c.source+' GPS (approximate placement).</div>':''))
    +'<button class="btn" style="margin-top:10px;width:100%" onclick="worldView()">↩ Back to world view</button>';
  if(fly){var cc=document.getElementById('circuitCard');if(cc)cc.scrollIntoView({behavior:'smooth',block:'nearest'});}
}

function worldView(){ if(MAP) MAP.flyTo([28,12],2.4,{duration:1.4}); }

function stepRound(dir){
  var rounds=RACES.map(function(r){return r.round;}).sort(function(a,b){return a-b;});
  var i=rounds.indexOf(currentRound); if(i<0)i=0;
  var next=rounds[(i+dir+rounds.length)%rounds.length];
  showCircuit(next,true);
}

function initMap(){
  if(typeof L==='undefined'){
    document.getElementById('lmap').innerHTML='<div class="muted" style="padding:40px;text-align:center">Map needs an internet connection (tiles + Leaflet). Use the race cards below.</div>';
    showCircuit(PD.next || RACES[0].round, false);
    return;
  }
  var dark=L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
    {subdomains:'abcd', maxZoom:19, attribution:'© OpenStreetMap © CARTO'});
  var sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:19, attribution:'Imagery © Esri'});
  MAP=L.map('lmap',{layers:[dark],zoomSnap:.2,worldCopyJump:true}).setView([28,12],2.4);
  L.control.layers({'Dark map':dark,'Satellite':sat},null,{position:'topleft'}).addTo(MAP);
  trackLayer=L.layerGroup().addTo(MAP);
  // season route (dashed) + race pins
  L.polyline(RACES.map(function(r){return [r.lat,r.lng];}),
    {color:'#E10600',weight:1,opacity:.35,dashArray:'4 6'}).addTo(MAP);
  RACES.forEach(function(r){
    L.circleMarker([r.lat,r.lng],{radius:r.status==='next'?8:6,color:'#0c0c0c',weight:1.5,
      fillColor:COL[r.status],fillOpacity:.95})
      .bindTooltip('R'+r.round+' '+r.name+' · '+r.date)
      .on('click',function(){showCircuit(r.round,true);})
      .addTo(MAP);
  });
  showCircuit(PD.next || RACES[0].round, false);
}
if(document.readyState!=='loading')initMap();else window.addEventListener('DOMContentLoaded',initMap);
"""
    head_extra = ('<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">'
                  '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>'
                  '<style>.leaflet-container{background:#15151E;font-family:inherit}'
                  '.leaflet-control-layers,.leaflet-bar a{background:#1F1F2B;color:#F7F4F1;border-color:#3a3a46}'
                  '.leaflet-bar a:hover{background:#272733}'
                  '.leaflet-control-layers-expanded{background:#1F1F2B;color:#F7F4F1}'
                  '.leaflet-tooltip{background:#1F1F2B;color:#F7F4F1;border:1px solid #3a3a46}</style>')
    return page("PITWALL F1 · Schedule", "Schedule", body, data=page_data, js=js, head_extra=head_extra)


def build_drivers(d):
    standings = d["standings"]
    cards = []
    for x in standings["drivers"]:
        cid = x["constructorId"]
        cards.append(f"""
        <div class="card" style="display:flex;gap:14px;align-items:center">
          {dbadge(x.get('num'), team_color(cid), 'lg')}
          <div style="min-width:0">
            <div style="font-family:'Titillium Web';font-weight:700;font-size:16px">{esc(x['family'])}</div>
            <div class="muted" style="font-size:12px">{esc(x['given'])} · {flag(x['nationality'])} {esc(x['nationality'])}</div>
            <div class="flex gap8 ac" style="margin-top:6px">
              <span class="chip" style="border-color:{team_color(cid)};color:{team_color(cid)}">{esc(x['constructor'])}</span>
            </div>
            <div class="muted mono" style="font-size:12px;margin-top:6px">
              P{x['pos']} · {x['points']:.0f} pts · {x['wins']} wins</div>
          </div>
        </div>""")
    body = ('<div class="page-head"><div><h1>Drivers</h1>'
            '<p>The 2026 grid — numbers, teams, nationalities and season form.</p></div>'
            f'<div class="chip lime">{len(standings["drivers"])} DRIVERS</div></div>'
            '<div class="grid g3">' + "".join(cards) + "</div>")
    return page("PITWALL F1 · Drivers", "Drivers", body)


# the remaining pages live in part 2 (appended below)
from pages_more import build_results, build_stats, build_prediction


# ═════════════════════════════════════════════════════════════════════════════
# Orchestration
# ═════════════════════════════════════════════════════════════════════════════
def ensure_data():
    need = ["schedule.json", "results.json", "qualifying.json", "sprint.json",
            "standings.json", "drivers.json", "sample_race.json"]
    if not all(os.path.exists(os.path.join(DATA, n)) for n in need):
        print("» data missing → fetching")
        f1_fetch.fetch_all()


def main():
    os.makedirs(SITE, exist_ok=True)
    ensure_data()

    print("» running prediction engine")
    preds = f1_predict.run(verbose=False)
    with open(os.path.join(DATA, "predictions.json"), "w") as f:
        json.dump(preds, f, separators=(",", ":"))

    print("» loading + deriving")
    d = {
        "sched": _load("schedule.json"),
        "results": _load("results.json"),
        "quali": _load("qualifying.json"),
        "sprint": _load("sprint.json"),
        "standings": _load("standings.json"),
        "drivers": _load("drivers.json"),
        "sample": _load("sample_race.json"),
        "geo": _load_opt("circuits_geo.json", {}),
        "news": _load_opt("news.json", []),
        "preds": preds,
    }
    rounds, evo = compute_evolution(d["results"], d["sprint"], d["standings"])
    d["evo_rounds"], d["evo"] = rounds, evo
    d["stats"] = compute_stats(d["results"], d["quali"], d["sprint"], d["standings"])
    d["incidents"] = compute_incidents(d["results"], d["standings"])

    ctx = {"page": page, "esc": esc, "flag": flag, "dbadge": dbadge,
           "bar_row": bar_row, "team_color": team_color, "team_dot": team_dot,
           "line_chart": line_chart, "C": C}

    # live page = the f1-race-replay browser port, fed by the baked replay of
    # the latest Grand Prix (f1_prebake.py). Re-bake if it's stale.
    completed = max((r["round"] for r in d["results"].get("2026", [])), default=0)
    replay = _load_opt("replay_race.json", None)
    if completed and (replay is None or replay.get("meta", {}).get("round") != completed):
        print(f"» baking replay for round {completed} (f1_prebake)")
        try:
            import subprocess
            subprocess.run([sys.executable, os.path.join(HERE, "f1_prebake.py")],
                           check=True, timeout=1800)
            replay = _load_opt("replay_race.json", None)
        except Exception as e:  # noqa: BLE001 — keep the previous bake if any
            print("   ! prebake failed:", e)
    d["replay"] = replay

    print("» rendering pages")
    pages = {
        "index.html": build_splash(d),
        "dashboard.html": build_overview(d),
        "live-timing.html": page("PITWALL F1 · Race Replay", "Live Timing",
                                  live_timing_body(d, ctx), data=replay,
                                  js=LIVE_JS, live_badge="Replay"),
        "schedule.html": build_schedule(d),
        "results.html": build_results(d, ctx),
        "standings.html": ('<!DOCTYPE html><meta charset="utf-8">'
                           '<meta http-equiv="refresh" content="0; url=results.html#standings">'
                           '<a href="results.html#standings">Standings moved → Results &amp; Standings</a>'),
        "drivers.html": build_drivers(d),
        "driver-stats.html": build_stats(d, ctx),
        "prediction.html": build_prediction(d, ctx),
    }
    for name, html_str in pages.items():
        with open(os.path.join(SITE, name), "w") as f:
            f.write(html_str)
        print(f"   → site/{name}  ({len(html_str)//1024} KB)")
    print("✓ build complete →", SITE)


if __name__ == "__main__":
    main()
