"""Panel web embebido — solo stdlib (http.server).

Sirve un dashboard en http://0.0.0.0:<web_port> para monitorear y
configurar el host desde cualquier navegador de la red local.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config as config_mod
from .engine import MIN_SIGMA

PAGE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Viewifi Host</title>
<style>
:root{--bg:#0A0E14;--surface:#151A26;--surface2:#1C2230;--primary:#1B98E0;--cyan:#00E5FF;
--green:#00E676;--red:#FF1744;--amber:#FFC400;--text:#E8EDF5;--muted:#8B94A7;--radius:16px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,Roboto,sans-serif;min-height:100vh}
header{display:flex;align-items:center;gap:12px;padding:18px 24px;border-bottom:1px solid #222A3A;flex-wrap:wrap}
.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--primary),var(--cyan));
display:flex;align-items:center;justify-content:center;font-weight:800;color:#04121F}
h1{font-size:18px;font-weight:600}
.chip{margin-left:auto;padding:5px 14px;border-radius:999px;font-size:12px;font-weight:700;letter-spacing:.5px}
.chip.on{background:rgba(0,230,118,.12);color:var(--green);border:1px solid rgba(0,230,118,.35)}
.chip.alarm{background:rgba(255,23,68,.15);color:var(--red);border:1px solid rgba(255,23,68,.4)}
.chip.off{background:rgba(139,148,167,.12);color:var(--muted);border:1px solid #2A3244}
main{max-width:1100px;margin:0 auto;padding:24px;display:grid;gap:20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
.card{background:var(--surface);border:1px solid #222A3A;border-radius:var(--radius);padding:16px}
.card .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
.card .v{font-size:24px;font-weight:700;margin-top:6px}
.card .v small{font-size:13px;color:var(--muted);font-weight:400}
.panel{background:var(--surface);border:1px solid #222A3A;border-radius:var(--radius);padding:20px}
.panel h2{font-size:14px;font-weight:600;margin-bottom:14px;color:var(--cyan);letter-spacing:.5px}
canvas{width:100%;height:220px;display:block}
.btns{display:flex;gap:10px;flex-wrap:wrap}
button{cursor:pointer;border:none;border-radius:12px;padding:11px 18px;font-size:13px;font-weight:600;
background:var(--surface2);color:var(--text);transition:.15s}
button:hover{filter:brightness(1.2)}
button.primary{background:var(--primary);color:#fff}
button.danger{background:rgba(255,23,68,.15);color:var(--red)}
form{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
label{display:block;font-size:11px;color:var(--muted);margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px}
input,select{width:100%;background:var(--surface2);border:1px solid #2A3244;border-radius:10px;
padding:10px 12px;color:var(--text);font-size:14px}
input:focus{outline:none;border-color:var(--primary)}
.formfull{grid-column:1/-1}
.ev{display:flex;justify-content:space-between;align-items:center;padding:9px 4px;border-bottom:1px solid #1E2536;font-size:13px;gap:10px;flex-wrap:wrap}
.badge{padding:2px 10px;border-radius:999px;font-size:11px;font-weight:700}
.badge.HIGH{background:rgba(255,23,68,.15);color:var(--red)}
.badge.MEDIUM{background:rgba(255,196,0,.12);color:var(--amber)}
.badge.LOW,.badge.NONE{background:rgba(27,152,224,.12);color:var(--primary)}
.muted{color:var(--muted);font-size:12px}
#msg{font-size:13px;margin-top:10px;min-height:18px}
</style>
</head>
<body>
<header>
  <div class="logo">V</div>
  <h1>Viewifi Host <span class="muted" id="devname"></span></h1>
  <span class="chip off" id="chip">…</span>
</header>
<main>
  <div class="cards">
    <div class="card"><div class="k">Señal RSSI</div><div class="v" id="rssi">—</div></div>
    <div class="card"><div class="k">Línea base</div><div class="v" id="base">—</div></div>
    <div class="card"><div class="k">Ruido σ</div><div class="v" id="sigma">—</div></div>
    <div class="card"><div class="k">Desviación</div><div class="v" id="dev">—</div></div>
    <div class="card"><div class="k">Eventos hoy</div><div class="v" id="today">—</div></div>
  </div>

  <div class="panel"><h2>SEÑAL EN VIVO</h2><canvas id="chart"></canvas>
    <div class="muted">Azul punteada: línea base · roja punteada: umbral de alarma · puntos rojos: perturbación</div></div>

  <div class="panel"><h2>CONTROLES</h2>
    <div class="btns">
      <button class="primary" onclick="action('arm')">▶ Armar monitoreo</button>
      <button class="danger" onclick="action('disarm')">■ Desarmar</button>
      <button onclick="action('calibrate')">⟳ Recalibrar (30 s)</button>
      <button onclick="testTg()">✉ Probar Telegram</button>
    </div><div id="msg"></div></div>

  <div class="panel"><h2>CONFIGURACIÓN</h2>
    <form id="cfg" onsubmit="saveCfg(event)">
      <div><label>Nombre del host</label><input name="device_name"></div>
      <div><label>Zona</label><input name="zone"></div>
      <div><label>Sensibilidad (0.5–5, menor = más sensible)</label><input name="sensitivity" type="number" step="0.1" min="0.5" max="5"></div>
      <div><label>Intervalo muestreo (ms)</label><input name="sample_interval_ms" type="number" min="200" max="2000" step="50"></div>
      <div><label>Vigilancia (heartbeat)</label><select name="surveillance"><option value="true">Sí</option><option value="false">No</option></select></div>
      <div><label>Heartbeat cada (min, 0 = off)</label><input name="heartbeat_minutes" type="number" min="0" max="1440"></div>
      <div><label>Resumen diario</label><select name="digest_enabled"><option value="false">No</option><option value="true">Sí</option></select></div>
      <div><label>Horario protegido</label><select name="protected_schedule_enabled"><option value="false">No</option><option value="true">Sí</option></select></div>
      <div><label>Inicio protegido (min del día)</label><input name="protected_start_min" type="number" min="0" max="1439"></div>
      <div><label>Fin protegido (min del día)</label><input name="protected_end_min" type="number" min="0" max="1439"></div>
      <div><label>Evidencia: foto (fswebcam)</label><select name="evidence_photo"><option value="false">No</option><option value="true">Sí</option></select></div>
      <div><label>Evidencia: audio (arecord)</label><select name="evidence_audio"><option value="false">No</option><option value="true">Sí</option></select></div>
      <div><label>Telegram Bot Token</label><input name="telegram_bot_token" autocomplete="off"></div>
      <div><label>Telegram Chat ID</label><input name="telegram_chat_id"></div>
      <div><label>Supabase URL (opcional)</label><input name="supabase_url"></div>
      <div><label>Supabase Anon Key</label><input name="supabase_anon_key" autocomplete="off"></div>
      <div><label>Supabase Email</label><input name="supabase_email"></div>
      <div><label>Supabase Password</label><input name="supabase_password" type="password" placeholder="(vacío = no cambiar)"></div>
      <div><label>Puerto del panel web</label><input name="web_port" type="number" min="1024" max="65535"></div>
      <div><label>Contraseña del panel (vacío = abierto en LAN)</label><input name="web_password" type="password" placeholder="(vacío = no cambiar)"></div>
      <div class="formfull"><button class="primary" type="submit">Guardar configuración</button></div>
    </form></div>

  <div class="panel"><h2>EVENTOS RECIENTES</h2><div id="events" class="muted">Cargando…</div></div>
  <div class="muted" style="text-align:center">Viewifi Host · panel local · sin dependencias externas</div>
</main>
<script>
const KEY = localStorage.getItem('vkey') || '';
const H = KEY ? {'Authorization':'Bearer '+KEY} : {};
async function api(p, opt){ const r = await fetch(p, Object.assign({headers:Object.assign({},H,(opt||{}).headers)}, opt));
  if(r.status===401){ const k = prompt('Contraseña del panel:'); if(k){localStorage.setItem('vkey',k);location.reload();} throw 0; }
  return r.json(); }
const hist = [];
function draw(base, thr){
  const c = document.getElementById('chart'), x = c.getContext('2d');
  const W = c.width = c.clientWidth*2, Hh = c.height = 440;
  x.fillStyle='#0A0E14'; x.fillRect(0,0,W,Hh);
  if(hist.length<2) return;
  const vals = hist.map(p=>p[0]);
  let lo = Math.min(...vals, base-thr-1), hi = Math.max(...vals, base+thr+1);
  if(hi-lo<4){lo-=2;hi+=2;}
  const Y = v => Hh-20-(v-lo)/(hi-lo)*(Hh-40), X = i => 10+i/(hist.length-1)*(W-20);
  x.strokeStyle='#1E2536'; x.lineWidth=1; for(let g=0;g<5;g++){x.beginPath();x.moveTo(0,g*Hh/4);x.lineTo(W,g*Hh/4);x.stroke();}
  x.strokeStyle='#1B98E0'; x.setLineDash([6,6]); x.beginPath(); x.moveTo(0,Y(base)); x.lineTo(W,Y(base)); x.stroke();
  x.strokeStyle='#FF1744'; x.beginPath(); x.moveTo(0,Y(base-thr)); x.lineTo(W,Y(base-thr)); x.stroke();
  x.beginPath(); x.moveTo(0,Y(base+thr)); x.lineTo(W,Y(base+thr)); x.stroke(); x.setLineDash([]);
  x.strokeStyle='#00E5FF'; x.lineWidth=3; x.beginPath();
  hist.forEach((p,i)=> i?x.lineTo(X(i),Y(p[0])):x.moveTo(X(i),Y(p[0]))); x.stroke();
  hist.forEach((p,i)=>{ if(p[1]){ x.fillStyle='#FF1744'; x.beginPath(); x.arc(X(i),Y(p[0]),7,0,7); x.fill(); }});
}
async function tick(){
  try{
    const s = await api('/api/signal');
    document.getElementById('rssi').innerHTML = s.rssi===null?'—':s.rssi.toFixed(1)+' <small>dBm</small>';
    document.getElementById('base').innerHTML = s.baseline.toFixed(1)+' <small>dBm</small>';
    document.getElementById('sigma').textContent = s.sigma.toFixed(2);
    const dev = document.getElementById('dev');
    dev.textContent = s.deviation.toFixed(1)+' dB';
    dev.style.color = s.moving ? 'var(--red)' : 'var(--text)';
    document.getElementById('today').textContent = s.events_today;
    const chip = document.getElementById('chip');
    if(s.moving){chip.className='chip alarm';chip.textContent='● MOVIMIENTO';}
    else if(s.state==='MONITORING'){chip.className='chip on';chip.textContent='● MONITOREANDO';}
    else if(s.state==='CALIBRATING'){chip.className='chip on';chip.textContent='◌ CALIBRANDO';}
    else{chip.className='chip off';chip.textContent='○ DETENIDO';}
    if(s.rssi!==null){ hist.push([s.rssi, s.moving]); if(hist.length>160) hist.shift(); }
    draw(s.baseline, s.threshold);
  }catch(e){}
}
async function refreshAll(){
  try{
    const st = await api('/api/status');
    document.getElementById('devname').textContent = '· '+st.device_name+' · '+st.zone+' · '+st.source;
    const f = document.getElementById('cfg');
    for(const el of f.elements){ if(!el.name) continue;
      if(el.name==='web_password'||el.name==='supabase_password') continue;
      if(el.name in st.config) el.value = String(st.config[el.name]); }
    const ev = await api('/api/events');
    document.getElementById('events').innerHTML = ev.length
      ? ev.map(e=>`<div class="ev"><span><span class="badge ${e.level}">${e.level}</span> ${e.classification||''} ${e.rssi!==null?e.rssi+' dBm':''}</span><span class="muted">${e.ts}</span></div>`).join('')
      : '<span class="muted">Sin eventos todavía.</span>';
  }catch(e){}
}
async function action(cmd){ const r = await api('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd})});
  document.getElementById('msg').textContent = r.ok ? '✔ '+r.msg : '✘ '+r.msg; }
async function testTg(){ const r = await api('/api/telegram/test',{method:'POST'});
  document.getElementById('msg').textContent = r.ok ? '✔ Mensaje de prueba enviado' : '✘ '+(r.msg||'falló'); }
async function saveCfg(e){ e.preventDefault(); const f = e.target, cfg = {};
  for(const el of f.elements){ if(!el.name||el.value==='') continue;
    let v = el.value; if(el.type==='number') v = parseFloat(v); if(v==='true') v=true; if(v==='false') v=false;
    cfg[el.name]=v; }
  const r = await api('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
  document.getElementById('msg').textContent = r.ok ? '✔ Configuración guardada' : '✘ error al guardar'; }
tick(); refreshAll(); setInterval(tick, 1000); setInterval(refreshAll, 10000);
</script>
</body>
</html>
"""

# Claves de configuración editables desde el panel
EDITABLE = {
    "zone", "device_name", "sensitivity", "sample_interval_ms",
    "surveillance", "heartbeat_minutes", "digest_enabled",
    "protected_schedule_enabled", "protected_start_min", "protected_end_min",
    "evidence_photo", "evidence_audio",
    "telegram_bot_token", "telegram_chat_id",
    "supabase_url", "supabase_anon_key", "supabase_email", "supabase_password",
    "web_port", "web_password",
}


class _Handler(BaseHTTPRequestHandler):
    host = None  # ViewifiHost, asignado por start_dashboard

    def log_message(self, *args):
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(json.dumps(obj).encode(), "application/json", code)

    def _auth_ok(self) -> bool:
        pw = self.host.cfg.get("web_password") or ""
        if not pw:
            return True
        if self.headers.get("Authorization") == f"Bearer {pw}":
            return True
        q = parse_qs(urlparse(self.path).query)
        return q.get("key", [""])[0] == pw

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(PAGE.encode(), "text/html; charset=utf-8")
            return
        if not self._auth_ok():
            self._json({"error": "unauthorized"}, 401)
            return
        eng = self.host.engine
        if path == "/api/signal":
            rssi = self.host.last_rssi
            sigma = max(eng.sigma or MIN_SIGMA, MIN_SIGMA)
            threshold = max(eng.sensitivity * 0.6 * sigma, 1.5)
            self._json({
                "rssi": rssi,
                "moving": eng.elevated_run > 0,
                "state": eng.state,
                "deviation": abs(rssi - eng.calm_mean) if rssi is not None else 0.0,
                "baseline": eng.calm_mean,
                "sigma": sigma,
                "threshold": threshold,
                "events_today": self.host.store.count_today(),
            })
        elif path == "/api/status":
            cfg = dict(self.host.cfg)
            cfg["supabase_password"] = ""
            cfg["web_password"] = ""
            self._json({
                "device_name": cfg.get("device_name"),
                "zone": cfg.get("zone"),
                "source": self.host.source_name,
                "config": cfg,
            })
        elif path == "/api/events":
            rows = self.host.store.recent(30)
            self._json([{
                "ts": datetime.fromtimestamp(r[0] / 1000).strftime("%Y-%m-%d %H:%M:%S"),
                "level": r[1], "rssi": r[2], "variance": r[3],
                "classification": r[4], "zone": r[5],
            } for r in rows])
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._auth_ok():
            self._json({"error": "unauthorized"}, 401)
            return
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            body = {}
        if path == "/api/config":
            changed = {k: v for k, v in body.items() if k in EDITABLE}
            self.host.cfg.update(changed)
            config_mod.save(self.host.cfg)
            self.host.apply_config()
            self._json({"ok": True})
        elif path == "/api/action":
            cmd = body.get("cmd")
            if cmd == "arm":
                self.host.engine.arm()
                self._json({"ok": True, "msg": "Monitoreo armado"})
            elif cmd == "disarm":
                self.host.engine.disarm()
                self._json({"ok": True, "msg": "Monitoreo desarmado"})
            elif cmd == "calibrate":
                self.host.engine.start_calibration()
                self._json({"ok": True, "msg": "Recalibrando — mantén la sala quieta 30 s"})
            else:
                self._json({"ok": False, "msg": "comando desconocido"}, 400)
        elif path == "/api/telegram/test":
            if not self.host.bot.enabled:
                self._json({"ok": False, "msg": "configura el token y el chat ID primero"})
            else:
                self.host.bot.send_message(
                    f"✅ Viewifi test — panel web de {self.host.cfg['device_name']}")
                self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)


def start_dashboard(host, port: int) -> None:
    """Lanza el panel web en un hilo daemon."""
    _Handler.host = host
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
