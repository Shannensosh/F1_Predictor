"""pages_live.py — faithful browser port of the f1-race-replay desktop window,
now with a race picker (every baked 2026 round, most-recent default) and a
best-effort LIVE mode that follows a running session straight from OpenF1.

Replay: the renderer replicates src/interfaces/race_replay.py 1:1 on a <canvas>
(black background; inner+outer track strips coloured by track status; green DRS
segments; checkered finish line; 6px car dots + optional labels; LAP/TIME/STATUS;
session banner; right leaderboard; weather panel; controls legend; bottom
progress bar; centre transport buttons; the app's keyboard map). Each race is a
data/replay/r{round}.json baked by f1_prebake.py and fetched on demand so the
page stays light.

Live: when a session is running, the page polls the free, CORS-enabled OpenF1
API (location / position / intervals / stints / weather / race-control) every
few seconds and auto-scales the cars onto a self-tracing outline. It falls back
to replay when nothing is live; the free feed runs a short delay, so live mode
is explicitly best-effort."""


def live_timing_body(d, ctx):
    esc = ctx["esc"]
    races = (d.get("replay_index") or {}).get("races", [])
    opts = "".join(
        f'<option value="{esc(r["file"])}" data-laps="{r.get("total_laps") or ""}" '
        f'data-gps="{r.get("gps_last_lap") or ""}">'
        f'R{r["round"]} · {esc(r.get("event",""))} — {esc(r.get("circuit",""))} '
        f'({esc(r.get("date",""))})</option>'
        for r in races)
    if not opts:
        opts = '<option value="">No baked replays yet — run python3 build.py</option>'
    return f"""
    <div class="page-head"><div><h1>Live Timing &amp; Replay</h1>
    <p>Watch any 2026 Grand Prix back in the f1-race-replay interface — or, during a live
    session, follow the cars in real time from the OpenF1 feed.</p></div></div>

    <div class="rt-bar">
      <label class="rt-field"><span>Replay race</span>
        <select id="raceSel" class="rt-select">{opts}</select></label>
      <button id="liveBtn" class="rt-live" title="Check for a live session and follow it live">
        <span class="rt-dot"></span> LIVE</button>
      <span id="rt-status" class="rt-status"></span>
    </div>
    <div id="rt-note"></div>

    <div class="replay-shell"><canvas id="replay" tabindex="0"></canvas></div>

    <div class="note" style="margin-top:10px">SPACE pause/resume · ←/→ rewind/fast-forward ·
    ↑/↓ speed (0.1×–256×) · 1–4 = 0.5/1/2/4× · R restart · D DRS zones · L driver labels ·
    B progress bar · click a leaderboard row or car to select drivers (Shift for several) ·
    click the progress bar to seek. <b>Live mode</b> polls OpenF1 every few seconds and is
    best-effort — the free feed runs a short delay and the 2026 feed can have gaps.</div>"""


LIVE_JS = r"""
var MANIFEST=(typeof PAGE_DATA==='function'?PAGE_DATA():null)||{races:[]};
var OPENF1='https://api.openf1.org/v1/';

(function(){
var cv=document.getElementById('replay'); if(!cv) return;
var ctx=cv.getContext('2d');
var selEl=document.getElementById('raceSel');
var liveBtn=document.getElementById('liveBtn');
var statusEl=document.getElementById('rt-status');

/* ── constants from the desktop app ─────────────────────────────────────── */
var PLAYBACK_SPEEDS=[0.1,0.2,0.5,1.0,2.0,4.0,8.0,16.0,32.0,64.0,128.0,256.0];
var LEFT_M=340, RIGHT_M=260, PAD=0.05;
var STATUS_COLORS={GREEN:'rgb(150,150,150)',YELLOW:'rgb(220,180,0)',RED:'rgb(200,30,30)',
                   VSC:'rgb(200,130,50)',SC:'rgb(180,100,30)'};
var STATUS_TEXT={ '2':['YELLOW FLAG','rgb(220,180,0)'], '4':['SAFETY CAR','rgb(255,165,0)'],
                  '5':['RED FLAG','rgb(220,40,40)'], '6':['VIRTUAL SAFETY CAR','rgb(200,130,50)'],
                  '7':['VIRTUAL SAFETY CAR','rgb(200,130,50)'] };
var TYRES=['#FF3B30','#FFD60A','#E8E8E8','#2DD45F','#3B9BFF'];     // S M H I W
var TYRE_NAME=['SOFT','MEDIUM','HARD','INTER','WET'];
var TYRE_IDX={SOFT:0,MEDIUM:1,HARD:2,INTERMEDIATE:3,WET:4};

/* ── shared render state ─────────────────────────────────────────────────── */
var mode='replay';                       // 'replay' | 'live'
var D=null, frames=[], NF=0, FPS=1, META={}, COLORS={};
var fi=0, paused=false, speed=1.0, lastTs=null;
var showDRS=true, showLabels=false, showProgress=true;
var selected=[];                         // selected driver codes
var holdRewind=false, holdForward=false;
var buttons=[];                          // transport hit rects (replay)
var lbRects=[];                          // leaderboard hit rects
var rafStarted=false;
var userChoseReplay=false;               // a manual race pick disables live auto-switch

/* replay track geometry (rebuilt per race) */
var rot=0,cosR=1,sinR=0, ref=[],inner=[],outer=[],drsZones=[];
var rInner=[],rOuter=[],rRef=[],refN=[], wcx=0,wcy=0;
var scale=1,tx=0,ty=0,W=0,H=0;

function rotPt(x,y,cx,cy){var tx2=x-cx,ty2=y-cy;return [tx2*cosR-ty2*sinR+cx, tx2*sinR+ty2*cosR+cy];}
function w2s(p){ return [scale*p[0]+tx, ty-scale*p[1]]; }
function setStatus(t){ if(statusEl) statusEl.textContent=t||''; }

/* ── canvas sizing ──────────────────────────────────────────────────────── */
function resize(){
  W=cv.clientWidth; H=cv.clientHeight;
  cv.width=W*devicePixelRatio; cv.height=H*devicePixelRatio;
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
  if(mode==='replay' && rInner.length) fitReplay();
}
function fitReplay(){
  var xs=[],ys=[];
  rInner.concat(rOuter).forEach(function(p){xs.push(p[0]);ys.push(p[1]);});
  var x0=Math.min.apply(null,xs),x1=Math.max.apply(null,xs),
      y0=Math.min.apply(null,ys),y1=Math.max.apply(null,ys);
  var iw=Math.max(1,W-LEFT_M-RIGHT_M), uw=iw*(1-2*PAD), uh=H*(1-2*PAD);
  scale=Math.min(uw/Math.max(1,x1-x0), uh/Math.max(1,y1-y0));
  var scx=LEFT_M+iw/2, scy=H/2;
  tx=scx-scale*(x0+x1)/2; ty=scy+scale*(y0+y1)/2;   // y flipped
}
window.addEventListener('resize',resize);

/* ── helpers ────────────────────────────────────────────────────────────── */
function curStatus(t){
  if(!D||!D.statuses) return '1';
  var s='1';
  for(var i=0;i<D.statuses.length;i++){
    var st=D.statuses[i];
    if(st[1]<=t && (st[2]==null||t<st[2])){ s=st[0]; break; }
  }
  return s;
}
function trackColor(s){
  if(s==='2')return STATUS_COLORS.YELLOW;
  if(s==='4')return STATUS_COLORS.SC;
  if(s==='5')return STATUS_COLORS.RED;
  if(s==='6'||s==='7')return STATUS_COLORS.VSC;
  return STATUS_COLORS.GREEN;
}
function lerpCar(code){
  var i0=Math.min(Math.floor(fi),NF-1), i1=Math.min(i0+1,NF-1), f=fi-i0;
  var a=frames[i0].d[code], b=frames[i1].d[code];
  if(!a) return null; if(!b) return a;
  return [a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f, a[2],a[3],a[4],a[5],a[6],a[7],a[8],a[9], a[10]+(b[10]-a[10])*f];
}
function nearestRefIdx(x,y){
  var best=0,bd=1e18;
  for(var i=0;i<rRef.length;i+=4){
    var dx=rRef[i][0]-x, dy=rRef[i][1]-y, d=dx*dx+dy*dy;
    if(d<bd){bd=d;best=i;}
  }
  return best;
}
function fmtTime(t){
  var h=Math.floor(t/3600),m=Math.floor(t%3600/60),s=Math.floor(t%60);
  return (h<10?'0':'')+h+':'+(m<10?'0':'')+m+':'+(s<10?'0':'')+s;
}

/* ── REPLAY drawing (mirrors on_draw) ───────────────────────────────────── */
function strip(pts,color,width){
  ctx.strokeStyle=color; ctx.lineWidth=width; ctx.lineJoin='round'; ctx.beginPath();
  for(var i=0;i<pts.length;i++){var s=w2s(pts[i]); i?ctx.lineTo(s[0],s[1]):ctx.moveTo(s[0],s[1]);}
  ctx.stroke();
}
function draw(){
  ctx.fillStyle='#000'; ctx.fillRect(0,0,W,H);
  var idx=Math.min(Math.floor(fi),NF-1), frame=frames[idx], t=frame.t;
  var st=curStatus(t), tcol=trackColor(st);

  strip(rInner,tcol,4); strip(rOuter,tcol,4);

  if(showDRS&&drsZones.length){
    drsZones.forEach(function(z){
      ctx.strokeStyle='rgb(0,255,0)'; ctx.lineWidth=6; ctx.beginPath();
      for(var i=z[0];i<=Math.min(z[1],rOuter.length-1);i++){
        var s=w2s(rOuter[i]); i===z[0]?ctx.moveTo(s[0],s[1]):ctx.lineTo(s[0],s[1]);
      }
      ctx.stroke();
    });
  }

  // checkered finish line (20 squares, extended 20px past both edges)
  var si=w2s(rInner[0]), so=w2s(rOuter[0]);
  var fdx=so[0]-si[0], fdy=so[1]-si[1], fl=Math.hypot(fdx,fdy)||1;
  var ei=[si[0]-20*fdx/fl, si[1]-20*fdy/fl], eo=[so[0]+20*fdx/fl, so[1]+20*fdy/fl];
  for(var q=0;q<20;q++){
    var t1=q/20,t2=(q+1)/20;
    ctx.strokeStyle=q%2?'#000':'#FFF'; ctx.lineWidth=6; ctx.beginPath();
    ctx.moveTo(ei[0]+t1*(eo[0]-ei[0]), ei[1]+t1*(eo[1]-ei[1]));
    ctx.lineTo(ei[0]+t2*(eo[0]-ei[0]), ei[1]+t2*(eo[1]-ei[1]));
    ctx.stroke();
  }

  var noPos=!!frame.np;
  if(noPos) ctx.globalAlpha=0.25;
  var codes=Object.keys(frame.d), li=0;
  codes.forEach(function(code){
    if(D.gps_end && D.gps_end[code]!=null && t>D.gps_end[code]+30) return;
    var c0=frame.d[code];
    if(c0 && frame.lap-c0[2]>=3) return;
    var c=lerpCar(code); if(!c) return;
    var rp=rotPt(c[0],c[1],wcx,wcy), s=w2s(rp);
    var col=COLORS[code]||'#FFF';
    var isSel=selected.indexOf(code)>=0;
    if(showLabels||isSel){
      var ri=nearestRefIdx(rp[0],rp[1]);
      var nx=refN[ri][0], ny=refN[ri][1];
      var off=(li%2===0)?45:75;
      var lx=s[0]+nx*off, ly=s[1]-ny*off;
      ctx.strokeStyle=col; ctx.lineWidth=1; ctx.beginPath();
      ctx.moveTo(s[0],s[1]); ctx.lineTo(lx,ly); ctx.stroke();
      ctx.fillStyle=col; ctx.font='bold 10px Titillium Web,sans-serif';
      ctx.textAlign=nx>=0?'left':'right'; ctx.textBaseline='middle';
      ctx.fillText(code, lx+(nx>=0?3:-3), ly);
    }
    ctx.beginPath(); ctx.arc(s[0],s[1],isSel?8:6,0,7); ctx.fillStyle=col; ctx.fill();
    if(isSel){ ctx.strokeStyle='#FFF'; ctx.lineWidth=2; ctx.stroke(); }
    li++;
  });
  ctx.globalAlpha=1;
  if(noPos){
    ctx.fillStyle='rgba(220,40,40,.92)'; ctx.font='700 15px Titillium Web,sans-serif';
    ctx.textAlign='center'; ctx.textBaseline='top';
    ctx.fillText('GPS FEED ENDED ON LAP '+frame.lap+' (RED-FLAG PERIOD) — TIMING CONTINUES TO THE FLAG',
                 LEFT_M+(W-LEFT_M-RIGHT_M)/2, 34);
  }

  drawHUD(frame,t,st);
  if(showProgress) drawProgress(t);
  drawButtons();
}

function drawHUD(frame,t,st){
  ctx.textAlign='left'; ctx.textBaseline='top';
  ctx.fillStyle='#FFF'; ctx.font='700 24px Titillium Web,sans-serif';
  ctx.fillText('LAP '+frame.lap+(META.total_laps?' / '+META.total_laps:''), 20, 16);
  ctx.font='20px Titillium Web,sans-serif';
  ctx.fillText(fmtTime(t), 20, 52);
  var stx=STATUS_TEXT[st];
  if(stx){ ctx.font='700 24px Titillium Web,sans-serif'; ctx.fillStyle=stx[1]; ctx.fillText(stx[0],20,84); }

  ctx.textAlign='center'; ctx.fillStyle='#BBB'; ctx.font='13px Titillium Web,sans-serif';
  ctx.fillText((META.event||'')+' — '+(META.circuit||'')+', '+(META.country||'')+'  ·  '+META.year+' R'+META.round+'  ·  '+META.total_laps+' laps',
               LEFT_M+(W-LEFT_M-RIGHT_M)/2, 10);

  var wrow=null;
  for(var i=Math.min(Math.floor(fi),NF-1);i>=0;i--){ if(frames[i].w){wrow=frames[i].w;break;} }
  if(wrow){
    ctx.textAlign='left'; ctx.fillStyle='#9B9BA8'; ctx.font='12px Titillium Web,sans-serif';
    var wy=170;
    ctx.fillText('AIR '+wrow[0].toFixed(0)+'°  TRACK '+wrow[1].toFixed(0)+'°',20,wy);
    ctx.fillText('HUM '+wrow[2].toFixed(0)+'%   WIND '+wrow[3].toFixed(1)+' m/s '+Math.round(wrow[4])+'°',20,wy+16);
    if(wrow[5]) { ctx.fillStyle='#3B9BFF'; ctx.fillText('RAINING',20,wy+32); }
  }

  var y=230;
  selected.slice(0,4).forEach(function(code){
    var c=frames[Math.min(Math.floor(fi),NF-1)].d[code]; if(!c) return;
    ctx.fillStyle='rgba(20,20,26,.85)'; ctx.fillRect(20,y,300,64);
    ctx.strokeStyle='#333'; ctx.strokeRect(20,y,300,64);
    ctx.fillStyle=COLORS[code]||'#FFF'; ctx.fillRect(20,y,4,64);
    ctx.fillStyle='#FFF'; ctx.font='700 16px Titillium Web,sans-serif'; ctx.textAlign='left';
    ctx.fillText(code+'   P'+c[3]+'   LAP '+c[2], 34, y+10);
    var ty2=c[4]>=0?TYRE_NAME[c[4]]:'–';
    ctx.font='13px Titillium Web,sans-serif'; ctx.fillStyle='#BBB';
    ctx.fillText('TYRE '+ty2+' ('+c[5]+' laps)'+(c[6]?'   IN PIT':''), 34, y+34);
    if(c[4]>=0){ ctx.beginPath(); ctx.arc(300,y+18,8,0,7); ctx.strokeStyle=TYRES[c[4]]; ctx.lineWidth=3; ctx.stroke(); }
    y+=72;
  });

  ctx.font='11px Titillium Web,sans-serif'; ctx.fillStyle='#777'; ctx.textAlign='left';
  var L=['[SPACE] Pause','[←/→] Rewind / FF','[↑/↓] Speed','[1-4] 0.5/1/2/4×','[R] Restart',
         '[D] DRS zones','[L] Labels','[B] Progress bar','[Click] Select driver'];
  L.forEach(function(s,i){ ctx.fillText(s, 20, H-180+i*16); });

  drawLeaderboard(frame);
}

function drawLeaderboard(frame){
  lbRects=[];
  var x=Math.max(20,W-RIGHT_M+12), w=240, rowH=25;
  var codes=Object.keys(frame.d).sort(function(a,b){return frame.d[a][3]-frame.d[b][3];});
  var leaderDist=frame.d[codes[0]]?frame.d[codes[0]][10]:0;
  ctx.fillStyle='rgba(12,12,16,.82)';
  ctx.fillRect(x-8, 30, w+8, Math.min(H-140, codes.length*rowH+40));
  ctx.fillStyle='#9B9BA8'; ctx.font='700 12px Titillium Web,sans-serif'; ctx.textAlign='left'; ctx.textBaseline='top';
  ctx.fillText('LEADERBOARD', x, 38);
  codes.forEach(function(code,i){
    var c=frame.d[code], y=58+i*rowH;
    if(y>H-130) return;
    var sel=selected.indexOf(code)>=0;
    if(sel){ ctx.fillStyle='rgba(225,6,0,.25)'; ctx.fillRect(x-6,y-3,w,rowH-2); }
    ctx.fillStyle='#888'; ctx.font='12px JetBrains Mono,monospace'; ctx.textAlign='right';
    ctx.fillText(String(c[3]), x+20, y);
    ctx.fillStyle=COLORS[code]||'#FFF'; ctx.fillRect(x+26,y+1,4,12);
    ctx.fillStyle='#FFF'; ctx.font='700 13px Titillium Web,sans-serif'; ctx.textAlign='left';
    ctx.fillText(code, x+36, y);
    if(c[4]>=0){ ctx.beginPath(); ctx.arc(x+86,y+7,6,0,7); ctx.strokeStyle=TYRES[c[4]]; ctx.lineWidth=2.5; ctx.stroke(); }
    if(c[6]){ ctx.fillStyle='#FFB020'; ctx.font='700 10px Titillium Web,sans-serif'; ctx.fillText('PIT', x+98, y+2); }
    ctx.fillStyle='#AAA'; ctx.font='12px JetBrains Mono,monospace'; ctx.textAlign='right';
    var gap;
    if(frame.lap-c[2]>=3){ gap='OUT'; ctx.fillStyle='#E10600'; }
    else gap=i===0?'LEADER':('+'+(Math.abs(leaderDist-c[10])/10/55.56).toFixed(1));
    ctx.fillText(gap, x+w-8, y);
    lbRects.push([code, x-6, y-3, x+w-6, y+rowH-5]);
  });
}

function drawProgress(t){
  var left=LEFT_M, right=W-RIGHT_M, bottom=H-30, h=24;
  var total=frames[NF-1].t||1;
  ctx.fillStyle='rgba(40,40,46,.9)'; ctx.fillRect(left,bottom-h,right-left,h);
  D.statuses.forEach(function(s){
    if(s[0]==='1') return;
    var a=(s[1]/total)*(right-left), b=((s[2]==null?total:s[2])/total)*(right-left);
    ctx.fillStyle=trackColor(s[0]);
    ctx.fillRect(left+a, bottom-h+4, Math.max(2,b-a), 16);
  });
  var gmax=0;
  if(D.gps_end){ for(var k in D.gps_end) gmax=Math.max(gmax,D.gps_end[k]); }
  if(gmax>0&&gmax<total){
    var gx=left+(gmax/total)*(right-left);
    ctx.fillStyle='rgba(0,0,0,.45)'; ctx.fillRect(gx,bottom-h,right-gx,h);
    ctx.fillStyle='#FFF'; ctx.fillRect(gx-1,bottom-h-3,2,h+6);
  }
  ctx.fillStyle='#E8E8E8'; ctx.fillRect(left, bottom-h, (t/total)*(right-left), 3);
  ctx.strokeStyle='#555'; ctx.strokeRect(left,bottom-h,right-left,h);
}

function drawButtons(){
  buttons=[];
  var cx=W/2, y=H-100, bw=46, bh=34, gap=10;
  var defs=[['rew','⏪'],['play',paused?'▶':'⏸'],['fwd','⏩'],['spd',speed+'×'],['rst','⟲']];
  var totalW=defs.length*bw+(defs.length-1)*gap, x=cx-totalW/2;
  defs.forEach(function(d){
    ctx.fillStyle=d[0]==='play'?'#E10600':'rgba(34,34,40,.92)';
    ctx.fillRect(x,y,bw,bh);
    ctx.strokeStyle='#555'; ctx.strokeRect(x,y,bw,bh);
    ctx.fillStyle='#FFF'; ctx.font='700 13px Titillium Web,sans-serif';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillText(d[1], x+bw/2, y+bh/2);
    buttons.push([d[0],x,y,x+bw,y+bh]);
    x+=bw+gap;
  });
}

/* ── LIVE mode (OpenF1) ─────────────────────────────────────────────────── */
var LIVE={key:null, meta:{}, colors:{}, names:{}, cars:{}, flag:'1', weather:null,
          trackPts:[], timer:null, active:false, lap:null, _stintAt:0, _wxAt:0, _posAt:0};

function jget(url){ return fetch(url).then(function(r){ if(!r.ok) throw new Error(r.status); return r.json(); }); }

function checkLive(){
  return jget(OPENF1+'sessions?session_key=latest').then(function(a){
    var s=a&&a[0]; if(!s) return null;
    var now=Date.now(), st=Date.parse(s.date_start), en=Date.parse(s.date_end);
    if(isFinite(st)&&isFinite(en)&&now>=st-300000&&now<=en+1200000) return s;   // -5min .. +20min
    return null;
  }).catch(function(){ return null; });
}

function startLive(sess){
  mode='live'; LIVE.active=true; LIVE.key=sess.session_key;
  LIVE.cars={}; LIVE.trackPts=[]; LIVE.colors={}; LIVE.names={}; LIVE.flag='1';
  LIVE.meta={circuit:sess.circuit_short_name||sess.location||'', country:sess.country_name||'',
             session:sess.session_name||'', year:sess.year};
  if(liveBtn) liveBtn.classList.add('on');
  setStatus('LIVE — '+LIVE.meta.circuit+' '+LIVE.meta.session+' · connecting…');
  jget(OPENF1+'drivers?session_key='+LIVE.key).then(function(ds){
    ds.forEach(function(dd){
      var code=dd.name_acronym||(''+dd.driver_number);
      LIVE.names[dd.driver_number]=code;
      LIVE.colors[code]=dd.team_colour?('#'+dd.team_colour):'#FFFFFF';
    });
  }).catch(function(){});
  pollLive();
  LIVE.timer=setInterval(pollLive, 3000);
  startLoop();
}
function stopLive(){
  LIVE.active=false;
  if(LIVE.timer){ clearInterval(LIVE.timer); LIVE.timer=null; }
  if(liveBtn) liveBtn.classList.remove('on');
}

function pollLive(){
  if(!LIVE.key) return;
  var since=new Date(Date.now()-5000).toISOString();
  jget(OPENF1+'location?session_key='+LIVE.key+'&date>'+since).then(function(rows){
    var latest={};
    rows.forEach(function(r){ var c=LIVE.names[r.driver_number]; if(!c)return;
      if(!latest[c]||r.date>latest[c].date) latest[c]=r; });
    Object.keys(latest).forEach(function(c){ var r=latest[c];
      if(Math.abs(r.x)+Math.abs(r.y)<2) return;
      if(!LIVE.cars[c]) LIVE.cars[c]={};
      LIVE.cars[c].x=r.x; LIVE.cars[c].y=r.y;
      LIVE.trackPts.push([r.x,r.y]);
    });
    if(LIVE.trackPts.length>4000) LIVE.trackPts=LIVE.trackPts.slice(-4000);
    var n=Object.keys(LIVE.cars).length;
    setStatus('LIVE — '+(LIVE.meta.circuit||'')+' '+(LIVE.meta.session||'')+' · '+(n?n+' cars':'waiting for cars…'));
  }).catch(function(){ setStatus('LIVE — waiting for the position feed…'); });

  // running order changes infrequently → full fetch, but only every ~8s
  if(Date.now()-LIVE._posAt>8000){ LIVE._posAt=Date.now();
    jget(OPENF1+'position?session_key='+LIVE.key).then(function(rows){
      var pos={}; rows.forEach(function(r){ var c=LIVE.names[r.driver_number]; if(!c)return;
        if(!pos[c]||r.date>pos[c].date) pos[c]=r; });
      Object.keys(pos).forEach(function(c){ if(!LIVE.cars[c])LIVE.cars[c]={}; LIVE.cars[c].pos=pos[c].position; });
    }).catch(function(){});
  }
  // intervals are high-frequency → only pull the last few seconds to cap payload
  jget(OPENF1+'intervals?session_key='+LIVE.key+'&date>'+since).then(function(rows){
    var iv={}; rows.forEach(function(r){ var c=LIVE.names[r.driver_number]; if(!c)return;
      if(!iv[c]||r.date>iv[c].date) iv[c]=r; });
    Object.keys(iv).forEach(function(c){ if(!LIVE.cars[c])LIVE.cars[c]={};
      if(iv[c].gap_to_leader!=null) LIVE.cars[c].gap=iv[c].gap_to_leader; });
  }).catch(function(){});

  if(Date.now()-LIVE._stintAt>15000){ LIVE._stintAt=Date.now();
    jget(OPENF1+'stints?session_key='+LIVE.key).then(function(rows){
      var st={}; rows.forEach(function(r){ var c=LIVE.names[r.driver_number]; if(!c)return;
        if(!st[c]||(r.stint_number||0)>=(st[c].stint_number||0)) st[c]=r; });
      Object.keys(st).forEach(function(c){ if(!LIVE.cars[c])LIVE.cars[c]={};
        var ti=TYRE_IDX[(st[c].compound||'').toUpperCase()]; LIVE.cars[c].tyre=(ti==null?-1:ti); });
    }).catch(function(){});
  }
  if(Date.now()-LIVE._wxAt>15000){ LIVE._wxAt=Date.now();
    jget(OPENF1+'weather?session_key='+LIVE.key).then(function(rows){
      if(rows.length) LIVE.weather=rows[rows.length-1]; }).catch(function(){});
    jget(OPENF1+'race_control?session_key='+LIVE.key).then(function(rows){
      var f='1';
      for(var i=rows.length-1;i>=0;i--){
        var fl=(rows[i].flag||'').toUpperCase(), msg=(rows[i].message||'').toUpperCase();
        if(msg.indexOf('SAFETY CAR')>=0 && msg.indexOf('VIRTUAL')>=0){f='6';break;}
        if(msg.indexOf('SAFETY CAR')>=0){f='4';break;}
        if(fl==='RED'){f='5';break;}
        if(fl==='YELLOW'||fl==='DOUBLE YELLOW'){f='2';break;}
        if(fl==='GREEN'||fl==='CLEAR'){f='1';break;}
      }
      LIVE.flag=f; }).catch(function(){});
  }
}

function drawLive(){
  ctx.fillStyle='#000'; ctx.fillRect(0,0,W,H);
  var codes=Object.keys(LIVE.cars).filter(function(c){return LIVE.cars[c].x!=null;});
  var tp=LIVE.trackPts;
  if(!tp.length){
    ctx.fillStyle='#9B9BA8'; ctx.font='600 15px Titillium Web,sans-serif';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillText('LIVE — waiting for car positions from OpenF1…', W/2, H/2);
    liveHUD(null); return;
  }
  var x0=1e18,x1=-1e18,y0=1e18,y1=-1e18;
  for(var i=0;i<tp.length;i++){var p=tp[i]; if(p[0]<x0)x0=p[0]; if(p[0]>x1)x1=p[0]; if(p[1]<y0)y0=p[1]; if(p[1]>y1)y1=p[1];}
  var iw=Math.max(1,W-LEFT_M-RIGHT_M), uw=iw*(1-2*PAD), uh=H*(1-2*PAD);
  var sc=Math.min(uw/Math.max(1,x1-x0), uh/Math.max(1,y1-y0));
  var scx=LEFT_M+iw/2, scy=H/2, ltx=scx-sc*(x0+x1)/2, lty=scy+sc*(y0+y1)/2;
  function L2S(x,y){ return [sc*x+ltx, lty-sc*y]; }

  // self-tracing outline (faint breadcrumb of every position seen)
  ctx.fillStyle='rgba(120,120,135,.16)';
  for(var i=0;i<tp.length;i++){ var s=L2S(tp[i][0],tp[i][1]); ctx.fillRect(s[0],s[1],2,2); }

  codes.sort(function(a,b){return (LIVE.cars[a].pos||99)-(LIVE.cars[b].pos||99);});
  codes.forEach(function(c){
    var car=LIVE.cars[c], s=L2S(car.x,car.y), col=LIVE.colors[c]||'#FFF';
    var sel=selected.indexOf(c)>=0;
    if(showLabels||sel){
      ctx.fillStyle=col; ctx.font='bold 10px Titillium Web,sans-serif';
      ctx.textAlign='left'; ctx.textBaseline='middle'; ctx.fillText(c, s[0]+9, s[1]-7);
    }
    ctx.beginPath(); ctx.arc(s[0],s[1],sel?8:6,0,7); ctx.fillStyle=col; ctx.fill();
    if(sel){ ctx.strokeStyle='#FFF'; ctx.lineWidth=2; ctx.stroke(); }
  });

  liveLeaderboard(codes);
  liveHUD(codes);
}

function liveHUD(codes){
  ctx.textAlign='left'; ctx.textBaseline='top';
  ctx.fillStyle='#FFF'; ctx.font='700 22px Titillium Web,sans-serif';
  ctx.fillText('● LIVE', 20, 16);
  ctx.font='13px Titillium Web,sans-serif'; ctx.fillStyle='#BBB';
  ctx.fillText((LIVE.meta.circuit||'')+'  ·  '+(LIVE.meta.session||''), 20, 48);
  var stx=STATUS_TEXT[LIVE.flag];
  if(stx){ ctx.font='700 20px Titillium Web,sans-serif'; ctx.fillStyle=stx[1]; ctx.fillText(stx[0],20,72); }
  var w=LIVE.weather;
  if(w){
    ctx.fillStyle='#9B9BA8'; ctx.font='12px Titillium Web,sans-serif';
    ctx.fillText('AIR '+(w.air_temperature!=null?w.air_temperature.toFixed(0):'–')+'°  TRACK '+(w.track_temperature!=null?w.track_temperature.toFixed(0):'–')+'°', 20, 108);
    ctx.fillText('HUM '+(w.humidity!=null?w.humidity.toFixed(0):'–')+'%   WIND '+(w.wind_speed!=null?w.wind_speed.toFixed(1):'–')+' m/s '+(w.wind_direction!=null?Math.round(w.wind_direction):'–')+'°', 20, 124);
    if(w.rainfall){ ctx.fillStyle='#3B9BFF'; ctx.fillText('RAINING', 20, 140); }
  }
  ctx.fillStyle='#777'; ctx.font='11px Titillium Web,sans-serif';
  ctx.fillText('OpenF1 live feed · best-effort, short delay', 20, H-40);
}

function liveLeaderboard(codes){
  lbRects=[];
  var x=Math.max(20,W-RIGHT_M+12), w=240, rowH=25;
  ctx.fillStyle='rgba(12,12,16,.82)';
  ctx.fillRect(x-8, 30, w+8, Math.min(H-140, codes.length*rowH+40));
  ctx.fillStyle='#9B9BA8'; ctx.font='700 12px Titillium Web,sans-serif'; ctx.textAlign='left'; ctx.textBaseline='top';
  ctx.fillText('LEADERBOARD · LIVE', x, 38);
  codes.forEach(function(code,i){
    var c=LIVE.cars[code], y=58+i*rowH;
    if(y>H-60) return;
    var sel=selected.indexOf(code)>=0;
    if(sel){ ctx.fillStyle='rgba(225,6,0,.25)'; ctx.fillRect(x-6,y-3,w,rowH-2); }
    ctx.fillStyle='#888'; ctx.font='12px JetBrains Mono,monospace'; ctx.textAlign='right';
    ctx.fillText(String(c.pos||(i+1)), x+20, y);
    ctx.fillStyle=LIVE.colors[code]||'#FFF'; ctx.fillRect(x+26,y+1,4,12);
    ctx.fillStyle='#FFF'; ctx.font='700 13px Titillium Web,sans-serif'; ctx.textAlign='left';
    ctx.fillText(code, x+36, y);
    if(c.tyre!=null&&c.tyre>=0){ ctx.beginPath(); ctx.arc(x+90,y+7,6,0,7); ctx.strokeStyle=TYRES[c.tyre]; ctx.lineWidth=2.5; ctx.stroke(); }
    ctx.fillStyle='#AAA'; ctx.font='12px JetBrains Mono,monospace'; ctx.textAlign='right';
    var gap=(i===0)?'LEADER':(c.gap!=null?('+'+(typeof c.gap==='number'?c.gap.toFixed(1):c.gap)):'–');
    ctx.fillText(gap, x+w-8, y);
    lbRects.push([code, x-6, y-3, x+w-6, y+rowH-5]);
  });
}

/* ── data loading (replay) ──────────────────────────────────────────────── */
function initGeometry(){
  rot=(META.rotation||0)*Math.PI/180; cosR=Math.cos(rot); sinR=Math.sin(rot);
  wcx=0;wcy=0; var n=0; inner.concat(outer).forEach(function(p){wcx+=p[0];wcy+=p[1];n++;}); wcx/=(n||1); wcy/=(n||1);
  rInner=inner.map(function(p){return rotPt(p[0],p[1],wcx,wcy);});
  rOuter=outer.map(function(p){return rotPt(p[0],p[1],wcx,wcy);});
  rRef=ref.map(function(p){return rotPt(p[0],p[1],wcx,wcy);});
  refN=[];
  for(var i=0;i<rRef.length;i++){
    var a=rRef[Math.max(0,i-1)], b=rRef[Math.min(rRef.length-1,i+1)];
    var dx=b[0]-a[0], dy=b[1]-a[1], Ln=Math.hypot(dx,dy)||1;
    refN.push([-dy/Ln,dx/Ln]);
  }
}
function setReplayData(data){
  stopLive(); mode='replay';
  D=data; frames=D.frames||[]; NF=frames.length; FPS=D.fps||1; META=D.meta||{}; COLORS=D.colors||{};
  ref=(D.track&&D.track.ref)||[]; inner=(D.track&&D.track.inner)||[];
  outer=(D.track&&D.track.outer)||[]; drsZones=(D.track&&D.track.drs)||[];
  initGeometry(); fi=0; paused=false; selected=[]; lastTs=null;
  resize(); updateNote();
}
function updateNote(){
  var el=document.getElementById('rt-note'); if(!el) return;
  var gll=META.gps_last_lap, tl=META.total_laps;
  if(mode==='replay' && gll && tl && gll<tl){
    el.innerHTML='<div class="note" style="margin:0 0 12px;border-left-color:var(--amber)">⚠ <b>GPS coverage:</b> '
      +'car positions cover laps 1–'+gll+' of '+tl+' for this race (the upstream feed was cut); '
      +'playback switches to timing-only after.</div>';
  } else el.innerHTML='';
}
// replays load via <script> (JSONP) not fetch(), so the page also works when
// opened straight off disk as a file:// URL (where fetch() of a local file is
// blocked). Each replay/r{n}.js calls __onReplay(payload).
var _replayScript=null;
window.__onReplay=function(data){ setReplayData(data); setStatus('Replay · '+(META.event||'')); startLoop(); };
function loadRace(file){
  if(!file){ setStatus('No replay selected'); return; }
  setStatus('Loading replay…');
  if(_replayScript){ _replayScript.onerror=null; _replayScript.remove(); _replayScript=null; }
  var s=document.createElement('script');
  s.src='replay/'+file;
  s.onerror=function(){ setStatus('Could not load replay ('+file+')'); };
  _replayScript=s; document.head.appendChild(s);
}

/* ── unified loop ───────────────────────────────────────────────────────── */
function tick(ts){
  if(lastTs==null) lastTs=ts;
  var dt=(ts-lastTs)/1000; lastTs=ts;
  if(mode==='replay'){
    if(D && NF){
      var dir=holdRewind?-8:(holdForward?8:1);
      if(!paused||holdRewind||holdForward){
        fi+=dt*speed*FPS*dir;
        if(fi>=NF-1){fi=NF-1; paused=true;}
        if(fi<0) fi=0;
      }
      draw();
    } else { ctx.fillStyle='#000'; ctx.fillRect(0,0,W,H); }
  } else {
    drawLive();
  }
  requestAnimationFrame(tick);
}
function startLoop(){ if(!rafStarted){ rafStarted=true; requestAnimationFrame(tick); } }

/* ── input (the app's keymap; replay only) ──────────────────────────────── */
function speedStep(d){
  var i=PLAYBACK_SPEEDS.indexOf(speed); if(i<0)i=3;
  i=Math.max(0,Math.min(PLAYBACK_SPEEDS.length-1,i+d));
  speed=PLAYBACK_SPEEDS[i];
}
document.addEventListener('keydown',function(e){
  if(/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
  if(e.key==='l'||e.key==='L'){showLabels=!showLabels; return;}
  if(mode!=='replay') return;
  if(e.code==='Space'){e.preventDefault();paused=!paused;}
  else if(e.key==='ArrowLeft'){e.preventDefault();holdRewind=true;}
  else if(e.key==='ArrowRight'){e.preventDefault();holdForward=true;}
  else if(e.key==='ArrowUp'){e.preventDefault();speedStep(1);}
  else if(e.key==='ArrowDown'){e.preventDefault();speedStep(-1);}
  else if(e.key>='1'&&e.key<='4'){speed=[0.5,1,2,4][+e.key-1];}
  else if(e.key==='r'||e.key==='R'){fi=0;paused=false;}
  else if(e.key==='d'||e.key==='D'){showDRS=!showDRS;}
  else if(e.key==='b'||e.key==='B'){showProgress=!showProgress;}
});
document.addEventListener('keyup',function(e){
  if(e.key==='ArrowLeft')holdRewind=false;
  if(e.key==='ArrowRight')holdForward=false;
});
cv.addEventListener('click',function(e){
  var r=cv.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
  if(mode==='live'){
    for(var j=0;j<lbRects.length;j++){ var L=lbRects[j];
      if(mx>=L[1]&&my>=L[2]&&mx<=L[3]&&my<=L[4]){ toggleSel(L[0],e.shiftKey); return; } }
    return;
  }
  for(var i=0;i<buttons.length;i++){
    var b=buttons[i];
    if(mx>=b[1]&&mx<=b[3]&&my>=b[2]&&my<=b[4]){
      if(b[0]==='play')paused=!paused;
      else if(b[0]==='rew')fi=Math.max(0,fi-15*FPS*10);
      else if(b[0]==='fwd')fi=Math.min(NF-1,fi+15*FPS*10);
      else if(b[0]==='spd')speedStep(1);
      else if(b[0]==='rst'){fi=0;paused=false;}
      return;
    }
  }
  for(var j=0;j<lbRects.length;j++){
    var L=lbRects[j];
    if(mx>=L[1]&&my>=L[2]&&mx<=L[3]&&my<=L[4]){ toggleSel(L[0],e.shiftKey); return; }
  }
  if(!frames.length) return;
  var frame=frames[Math.min(Math.floor(fi),NF-1)];
  var best=null,bd=15*15;
  Object.keys(frame.d).forEach(function(code){
    var c=frame.d[code], rp=rotPt(c[0],c[1],wcx,wcy), s=w2s(rp);
    var d2=(s[0]-mx)*(s[0]-mx)+(s[1]-my)*(s[1]-my);
    if(d2<bd){bd=d2;best=code;}
  });
  if(best) toggleSel(best,e.shiftKey);
  var left=LEFT_M,right=W-RIGHT_M,bottom=H-30;
  if(showProgress&&my>=bottom-24&&my<=bottom&&mx>=left&&mx<=right){
    fi=((mx-left)/(right-left))*(NF-1);
  }
});
function toggleSel(code,multi){
  var i=selected.indexOf(code);
  if(multi){ i>=0?selected.splice(i,1):selected.push(code); }
  else if(i>=0&&selected.length===1){ selected=[]; }
  else { selected=[code]; }
}

/* ── wiring ─────────────────────────────────────────────────────────────── */
if(selEl){ selEl.addEventListener('change',function(){ userChoseReplay=true; stopLive(); loadRace(selEl.value); }); }
if(liveBtn){ liveBtn.addEventListener('click',function(){
  if(LIVE.active){ stopLive(); loadRace(selEl?selEl.value:''); return; }
  userChoseReplay=false;                 // explicit LIVE click re-enables auto-follow
  setStatus('Checking for a live session…');
  checkLive().then(function(s){
    if(s) startLive(s);
    else setStatus('No live session right now — showing replays. (Try again during a race weekend.)');
  });
}); }

/* ── init: auto-follow a live session, else load the latest replay ──────── */
resize(); startLoop();
if(!MANIFEST.races.length && !selEl){
  setStatus('No baked replays found — run python3 build.py.');
}
checkLive().then(function(s){
  if(s){ startLive(s); }
  else if(selEl && selEl.value){ loadRace(selEl.value); }
  else { setStatus('No replays available yet.'); }
});
// while idling on the default replay, quietly re-check every 90s so the page
// flips to LIVE on its own when a session goes green — but never override a
// replay the user explicitly picked (they can opt back in with the LIVE button)
setInterval(function(){
  if(LIVE.active || userChoseReplay) return;
  checkLive().then(function(s){ if(s && !LIVE.active && !userChoseReplay) startLive(s); });
}, 90000);
})();
"""
