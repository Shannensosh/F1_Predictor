"""pages_more.py — results, standings, driver-stats, prediction pages.
Each builder takes (d, ctx) where ctx carries shared helpers from build.py."""

import json


# ═════════════════════════════════════════════════════════════════════════════
# Results
# ═════════════════════════════════════════════════════════════════════════════
def build_results(d, ctx):
    page, esc, team_color = ctx["page"], ctx["esc"], ctx["team_color"]
    results, quali, sprint = d["results"], d["qualifying"] if "qualifying" in d else d["quali"], d["sprint"]
    standings = d["standings"]
    colors = {x["constructorId"]: team_color(x["constructorId"]) for x in standings["drivers"]}

    def index_round(arr):
        return {str(r["round"]): r for r in arr}

    payload = {
        "race": index_round(results.get("2026", [])),
        "quali": index_round(quali.get("2026", [])),
        "sprint": index_round(sprint.get("2026", [])),
        "colors": colors,
    }
    rounds = sorted(payload["race"].keys(), key=int)
    sprint_rounds = set(payload["sprint"].keys())
    opts = "".join(
        f'<option value="{r}">R{r} · {esc(payload["race"][r]["raceName"])}'
        f'{" (Sprint)" if r in sprint_rounds else ""}</option>'
        for r in rounds)

    toolbar = f"""
    <div class="toolbar">
      <select id="rsel" onchange="render()">{opts}</select>
      <div class="seg" id="catseg">
        <button class="active" data-c="race" onclick="setCat(this)">Race</button>
        <button data-c="quali" onclick="setCat(this)">Qualifying</button>
        <button data-c="sprint" onclick="setCat(this)">Sprint</button>
      </div>
      <input id="flt" type="search" placeholder="Filter driver…" oninput="render()" style="flex:1;min-width:160px">
    </div>
    <div id="rwrap" class="tbl-wrap"></div>
    <div class="note" id="rnote" style="margin-top:10px"></div>"""

    # ── season aggregates (wins / podiums / poles / fastest laps) ───────────
    team_dot, line_chart = ctx["team_dot"], ctx["line_chart"]
    team_color = ctx["team_color"]
    agg = {x["driverId"]: {"wins": 0, "pod": 0, "pole": 0, "fl": 0} for x in standings["drivers"]}
    for race in d["results"].get("2026", []):
        for res in race["results"]:
            a = agg.get(res["driverId"])
            if not a:
                continue
            if isinstance(res["pos"], int):
                if res["pos"] == 1: a["wins"] += 1
                if res["pos"] <= 3: a["pod"] += 1
            if str(res.get("fastestRank")) == "1": a["fl"] += 1
    for race in (d["quali"] if "quali" in d else d["qualifying"]).get("2026", []):
        for q in race["results"]:
            if q["pos"] == 1 and q["driverId"] in agg:
                agg[q["driverId"]]["pole"] += 1

    def _top(metric, label):
        best = max(standings["drivers"], key=lambda x: agg[x["driverId"]][metric])
        v = agg[best["driverId"]][metric]
        return (f'<div class="card kpi"><span class="k-label">{label}</span>'
                f'<span class="k-val sm">{esc(best["family"])}</span>'
                f'<span class="k-sub">{team_dot(best["constructorId"])}{v}</span></div>')
    leader = standings["drivers"][0]
    tiles = (f'<div class="grid g4">'
             f'<div class="card kpi glow"><span class="k-label">Championship Leader</span>'
             f'<span class="k-val sm">{esc(leader["family"])}</span>'
             f'<span class="k-sub">{team_dot(leader["constructorId"])}{leader["points"]:.0f} pts</span></div>'
             + _top("wins", "Most Wins") + _top("pod", "Most Podiums")
             + _top("fl", "Most Fastest Laps") + "</div>")

    drows = "".join(
        f'<tr><td><span class="pos pos-{x["pos"] if x["pos"]<=3 else 0}">{x["pos"]}</span></td>'
        f'<td>{team_dot(x["constructorId"])}<b>{esc(x["code"])}</b> {esc(x["family"])}</td>'
        f'<td>{esc(x["constructor"])}</td>'
        f'<td class="num">{agg[x["driverId"]]["wins"]}</td>'
        f'<td class="num">{agg[x["driverId"]]["pod"]}</td>'
        f'<td class="num">{agg[x["driverId"]]["pole"]}</td>'
        f'<td class="num">{agg[x["driverId"]]["fl"]}</td>'
        f'<td class="num"><b>{x["points"]:.0f}</b></td></tr>'
        for x in standings["drivers"])
    crows = "".join(
        f'<tr><td><span class="pos pos-{x["pos"] if x["pos"]<=3 else 0}">{x["pos"]}</span></td>'
        f'<td>{team_dot(x["constructorId"])}<b>{esc(x["name"])}</b></td>'
        f'<td class="num">{x["wins"]}</td><td class="num"><b>{x["points"]:.0f}</b></td></tr>'
        for x in standings["constructors"])

    top8 = standings["drivers"][:8]
    series = [{"name": x["code"], "color": team_color(x["constructorId"]),
               "pts": d["evo"].get(x["driverId"], [])} for x in top8 if d["evo"].get(x["driverId"])]
    chart = line_chart(d["evo_rounds"], series)

    standings_html = f"""
    <div id="standings"></div>
    {tiles}
    <div class="grid g2" style="margin-top:14px;align-items:start">
      <div><div class="sec-title">Drivers' Championship</div>
        <div class="tbl-wrap"><table><thead><tr><th>Pos</th><th>Driver</th><th>Team</th>
        <th class="num" title="Wins">W</th><th class="num" title="Podiums">Pod</th>
        <th class="num" title="Poles">PP</th><th class="num" title="Fastest laps">FL</th>
        <th class="num">Pts</th></tr></thead><tbody>{drows}</tbody></table></div></div>
      <div><div class="sec-title">Constructors' Championship</div>
        <div class="tbl-wrap"><table><thead><tr><th>Pos</th><th>Constructor</th>
        <th class="num">Wins</th><th class="num">Pts</th></tr></thead><tbody>{crows}</tbody></table></div>
        <div class="sec-title">Points Evolution · Top 8</div>
        <div class="card card-pad">{chart}</div></div>
    </div>"""

    body = ('<div class="page-head"><div><h1>Results &amp; Standings</h1>'
            '<p>The championship picture and every 2026 session in one place — standings with '
            'wins, podiums, poles and fastest laps, plus the full results browser.</p></div></div>'
            + standings_html
            + '<div class="sec-title">Session Results</div>'
            + toolbar)

    js = r"""
var D=PAGE_DATA(),CAT='race';
function setCat(btn){CAT=btn.dataset.c;[].forEach.call(btn.parentNode.children,function(b){b.classList.toggle('active',b===btn)});render();}
function dot(cid){return '<span class="teamdot" style="--c:'+(D.colors[cid]||'#888')+'"></span>';}
function posCls(p){return (p>=1&&p<=3)?('pos pos-'+p):'pos';}
function render(){
  var rd=document.getElementById('rsel').value, flt=document.getElementById('flt').value.toLowerCase();
  var src=D[CAT], race=src[rd], wrap=document.getElementById('rwrap'), note=document.getElementById('rnote');
  if(!race||!race.results||!race.results.length){wrap.innerHTML='';note.textContent='No '+CAT+' data for this round.';return;}
  note.textContent='';
  var head,rowf;
  if(CAT==='quali'){
    head='<th>Pos</th><th>Driver</th><th>Team</th><th class="num">Q1</th><th class="num">Q2</th><th class="num">Q3</th>';
    rowf=function(r){return '<td><span class="'+posCls(r.pos)+'">'+r.pos+'</span></td>'
      +'<td>'+dot(r.constructorId)+'<b>'+r.code+'</b> '+r.given+' '+r.family+'</td>'
      +'<td>'+r.constructor+'</td>'
      +'<td class="num">'+(r.q1||'–')+'</td><td class="num">'+(r.q2||'–')+'</td><td class="num">'+(r.q3||'–')+'</td>';};
  } else if(CAT==='sprint'){
    head='<th>Pos</th><th>Driver</th><th>Team</th><th class="num">Grid</th><th>Status</th><th class="num">Pts</th>';
    rowf=function(r){return '<td><span class="'+posCls(r.pos)+'">'+r.posText+'</span></td>'
      +'<td>'+dot(r.constructorId)+'<b>'+r.code+'</b> '+r.given+' '+r.family+'</td>'
      +'<td>'+r.constructor+'</td><td class="num">'+(r.grid==null?'–':r.grid)+'</td>'
      +'<td>'+(r.status||'')+'</td><td class="num">'+(r.points||0)+'</td>';};
  } else {
    head='<th>Pos</th><th>Driver</th><th>Team</th><th class="num">Grid</th><th class="num">Laps</th><th>Time / Status</th><th class="num">Pts</th><th class="num">Fastest</th>';
    rowf=function(r){return '<td><span class="'+posCls(r.pos)+'">'+r.posText+'</span></td>'
      +'<td>'+dot(r.constructorId)+'<b>'+r.code+'</b> '+r.given+' '+r.family+'</td>'
      +'<td>'+r.constructor+'</td><td class="num">'+(r.grid==null?'–':r.grid)+'</td>'
      +'<td class="num">'+(r.laps==null?'–':r.laps)+'</td>'
      +'<td>'+(r.time||r.status||'')+'</td><td class="num">'+(r.points||0)+'</td>'
      +'<td class="num">'+(r.fastestLap||'–')+'</td>';};
  }
  var rows=race.results.filter(function(r){return !flt||((r.family+' '+r.given+' '+r.code).toLowerCase().indexOf(flt)>=0);})
    .map(function(r){return '<tr>'+rowf(r)+'</tr>';}).join('');
  // fixed layout + shared colgroup → Pos/Driver/Team align across all three tabs
  var cg='<colgroup><col style="width:54px"><col style="width:32%"><col style="width:20%"></colgroup>';
  wrap.innerHTML='<table style="table-layout:fixed">'+cg+'<thead><tr>'+head+'</tr></thead><tbody>'+rows+'</tbody></table>';
}
document.getElementById('rsel').value=document.getElementById('rsel').options[document.getElementById('rsel').options.length-1].value;
render();
"""
    return page("PITWALL F1 · Results & Standings", "Results", body, data=payload, js=js)


# ═════════════════════════════════════════════════════════════════════════════
# Standings
# ═════════════════════════════════════════════════════════════════════════════
def build_standings(d, ctx):
    page, esc, team_dot = ctx["page"], ctx["esc"], ctx["team_dot"]
    team_color, line_chart, dbadge = ctx["team_color"], ctx["line_chart"], ctx["dbadge"]
    standings = d["standings"]
    dr, cons = standings["drivers"], standings["constructors"]

    drows = "".join(
        f'<tr><td><span class="pos pos-{x["pos"] if x["pos"]<=3 else 0}">{x["pos"]}</span></td>'
        f'<td>{team_dot(x["constructorId"])}<b>{esc(x["code"])}</b> {esc(x["given"])} {esc(x["family"])}</td>'
        f'<td>{esc(x["constructor"])}</td>'
        f'<td class="num">{x["wins"]}</td><td class="num"><b>{x["points"]:.0f}</b></td></tr>'
        for x in dr)
    crows = "".join(
        f'<tr><td><span class="pos pos-{x["pos"] if x["pos"]<=3 else 0}">{x["pos"]}</span></td>'
        f'<td>{team_dot(x["constructorId"])}<b>{esc(x["name"])}</b></td>'
        f'<td class="num">{x["wins"]}</td><td class="num"><b>{x["points"]:.0f}</b></td></tr>'
        for x in cons)

    # evolution chart — top 8 drivers by current points
    top = sorted(dr, key=lambda x: x["points"], reverse=True)[:8]
    series = [{"name": x["code"], "color": team_color(x["constructorId"]),
               "pts": d["evo"].get(x["driverId"], [])} for x in top if d["evo"].get(x["driverId"])]
    chart = line_chart(d["evo_rounds"], series)

    body = f"""
    <div class="page-head"><div><h1>Standings</h1>
    <p>Drivers' and Constructors' Championships, plus how the points race has evolved
    round-by-round.</p></div></div>
    <div class="sec-title">Points Evolution · Top 8</div>
    <div class="card card-pad">{chart}</div>
    <div class="grid g2" style="margin-top:20px;align-items:start">
      <div><div class="sec-title">Drivers' Championship</div>
        <div class="tbl-wrap"><table><thead><tr><th>Pos</th><th>Driver</th><th>Team</th>
        <th class="num">Wins</th><th class="num">Pts</th></tr></thead><tbody>{drows}</tbody></table></div></div>
      <div><div class="sec-title">Constructors' Championship</div>
        <div class="tbl-wrap"><table><thead><tr><th>Pos</th><th>Constructor</th>
        <th class="num">Wins</th><th class="num">Pts</th></tr></thead><tbody>{crows}</tbody></table></div></div>
    </div>"""
    return page("PITWALL F1 · Standings", "Standings", body)


# ═════════════════════════════════════════════════════════════════════════════
# Driver stats
# ═════════════════════════════════════════════════════════════════════════════
def build_stats(d, ctx):
    page, esc, team_color = ctx["page"], ctx["esc"], ctx["team_color"]
    stats, standings = d["stats"], d["standings"]
    rows = []
    for x in standings["drivers"]:
        st = stats[x["driverId"]]
        rows.append({
            "code": x["code"], "name": f'{x["given"]} {x["family"]}',
            "team": x["constructor"], "color": team_color(x["constructorId"]),
            "num": x.get("num"),
            "y2026": st["y2026"], "all": st["all"],
        })

    # highlight tiles (2026)
    def leader(metric, fmt, lo=False, key="y2026"):
        valid = [r for r in rows if r[key].get(metric) is not None and r[key]["races"]]
        if not valid:
            return ("–", "")
        best = min(valid, key=lambda r: r[key][metric]) if lo else max(valid, key=lambda r: r[key][metric])
        return (fmt(best[key][metric]), best["code"])
    w_val, w_who = leader("wins", lambda v: f"{v}")
    p_val, p_who = leader("podiums", lambda v: f"{v}")
    pole_val, pole_who = leader("poles", lambda v: f"{v}")
    comp_val, comp_who = leader("completion", lambda v: f"{v:.0f}%")
    tiles = f"""
    <div class="grid g4">
      <div class="card kpi glow"><span class="k-label">Most Wins · 2026</span>
        <span class="k-val">{w_val}</span><span class="k-sub">{w_who}</span></div>
      <div class="card kpi"><span class="k-label">Most Podiums</span>
        <span class="k-val">{p_val}</span><span class="k-sub">{p_who}</span></div>
      <div class="card kpi"><span class="k-label">Most Poles</span>
        <span class="k-val">{pole_val}</span><span class="k-sub">{pole_who}</span></div>
      <div class="card kpi"><span class="k-label">Best Completion</span>
        <span class="k-val">{comp_val}</span><span class="k-sub">{comp_who}</span></div>
    </div>"""

    body = f"""
    <div class="page-head"><div><h1>Driver Statistics</h1>
    <p>Race completion, wins, podiums, poles, retirements and average finish. Toggle between
    the 2026 season and the 2024–26 aggregate; click a column to sort.</p></div></div>
    {tiles}
    <div class="toolbar" style="margin-top:18px">
      <div class="seg" id="modeseg">
        <button class="active" data-m="y2026" onclick="setMode(this)">2026 Season</button>
        <button data-m="all" onclick="setMode(this)">2024–26</button>
      </div>
      <input id="sflt" type="search" placeholder="Filter driver…" oninput="srender()" style="flex:1;min-width:160px">
    </div>
    <div id="swrap" class="tbl-wrap"></div>"""

    js = r"""
var S=PAGE_DATA(),MODE='y2026',SORT='points',DIR=-1;
function setMode(btn){MODE=btn.dataset.m;[].forEach.call(btn.parentNode.children,function(b){b.classList.toggle('active',b===btn)});srender();}
function sortBy(k){if(SORT===k)DIR=-DIR;else{SORT=k;DIR=-1;}srender();}
var COLS=[['code','Driver',0],['team','Team',0],['races','R',1],['wins','Wins',1],
  ['podiums','Podiums',1],['poles','Poles',1],['dnf','DNF',1],['completion','Finish %',1],
  ['avg_finish','Avg Fin',1],['ppr','Pts/Race',1],['points','Pts',1]];
function val(r,k){if(k==='code'||k==='team')return r[k];return r[MODE][k];}
function srender(){
  var flt=document.getElementById('sflt').value.toLowerCase();
  var data=S.filter(function(r){return !flt||(r.name+' '+r.code).toLowerCase().indexOf(flt)>=0;});
  data.sort(function(a,b){var x=val(a,SORT),y=val(b,SORT);if(x==null)x=-1;if(y==null)y=-1;
    return (x<y?-1:x>y?1:0)*DIR;});
  var head=COLS.map(function(c){return '<th class="'+(c[2]?'num':'')+'" style="cursor:pointer" onclick="sortBy(\''+c[0]+'\')">'+c[1]+(SORT===c[0]?(DIR<0?' ▾':' ▴'):'')+'</th>';}).join('');
  var body=data.map(function(r){var m=r[MODE];
    return '<tr><td><span class="teamdot" style="--c:'+r.color+'"></span><b>'+r.code+'</b></td>'
      +'<td>'+r.team+'</td><td class="num">'+m.races+'</td><td class="num">'+m.wins+'</td>'
      +'<td class="num">'+m.podiums+'</td><td class="num">'+m.poles+'</td>'
      +'<td class="num">'+m.dnf+'</td><td class="num">'+(m.completion!=null?m.completion+'%':'–')+'</td>'
      +'<td class="num">'+(m.avg_finish!=null?m.avg_finish:'–')+'</td>'
      +'<td class="num">'+m.ppr+'</td><td class="num"><b>'+m.points.toFixed(0)+'</b></td></tr>';}).join('');
  document.getElementById('swrap').innerHTML='<table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table>';
}
srender();
"""
    return page("PITWALL F1 · Driver Stats", "Stats", body, data=rows, js=js)


# ═════════════════════════════════════════════════════════════════════════════
# Prediction
# ═════════════════════════════════════════════════════════════════════════════
def build_prediction(d, ctx):
    page, esc, bar_row = ctx["page"], ctx["esc"], ctx["bar_row"]
    team_color, flag = ctx["team_color"], ctx["flag"]
    p = d["preds"]
    nr, drivers, cons = p["next_race"], p["drivers"], p["constructors"]
    m = p["model"]
    tr = nr["circuit_traits"]

    header = f"""
    <div class="card glow card-pad" style="display:grid;grid-template-columns:1fr auto;gap:18px;align-items:center">
      <div><div class="caps">Next race · Round {nr['round']}</div>
        <h2 style="font-size:24px;font-weight:800;margin:6px 0 2px">{flag(nr['country'])} {esc(nr['name'])}</h2>
        <div class="muted">{esc(nr['circuitName'])} · {esc(nr['date'])} · {esc(tr['type'].title())} circuit</div>
        <div class="flex gap8 wrap-f" style="margin-top:12px">
          <span class="chip lime">Downforce {tr['downforce']}</span>
          <span class="chip">Power {tr['power']}</span>
          <span class="chip">Tyre stress {tr['tyre_stress']}</span>
          <span class="chip dim">Overtaking {tr['overtaking']}</span>
        </div></div>
      <div class="center"><div class="caps">Pole favourite</div>
        <div style="font-family:'Titillium Web';font-weight:800;font-size:22px;color:var(--lime)">{esc(drivers[0]['name'].split()[-1])}</div>
        <div class="mono" style="font-size:26px">{drivers[0]['win_pct']:.0f}%</div></div>
    </div>"""

    # ── weather forecast + wet-pace factor ──────────────────────────────────
    fc = p.get("forecast"); rw = p.get("rain_weight", 0) or 0
    _wmo = {0: ("Clear", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"),
            3: ("Overcast", "☁️"), 45: ("Fog", "🌫️"), 48: ("Fog", "🌫️"),
            51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Drizzle", "🌧️"),
            61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
            80: ("Rain showers", "🌦️"), 81: ("Showers", "🌧️"), 82: ("Heavy showers", "⛈️"),
            95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm", "⛈️"), 99: ("Thunderstorm", "⛈️")}
    if fc and fc.get("in_range"):
        cond, icon = _wmo.get(fc.get("wcode"), ("—", "🌡️"))
        rainy = rw > 0
        wet_top = sorted(drivers, key=lambda x: -x["wet_skill"])[:6]
        def _wadj(x):
            if not rainy:
                return f'{x["wet_skill"]}'
            pct = (x["wet_factor"] - 1) * 100
            return f'{x["wet_skill"]} · {"+" if pct >= 0 else ""}{pct:.1f}%'
        wet_rows = "".join(
            f'<div class="barrow"><span class="blabel">{esc(x["name"].split()[-1])}</span>'
            f'<span class="bar"><i style="width:{x["wet_skill"]:.0f}%;background:{team_color(x["constructorId"])}"></i></span>'
            f'<span class="bval">{_wadj(x)}</span></div>'
            for x in wet_top)
        status_chip = (f'<span class="chip amber">🌧️ Wet adjustment ACTIVE · rain weight {rw:.2f}</span>'
                       if rainy else '<span class="chip green">Dry forecast — no wet adjustment</span>')
        weather_panel = f"""
        <div class="grid g2" style="margin-top:14px;align-items:start">
          <div class="card"><div class="sec-title" style="margin-top:0">Race-Day Forecast · {esc(p['next_race']['name'].replace(' Grand Prix',''))}</div>
            <div class="flex gap16 ac wrap-f">
              <div style="font-size:40px">{icon}</div>
              <div><div style="font-family:'Titillium Web';font-weight:700;font-size:18px">{esc(cond)}</div>
                <div class="muted mono" style="font-size:12px">{esc(fc.get('date',''))} · forecast (Open-Meteo)</div></div>
            </div>
            <div class="flex gap8 wrap-f" style="margin-top:12px">
              <span class="chip">🌡️ {fc.get('tmax','–')}° / {fc.get('tmin','–')}°</span>
              <span class="chip {'amber' if (fc.get('precip_prob') or 0)>=40 else 'dim'}">🌧️ {fc.get('precip_prob','–')}% rain</span>
              <span class="chip dim">💨 {fc.get('wind','–')} km/h</span>
            </div>
            <div style="margin-top:12px">{status_chip}</div>
            <div class="note" style="margin-top:10px">When rain is likely, a curated driver <b>wet-skill</b> swings the
              next-race odds — strong wet drivers gain, weaker ones lose, scaled by the rain probability.</div>
          </div>
          <div class="card"><div class="sec-title" style="margin-top:0">Wet-Weather Pace (curated){' · live adjustment' if rainy else ''}</div>
            {wet_rows}</div>
        </div>"""
    else:
        weather_panel = (f'<div class="note" style="margin-top:14px">🌡️ Race-day forecast for '
                         f'{esc(p["next_race"]["name"])} isn\'t available yet (more than ~16 days out). '
                         f'Wet-pace adjustment will activate automatically once the forecast is in range.</div>')

    # next-race win% + podium bars
    wmax = drivers[0]["win_pct"] or 1
    win_bars = "".join(
        f'<div class="barrow"><span class="blabel">{flag("")}{esc(x["name"].split()[-1])}</span>'
        f'<span class="bar"><i style="width:{(x["win_pct"]/wmax*100):.0f}%;background:{team_color(x["constructorId"])}"></i></span>'
        f'<span class="bval">{x["win_pct"]:.1f}%</span></div>'
        for x in drivers if x["win_pct"] >= 0.05)
    pod_bars = "".join(
        f'<div class="barrow"><span class="blabel">{esc(x["name"].split()[-1])}</span>'
        f'<span class="bar green"><i style="width:{min(100,x["podium_pct"]):.0f}%"></i></span>'
        f'<span class="bval">{x["podium_pct"]:.0f}%</span></div>'
        for x in sorted(drivers, key=lambda x: -x["podium_pct"])[:10])

    # title bars
    title_sorted = sorted(drivers, key=lambda x: -x["title_pct"])
    tmax = title_sorted[0]["title_pct"] or 1
    title_bars = "".join(
        f'<div class="barrow"><span class="blabel"><b>{esc(x["name"].split()[-1])}</b> '
        f'<span class="muted mono" style="font-size:10px">{x["current_points"]:.0f}p</span></span>'
        f'<span class="bar"><i style="width:{(x["title_pct"]/tmax*100):.0f}%;background:{team_color(x["constructorId"])}"></i></span>'
        f'<span class="bval">{x["title_pct"]:.1f}%</span></div>'
        for x in title_sorted if x["title_pct"] >= 0.05)
    cmax = cons[0]["title_pct"] or 1
    cons_bars = "".join(
        f'<div class="barrow"><span class="blabel">{esc(x["name"])}</span>'
        f'<span class="bar"><i style="width:{(x["title_pct"]/cmax*100):.0f}%;background:{team_color(x["constructorId"])}"></i></span>'
        f'<span class="bval">{x["title_pct"]:.1f}%</span></div>'
        for x in cons if x["title_pct"] >= 0.05)

    grids = f"""
    <div class="grid g2" style="margin-top:20px;align-items:start">
      <div class="card"><div class="sec-title" style="margin-top:0">{esc(nr['name'])} · Win Probability</div>{win_bars}</div>
      <div class="card"><div class="sec-title" style="margin-top:0">Podium Probability</div>{pod_bars}</div>
    </div>
    <div class="grid g2" style="margin-top:14px;align-items:start">
      <div class="card"><div class="sec-title" style="margin-top:0">2026 Drivers' Title</div>{title_bars}</div>
      <div class="card"><div class="sec-title" style="margin-top:0">2026 Constructors' Title</div>{cons_bars}</div>
    </div>"""

    # factor breakdown (expandable per driver)
    def fitfmt(v): return ("+" if v >= 0 else "") + f"{v*100:.1f}"
    # ── factor catalogue (self-documenting, from the model metadata) ────────
    src_cls = {"real": "green", "curated": "amber", "mixed": "lime", "model": "dim"}
    src_txt = {"real": "REAL DATA", "curated": "CURATED EST.", "mixed": "MIXED", "model": "MODEL"}
    kind_txt = {"base": "Base rating", "multiplier": "Per-race ×", "sim": "Simulation"}
    cat_cards = "".join(
        f"""<div class="card">
          <div class="flex jb ac" style="margin-bottom:6px">
            <span style="font-family:'Titillium Web';font-weight:700;font-size:14px">{esc(fa['label'])}</span>
            <span class="chip {src_cls.get(fa['source'],'dim')}">{src_txt.get(fa['source'],fa['source'].upper())}</span>
          </div>
          <div class="flex gap8 wrap-f" style="margin-bottom:8px">
            <span class="chip dim">{esc(kind_txt.get(fa['kind'],fa['kind']))}</span>
            {f'<span class="chip lime">weight {fa["weight"]*100:.0f}%</span>' if fa.get('weight') else ''}
            <span class="chip dim">{esc(fa['data'])}</span>
          </div>
          <div class="muted" style="font-size:12px;line-height:1.45">{esc(fa['desc'])}</div>
        </div>"""
        for fa in m["factors"])
    catalogue = (f'<div class="sec-title">Factors used by the model</div>'
                 f'<p class="muted" style="font-size:12.5px;margin:-4px 0 12px">'
                 f'Four <b>base factors</b> form each driver\'s Power Rating (weights sum to 100%). '
                 f'Two <b>per-race multipliers</b> then adjust it for the specific circuit, and a '
                 f'simulation shock adds season-long uncertainty. Source badges show real API data vs '
                 f'curated estimates.</p>'
                 f'<div class="grid g3">{cat_cards}</div>')

    # ── per-driver breakdown ─────────────────────────────────────────────────
    wts = m["weights"]
    nr_short = esc(nr["name"].replace(" Grand Prix", ""))
    details = []
    for x in drivers[:14]:
        fp = x["fit_parts"]
        trk = (f'{x["track_avg_finish"]:.1f} avg finish'
               if x["track_avg_finish"] is not None else "no prior history")
        parts_html = " · ".join(
            f'{lbl} {fitfmt(fp[k])}' for k, lbl in
            [("downforce", "downforce"), ("power", "power"), ("tyre", "tyre"),
             ("weight", "weight"), ("balance", "balance")])
        details.append(f"""
        <details class="card" style="margin-bottom:8px">
          <summary style="cursor:pointer;display:flex;align-items:center;gap:12px;list-style:none">
            <span class="teamdot" style="--c:{team_color(x['constructorId'])}"></span>
            <b>{esc(x['name'])}</b><span class="muted" style="font-size:12px">{esc(x['constructor'])}</span>
            <span style="margin-left:auto" class="chip lime">{x['win_pct']:.1f}% win</span>
            <span class="chip green">{x['podium_pct']:.0f}% podium</span>
            <span class="chip">{x['title_pct']:.1f}% title</span>
          </summary>
          <div style="margin-top:12px">
            <div class="caps" style="margin-bottom:6px">Base power rating = {x['rating']:.3f} (weighted sum)</div>
            {bar_row(f"Form ×{wts['form']:.2f}", x["form_n"], f'+{x["contrib"]["form"]*100:.0f}')}
            {bar_row(f"Qualifying ×{wts['quali']:.2f}", x["quali_n"], f'P{x["avg_grid"]:.0f}')}
            {bar_row(f"Reliability ×{wts['reliability']:.2f}", x["rel"], f'+{x["contrib"]["reliability"]*100:.0f}')}
            {bar_row(f"Car index ×{wts['car']:.2f}", x["car_n"], f'+{x["contrib"]["car"]*100:.0f}')}
            <div class="divider"></div>
            <div class="caps" style="margin-bottom:6px">Per-race multipliers · {nr_short}</div>
            <div class="flex gap8 wrap-f" style="font-size:12px">
              <span class="chip {'green' if x['fit']>=1 else 'red'}">Circuit fit {fitfmt(x['fit']-1)}%</span>
              <span class="chip {'green' if x['track_factor']>=1 else 'red'}">Track history {fitfmt(x['track_factor']-1)}%</span>
              <span class="chip dim">{trk}</span>
              <span class="chip dim">Balance: {esc(x['balance'])}</span>
              <span class="chip dim">~{x['weight_kg']} kg</span>
            </div>
            <div class="muted" style="font-size:11px;margin-top:8px">Circuit-fit parts — {parts_html}</div>
            <div class="divider"></div>
            <div class="flex gap8 wrap-f" style="font-size:12px">
              <span class="chip lime">Race strength {x['race_strength']:.3f}</span>
              <span class="chip dim">= rating {x['rating']:.3f} × fit {x['fit']:.3f} × history {x['track_factor']:.3f}</span>
              <span class="chip dim">Exp. pts here {x['exp_next_pts']:.1f}</span>
            </div>
          </div>
        </details>""")

    methodology = f"""
    <div class="sec-title">How the numbers are produced</div>
    <div class="card card-pad">
      <p style="font-size:13.5px">For each driver a <b>Power Rating</b> is the weighted sum of the four base
      factors above. For every one of the {p['remaining_count']} remaining rounds that rating is multiplied
      by <b>circuit fit</b> and <b>track history</b> to get a per-race <b>strength</b>. A Plackett–Luce /
      Gumbel simulator then runs the whole rest of the season <b>{m['n_sims']:,} times</b> — sampling a
      finishing order each race (plus retirements and a season-long form shock) — and counts how often each
      driver wins the next race and the title.</p>
      <div class="grid g4" style="margin-top:14px">
        <div class="card kpi"><span class="k-label">Simulations</span><span class="k-val sm">{m['n_sims']:,}</span><span class="k-sub">full seasons</span></div>
        <div class="card kpi"><span class="k-label">Remaining races</span><span class="k-val sm">{p['remaining_count']}</span><span class="k-sub">rounds left</span></div>
        <div class="card kpi"><span class="k-label">Circuit / history</span><span class="k-val sm">±{m['track_factor_max']*100:.0f}%</span><span class="k-sub">per-race nudge</span></div>
        <div class="card kpi"><span class="k-label">Decisiveness β</span><span class="k-val sm">{m['beta']}</span><span class="k-sub">favourite strength</span></div>
      </div>
      <p class="muted" style="font-size:12px;margin-top:14px">
        Recency weighting: 2026 races count ×{m['season_weight']['2026']:.2f}, 2025 ×{m['season_weight']['2025']:.2f},
        2024 ×{m['season_weight']['2024']:.2f}; within a season weight halves every {m['recency_halflife']:.0f} races.
        Retirement chance per race = (1 − reliability). Season form shock σ = {m['season_shock']}.
      </p>
    </div>
    <div class="disclaimer">⚠️ <b>Educational / entertainment model.</b> Real data (results, qualifying,
    reliability, standings) drives the ratings; car downforce, weight and handling balance are
    <b>curated approximations</b> (no public API exposes them) and are labelled as estimates throughout.
    Probabilities are model outputs, not predictions of fact. <b>Not betting advice.</b></div>"""

    body = ('<div class="page-head"><div><h1>Prediction Engine</h1>'
            '<p>Win probability for the next Grand Prix and the 2026 title race — transparent, '
            'recency-weighted, and Monte-Carlo simulated.</p></div></div>'
            + header + weather_panel + grids
            + catalogue
            + '<div class="sec-title">Driver Factor Breakdown</div>'
            + '<p class="muted" style="font-size:12.5px;margin:-4px 0 12px">Click a driver to see how '
              'their rating is built and adjusted for ' + nr_short + '.</p>'
            + "".join(details)
            + methodology)
    return page("PITWALL F1 · Prediction", "Prediction", body)
