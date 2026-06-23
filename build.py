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
import unicodedata

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
    ("drivers.html", "Drivers"), ("prediction.html", "Prediction"),
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


def short_team(name):
    """Drop the marketing ' F1 Team' / ' Racing' / ' Team' suffix for clean tables."""
    n = (name or "").strip()
    for suf in (" F1 Team", " Formula 1 Team", " Racing", " Team"):
        if n.endswith(suf):
            n = n[:-len(suf)].strip()
    return n


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

    # ── stat tiles (trophy-cabinet aesthetic): icon · figure · label · name ──
    ICON = {
        "trophy": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4zM7 6H4v2a3 3 0 0 0 3 3M17 6h3v2a3 3 0 0 1-3 3"/></svg>',
        "flag": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 21V4M5 4h12l-2.5 4L17 12H5"/></svg>',
        "target": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1" fill="currentColor"/></svg>',
    }

    def stat_tile(icon, big, unit, label, name, nat):
        return f"""
        <div class="stat-tile">
          <div class="st-icon">{ICON[icon]}</div>
          <div class="st-fig">{big}<span class="st-unit">{esc(unit)}</span></div>
          <div class="st-label">{esc(label)}</div>
          <div class="st-name">{flag(nat)} {esc(name)}</div>
        </div>"""

    tiles = []
    if leader:
        tiles.append(stat_tile("trophy", f'{leader["points"]:.0f}', "PTS", "Championship Leader",
                               f'{leader["given"]} {leader["family"]}', leader["nationality"]))
    if last_win:
        tiles.append(stat_tile("flag", "P1", "",
                               f'Last Winner · {last["raceName"].replace(" Grand Prix","") if last else ""}',
                               f'{last_win["given"]} {last_win["family"]}', last_win.get("nationality")))
    pc_d = next((x for x in dr if x["driverId"] == pred_champ["driverId"]), None)
    tiles.append(stat_tile("target", f'{pred_champ["title_pct"]:.0f}', "% TITLE", "Predicted Champion",
                           pred_champ["name"], pc_d["nationality"] if pc_d else None))
    lead = f'<div class="lead-grid">{"".join(tiles)}</div>'

    cars = standings.get("cars", {})
    dphotos = standings.get("driver_photos", {})
    prev_drv = standings.get("prev_drivers", {})
    prev_con = standings.get("prev_constructors", {})
    PLACE = {1: "1ST PLACE", 2: "2ND PLACE", 3: "3RD PLACE"}

    # race-on-race movement vs the previous round's official standings
    def delta_cell(prev_pos, cur_pos):
        if not prev_pos:
            return '<td class="st-mv flat" title="No change recorded">–</td>'
        diff = int(prev_pos) - int(cur_pos)          # +ve = gained places
        if diff > 0:
            return f'<td class="st-mv up" title="Up {diff} from last race">▲{diff}</td>'
        if diff < 0:
            return f'<td class="st-mv down" title="Down {abs(diff)} from last race">▼{abs(diff)}</td>'
        return '<td class="st-mv flat" title="No change">–</td>'

    # ── drivers' championship: FINALISTS-style image-back cards + rest ───────
    # index whatever the user dropped in site/assets/drivers/ (any filename that
    # contains the driver's surname / id / code works — e.g. lewishamilton.jpg)
    def _norm(s):
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        return "".join(ch for ch in s.lower() if ch.isalnum())
    _drv_dir = os.path.join(SITE, "assets", "drivers")
    _drv_files = []
    if os.path.isdir(_drv_dir):
        for fn in os.listdir(_drv_dir):
            if fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")):
                _drv_files.append((_norm(os.path.splitext(fn)[0]), fn))

    def _custom_driver_img(x):
        fam = _norm(x["family"]); did = _norm(x["driverId"]); code = _norm(x.get("code") or "")
        for stem, fn in _drv_files:
            if (len(fam) >= 4 and fam in stem) or stem == did or (code and stem == code):
                return f"assets/drivers/{fn}"
        return None

    # index whatever the user dropped in site/assets/cars/ (filename = constructorId
    # or team name, e.g. mclaren.jpg / red_bull.png) — overrides the Commons photo
    _car_dir = os.path.join(SITE, "assets", "cars")
    _car_files = []
    if os.path.isdir(_car_dir):
        for fn in os.listdir(_car_dir):
            if fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")):
                _car_files.append((_norm(os.path.splitext(fn)[0]), fn))

    def _custom_car_img(x):
        cid = _norm(x["constructorId"]); nm = _norm(x["name"])
        for stem, fn in _car_files:
            if stem == cid or stem == nm or (len(nm) >= 4 and nm in stem) or (len(stem) >= 4 and stem in cid):
                return f"assets/cars/{fn}"
        return None

    def fin_driver(x):
        did = x["driverId"]
        custom = _custom_driver_img(x)          # drop a cockpit/action shot here
        if custom:
            bg = f'<img class="fin-bg cover" src="{esc(custom)}" alt="" loading="lazy">'
        else:
            # fall back to the official F1 headshot (tight studio portrait, right-framed)
            u = photo(x.get("num")) or dphotos.get(did)
            bg = f'<img class="fin-bg" src="{esc(u)}" alt="" loading="lazy" onerror="this.remove()">' if u else ""
        return f"""
        <div class="fin-card driver{' lead' if x['pos']==1 else ''}" style="--c:{team_color(x['constructorId'])}">
          {bg}<div class="fin-scrim"></div><div class="fin-bar"></div>
          <div class="fin-place">{PLACE.get(x['pos'], 'P'+str(x['pos']))}</div>
          <div class="fin-top">{team_dot(x['constructorId'])}{esc(x['constructor'])}</div>
          <div class="fin-pts">{x['points']:.0f}<span>PTS</span></div>
          <div class="fin-name">{flag(x['nationality'])} {esc(x['given'])} {esc(x['family'])}</div>
        </div>"""
    stats = d.get("stats", {})
    def _pod(did): return stats.get(did, {}).get("y2026", {}).get("podiums", 0)

    drows = "".join(
        f'<tr><td class="st-pos">{x["pos"]}</td>'
        f'{delta_cell(prev_drv.get(x["driverId"]), x["pos"])}'
        f'<td class="st-drv">{team_dot(x["constructorId"])}'
        f'<b>{esc(x["given"])} {esc(x["family"])}</b></td>'
        f'<td class="st-cty">{flag(x["nationality"])} {esc(x["nationality"])}</td>'
        f'<td class="st-team">{esc(short_team(x["constructor"]))}</td>'
        f'<td class="num">{_pod(x["driverId"])}</td>'
        f'<td class="num">{x["wins"]}</td>'
        f'<td class="num pts">{x["points"]:.0f}</td></tr>'
        for x in dr)
    drivers_table = f"""
      <table class="std-table">
        <thead><tr><th>Pos</th><th class="st-mv" title="Change vs last race">+/–</th>
          <th>Driver</th><th class="st-cty">Country</th><th>Team</th>
          <th class="num">Podiums</th><th class="num">Wins</th><th class="num">Points</th></tr></thead>
        <tbody>{drows}</tbody>
      </table>"""
    drivers_sec = f"""
    <div class="sec-head"><h2>Drivers' Championship</h2>
      <div class="sec-sub">Top three on the road · after {completed} rounds</div></div>
    <div class="fin-grid">{"".join(fin_driver(x) for x in dr[:3])}</div>
    <details class="standings-more"><summary>Full standings · all {len(dr)} drivers →</summary>
      {drivers_table}</details>"""

    # ── constructors' championship: car-photo image-back cards + rest ───────
    def fin_team(x):
        u = _custom_car_img(x) or cars.get(x["constructorId"])
        bg = f'<img class="fin-bg" src="{esc(u)}" alt="" loading="lazy" onerror="this.remove()">' if u else ""
        return f"""
        <div class="fin-card team{' lead' if x['pos']==1 else ''}" style="--c:{team_color(x['constructorId'])}">
          {bg}<div class="fin-scrim"></div><div class="fin-bar"></div>
          <div class="fin-place">{PLACE.get(x['pos'], 'P'+str(x['pos']))}</div>
          <div class="fin-top">{team_dot(x['constructorId'])}{x['wins']} wins '26</div>
          <div class="fin-pts">{x['points']:.0f}<span>PTS</span></div>
          <div class="fin-name">{esc(x['name'])}</div>
        </div>"""
    # team podiums = sum of its drivers' 2026 podiums
    team_pod = {}
    for x in dr:
        team_pod[x["constructorId"]] = team_pod.get(x["constructorId"], 0) + _pod(x["driverId"])
    crows = "".join(
        f'<tr><td class="st-pos">{x["pos"]}</td>'
        f'{delta_cell(prev_con.get(x["constructorId"]), x["pos"])}'
        f'<td class="st-drv">{team_dot(x["constructorId"])}<b>{esc(short_team(x["name"]))}</b></td>'
        f'<td class="st-cty">{flag(x.get("nationality"))} {esc(x.get("nationality") or "")}</td>'
        f'<td class="num">{team_pod.get(x["constructorId"], 0)}</td>'
        f'<td class="num">{x["wins"]}</td>'
        f'<td class="num pts">{x["points"]:.0f}</td></tr>'
        for x in cons)
    cons_table = f"""
      <table class="std-table cons">
        <thead><tr><th>Pos</th><th class="st-mv" title="Change vs last race">+/–</th>
          <th>Team</th><th class="st-cty">Country</th>
          <th class="num">Podiums</th><th class="num">Wins</th><th class="num">Points</th></tr></thead>
        <tbody>{crows}</tbody>
      </table>"""
    cons_sec = f"""
    <div class="sec-head"><h2>Constructors' Championship</h2>
      <div class="sec-sub">The teams' title fight</div></div>
    <div class="fin-grid">{"".join(fin_team(x) for x in cons[:3])}</div>
    <details class="standings-more"><summary>Full standings · all {len(cons)} teams →</summary>{cons_table}</details>"""

    # ── one photo-led news feed (latest F1 headlines, most recent first) ────
    news = d.get("news", [])
    feed = []
    for n in news[:14]:
        img = n.get("image")
        imgdiv = (f'<div class="nf-img" style="background-image:url(\'{esc(img)}\')"></div>'
                  if img else '<div class="nf-img nf-noimg"><span>PITWALL</span></div>')
        feed.append(
            f'<a class="nf-card" href="{esc(n["link"])}" target="_blank" rel="noopener noreferrer">'
            f'{imgdiv}<div class="nf-body"><span class="nf-cat">F1 News</span>'
            f'<div class="nf-title">{esc(n["title"])}</div>'
            f'<div class="nf-date">{esc((n.get("date") or "")[:16])} · motorsport.com ↗</div></div></a>')
    news_feed = (f'<div class="sec-head"><h2>From the Paddock</h2>'
                 f'<div class="sec-sub">Latest F1 headlines · scroll for more →</div></div>'
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
    page_data = {"races": races_geo, "circuits": circ_detail, "next": next_round,
                 "recent": completed or next_round}
    # race cards — single horizontally-scrollable row, dashboard summary-tile
    # aesthetic, embedded as a strip along the bottom of the map panel (no track art)
    cards = []
    for r in sorted(sched, key=lambda r: r["round"]):
        rnd = r["round"]
        win = win_by_round.get(rnd)
        if rnd in win_by_round:
            status, badge = "done", '<span class="chip green">Completed</span>'
        elif rnd == next_round:
            status, badge = "next", '<span class="chip lime">Next</span>'
        else:
            status, badge = "up", '<span class="chip dim">Upcoming</span>'
        if win:
            foot = (f'<span class="rc-foot-k">Winner</span>'
                    f'<span class="rc-foot-v">🏆 {esc(win["given"][0])}. {esc(win["family"])}</span>')
        elif status == "next":
            foot = ('<span class="rc-foot-k">Status</span>'
                    '<span class="rc-foot-v lime">Lights out next</span>')
        else:
            foot = ('<span class="rc-foot-k">Status</span>'
                    '<span class="rc-foot-v muted">Upcoming</span>')
        cards.append(f"""
        <div class="rc-card {status}" id="r{rnd}" data-round="{rnd}"
             onclick="showCircuit({rnd},true)">
          <div class="rc-top"><span class="caps">Round {rnd}</span>{badge}</div>
          <div class="rc-name">{flag(r['country'])} {esc(r['name'])}</div>
          <div class="rc-circ">{esc(r['circuitName'])}</div>
          <div class="rc-date mono">{esc(r['date'])} · {esc(r['locality'])}</div>
          <div class="rc-foot">{foot}</div>
        </div>""")

    rc_strip = ('<div class="rc-embed">'
                '<div class="rc-head"><span class="caps">All Rounds · 2026</span>'
                '<div class="rc-nav"><button class="btn icon" onclick="scrollCards(-1)" '
                'title="Scroll left">‹</button><button class="btn icon" onclick="scrollCards(1)" '
                'title="Scroll right">›</button></div></div>'
                '<div class="rc-row" id="rcRow">' + "".join(cards) + "</div></div>")

    worldmap = f"""
    <div class="mapbox" id="circuitCard">
      <div class="map-stage">
        <div id="lmap"></div>
        <div class="map-ctrls">
          <button class="btn icon" onclick="stepRound(-1)" title="Previous round">‹</button>
          <button class="btn icon" onclick="stepRound(1)" title="Next round">›</button>
          <button class="btn" onclick="worldView()">World view</button>
        </div>
      </div>
      {rc_strip}
    </div>
    <div class="flex gap16 wrap-f" style="margin:10px 0 4px;font-size:12px">
      <span class="flex ac gap8"><span class="teamdot" style="--c:#9b9ba8"></span>Completed</span>
      <span class="flex ac gap8"><span class="teamdot" style="--c:#27D45F"></span>Next race</span>
      <span class="flex ac gap8"><span class="teamdot" style="--c:#E10600"></span>Upcoming</span>
      <span class="flex ac gap8"><span class="teamdot" style="--c:#E10600"></span>Zone 1
        <span class="teamdot" style="--c:#19C3B1;margin-left:10px"></span>Zone 2
        <span class="teamdot" style="--c:#F4D34A;margin-left:10px"></span>Zone 3</span>
      <span class="muted">Opens on the most recent race in satellite view. Click a pin or race card to fly
      to a circuit — the real track outline is split into three coloured zones on real terrain. Switch the
      base layer (top-left) for the dark map.</span>
    </div>"""

    body = ('<div class="page-head"><div><h1>2026 Calendar</h1>'
            f'<p>{len(sched)} Grands Prix across the globe — every circuit positioned by real '
            'latitude / longitude on an interactive street &amp; satellite map.</p></div>'
            f'<div class="chip lime">{len(sched)} ROUNDS</div></div>'
            + worldmap)
    js = r"""
var PD=PAGE_DATA(), RACES=PD.races, CIRC=PD.circuits;
var COL={done:'#9b9ba8',next:'#27D45F',up:'#E10600'};
var MAP=null, trackLayer=null, currentRound=null;
function jumpTo(rnd){var el=document.getElementById('r'+rnd);if(el)el.scrollIntoView({behavior:'smooth',block:'center'});}
function scrollCards(dir){var el=document.getElementById('rcRow');if(el)el.scrollBy({left:dir*Math.max(280,el.clientWidth*0.8),behavior:'smooth'});}
function markCard(rnd){var row=document.getElementById('rcRow');if(!row)return;
  [].forEach.call(row.children,function(c){c.classList.toggle('on',+c.getAttribute('data-round')===+rnd);});}
function focusCard(rnd){var row=document.getElementById('rcRow'),c=document.getElementById('r'+rnd);
  if(!row||!c)return; row.scrollTo({left:c.offsetLeft-row.clientWidth/2+c.clientWidth/2,behavior:'smooth'});}

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

function cap(s){return (s||'').charAt(0).toUpperCase()+(s||'').slice(1);}
var ZC=['#E10600','#19C3B1','#F4D34A'];   // track zones Z1 / Z2 / Z3
function splitZones(coords){
  var n=coords.length; if(n<6) return [coords];
  function dist(a,b){var dy=a[0]-b[0],dx=(a[1]-b[1])*Math.cos(a[0]*Math.PI/180);return Math.sqrt(dx*dx+dy*dy);}
  var cum=[0]; for(var i=1;i<n;i++)cum.push(cum[i-1]+dist(coords[i-1],coords[i]));
  var tot=cum[n-1]||1, b1=tot/3, b2=2*tot/3, s=[[],[],[]];
  for(var i=0;i<n;i++){var z=cum[i]<=b1?0:(cum[i]<=b2?1:2); s[z].push(coords[i]);}
  if(s[1].length)s[0].push(s[1][0]); if(s[2].length)s[1].push(s[2][0]);
  return s;
}
function circPopup(c){
  return '<div class="cpop"><div class="caps">Round '+c.round+' · '+(c.date||'')+'</div>'
    +'<div class="cpop-t">'+c.name+'</div>'
    +'<div class="cpop-s">'+c.circuitName+' · '+(c.locality||'')+', '+c.country+'</div>'
    +'<div class="cpop-chips"><span class="chip lime">'+c.turns+' turns</span>'
    +'<span class="chip">'+c.drs+' DRS</span><span class="chip">~'+c.straight_m+'m</span>'
    +'<span class="chip dim">'+cap(c.type)+'</span></div>'
    +'<div class="caps" style="margin-top:9px">Track Zones</div>'
    +['s1','s2','s3'].map(function(k,i){return '<div class="cpop-z"><span class="zdot" style="background:'+ZC[i]+'"></span><b>Z'+(i+1)+'</b> '+c[k]+'</div>';}).join('')
    +'<div class="cpop-chips" style="margin-top:9px"><span class="chip">DF '+c.downforce+'</span>'
    +'<span class="chip">PWR '+c.power+'</span><span class="chip">Tyre '+c.tyre+'</span>'
    +'<span class="chip dim">Overtaking '+c.overtaking+'</span></div></div>';
}
function showCircuit(rnd, fly){
  var c=CIRC[rnd]; if(!c) return;
  currentRound=+rnd;
  markCard(rnd);
  if(fly) focusCard(rnd);
  if(!MAP) return;
  var coords=outlineLatLng(c);
  trackLayer.clearLayers();
  if(coords){
    L.polyline(coords,{color:'#0c0c12',weight:11,opacity:.92}).addTo(trackLayer);          // casing
    splitZones(coords).forEach(function(seg,i){ if(seg.length>1)
      L.polyline(seg,{color:ZC[i],weight:5,opacity:1}).addTo(trackLayer); });               // Z1/Z2/Z3
    L.circleMarker(coords[0],{radius:5,color:'#fff',weight:2,fillColor:'#27D45F',fillOpacity:1}).addTo(trackLayer);
  }
  if(fly!==false){
    if(coords) MAP.flyToBounds(L.latLngBounds(coords).pad(0.55), {duration:1.5});
    else MAP.flyTo([c.lat,c.lng], 11, {duration:1.5});
  }
  var at = coords ? coords[0] : [c.lat,c.lng];
  L.popup({maxWidth:290,autoClose:false,closeOnClick:false,autoPan:false,className:'circ-popup'})
    .setLatLng(at).setContent(circPopup(c)).openOn(MAP);
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
    showCircuit(PD.recent || PD.next || RACES[0].round, false);
    return;
  }
  var dark=L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
    {subdomains:'abcd', maxZoom:19, attribution:'© OpenStreetMap © CARTO'});
  var sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:19, attribution:'Imagery © Esri'});
  MAP=L.map('lmap',{layers:[sat],zoomSnap:.2,worldCopyJump:true}).setView([28,12],2.4);
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
  // default view: most recent race, zoomed in (satellite)
  var rr = PD.recent || PD.next || RACES[0].round;
  showCircuit(rr, false);
  var rc=CIRC[rr], rco=rc?outlineLatLng(rc):null;
  if(rco) MAP.fitBounds(L.latLngBounds(rco).pad(0.6));
  else if(rc) MAP.setView([rc.lat,rc.lng],11);
  focusCard(rr);
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
    standings = d["standings"]; drivers = standings["drivers"]
    careers = d.get("careers", {}); stats = d.get("stats", {})
    results, sprint, sched, quali = d["results"], d["sprint"], d["sched"], d["quali"]
    qmap = {(r["round"], q["driverId"]): q["pos"]
            for r in quali.get("2026", []) for q in r["results"]}
    photos = standings.get("photos", {}); dphotos = standings.get("driver_photos", {})
    def photo(num): return photos.get(str(num))

    # custom drop-in cockpit shots (same matcher as the dashboard FINALISTS cards)
    def _norm(s):
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        return "".join(ch for ch in s.lower() if ch.isalnum())
    _drv_dir = os.path.join(SITE, "assets", "drivers"); _drv_files = []
    if os.path.isdir(_drv_dir):
        for fn in os.listdir(_drv_dir):
            if fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")):
                _drv_files.append((_norm(os.path.splitext(fn)[0]), fn))
    def custom_img(x):
        fam = _norm(x["family"]); did = _norm(x["driverId"]); code = _norm(x.get("code") or "")
        for stem, fn in _drv_files:
            if (len(fam) >= 4 and fam in stem) or stem == did or (code and stem == code):
                return f"assets/drivers/{fn}"
        return None

    # official 2026 headshots from formula1.com/en/drivers — current team/livery for
    # every driver (the OpenF1/default headshots lag on team switches, e.g. Pérez still
    # in Red Bull). F1 serves full-body cutouts; the Cloudinary g_north crop trims them
    # to head-and-shoulders to match the existing format. driverId → "team/code".
    F1_HEADSHOT = {
        "antonelli": "mercedes/andant01", "russell": "mercedes/georus01",
        "hamilton": "ferrari/lewham01", "leclerc": "ferrari/chalec01",
        "norris": "mclaren/lannor01", "piastri": "mclaren/oscpia01",
        "max_verstappen": "redbullracing/maxver01", "hadjar": "redbullracing/isahad01",
        "gasly": "alpine/piegas01", "colapinto": "alpine/fracol01",
        "alonso": "astonmartin/feralo01", "stroll": "astonmartin/lanstr01",
        "hulkenberg": "audi/nichul01", "bortoleto": "audi/gabbor01",
        "perez": "cadillac/serper01", "bottas": "cadillac/valbot01",
        "ocon": "haas/estoco01", "bearman": "haas/olibea01",
        "lawson": "racingbulls/lialaw01", "arvid_lindblad": "racingbulls/arvlin01",
        "albon": "williams/alealb01", "sainz": "williams/carsai01",
    }
    def f1_headshot(p):
        t, c = p.split("/")
        return ("https://media.formula1.com/image/upload/c_fill,w_640,h_620,g_north/"
                f"q_auto/v1740000001/common/f1/2026/{t}/{c}/2026{t}{c}right.webp")
    def detail_photo(x):
        did = x["driverId"]
        if did in F1_HEADSHOT:
            return f1_headshot(F1_HEADSHOT[did])
        return photo(x.get("num")) or dphotos.get(did) or custom_img(x) or ""

    # 2026 per-round points (race + sprint), GPs and top-10s per driver
    def _fin(s):
        s = s or ""
        return s == "Finished" or s.startswith("+") or s == "Lapped"
    rnd_pts = {x["driverId"]: {} for x in drivers}
    gps26 = {x["driverId"]: 0 for x in drivers}; top26 = {x["driverId"]: 0 for x in drivers}
    inpts26 = {x["driverId"]: 0 for x in drivers}; dnf26 = {x["driverId"]: 0 for x in drivers}
    for race in results.get("2026", []):
        for res in race["results"]:
            did = res["driverId"]
            if did not in rnd_pts:
                continue
            rnd_pts[did][race["round"]] = rnd_pts[did].get(race["round"], 0) + (res.get("points") or 0)
            gps26[did] += 1
            if isinstance(res.get("pos"), int) and res["pos"] <= 10:
                top26[did] += 1
            if (res.get("points") or 0) > 0:
                inpts26[did] += 1
            if not _fin(res.get("status")):
                dnf26[did] += 1
    for race in sprint.get("2026", []):
        for res in race["results"]:
            did = res["driverId"]
            if did in rnd_pts:
                rnd_pts[did][race["round"]] = rnd_pts[did].get(race["round"], 0) + (res.get("points") or 0)
    rounds = [r["round"] for r in sched]

    # previous-season (2025) points-by-round → cumulative evolution overlay
    pts25 = {x["driverId"]: {} for x in drivers}
    for grp in (results.get("2025", []), sprint.get("2025", [])):
        for race in grp:
            for res in race["results"]:
                did = res["driverId"]
                if did in pts25:
                    pts25[did][race["round"]] = pts25[did].get(race["round"], 0) + (res.get("points") or 0)
    rounds25 = sorted({race["round"] for race in results.get("2025", [])})

    def _cum(rmap, rlist):
        out, c = [], 0
        for r in rlist:
            c += rmap.get(r, 0)
            out.append([r, round(c)])
        return out

    # inlined per-driver payload (career = historical ≤2025 + live 2026)
    DRV = {}
    for x in drivers:
        did = x["driverId"]; cid = x["constructorId"]
        h = careers.get(did) or {}; st = stats.get(did, {}).get("y2026", {})
        byr = [{"r": r, "p": round(rnd_pts[did].get(r, 0))} for r in rounds if r in rnd_pts[did]]
        career = {
            "debut": h.get("debut") or 2026, "last": 2026,
            "gps": (h.get("gps") or 0) + gps26[did],
            "points": round((h.get("points") or 0) + (x.get("points") or 0)),
            "wins": (h.get("wins") or 0) + (x.get("wins") or 0),
            "podiums": (h.get("podiums") or 0) + st.get("podiums", 0),
            "poles": (h.get("poles") or 0) + st.get("poles", 0),
            "top10s": (h.get("top10s") or 0) + top26[did],
        }
        s2026 = {"points": round(x.get("points") or 0), "wins": x.get("wins") or 0,
                 "podiums": st.get("podiums", 0), "poles": st.get("poles", 0), "gps": gps26[did]}
        perf = {"races": gps26[did], "wins": x.get("wins") or 0, "podiums": st.get("podiums", 0),
                "inpoints": inpts26[did], "dnf": dnf26[did]}
        qr = []
        for race in results.get("2026", []):
            res = next((r for r in race["results"] if r["driverId"] == did), None)
            if not res:
                continue
            rp = res["pos"] if isinstance(res["pos"], int) else None
            qr.append([qmap.get((race["round"], did)), rp])
        DRV[did] = {
            "given": x["given"], "family": x["family"], "code": x.get("code"),
            "team": short_team(x["constructor"]), "color": team_color(cid),
            "flag": flag(x["nationality"]), "nat": x["nationality"],
            "photo": detail_photo(x),
            "career": career, "s2026": s2026, "perf": perf, "qr": qr,
            "evo26": _cum(rnd_pts[did], sorted(rnd_pts[did].keys())),
            "evo25": _cum(pts25[did], rounds25), "cpos": x["pos"],
        }

    def card(x):
        did = x["driverId"]; cid = x["constructorId"]; cu = custom_img(x)
        if cu:
            bg = f'<img class="fin-bg cover" src="{esc(cu)}" alt="" loading="lazy">'
        else:
            u = photo(x.get("num")) or dphotos.get(did)
            bg = f'<img class="fin-bg" src="{esc(u)}" alt="" loading="lazy" onerror="this.remove()">' if u else ""
        return (f'<button class="fin-card driver drv-card" style="--c:{team_color(cid)}" '
                f'onclick="openDriver(\'{did}\')">{bg}<div class="fin-scrim"></div><div class="fin-bar"></div>'
                f'<div class="fin-place">P{x["pos"]}</div>'
                f'<div class="fin-top">{team_dot(cid)}{esc(short_team(x["constructor"]))}</div>'
                f'<div class="fin-pts">{x["points"]:.0f}<span>PTS</span></div>'
                f'<div class="fin-name">{flag(x["nationality"])} {esc(x["given"])} {esc(x["family"])}</div></button>')

    grid = '<div class="drv-grid">' + "".join(card(x) for x in drivers) + "</div>"
    modal = ('<div class="drv-modal" id="drv-modal" onclick="closeDriver(event)">'
             '<div class="drv-detail" id="drv-detail" onclick="event.stopPropagation()"></div></div>')
    body = ('<div class="page-head"><div><h1>Drivers</h1>'
            "<p>The 2026 grid — tap any driver for their career history and this season's form.</p></div>"
            f'<div class="chip lime">{len(drivers)} DRIVERS</div></div>' + grid + modal)

    js = r"""
var D=PAGE_DATA();
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;');}
var IC={
 win:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4zM7 6H4v2a3 3 0 0 0 3 3M17 6h3v2a3 3 0 0 1-3 3"/></svg>',
 pod:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 21h16M7 21v-7h4v7M11 14V9h4v12M15 21V5h4v16"/></svg>',
 pole:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1" fill="currentColor"/></svg>',
 top:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8M15 7h6v6"/></svg>'
};
function statRow(icon,val,label){
  return '<div class="dd-stat"><span class="dd-ic">'+icon+'</span><div class="dd-stxt">'
    +'<div class="dd-val">'+val+'</div><div class="dd-lab">'+label+'</div></div></div>';
}
function svg(w,h,inner){return '<svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="xMidYMid meet" class="dd-svg">'+inner+'</svg>';}
function mix(hex,f){hex=String(hex).replace('#','');if(hex.length===3)hex=hex.split('').map(function(c){return c+c;}).join('');
  var r=parseInt(hex.substr(0,2),16),g=parseInt(hex.substr(2,2),16),b=parseInt(hex.substr(4,2),16);
  r=Math.round(r+(255-r)*f);g=Math.round(g+(255-g)*f);b=Math.round(b+(255-b)*f);return 'rgb('+r+','+g+','+b+')';}
function ring(cx,cy,r,frac,color,w){var C=2*Math.PI*r;
  return '<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="'+w+'"/>'
   +'<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="'+color+'" stroke-width="'+w+'" stroke-linecap="round" stroke-dasharray="'+(frac*C).toFixed(1)+' '+C.toFixed(1)+'" transform="rotate(-90 '+cx+' '+cy+')"/>';}
function donutTriple(p,color){
  var races=p.races||1;
  var rg=[['Wins',p.wins,color],['Podiums',p.podiums,mix(color,.42)],['In Points',p.inpoints,mix(color,.7)],['DNF/DSQ',p.dnf,'#6b6b73']];
  var g='', cx=92, cy=98;
  rg.forEach(function(d,i){g+=ring(cx,cy,76-i*15,Math.min(1,d[1]/races),d[2],10);});
  rg.forEach(function(d,i){var y=44+i*30;
    g+='<rect x="184" y="'+(y-11)+'" width="11" height="11" rx="2" fill="'+d[2]+'"/>'
     +'<text x="202" y="'+(y-1)+'" class="dn-lab">'+d[0]+'</text>'
     +'<text x="300" y="'+(y-1)+'" class="dn-val" text-anchor="end">'+d[1]+'</text>';});
  return svg(312,196,g);
}
function donutPct(p,color){
  var races=p.races||1, frac=p.inpoints/races, cx=156, cy=98, r=64, C=2*Math.PI*r, w=18;
  var g='<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="'+w+'"/>'
   +'<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="'+color+'" stroke-width="'+w+'" stroke-linecap="round" stroke-dasharray="'+(frac*C).toFixed(1)+' '+C.toFixed(1)+'" transform="rotate(-90 '+cx+' '+cy+')"/>'
   +'<text x="'+cx+'" y="'+(cy+2)+'" class="dn-pct" text-anchor="middle">'+(frac*100).toFixed(1)+'%</text>'
   +'<text x="'+cx+'" y="'+(cy+22)+'" class="dn-sub" text-anchor="middle">'+p.inpoints+' / '+races+' races</text>';
  return svg(312,196,g);
}
function smooth(pts){if(pts.length<2)return pts.length?('M'+pts[0][0]+','+pts[0][1]):'';
  var d='M'+pts[0][0].toFixed(1)+','+pts[0][1].toFixed(1);
  for(var i=0;i<pts.length-1;i++){var p0=pts[i-1]||pts[i],p1=pts[i],p2=pts[i+1],p3=pts[i+2]||p2;
    var c1x=p1[0]+(p2[0]-p0[0])/6,c1y=p1[1]+(p2[1]-p0[1])/6,c2x=p2[0]-(p3[0]-p1[0])/6,c2y=p2[1]-(p3[1]-p1[1])/6;
    d+=' C'+c1x.toFixed(1)+','+c1y.toFixed(1)+' '+c2x.toFixed(1)+','+c2y.toFixed(1)+' '+p2[0].toFixed(1)+','+p2[1].toFixed(1);}
  return d;}
function evoLine(e26,e25,color){
  var W=336,H=196,L=34,R=12,T=26,B=24,pw=W-L-R,ph=H-T-B;
  var maxR=Math.max(e26.length?e26[e26.length-1][0]:1,e25.length?e25[e25.length-1][0]:1,2);
  var maxP=Math.max(e26.length?e26[e26.length-1][1]:0,e25.length?e25[e25.length-1][1]:0,1);
  function X(r){return L+pw*(r-1)/Math.max(1,maxR-1);}
  function Y(p){return T+ph*(1-p/maxP);}
  var g='';
  for(var i=0;i<=3;i++){var y=T+ph*i/3,v=maxP*(1-i/3);
    g+='<line x1="'+L+'" y1="'+y.toFixed(1)+'" x2="'+(W-R)+'" y2="'+y.toFixed(1)+'" stroke="rgba(255,255,255,.07)"/>'
     +'<text x="'+(L-5)+'" y="'+(y+3).toFixed(1)+'" class="dd-bx" text-anchor="end">'+Math.round(v)+'</text>';}
  if(e25.length>1) g+='<path d="'+smooth(e25.map(function(p){return [X(p[0]),Y(p[1])];}))+'" fill="none" stroke="#6b6b73" stroke-width="2" stroke-opacity=".85"/>';
  if(e26.length>1) g+='<path d="'+smooth(e26.map(function(p){return [X(p[0]),Y(p[1])];}))+'" fill="none" stroke="'+color+'" stroke-width="2.6"/>';
  g+='<rect x="'+L+'" y="8" width="10" height="10" rx="2" fill="'+color+'"/><text x="'+(L+15)+'" y="17" class="dd-bx">2026</text>'
   +'<rect x="'+(L+60)+'" y="8" width="10" height="10" rx="2" fill="#6b6b73"/><text x="'+(L+75)+'" y="17" class="dd-bx">2025</text>';
  return svg(W,H,g);
}
function sankeyAgg(qr,color){
  var BK=[['P1-3',1,3],['P4-6',4,6],['P7-10',7,10],['P11-15',11,15],['P16-20',16,22]];
  function bk(p){if(p==null)return 'DNF';for(var i=0;i<BK.length;i++)if(p>=BK[i][1]&&p<=BK[i][2])return BK[i][0];return 'P16-20';}
  var ORD=['P1-3','P4-6','P7-10','P11-15','P16-20','DNF'], idx={}; ORD.forEach(function(o,i){idx[o]=i;});
  var ql={},rl={},flows={},total=0;
  qr.forEach(function(p){if(p[0]==null)return;var qb=bk(p[0]),rb=bk(p[1]);
    ql[qb]=(ql[qb]||0)+1; rl[rb]=(rl[rb]||0)+1; flows[qb+'>'+rb]=(flows[qb+'>'+rb]||0)+1; total++;});
  if(!total) return '<div class="dd-nobars">No qualifying data yet.</div>';
  var W=336,H=196,T=22,B=10,Lx=64,Rx=W-64,nodeW=9;
  var qOrd=ORD.filter(function(o){return ql[o];}), rOrd=ORD.filter(function(o){return rl[o];});
  var gap=7, px=(H-T-B-gap*(Math.max(qOrd.length,rOrd.length)-1))/total;
  function lay(ord,cnt){var y=T,pos={};ord.forEach(function(o){var h=cnt[o]*px;pos[o]={y:y,h:h,off:0};y+=h+gap;});return pos;}
  var QP=lay(qOrd,ql), RP=lay(rOrd,rl);
  function col(a,b){return b<a?'#27D45F':(b>a?'#E1112A':'#3671C6');}
  var g='<text x="'+Lx+'" y="14" class="sk-h" text-anchor="end">Qualifying</text>'
   +'<text x="'+Rx+'" y="14" class="sk-h" text-anchor="start">Race</text>';
  qOrd.forEach(function(qb){rOrd.forEach(function(rb){var c=flows[qb+'>'+rb]; if(!c)return;
    var h=c*px, y0=QP[qb].y+QP[qb].off+h/2, y1=RP[rb].y+RP[rb].off+h/2; QP[qb].off+=h; RP[rb].off+=h;
    var x0=Lx+nodeW, x1=Rx-nodeW, cx=(x0+x1)/2;
    var d='M'+x0+','+(y0-h/2).toFixed(1)+' C'+cx+','+(y0-h/2).toFixed(1)+' '+cx+','+(y1-h/2).toFixed(1)+' '+x1+','+(y1-h/2).toFixed(1)
      +' L'+x1+','+(y1+h/2).toFixed(1)+' C'+cx+','+(y1+h/2).toFixed(1)+' '+cx+','+(y0+h/2).toFixed(1)+' '+x0+','+(y0+h/2).toFixed(1)+'Z';
    g+='<path d="'+d+'" fill="'+col(idx[qb],idx[rb])+'" fill-opacity="0.42"><title>Qual '+qb+' → Race '+rb+': '+c+' race'+(c>1?'s':'')+'</title></path>';});});
  qOrd.forEach(function(o){g+='<rect x="'+Lx+'" y="'+QP[o].y.toFixed(1)+'" width="'+nodeW+'" height="'+Math.max(2,QP[o].h).toFixed(1)+'" rx="2" fill="'+color+'"/>'
    +'<text x="'+(Lx-5)+'" y="'+(QP[o].y+QP[o].h/2+3).toFixed(1)+'" class="sk-l" text-anchor="end">'+o+' ('+ql[o]+')</text>';});
  rOrd.forEach(function(o){g+='<rect x="'+(Rx-nodeW)+'" y="'+RP[o].y.toFixed(1)+'" width="'+nodeW+'" height="'+Math.max(2,RP[o].h).toFixed(1)+'" rx="2" fill="'+(o==='DNF'?'#6b6b73':color)+'"/>'
    +'<text x="'+(Rx+5)+'" y="'+(RP[o].y+RP[o].h/2+3).toFixed(1)+'" class="sk-l" text-anchor="start">'+o+' ('+rl[o]+')</text>';});
  return svg(W,H,g);
}
function openDriver(did){
  var x=D[did]; if(!x)return; var c=x.career, s=x.s2026;
  var html='<button class="drv-close" onclick="closeDriver(event)">‹ Back</button>'
   +'<div class="dd-hero" style="background:linear-gradient(120deg,'+x.color+' -12%,#120d10 50%,#0a0a0e 100%)">'
   +'<div class="dd-info">'
   +'<div class="dd-name">'+esc(x.given)+' <span class="dd-fam" style="color:'+x.color+'">'+esc(x.family)+'</span></div>'
   +'<div class="dd-sub">'+x.flag+' '+esc(x.nat)+' · '+esc(x.team)+' <span class="dd-since">· since debut '+c.debut+'–'+c.last+'</span></div>'
   +'<div class="dd-bigrow"><div class="dd-big"><span>'+c.gps+'</span><small>GPs</small></div>'
   +'<div class="dd-big"><span>'+c.points.toLocaleString()+'</span><small>Career pts</small></div></div>'
   +'<div class="dd-grid">'
   + statRow(IC.win,c.wins,'Wins') + statRow(IC.pod,c.podiums,'Podiums')
   + statRow(IC.pole,c.poles,'Poles') + statRow(IC.top,c.top10s,'Top 10s')
   +'</div>'
   +'<div class="dd-2026"><span class="dd-2026-h">2026 Season</span>'
   +'<span class="dd-2026-row"><b>'+s.points+'</b> pts &nbsp;·&nbsp; <b>'+s.wins+'</b> wins &nbsp;·&nbsp; <b>'+s.podiums+'</b> podiums &nbsp;·&nbsp; <b>'+s.poles+'</b> poles</span></div>'
   +'</div>'
   + (x.photo?'<div class="dd-photo"><img src="'+esc(x.photo)+'" alt="" loading="lazy" onerror="this.parentNode.style.display=\'none\'"></div>':'')
   +'</div>'
   +'<div class="dd-charts"><div class="dd-section-h">Season Performance</div>'
   +'<div class="dd-chart"><div class="dd-ct">Results Breakdown</div>'+donutTriple(x.perf,x.color)+'</div>'
   +'<div class="dd-chart"><div class="dd-ct">Qualifying → Race</div>'+sankeyAgg(x.qr,x.color)+'</div>'
   +'<div class="dd-chart"><div class="dd-ct">Points Evolution vs 2025</div>'+evoLine(x.evo26,x.evo25,x.color)+'</div>'
   +'</div>';
  var det=document.getElementById('drv-detail'); det.innerHTML=html; det.scrollTop=0;
  document.getElementById('drv-modal').classList.add('open'); document.body.style.overflow='hidden';
}
function closeDriver(e){document.getElementById('drv-modal').classList.remove('open'); document.body.style.overflow='';}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeDriver();});
"""
    return page("PITWALL F1 · Drivers", "Drivers", body, data=DRV, js=js)


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
    d["race_analytics"] = _load_opt("race_analytics.json", {})
    d["careers"] = _load_opt("driver_careers.json", {})

    ctx = {"page": page, "esc": esc, "flag": flag, "dbadge": dbadge,
           "bar_row": bar_row, "team_color": team_color, "team_dot": team_dot,
           "line_chart": line_chart, "short_team": short_team, "C": C}

    # per-race analytics (Results tab) — extract any round missing from the
    # cache (incremental; FastF1). Existing rounds are skipped inside the script.
    completed = max((r["round"] for r in d["results"].get("2026", [])), default=0)
    have_ax = set(d["race_analytics"].keys())
    want_ax = {str(r["round"]) for r in d["results"].get("2026", [])}
    if want_ax - have_ax:
        print(f"» extracting race analytics for {sorted(want_ax - have_ax)} (f1_analytics)")
        try:
            import subprocess
            subprocess.run([sys.executable, os.path.join(HERE, "f1_analytics.py")],
                           check=True, timeout=3600)
            d["race_analytics"] = _load_opt("race_analytics.json", {})
        except Exception as e:  # noqa: BLE001 — keep whatever we already had
            print("   ! analytics extraction failed:", e)

    # live page = the f1-race-replay browser port, fed by the baked replay of
    # the latest Grand Prix (f1_prebake.py). Re-bake if it's stale.
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
                           '<meta http-equiv="refresh" content="0; url=dashboard.html">'
                           '<a href="dashboard.html">Standings are on the dashboard →</a>'),
        "drivers.html": build_drivers(d),
        "driver-stats.html": ('<!DOCTYPE html><meta charset="utf-8">'
                              '<meta http-equiv="refresh" content="0; url=dashboard.html">'
                              '<a href="dashboard.html">→ Dashboard</a>'),
        "prediction.html": build_prediction(d, ctx),
    }
    for name, html_str in pages.items():
        with open(os.path.join(SITE, name), "w") as f:
            f.write(html_str)
        print(f"   → site/{name}  ({len(html_str)//1024} KB)")
    print("✓ build complete →", SITE)


if __name__ == "__main__":
    main()
