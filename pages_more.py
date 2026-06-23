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
    res_by_round = {r["round"]: r for r in results.get("2026", [])}
    quali_by_round = {q["round"]: q for q in quali.get("2026", [])}
    fin_by_round = {rno: {x["code"]: (x["pos"] if isinstance(x["pos"], int) else 99)
                          for x in r["results"]} for rno, r in res_by_round.items()}

    def race_overview(rno):
        race = res_by_round.get(rno)
        if not race:
            return None
        rows = race["results"]
        p1 = next((x for x in rows if x["pos"] == 1), None)
        p2 = next((x for x in rows if x["pos"] == 2), None)
        fl = next((x for x in rows if str(x.get("fastestRank")) == "1"), None)
        q = quali_by_round.get(rno, {})
        pole = next((x for x in (q.get("results") or []) if x["pos"] == 1), None)
        mover = None
        for x in rows:
            if isinstance(x["pos"], int) and x.get("grid"):
                gain = x["grid"] - x["pos"]
                if mover is None or gain > mover[0]:
                    mover = (gain, x["code"])
        dnf = [x for x in rows if not _is_finisher(x.get("status") or "")]
        total = len(rows)
        won_pole = bool(p1 and pole and p1["code"] == pole["code"])
        return {
            "winner": p1["code"] if p1 else "—",
            "winnerTeam": short_team(p1["constructor"]) if p1 else "",
            "winnerColor": team_color(p1["constructorId"]) if p1 else "#888",
            "wonFrom": (p1.get("grid") if p1 else None),
            "pole": pole["code"] if pole else "—",
            "poleColor": team_color(pole["constructorId"]) if pole else "#888",
            "poleNote": ("Converted to win" if won_pole else "Lost the lead") if pole else "No qualifying",
            "margin": (p2.get("time") if (p2 and p2.get("time")) else "—"),
            "fl": fl["code"] if fl else "—",
            "flColor": team_color(fl["constructorId"]) if fl else "#888",
            "flTime": (fl.get("fastestLap") or "") if fl else "",
            "mover": mover[1] if mover else "—",
            "moverGain": mover[0] if mover else 0,
            "dnfs": len(dnf), "classified": total - len(dnf), "total": total,
        }

    def progression(rno):
        race = res_by_round.get(rno)
        if not race:
            return []
        qpos = {x["code"]: x["pos"] for x in (quali_by_round.get(rno, {}).get("results") or [])}
        out = []
        for x in race["results"]:
            if not isinstance(x["pos"], int):
                continue
            out.append({"code": x["code"], "color": team_color(x["constructorId"]),
                        "q": qpos.get(x["code"]), "g": (x.get("grid") or None), "r": x["pos"]})
        return out

    def _median(a):
        if not a:
            return None
        s = sorted(a); n = len(s); m = n // 2
        return s[m] if n % 2 else (s[m - 1] + s[m]) / 2

    def _stdev(a):
        if len(a) < 2:
            return 0.0
        mu = sum(a) / len(a)
        return (sum((x - mu) ** 2 for x in a) / len(a)) ** 0.5

    def radar_round(rno, adrv):
        """Five 0–100 driver-performance metrics, scaled across the race field."""
        qpos = {x["code"]: x["pos"] for x in (quali_by_round.get(rno, {}).get("results") or [])}
        grid = {x["code"]: x.get("grid") for x in res_by_round.get(rno, {}).get("results", [])}
        N = len(res_by_round.get(rno, {}).get("results", [])) or 20
        meds, stds, gains, slen = {}, {}, {}, {}
        for x in adrv:
            if x["laps"]:
                meds[x["code"]] = _median(x["laps"]); stds[x["code"]] = _stdev(x["laps"])
            g = grid.get(x["code"])
            if g and isinstance(x["fin"], int) and x["fin"] <= N:
                gains[x["code"]] = g - x["fin"]
            if x["stints"]:
                tot = x["stints"][-1][2] - x["stints"][0][1] + 1
                slen[x["code"]] = tot / len(x["stints"])

        def scale(dct, code, invert=False, lo=42):
            if code not in dct or len(dct) < 2:
                return 50.0
            vals = list(dct.values()); mn, mx = min(vals), max(vals)
            if mx == mn:
                return 100.0
            f = (dct[code] - mn) / (mx - mn)
            if invert:
                f = 1 - f
            return round(lo + (100 - lo) * f, 1)
        out = {}
        for x in adrv:
            c = x["code"]
            out[c] = {
                "pace": scale(meds, c, invert=True),
                "consistency": scale(stds, c, invert=True),
                "qualifying": round(100 - 70 * ((qpos.get(c, N) - 1) / max(1, N - 1)), 1) if qpos.get(c) else 50.0,
                "racecraft": scale(gains, c),
                "tiremgmt": scale(slen, c),
            }
        return out

    ax_rounds, ax_data = [], {}
    for rnd in sorted(analytics, key=int):
        b = analytics[rnd]
        rno = int(rnd)
        fin = fin_by_round.get(rno, {})
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
                "lapseq": rd.get("lapseq", []),
                "sectors": rd.get("sectors", []),
                "topspeed": rd.get("topspeed"),
                "pos": rd.get("pos", []),
                "stints": rd.get("stints", []),
            })
        ax_data[rnd] = {"total_laps": b.get("total_laps", 0), "drivers": adrv,
                        "ov": race_overview(rno), "prog": progression(rno),
                        "radar": radar_round(rno, adrv)}
        ax_rounds.append({"r": rno, "name": esc(b.get("raceName", f"Round {rnd}"))})
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
    <div class="res-freeze">
      <div class="sec-head"><h2>Season Results</h2>
        <div class="sec-sub">Every driver, every session · {n_done} of {len(sched)} rounds run</div></div>
      <div class="toolbar"><div class="seg" id="catseg">{catseg}</div></div>
    </div>
    <div class="rmx-wrap" id="mxwrap"></div>
    {legend}"""

    ropts = "".join(f'<option value="{r["r"]}">R{r["r"]} · {r["name"]}</option>' for r in ax_rounds)
    tyre_key = """<div class="tyre-key">
        <span><i style="background:#E1112A"></i>Soft</span><span><i style="background:#F3D34A"></i>Medium</span>
        <span><i style="background:#E6E6E6"></i>Hard</span><span><i style="background:#42A65A"></i>Inter</span>
        <span><i style="background:#3A74D0"></i>Wet</span></div>"""
    prog_key = """<div class="tyre-key">
        <span><i style="background:#27D45F"></i>Gained</span><span><i style="background:#3671C6"></i>Maintained</span>
        <span><i style="background:#E1112A"></i>Lost</span></div>"""
    analysis = f"""
    <div class="res-freeze">
      <div class="sec-head"><h2>Race Analysis</h2>
        <div class="sec-sub">Race summary, on-track swings, pace and tyre strategy for any Grand Prix</div></div>
      <div class="toolbar"><select id="axsel" onchange="renderAX()">{ropts}</select></div>
    </div>

    <div class="ana-sec">Race Summary</div>
    <div class="ov-grid" id="ov-grid"></div>

    <div class="ana-sec">Positions</div>
    <div class="chart-grid">
      <div class="card-chart" data-zoom><div class="ch-title">Race Position Changes</div><div class="ch-host" id="ch-pos"></div></div>
      <div class="card-chart" data-zoom><div class="ch-title">Qualifying to Race · Position Updates</div>{prog_key}<div class="ch-host" id="ch-prog"></div></div>
    </div>

    <div class="ana-sec">Pacing</div>
    <div class="chart-grid">
      <div class="card-chart" data-zoom><div class="ch-title">Lap Time Distribution · Top 10</div><div class="ch-host" id="ch-box"></div></div>
      <div class="card-chart" data-zoom><div class="ch-title">Team Pace · Median Lap</div><div class="ch-host" id="ch-pace"></div></div>
    </div>

    <div class="ana-sec">Tyre</div>
    <div class="chart-grid">
      <div class="card-chart" data-zoom><div class="ch-title">Tyre Strategies</div>{tyre_key}<div class="ch-host" id="ch-tyre"></div></div>
      <div class="card-chart" data-zoom><div class="ch-title">Tyre Age vs Optimal Life</div>
        <div class="tyre-key"><span><i class="tk-solid"></i>Laps run</span>
          <span><i class="tk-dash"></i>Optimal life</span><span><i style="background:#ff2e2e"></i>Beyond optimal</span>
          <span class="rmx-note" style="margin-left:auto">Soft ~20 · Medium ~30 · Hard ~42 laps (indicative)</span></div>
        <div class="ch-host" id="ch-tyreage"></div></div>
    </div>

    <div class="ana-sec" style="margin-top:34px">Top 3 Drivers</div>
    <div class="chart-grid">
      <div class="card-chart" data-zoom><div class="ch-title">Driver Performance Radar</div><div class="ch-host" id="ch-radar"></div></div>
      <div class="card-chart"><div class="ch-title">Session Bests</div><div class="ch-host t3-table-host" id="t3-table"></div></div>
    </div>
    <div class="card-chart" data-zoom><div class="ch-title">Lap Time Evolution</div><div class="ch-host" id="ch-evo"></div></div>
    <div class="chart-grid">
      <div class="card-chart" data-zoom><div class="ch-title">Sector Time Comparison</div><div class="ch-host" id="ch-sector"></div></div>
      <div class="card-chart" data-zoom><div class="ch-title">Tyre Temp vs Lap Time</div>
        <div class="tyre-key"><span class="rmx-note">Tyre temperature is a modelled estimate (compound · stint age · pace) — not measured telemetry</span></div>
        <div class="ch-host" id="ch-ttemp"></div></div>
    </div>

    <div class="ch-modal" id="ch-modal" onclick="closeZoom(event)">
      <div class="ch-modal-inner" onclick="event.stopPropagation()">
        <div class="ch-modal-bar"><span id="ch-modal-title"></span>
          <button class="ch-close" onclick="closeZoom(event)">✕ Close</button></div>
        <div class="ch-modal-host" id="ch-modal-host"></div></div>
    </div>"""

    body = ('<div class="page-head"><div><h1>Results</h1>'
            '<p>Every driver and every session of the 2026 season — finishing positions and points, '
            'then a per-race breakdown: race summary, position changes, pace and tyre strategy.</p></div></div>'
            '<section class="res-sec">' + season + '</section>'
            '<section class="res-sec">' + analysis + '</section>')

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
  var W=900, H=480, L=56, R=56, T=16, B=72;
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
    g+='<rect x="'+(cx-bw/2)+'" y="'+Y(s.q3)+'" width="'+bw+'" height="'+Math.max(1,Y(s.q1)-Y(s.q3))+'" fill="'+c+'" fill-opacity="0.34" stroke="'+c+'"><title>'+esc(gr.label)+' — median '+s.med.toFixed(2)+'s · Q1 '+s.q1.toFixed(2)+' / Q3 '+s.q3.toFixed(2)+'</title></rect>';
    g+='<line x1="'+(cx-bw/2)+'" y1="'+Y(s.med)+'" x2="'+(cx+bw/2)+'" y2="'+Y(s.med)+'" stroke="#fff" stroke-width="2"/>';
    s.out.forEach(function(o){g+='<circle cx="'+cx+'" cy="'+Y(o)+'" r="2.3" fill="'+c+'" fill-opacity="0.85"/>';});
    g+='<text x="'+cx+'" y="'+(H-B+26)+'" class="ch-xlab" text-anchor="middle" transform="rotate(35 '+cx+' '+(H-B+26)+')">'+esc(gr.label)+'</text>';
  });
  g+='<text x="15" y="'+(T+ph/2)+'" class="ch-axtitle" transform="rotate(-90 15 '+(T+ph/2)+')" text-anchor="middle">Lap Time (s)</text>';
  el.innerHTML=svg(W,H,g);
}

/* ---------- race position chart ---------- */
function posChart(elId, drivers, totalLaps){
  var el=document.getElementById(elId);
  var maxP=20; drivers.forEach(function(d){d.pos.forEach(function(p){if(p[1]>maxP)maxP=p[1];});});
  var W=900, H=480, L=56, R=56, T=16, B=72;
  var pw=W-L-R, ph=H-T-B, span=Math.max(1,totalLaps-1);
  function X(l){return L+pw*(l-1)/span;}
  function Y(p){return T+ph*(p-1)/(maxP-1);}
  var g='';
  for(var p=1;p<=maxP;p+=(maxP>20?5:5)){var y=Y(p);
    g+='<line x1="'+L+'" y1="'+y+'" x2="'+(W-R)+'" y2="'+y+'" class="ch-grid"/>';
    g+='<text x="'+(L-6)+'" y="'+(y+3)+'" class="ch-ylab" text-anchor="end">'+p+'</text>';}
  for(var l=10;l<=totalLaps;l+=10){var x=X(l);
    g+='<line x1="'+x+'" y1="'+T+'" x2="'+x+'" y2="'+(H-B)+'" class="ch-grid"/>';
    g+='<text x="'+x+'" y="'+(H-B+20)+'" class="ch-xlab" text-anchor="middle">'+l+'</text>';}
  drivers.forEach(function(d){
    if(!d.pos.length)return;
    var pts=d.pos.map(function(p){return X(p[0]).toFixed(1)+','+Y(p[1]).toFixed(1);}).join(' ');
    var last=d.pos[d.pos.length-1];
    g+='<polyline points="'+pts+'" fill="none" stroke="'+d.color+'" stroke-width="1.6" stroke-opacity="0.92"><title>'+d.code+' — finished P'+last[1]+'</title></polyline>';
    g+='<text x="'+(X(last[0])+5)+'" y="'+(Y(last[1])+3)+'" class="ch-tag" fill="'+d.color+'">'+d.code+'</text>';
  });
  g+='<text x="'+(L+pw/2)+'" y="'+(H-B+44)+'" class="ch-axtitle" text-anchor="middle">Lap</text>';
  el.innerHTML=svg(W,H,g);
}

/* ---------- tyre data + helpers ---------- */
var TYRE={SOFT:'#E1112A',MEDIUM:'#F3D34A',HARD:'#E6E6E6',INTERMEDIATE:'#42A65A',WET:'#3A74D0'};
var TYRE_GRAD={SOFT:['#4a0c14','#ff3b4b','#4a0c14'],MEDIUM:['#4a3e0a','#ffe24a','#4a3e0a'],
 HARD:['#2c2c2c','#ffffff','#2c2c2c'],INTERMEDIATE:['#0e2e16','#4fd070','#0e2e16'],WET:['#0c1e3e','#4f8fe6','#0c1e3e']};
var TYRE_OPT={SOFT:20,MEDIUM:30,HARD:42,INTERMEDIATE:28,WET:32};   // indicative optimal life (laps)
var STOPW=['ZERO','ONE','TWO','THREE','FOUR','FIVE','SIX'];
function tyreTxt(c){return (c==='HARD'||c==='MEDIUM')?'#15151E':'#fff';}
function tyreDefs(){var s='<defs>';for(var k in TYRE_GRAD){var v=TYRE_GRAD[k];
  s+='<linearGradient id="tg-'+k+'" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="'+v[0]+'"/>'
    +'<stop offset="0.5" stop-color="'+v[1]+'"/><stop offset="1" stop-color="'+v[2]+'"/></linearGradient>';}
  return s+'</defs>';}
function wheel(cx,cy,r,ring){
  var s='<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="#0c0c12" stroke="'+ring+'" stroke-width="'+(r*0.36).toFixed(1)+'"/>'
   +'<circle cx="'+cx+'" cy="'+cy+'" r="'+(r*0.3).toFixed(1)+'" fill="#3a3a44"/>';
  for(var k=0;k<6;k++){var a=k*Math.PI/3;
    s+='<line x1="'+cx+'" y1="'+cy+'" x2="'+(cx+Math.cos(a)*r*0.58).toFixed(1)+'" y2="'+(cy+Math.sin(a)*r*0.58).toFixed(1)+'" stroke="#56565f" stroke-width="0.8"/>';}
  return s;}
function gd(c){return TYRE_GRAD[c]?c:'HARD';}

/* ---------- tyre strategy gantt (Pirelli-style) ---------- */
function tyreChart(elId, drivers, totalLaps){
  var rows=drivers.filter(function(d){return d.stints.length;}).sort(function(a,b){return a.fin-b.fin;});
  var rowH=24, gap=8, L=50, R=74, T=14, B=30, W=1040;
  var ph=rows.length*(rowH+gap), H=T+ph+B, pw=W-L-R;
  function X(l){return L+pw*l/Math.max(1,totalLaps);}
  var g=tyreDefs();
  for(var l=0;l<=totalLaps;l+=6){var x=X(l);
    g+='<line x1="'+x+'" y1="'+T+'" x2="'+x+'" y2="'+(T+ph)+'" class="ch-grid"/>';
    g+='<text x="'+x+'" y="'+(T+ph+16)+'" class="ch-xlab" text-anchor="middle">'+l+'</text>';}
  rows.forEach(function(d,i){
    var y=T+i*(rowH+gap), cy=y+rowH/2;
    g+='<text x="'+(L-10)+'" y="'+(cy+4)+'" class="ch-row" text-anchor="end">'+d.code+'</text>';
    d.stints.forEach(function(s){
      var c=s[0], x0=X(s[1]-1), w=X(s[2])-x0, n=s[2]-s[1]+1;
      g+='<rect x="'+x0.toFixed(1)+'" y="'+y+'" width="'+Math.max(1,w).toFixed(1)+'" height="'+rowH+'" rx="5" fill="url(#tg-'+gd(c)+')" stroke="rgba(0,0,0,.35)"><title>'+d.code+' — '+c+' · laps '+s[1]+'–'+s[2]+' ('+n+' laps)</title></rect>';
      var lab=w>80?(s[1]+'–'+s[2]+' ('+n+')'):(w>38?(s[1]+'–'+s[2]):'');
      if(lab) g+='<text x="'+(x0+w/2).toFixed(1)+'" y="'+(cy+3.5)+'" class="ch-stint" fill="'+tyreTxt(c)+'" text-anchor="middle">'+lab+'</text>';
    });
    g+='<text x="'+(W-R+8)+'" y="'+(cy+4)+'" class="tyre-stop" text-anchor="start">'+STOPW[d.stints.length-1]+'-STOP</text>';
  });
  document.getElementById(elId).innerHTML=svg(W,H,g);
}

/* ---------- race-overview stat tiles ---------- */
var IC={
 trophy:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4zM7 6H4v2a3 3 0 0 0 3 3M17 6h3v2a3 3 0 0 1-3 3"/></svg>',
 flag:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 21V4M5 4h12l-2.5 4L17 12H5"/></svg>',
 timer:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="13" r="8"/><path d="M12 13V9M9 2h6M19 5l1.5-1.5"/></svg>',
 gauge:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 14a9 9 0 0 1 18 0M12 14l4-3"/><circle cx="12" cy="14" r="1.2" fill="currentColor"/></svg>',
 up:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8M15 7h6v6"/></svg>',
 x:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/></svg>'
};
function ovTile(icon,fig,cls,label,sub){
  return '<div class="stat-tile ov-tile"><div class="st-icon">'+icon+'</div>'
    +'<div class="st-fig '+(cls||'')+'">'+fig+'</div><div class="st-label">'+label+'</div>'
    +'<div class="st-name">'+(sub||'')+'</div></div>';
}
function renderOverview(ov){
  var el=document.getElementById('ov-grid');
  if(!ov){el.innerHTML='';return;}
  el.innerHTML=
    ovTile(IC.trophy, ov.winner, 'red', 'Winner', ov.winnerTeam)
   +ovTile(IC.flag, ov.pole, 'wht', 'Pole', ov.poleNote)
   +ovTile(IC.timer, ov.margin, 'wht', 'Win Margin', 'gap to P2')
   +ovTile(IC.gauge, ov.fl, 'red', 'Fastest Lap', ov.flTime)
   +ovTile(IC.up, (ov.moverGain>0?'+':'')+ov.moverGain, 'grn', 'Biggest Mover', ov.mover)
   +ovTile(IC.x, ''+ov.dnfs, (ov.dnfs?'red':'wht'), 'DNFs', ov.classified+'/'+ov.total+' classified');
}

/* ---------- qualifying -> race position updates (curved, gain/lose colours) ---------- */
function deltaCol(a,b){return b<a?'#27D45F':(b>a?'#E1112A':'#3671C6');}  // up=green, down=red, same=blue
function progChart(elId, prog){
  var el=document.getElementById(elId);
  if(!prog||!prog.length){el.innerHTML='<div class="ch-empty">No data.</div>';return;}
  var maxP=20; prog.forEach(function(d){[d.q,d.g,d.r].forEach(function(v){if(v&&v>maxP)maxP=v;});});
  var W=900, H=480, L=56, R=56, T=16, B=72, pw=W-L-R, ph=H-T-B;
  var stages=[['Qualifying','q'],['Grid','g'],['Race','r']];
  function X(i){return L+pw*i/(stages.length-1);}
  function Y(p){return T+ph*(p-1)/(maxP-1);}
  function curve(x0,y0,x1,y1,c,tip){var cx=(x0+x1)/2;
    return '<path d="M'+x0.toFixed(1)+','+y0.toFixed(1)+' C'+cx.toFixed(1)+','+y0.toFixed(1)+' '+cx.toFixed(1)+','+y1.toFixed(1)+' '+x1.toFixed(1)+','+y1.toFixed(1)+'" fill="none" stroke="'+c+'" stroke-width="2" stroke-opacity="0.92"><title>'+tip+'</title></path>';}
  var g='';
  for(var p=1;p<=maxP;p+=5){var y=Y(p);
    g+='<line x1="'+L+'" y1="'+y+'" x2="'+(W-R)+'" y2="'+y+'" class="ch-grid"/>';
    g+='<text x="'+(L-6)+'" y="'+(y+3)+'" class="ch-ylab" text-anchor="end">'+p+'</text>';}
  stages.forEach(function(st,i){var x=X(i), anc=i===0?'start':(i===stages.length-1?'end':'middle');
    g+='<line x1="'+x+'" y1="'+T+'" x2="'+x+'" y2="'+(H-B)+'" class="ch-grid"/>';
    g+='<text x="'+x+'" y="'+(H-B+24)+'" class="sk-head" text-anchor="'+anc+'">'+st[0]+'</text>';});
  prog.forEach(function(d){
    if(d.q!=null&&d.g!=null) g+=curve(X(0),Y(d.q),X(1),Y(d.g),deltaCol(d.q,d.g),d.code+': Qualifying P'+d.q+' → Grid P'+d.g);
    if(d.g!=null&&d.r!=null) g+=curve(X(1),Y(d.g),X(2),Y(d.r),deltaCol(d.g,d.r),d.code+': Grid P'+d.g+' → Race P'+d.r);
    else if(d.g==null&&d.q!=null&&d.r!=null) g+=curve(X(0),Y(d.q),X(2),Y(d.r),deltaCol(d.q,d.r),d.code+': Qualifying P'+d.q+' → Race P'+d.r);
    [['q',0],['g',1],['r',2]].forEach(function(s){var v=d[s[0]]; if(v!=null) g+='<circle cx="'+X(s[1]).toFixed(1)+'" cy="'+Y(v).toFixed(1)+'" r="2.5" fill="#cfcdd6"/>';});
    if(d.r!=null) g+='<text x="'+(X(2)+6)+'" y="'+(Y(d.r)+3)+'" class="ch-tag" fill="'+(d.q!=null?deltaCol(d.q,d.r):'#cfcdd6')+'">'+d.code+'</text>';
  });
  el.innerHTML=svg(W,H,g);
}

/* ---------- tyre age vs optimal life (per driver, per stint) ---------- */
function tyreAgeChart(elId, drivers){
  var el=document.getElementById(elId);
  var rows=drivers.filter(function(d){return d.stints.length;}).sort(function(a,b){return a.fin-b.fin;});
  if(!rows.length){el.innerHTML='<div class="ch-empty">No data.</div>';return;}
  var rowH=24, gap=8, L=50, R=16, T=14, B=30, W=1040, segGap=12;
  var maxRow=1, maxStints=1;
  rows.forEach(function(d){var sum=0;
    d.stints.forEach(function(s){sum+=Math.max(s[2]-s[1]+1, TYRE_OPT[s[0]]||30);});
    maxRow=Math.max(maxRow,sum); maxStints=Math.max(maxStints,d.stints.length);});
  var lapPx=(W-L-R-(maxStints-1)*segGap)/maxRow;
  var ph=rows.length*(rowH+gap), H=T+ph+B;
  var g=tyreDefs();
  rows.forEach(function(d,i){
    var y=T+i*(rowH+gap), cy=y+rowH/2, x=L;
    g+='<text x="'+(L-10)+'" y="'+(cy+4)+'" class="ch-row" text-anchor="end">'+d.code+'</text>';
    d.stints.forEach(function(s){
      var c=s[0], n=s[2]-s[1]+1, o=TYRE_OPT[c]||30, col=TYRE[c]||'#777';
      var wOpt=o*lapPx, wWithin=Math.min(n,o)*lapPx, wOver=Math.max(0,n-o)*lapPx, wMax=Math.max(wOpt,wWithin+wOver);
      // optimal-life reference (dashed outline)
      g+='<rect x="'+x.toFixed(1)+'" y="'+y+'" width="'+wOpt.toFixed(1)+'" height="'+rowH+'" rx="4" fill="none" stroke="'+col+'" stroke-opacity="0.55" stroke-dasharray="3 3"/>';
      // laps actually run (within optimal)
      g+='<rect x="'+x.toFixed(1)+'" y="'+(y+3)+'" width="'+wWithin.toFixed(1)+'" height="'+(rowH-6)+'" rx="3" fill="url(#tg-'+gd(c)+')"><title>'+d.code+' — '+c+': '+n+' laps run vs ~'+o+' optimal ('+(n-o>=0?'+':'')+(n-o)+')</title></rect>';
      // laps beyond optimal (over-extended)
      if(wOver>0.5) g+='<rect x="'+(x+wWithin).toFixed(1)+'" y="'+(y+3)+'" width="'+wOver.toFixed(1)+'" height="'+(rowH-6)+'" rx="3" fill="#ff2e2e"><title>'+d.code+' — '+(n-o)+' laps beyond optimal</title></rect>';
      var solidW=wWithin+wOver, lc=wOver>0.5?'#fff':tyreTxt(c);
      if(solidW>15) g+='<text x="'+(x+solidW/2).toFixed(1)+'" y="'+(cy+3.5)+'" class="ch-stint" fill="'+lc+'" text-anchor="middle">'+n+'</text>';
      else g+='<text x="'+(x+solidW+5).toFixed(1)+'" y="'+(cy+3.5)+'" class="ch-stint" fill="#9a9aa3" text-anchor="start">'+n+'</text>';
      x+=wMax+segGap;
    });
  });
  el.innerHTML=svg(W,H,g);
}

/* ========== Top-3 drivers section ========== */
function medianOf(a){if(!a||!a.length)return null;var s=a.slice().sort(function(x,y){return x-y;});var m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2;}
function fmtLap(s){if(s==null)return '–';var m=Math.floor(s/60),r=s-m*60;return m>0?(m+':'+(r<10?'0':'')+r.toFixed(3)):r.toFixed(3);}
var TEMP_BASE={SOFT:97,MEDIUM:94,HARD:91,INTERMEDIATE:72,WET:62};
function stintOf(d,lap){for(var i=0;i<d.stints.length;i++){if(lap>=d.stints[i][1]&&lap<=d.stints[i][2])return d.stints[i];}return null;}
function lapTemp(c,age,t,med){return (TEMP_BASE[c]||93)+0.12*age+18*((t/(med||t))-1);}
function avgTemp(d){if(!d.lapseq||!d.lapseq.length)return null;var med=medianOf(d.laps),s=0,n=0;
  d.lapseq.forEach(function(p){var st=stintOf(d,p[0]); if(!st)return; s+=lapTemp(st[0],p[0]-st[1]+1,p[1],med); n++;});return n?s/n:null;}

function radarChart(elId, top3, radar){
  var el=document.getElementById(elId);
  var axes=[['Consistency','consistency'],['Pace','pace'],['Qualifying','qualifying'],['Racecraft','racecraft'],['Tyre Mgmt','tiremgmt']];
  var W=900,H=480,cx=W/2,cy=H/2+12,Rad=168,n=axes.length;
  function pt(i,v){var a=-Math.PI/2+2*Math.PI*i/n,r=Rad*v/100;return [cx+Math.cos(a)*r,cy+Math.sin(a)*r];}
  var g='';
  [20,40,60,80,100].forEach(function(v){var poly=axes.map(function(_,i){var p=pt(i,v);return p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' ');
    g+='<polygon points="'+poly+'" fill="none" stroke="rgba(255,255,255,.10)"/>';});
  axes.forEach(function(ax,i){var p=pt(i,100),pl=pt(i,119);
    g+='<line x1="'+cx+'" y1="'+cy+'" x2="'+p[0].toFixed(1)+'" y2="'+p[1].toFixed(1)+'" stroke="rgba(255,255,255,.12)"/>';
    var anc=Math.abs(pl[0]-cx)<12?'middle':(pl[0]<cx?'end':'start');
    g+='<text x="'+pl[0].toFixed(1)+'" y="'+pl[1].toFixed(1)+'" class="radar-ax" text-anchor="'+anc+'">'+ax[0]+'</text>';});
  top3.forEach(function(d){var rd=radar[d.code]||{};
    var poly=axes.map(function(ax,i){var v=rd[ax[1]]; return pt(i,v==null?50:v);});
    g+='<polygon points="'+poly.map(function(p){return p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' ')+'" fill="'+d.color+'" fill-opacity="0.15" stroke="'+d.color+'" stroke-width="2"><title>'+d.fam+'</title></polygon>';
    poly.forEach(function(p){g+='<circle cx="'+p[0].toFixed(1)+'" cy="'+p[1].toFixed(1)+'" r="2.4" fill="'+d.color+'"/>';});});
  top3.forEach(function(d,i){var ly=20+i*17;
    g+='<rect x="12" y="'+(ly-10)+'" width="11" height="11" rx="2" fill="'+d.color+'"/><text x="28" y="'+ly+'" class="radar-leg">'+d.fam+'</text>';});
  el.innerHTML=svg(W,H,g);
}

function t3Table(elId, top3){
  var rows=top3.map(function(d){
    var laps=d.laps||[], best=laps.length?Math.min.apply(null,laps):null;
    var avg=laps.length?laps.reduce(function(a,b){return a+b;},0)/laps.length:null, tmp=avgTemp(d);
    return '<tr><td class="st-drv"><span class="teamdot" style="--c:'+d.color+'"></span><b>'+d.code+'</b> '+d.fam+'</td>'
      +'<td class="num pts">'+fmtLap(best)+'</td><td class="num">'+fmtLap(avg)+'</td>'
      +'<td class="num">'+(d.topspeed!=null?d.topspeed.toFixed(1):'–')+'</td>'
      +'<td class="num">'+(tmp!=null?tmp.toFixed(1)+'°':'–')+'</td></tr>';}).join('');
  document.getElementById(elId).innerHTML='<table class="std-table"><thead><tr><th>Driver</th>'
    +'<th class="num">Best Lap</th><th class="num">Avg Lap</th><th class="num">Top Spd</th><th class="num">Avg °C</th></tr></thead><tbody>'+rows+'</tbody></table>';
}

function evoChart(elId, top3){
  var el=document.getElementById(elId);
  var laps=[],times=[]; top3.forEach(function(d){(d.lapseq||[]).forEach(function(p){laps.push(p[0]);times.push(p[1]);});});
  if(!times.length){el.innerHTML='<div class="ch-empty">No data.</div>';return;}
  var W=1180,H=305,L=58,R=120,T=16,B=46,pw=W-L-R,ph=H-T-B;
  var lmin=Math.min.apply(null,laps),lmax=Math.max.apply(null,laps);
  var tmin=Math.min.apply(null,times),tmax=Math.max.apply(null,times),tp=(tmax-tmin)*0.08||1;tmin-=tp;tmax+=tp;
  function X(l){return L+pw*(l-lmin)/Math.max(1,lmax-lmin);}
  function Y(t){return T+ph*(1-(t-tmin)/(tmax-tmin));}
  var g='';
  for(var i=0;i<=5;i++){var v=tmin+(tmax-tmin)*i/5,y=T+ph*(1-i/5);
    g+='<line x1="'+L+'" y1="'+y+'" x2="'+(W-R)+'" y2="'+y+'" class="ch-grid"/><text x="'+(L-6)+'" y="'+(y+3)+'" class="ch-ylab" text-anchor="end">'+v.toFixed(1)+'</text>';}
  for(var l=Math.ceil(lmin/10)*10;l<=lmax;l+=10){var x=X(l);
    g+='<line x1="'+x+'" y1="'+T+'" x2="'+x+'" y2="'+(H-B)+'" class="ch-grid"/><text x="'+x+'" y="'+(H-B+18)+'" class="ch-xlab" text-anchor="middle">'+l+'</text>';}
  top3.forEach(function(d){ if(!d.lapseq||!d.lapseq.length)return;
    var pts=d.lapseq.map(function(p){return X(p[0]).toFixed(1)+','+Y(p[1]).toFixed(1);}).join(' ');
    g+='<polyline points="'+pts+'" fill="none" stroke="'+d.color+'" stroke-width="1.8" stroke-opacity="0.92"><title>'+d.fam+'</title></polyline>';
    var last=d.lapseq[d.lapseq.length-1];
    g+='<text x="'+(X(last[0])+5)+'" y="'+(Y(last[1])+3)+'" class="ch-tag" fill="'+d.color+'">'+d.code+'</text>';});
  g+='<text x="'+(L+pw/2)+'" y="'+(H-B+40)+'" class="ch-axtitle" text-anchor="middle">Lap</text>';
  g+='<text x="15" y="'+(T+ph/2)+'" class="ch-axtitle" transform="rotate(-90 15 '+(T+ph/2)+')" text-anchor="middle">Lap Time (s)</text>';
  el.innerHTML=svg(W,H,g);
}

function sectorChart(elId, top3){
  var el=document.getElementById(elId), SC=['#E1112A','#19C3B1','#3671C6'];
  var maxv=0; top3.forEach(function(d){(d.sectors||[]).forEach(function(s){if(s&&s>maxv)maxv=s;});});
  if(!maxv){el.innerHTML='<div class="ch-empty">No data.</div>';return;}
  maxv*=1.12;
  var W=900,H=480,L=56,R=56,T=44,B=64,pw=W-L-R,ph=H-T-B;
  function Y(v){return T+ph*(1-v/maxv);}
  var g='';
  for(var i=0;i<=4;i++){var v=maxv*i/4,y=Y(v);
    g+='<line x1="'+L+'" y1="'+y+'" x2="'+(W-R)+'" y2="'+y+'" class="ch-grid"/><text x="'+(L-6)+'" y="'+(y+3)+'" class="ch-ylab" text-anchor="end">'+v.toFixed(0)+'</text>';}
  var gw=pw/top3.length, bw=Math.min(24,gw/4.2);
  top3.forEach(function(d,gi){var gx=L+gw*(gi+0.5);
    (d.sectors||[]).forEach(function(s,si){ if(s==null)return; var x=gx+(si-1)*(bw+4)-bw/2;
      g+='<rect x="'+x.toFixed(1)+'" y="'+Y(s).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+(Y(0)-Y(s)).toFixed(1)+'" rx="2" fill="'+SC[si]+'"><title>'+d.code+' Sector '+(si+1)+': '+s.toFixed(3)+'s</title></rect>';});
    g+='<text x="'+gx.toFixed(1)+'" y="'+(H-B+18)+'" class="ch-xlab" text-anchor="middle">'+d.code+'</text>';});
  ['Sector 1','Sector 2','Sector 3'].forEach(function(lab,i){var lx=L+i*96;
    g+='<rect x="'+lx+'" y="16" width="11" height="11" rx="2" fill="'+SC[i]+'"/><text x="'+(lx+16)+'" y="25" class="radar-leg">'+lab+'</text>';});
  g+='<text x="14" y="'+(T+ph/2)+'" class="ch-axtitle" transform="rotate(-90 14 '+(T+ph/2)+')" text-anchor="middle">Time (s)</text>';
  el.innerHTML=svg(W,H,g);
}

function ttempChart(elId, top3){
  var el=document.getElementById(elId), pts=[];
  top3.forEach(function(d){var med=medianOf(d.laps); (d.lapseq||[]).forEach(function(p){var st=stintOf(d,p[0]); if(!st)return; pts.push({x:lapTemp(st[0],p[0]-st[1]+1,p[1],med),y:p[1],c:d.color,code:d.code});});});
  if(!pts.length){el.innerHTML='<div class="ch-empty">No data.</div>';return;}
  var W=900,H=480,L=56,R=56,T=44,B=58,pw=W-L-R,ph=H-T-B;
  var xs=pts.map(function(p){return p.x;}),ys=pts.map(function(p){return p.y;});
  var xmin=Math.min.apply(null,xs)-1,xmax=Math.max.apply(null,xs)+1;
  var ymin=Math.min.apply(null,ys),ymax=Math.max.apply(null,ys),yp=(ymax-ymin)*0.08||1;ymin-=yp;ymax+=yp;
  function X(v){return L+pw*(v-xmin)/(xmax-xmin);}
  function Y(v){return T+ph*(1-(v-ymin)/(ymax-ymin));}
  var g='';
  for(var i=0;i<=5;i++){var v=ymin+(ymax-ymin)*i/5,y=T+ph*(1-i/5);
    g+='<line x1="'+L+'" y1="'+y+'" x2="'+(W-R)+'" y2="'+y+'" class="ch-grid"/><text x="'+(L-6)+'" y="'+(y+3)+'" class="ch-ylab" text-anchor="end">'+v.toFixed(1)+'</text>';}
  for(var j=0;j<=4;j++){var xv=xmin+(xmax-xmin)*j/4,x=X(xv);
    g+='<line x1="'+x+'" y1="'+T+'" x2="'+x+'" y2="'+(H-B)+'" class="ch-grid"/><text x="'+x+'" y="'+(H-B+18)+'" class="ch-xlab" text-anchor="middle">'+xv.toFixed(0)+'</text>';}
  pts.forEach(function(p){g+='<circle cx="'+X(p.x).toFixed(1)+'" cy="'+Y(p.y).toFixed(1)+'" r="2.4" fill="'+p.c+'" fill-opacity="0.72"><title>'+p.code+' · '+p.x.toFixed(0)+'°C · '+p.y.toFixed(2)+'s</title></circle>';});
  top3.forEach(function(d,i){g+='<rect x="'+(L+i*78)+'" y="16" width="11" height="11" rx="2" fill="'+d.color+'"/><text x="'+(L+i*78+16)+'" y="25" class="radar-leg">'+d.code+'</text>';});
  g+='<text x="'+(L+pw/2)+'" y="'+(H-B+40)+'" class="ch-axtitle" text-anchor="middle">Tyre Temp (°C · modelled)</text>';
  g+='<text x="14" y="'+(T+ph/2)+'" class="ch-axtitle" transform="rotate(-90 14 '+(T+ph/2)+')" text-anchor="middle">Lap Time (s)</text>';
  el.innerHTML=svg(W,H,g);
}

/* ---------- click-to-zoom modal ---------- */
function openZoom(card){
  var host=card.querySelector('.ch-host'); if(!host||!host.innerHTML.trim())return;
  var t=card.querySelector('.ch-title');
  document.getElementById('ch-modal-title').textContent=t?t.textContent:'';
  document.getElementById('ch-modal-host').innerHTML=host.innerHTML;
  document.getElementById('ch-modal').classList.add('open');
}
function closeZoom(e){document.getElementById('ch-modal').classList.remove('open');}
function attachZoom(){
  [].forEach.call(document.querySelectorAll('.card-chart[data-zoom]'),function(c){
    if(c._z)return; c._z=1; c.addEventListener('click',function(){openZoom(c);});
  });
}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeZoom();});

/* ---------- per-race orchestration ---------- */
function renderAX(){
  var rd=document.getElementById('axsel').value, R=AX.data[rd];
  if(!R){return;}
  var drv=R.drivers;
  renderOverview(R.ov);
  posChart('ch-pos', drv, R.total_laps);
  progChart('ch-prog', R.prog);
  var top=drv.filter(function(d){return d.laps&&d.laps.length>=3;}).sort(function(a,b){return a.fin-b.fin;}).slice(0,10);
  boxChart('ch-box', top.map(function(d){return {label:d.code,color:d.color,stats:quart(d.laps)};}));
  var teams={};
  drv.forEach(function(d){ if(!d.laps||!d.laps.length||!d.cid)return;
    if(!teams[d.cid]) teams[d.cid]={laps:[],color:d.color,name:d.team};
    teams[d.cid].laps=teams[d.cid].laps.concat(d.laps);});
  var tg=Object.keys(teams).map(function(k){return {label:teams[k].name,color:teams[k].color,stats:quart(teams[k].laps)};})
    .sort(function(a,b){return a.stats.med-b.stats.med;});
  boxChart('ch-pace', tg);
  tyreChart('ch-tyre', drv, R.total_laps);
  tyreAgeChart('ch-tyreage', drv);
  // Top-3 drivers (by finishing position)
  var top3=drv.filter(function(d){return typeof d.fin==='number'&&d.fin<=3;}).sort(function(a,b){return a.fin-b.fin;}).slice(0,3);
  radarChart('ch-radar', top3, R.radar||{});
  t3Table('t3-table', top3);
  evoChart('ch-evo', top3);
  sectorChart('ch-sector', top3);
  ttempChart('ch-ttemp', top3);
}

renderMatrix();
var sel=document.getElementById('axsel');
if(sel&&sel.options.length){sel.value=sel.options[sel.options.length-1].value; renderAX();}
attachZoom();
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
