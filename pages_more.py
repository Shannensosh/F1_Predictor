"""pages_more.py — results, standings, driver-stats, prediction pages.
Each builder takes (d, ctx) where ctx carries shared helpers from build.py."""

import json


# ═════════════════════════════════════════════════════════════════════════════
# Results
# ═════════════════════════════════════════════════════════════════════════════
def build_results(d, ctx):
    page, esc, team_color = ctx["page"], ctx["esc"], ctx["team_color"]
    team_dot, flag, short_team = ctx["team_dot"], ctx["flag"], ctx["short_team"]
    results, quali, sprint = d["results"], d["quali"], d["sprint"]
    standings, sched = d["standings"], d["sched"]
    analytics = d.get("race_analytics", {})
    drivers = standings["drivers"]
    code2did = {x["code"]: x["driverId"] for x in drivers}
    info_by_did = {x["driverId"]: x for x in drivers}

    def _is_finisher(st):
        return st == "Finished" or st.startswith("+") or st == "Lapped"

    def _disp(rr):
        st = rr.get("status") or ""
        pos, pt = rr.get("pos"), rr.get("posText")
        if pt == "W" or "not start" in st.lower():
            return "DNS", "dnf"
        if "disqualif" in st.lower():
            return "DSQ", "dnf"
        if not _is_finisher(st) or not isinstance(pos, int):
            return "RET", "dnf"
        return str(pos), "fin"

    def cell_pts(rr):
        """Race/Sprint cell: position text + points + colour kind."""
        text, kind = _disp(rr)
        pos, pts = rr.get("pos"), int(rr.get("points") or 0)
        if kind == "dnf":
            k = "dnf"
        elif isinstance(pos, int) and pos == 1:
            k = "win"
        elif isinstance(pos, int) and pos <= 3:
            k = "pod"
        elif pts > 0:
            k = "pts"
        else:
            k = "fin"
        c = {"t": text, "k": k}
        if pts > 0:
            c["p"] = pts
        return c

    def cell_pos(pos):
        """FP/Qualifying cell: classification position, no points."""
        if not isinstance(pos, int):
            return {"t": "–", "k": "none"}
        k = "win" if pos == 1 else "pod" if pos <= 3 else "pts" if pos <= 10 else "fin"
        return {"t": str(pos), "k": k}

    # ── matrix cells for every session category ─────────────────────────────
    cells = {"Race": {}, "Qualifying": {}, "Sprint": {}, "FP1": {}, "FP2": {}, "FP3": {}}
    for race in results.get("2026", []):
        cells["Race"][str(race["round"])] = {x["driverId"]: cell_pts(x) for x in race["results"]}
    for race in sprint.get("2026", []):
        cells["Sprint"][str(race["round"])] = {x["driverId"]: cell_pts(x) for x in race["results"]}
    for race in quali.get("2026", []):
        cells["Qualifying"][str(race["round"])] = {x["driverId"]: cell_pos(x["pos"]) for x in race["results"]}
    for rnd, b in analytics.items():
        for fpc, ranking in b.get("fp", {}).items():
            cells.setdefault(fpc, {})[rnd] = {}
            for code, pos in ranking:
                did = code2did.get(code)
                if did:
                    cells[fpc][rnd][did] = cell_pos(pos)

    mx = {
        "drivers": [{"did": x["driverId"], "code": x["code"], "fam": x["family"],
                     "color": team_color(x["constructorId"]), "cpos": x["pos"]} for x in drivers],
        "rounds": [{"r": r["round"], "flag": flag(r["country"]), "name": esc(r["name"]),
                    "sprint": bool(r.get("isSprint"))} for r in sched],
        "cells": cells,
    }

    # ── per-race analytics (charts) ─────────────────────────────────────────
    fin_by_round = {}
    for race in results.get("2026", []):
        fin_by_round[race["round"]] = {
            x["code"]: (x["pos"] if isinstance(x["pos"], int) else 99) for x in race["results"]}
    ax_rounds, ax_data = [], {}
    for rnd in sorted(analytics, key=int):
        b = analytics[rnd]
        fin = fin_by_round.get(int(rnd), {})
        adrv = []
        for code, rd in b.get("race", {}).items():
            did = code2did.get(code)
            inf = info_by_did.get(did) if did else None
            cid = inf["constructorId"] if inf else None
            adrv.append({
                "code": code,
                "fam": inf["family"] if inf else code,
                "team": short_team(inf["constructor"]) if inf else code,
                "cid": cid or code,
                "color": team_color(cid) if cid else "#888",
                "fin": fin.get(code, 99),
                "laps": rd.get("laps", []),
                "pos": rd.get("pos", []),
                "stints": rd.get("stints", []),
            })
        ax_data[rnd] = {"total_laps": b.get("total_laps", 0), "drivers": adrv}
        ax_rounds.append({"r": int(rnd), "name": esc(b.get("raceName", f"Round {rnd}"))})
    ax = {"rounds": ax_rounds, "data": ax_data}

    payload = {"mx": mx, "ax": ax}

    # ── page body ───────────────────────────────────────────────────────────
    cats = ["Race", "Qualifying", "Sprint", "FP1", "FP2", "FP3"]
    catseg = "".join(
        f'<button class="{"active" if c == "Race" else ""}" data-cat="{c}" '
        f'onclick="setCat(this)">{c}</button>' for c in cats)
    n_done = len(cells["Race"])
    legend = """
    <div class="rmx-legend">
      <span><i class="rc-win"></i>1st</span><span><i class="rc-pod"></i>Podium / top&nbsp;3</span>
      <span><i class="rc-pts"></i>Points / top&nbsp;10</span><span><i class="rc-fin"></i>Classified</span>
      <span><i class="rc-dnf"></i>RET / DNS</span>
      <span class="rmx-note">cell = finishing position · <sup>n</sup> = points (Race &amp; Sprint) ·
        “·S” marks a sprint round · hover for detail</span>
    </div>"""
    season = f"""
    <div class="sec-head"><h2>Season Results</h2>
      <div class="sec-sub">Every driver, every session · {n_done} of {len(sched)} rounds run</div></div>
    <div class="toolbar"><div class="seg" id="catseg">{catseg}</div></div>
    <div class="rmx-wrap" id="mxwrap"></div>
    {legend}"""

    ropts = "".join(f'<option value="{r["r"]}">R{r["r"]} · {r["name"]}</option>' for r in ax_rounds)
    analysis = f"""
    <div class="sec-head" style="margin-top:40px"><h2>Race Analysis</h2>
      <div class="sec-sub">Lap-time pace, on-track position swings and tyre strategy for any Grand Prix</div></div>
    <div class="toolbar"><select id="axsel" onchange="renderAX()">{ropts}</select></div>
    <div class="chart-grid">
      <div class="card-chart"><div class="ch-title">Lap Time Distribution · Top 10</div><div class="ch-host" id="ch-box"></div></div>
      <div class="card-chart"><div class="ch-title">Race Position Changes</div><div class="ch-host" id="ch-pos"></div></div>
    </div>
    <div class="card-chart"><div class="ch-title">Team Pace · Median Lap</div><div class="ch-host" id="ch-pace"></div></div>
    <div class="card-chart"><div class="ch-title">Tyre Strategies</div>
      <div class="tyre-key">
        <span><i style="background:#E1112A"></i>Soft</span><span><i style="background:#F3D34A"></i>Medium</span>
        <span><i style="background:#E6E6E6"></i>Hard</span><span><i style="background:#42A65A"></i>Inter</span>
        <span><i style="background:#3A74D0"></i>Wet</span></div>
      <div class="ch-host" id="ch-tyre"></div></div>"""

    body = ('<div class="page-head"><div><h1>Results</h1>'
            '<p>Every driver and every session of the 2026 season — finishing positions and points, '
            'then a per-race breakdown of pace, position changes and tyre strategy.</p></div></div>'
            + season + analysis)

    js = r"""
var D=PAGE_DATA(), MX=D.mx, AX=D.ax, CAT='Race';

/* ---------- season matrix ---------- */
function setCat(b){CAT=b.dataset.cat;[].forEach.call(b.parentNode.children,function(x){x.classList.toggle('active',x===b);});renderMatrix();}
function cellHTML(c){
  if(!c) return '<td class="rc rc-none">–</td>';
  var sup=(c.p!=null)?'<sup>'+c.p+'</sup>':'';
  return '<td class="rc rc-'+c.k+'">'+c.t+sup+'</td>';
}
function renderMatrix(){
  var cells=MX.cells[CAT]||{}, hasPts=(CAT==='Race'||CAT==='Sprint');
  var head=MX.rounds.map(function(r){
    return '<th class="rmx-race'+(r.sprint?' sprint':'')+'" title="R'+r.r+' · '+r.name+'">'
      +'<span class="rmx-fl">'+r.flag+'</span><span class="rmx-rnd">R'+r.r+(r.sprint?'·S':'')+'</span></th>';
  }).join('');
  var ptsH=hasPts?'<th class="rmx-pts-h">Pts</th>':'';
  var body=MX.drivers.map(function(d){
    var tot=0;
    var tds=MX.rounds.map(function(r){var c=(cells[r.r]||{})[d.did]; if(c&&c.p)tot+=c.p; return cellHTML(c);}).join('');
    var ptsC=hasPts?'<td class="rmx-pts">'+tot+'</td>':'';
    return '<tr><td class="rmx-drv"><span class="pos">'+d.cpos+'</span>'
      +'<span class="teamdot" style="--c:'+d.color+'"></span><b>'+d.code+'</b>'
      +'<span class="rmx-sur">'+d.fam+'</span></td>'+tds+ptsC+'</tr>';
  }).join('');
  document.getElementById('mxwrap').innerHTML=
    '<table class="results-matrix"><thead><tr><th class="rmx-drv-h">Driver</th>'+head+ptsH
    +'</tr></thead><tbody>'+body+'</tbody></table>';
}

/* ---------- chart helpers ---------- */
function quart(a){a=a.slice().sort(function(x,y){return x-y;});var n=a.length;
  function q(p){var i=(n-1)*p,lo=Math.floor(i),hi=Math.ceil(i);return a[lo]+(a[hi]-a[lo])*(i-lo);}
  var q1=q(.25),med=q(.5),q3=q(.75),iqr=q3-q1,loF=q1-1.5*iqr,hiF=q3+1.5*iqr;
  var inl=a.filter(function(x){return x>=loF&&x<=hiF;});
  return {q1:q1,med:med,q3:q3,wlo:inl.length?inl[0]:a[0],whi:inl.length?inl[inl.length-1]:a[n-1],
          out:a.filter(function(x){return x<loF||x>hiF;})};}
function svg(w,h,inner){return '<svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="xMidYMid meet" class="ch-svg">'+inner+'</svg>';}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');}

/* ---------- box chart (drivers / teams) ---------- */
function boxChart(elId, groups){
  var el=document.getElementById(elId);
  if(!groups.length){el.innerHTML='<div class="ch-empty">No lap data.</div>';return;}
  var W=Math.max(700, groups.length*82+96), H=400, L=58, R=18, T=16, B=64;
  var all=[]; groups.forEach(function(g){all.push(g.stats.wlo,g.stats.whi); g.stats.out.forEach(function(o){all.push(o);});});
  var lo=Math.min.apply(null,all), hi=Math.max.apply(null,all), pad=(hi-lo)*0.08||1; lo-=pad; hi+=pad;
  var pw=W-L-R, ph=H-T-B;
  function Y(v){return T+ph*(1-(v-lo)/(hi-lo));}
  var g='';
  for(var i=0;i<=5;i++){var v=lo+(hi-lo)*i/5,y=Y(v);
    g+='<line x1="'+L+'" y1="'+y+'" x2="'+(W-R)+'" y2="'+y+'" class="ch-grid"/>';
    g+='<text x="'+(L-8)+'" y="'+(y+3)+'" class="ch-ylab" text-anchor="end">'+v.toFixed(1)+'</text>';}
  var bw=Math.min(44, pw/groups.length*0.5);
  groups.forEach(function(gr,idx){
    var cx=L+pw*(idx+0.5)/groups.length, s=gr.stats, c=gr.color;
    g+='<line x1="'+cx+'" y1="'+Y(s.wlo)+'" x2="'+cx+'" y2="'+Y(s.whi)+'" class="ch-whisk"/>';
    g+='<line x1="'+(cx-bw*0.3)+'" y1="'+Y(s.wlo)+'" x2="'+(cx+bw*0.3)+'" y2="'+Y(s.wlo)+'" class="ch-whisk"/>';
    g+='<line x1="'+(cx-bw*0.3)+'" y1="'+Y(s.whi)+'" x2="'+(cx+bw*0.3)+'" y2="'+Y(s.whi)+'" class="ch-whisk"/>';
    g+='<rect x="'+(cx-bw/2)+'" y="'+Y(s.q3)+'" width="'+bw+'" height="'+Math.max(1,Y(s.q1)-Y(s.q3))+'" fill="'+c+'" fill-opacity="0.34" stroke="'+c+'"/>';
    g+='<line x1="'+(cx-bw/2)+'" y1="'+Y(s.med)+'" x2="'+(cx+bw/2)+'" y2="'+Y(s.med)+'" stroke="#fff" stroke-width="2"/>';
    s.out.forEach(function(o){g+='<circle cx="'+cx+'" cy="'+Y(o)+'" r="2.3" fill="'+c+'" fill-opacity="0.85"/>';});
    g+='<text x="'+cx+'" y="'+(H-B+20)+'" class="ch-xlab" text-anchor="middle" transform="rotate(35 '+cx+' '+(H-B+20)+')">'+esc(gr.label)+'</text>';
  });
  g+='<text x="15" y="'+(T+ph/2)+'" class="ch-axtitle" transform="rotate(-90 15 '+(T+ph/2)+')" text-anchor="middle">Lap Time (s)</text>';
  el.innerHTML=svg(W,H,g);
}

/* ---------- race position chart ---------- */
function posChart(elId, drivers, totalLaps){
  var el=document.getElementById(elId);
  var maxP=20; drivers.forEach(function(d){d.pos.forEach(function(p){if(p[1]>maxP)maxP=p[1];});});
  var W=Math.max(720, totalLaps*15+150), H=440, L=42, R=124, T=14, B=40;
  var pw=W-L-R, ph=H-T-B, span=Math.max(1,totalLaps-1);
  function X(l){return L+pw*(l-1)/span;}
  function Y(p){return T+ph*(p-1)/(maxP-1);}
  var g='';
  for(var p=1;p<=maxP;p+=(maxP>20?5:5)){var y=Y(p);
    g+='<line x1="'+L+'" y1="'+y+'" x2="'+(W-R)+'" y2="'+y+'" class="ch-grid"/>';
    g+='<text x="'+(L-6)+'" y="'+(y+3)+'" class="ch-ylab" text-anchor="end">'+p+'</text>';}
  for(var l=10;l<=totalLaps;l+=10){var x=X(l);
    g+='<line x1="'+x+'" y1="'+T+'" x2="'+x+'" y2="'+(H-B)+'" class="ch-grid"/>';
    g+='<text x="'+x+'" y="'+(H-B+16)+'" class="ch-xlab" text-anchor="middle">'+l+'</text>';}
  drivers.forEach(function(d){
    if(!d.pos.length)return;
    var pts=d.pos.map(function(p){return X(p[0]).toFixed(1)+','+Y(p[1]).toFixed(1);}).join(' ');
    g+='<polyline points="'+pts+'" fill="none" stroke="'+d.color+'" stroke-width="1.6" stroke-opacity="0.92"/>';
    var last=d.pos[d.pos.length-1];
    g+='<text x="'+(X(last[0])+5)+'" y="'+(Y(last[1])+3)+'" class="ch-tag" fill="'+d.color+'">'+d.code+'</text>';
  });
  g+='<text x="'+(L+pw/2)+'" y="'+(H-3)+'" class="ch-axtitle" text-anchor="middle">Lap</text>';
  el.innerHTML=svg(W,H,g);
}

/* ---------- tyre strategy gantt ---------- */
var TYRE={SOFT:'#E1112A',MEDIUM:'#F3D34A',HARD:'#E6E6E6',INTERMEDIATE:'#42A65A',WET:'#3A74D0'};
function tyreTxt(c){return (c==='HARD'||c==='MEDIUM')?'#15151E':'#fff';}
function tyreChart(elId, drivers, totalLaps){
  var rows=drivers.filter(function(d){return d.stints.length;}).sort(function(a,b){return a.fin-b.fin;});
  var rowH=22, gap=6, L=52, R=18, T=10, B=30, W=1010;
  var ph=rows.length*(rowH+gap), H=T+ph+B, pw=W-L-R;
  function X(l){return L+pw*l/Math.max(1,totalLaps);}
  var g='';
  for(var l=0;l<=totalLaps;l+=6){var x=X(l);
    g+='<line x1="'+x+'" y1="'+T+'" x2="'+x+'" y2="'+(T+ph)+'" class="ch-grid"/>';
    g+='<text x="'+x+'" y="'+(T+ph+16)+'" class="ch-xlab" text-anchor="middle">'+l+'</text>';}
  rows.forEach(function(d,i){
    var y=T+i*(rowH+gap);
    g+='<text x="'+(L-8)+'" y="'+(y+rowH*0.7)+'" class="ch-row" text-anchor="end">'+d.code+'</text>';
    d.stints.forEach(function(s){
      var c=s[0], x0=X(s[1]-1), w=X(s[2])-x0, col=TYRE[c]||'#777', n=s[2]-s[1]+1;
      g+='<rect x="'+x0.toFixed(1)+'" y="'+y+'" width="'+Math.max(1,w).toFixed(1)+'" height="'+rowH+'" rx="3" fill="'+col+'"/>';
      if(w>40) g+='<text x="'+(x0+w/2).toFixed(1)+'" y="'+(y+rowH*0.68)+'" class="ch-stint" fill="'+tyreTxt(c)+'" text-anchor="middle">'+(s[1]-1)+'-'+s[2]+' ('+n+')</text>';
    });
  });
  document.getElementById(elId).innerHTML=svg(W,H,g);
}

/* ---------- per-race orchestration ---------- */
function renderAX(){
  var rd=document.getElementById('axsel').value, R=AX.data[rd];
  if(!R){return;}
  var drv=R.drivers;
  var top=drv.filter(function(d){return d.laps&&d.laps.length>=3;}).sort(function(a,b){return a.fin-b.fin;}).slice(0,10);
  boxChart('ch-box', top.map(function(d){return {label:d.code,color:d.color,stats:quart(d.laps)};}));
  posChart('ch-pos', drv, R.total_laps);
  var teams={};
  drv.forEach(function(d){ if(!d.laps||!d.laps.length||!d.cid)return;
    if(!teams[d.cid]) teams[d.cid]={laps:[],color:d.color,name:d.team};
    teams[d.cid].laps=teams[d.cid].laps.concat(d.laps);});
  var tg=Object.keys(teams).map(function(k){return {label:teams[k].name,color:teams[k].color,stats:quart(teams[k].laps)};})
    .sort(function(a,b){return a.stats.med-b.stats.med;});
  boxChart('ch-pace', tg);
  tyreChart('ch-tyre', drv, R.total_laps);
}

renderMatrix();
var sel=document.getElementById('axsel');
if(sel&&sel.options.length){sel.value=sel.options[sel.options.length-1].value; renderAX();}
"""
    return page("PITWALL F1 · Results", "Results", body, data=payload, js=js)


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
