# app.py
import os, time, threading, requests
from flask import Flask, request, jsonify, make_response, Response

EVCC_BASE = os.getenv("EVCC_BASE_URL", "http://172.16.1.179:7070/api").rstrip("/") + "/"
DEFAULT_LP = int(os.getenv("DEFAULT_LP_ID", "1"))
CHANGE_COOLDOWN = int(os.getenv("MODE_COOLDOWN_SECONDS", "120"))  # seconds

app = Flask(__name__)
sess = requests.Session()

# throttle state
_last_mode_by_lp = {}       # lp -> last successful mode set
_last_change_ts_by_lp = {}  # lp -> monotonic timestamp of last successful change
_lock = threading.Lock()

def evcc(path: str) -> str:
    return EVCC_BASE + path.lstrip("/")

def lp() -> int:
    return int(request.args.get("lp", DEFAULT_LP))

def _can_change_mode(lp_id: int, new_mode: str):
    now = time.monotonic()
    with _lock:
        last_mode = _last_mode_by_lp.get(lp_id)
        last_ts = _last_change_ts_by_lp.get(lp_id)
        if last_ts is None:
            return True, 0
        elapsed = now - last_ts
        if new_mode == last_mode:  # idempotent
            return True, 0
        if elapsed >= CHANGE_COOLDOWN:
            return True, 0
        retry_after = int(max(1, round(CHANGE_COOLDOWN - elapsed)))
        return False, retry_after

def _mark_changed(lp_id: int, new_mode: str):
    with _lock:
        _last_mode_by_lp[lp_id] = new_mode
        _last_change_ts_by_lp[lp_id] = time.monotonic()

def _cooldown_remaining(lp_id: int):
    with _lock:
        ts = _last_change_ts_by_lp.get(lp_id)
        if ts is None:
            return 0
        remaining = CHANGE_COOLDOWN - (time.monotonic() - ts)
        return int(max(0, round(remaining)))

# ---------- API proxy & controls ----------
@app.get("/status")
def status():
    r = sess.get(evcc("state"), timeout=5)
    r.raise_for_status()
    return jsonify(r.json())

@app.get("/cooldown")
def cooldown():
    lp_id = lp()
    return jsonify({
        "lp": lp_id,
        "remaining": _cooldown_remaining(lp_id),
        "window": CHANGE_COOLDOWN,
        "last_mode": _last_mode_by_lp.get(lp_id)
    })

@app.post("/mode/<mode>")
def set_mode(mode):
    lp_id = lp()
    ok, retry_after = _can_change_mode(lp_id, mode)
    if not ok:
        msg = {
            "error": "mode-change-throttled",
            "detail": f"Loadpoint {lp_id} mode was changed recently. Try again in ~{retry_after}s.",
            "retry_after_seconds": retry_after,
            "cooldown_seconds": CHANGE_COOLDOWN
        }
        resp = make_response(jsonify(msg), 429)
        resp.headers["Retry-After"] = str(retry_after)
        return resp

    r = sess.post(evcc(f"loadpoints/{lp_id}/mode/{mode}"), timeout=5)
    if r.status_code >= 400:
        return make_response(jsonify({
            "error": "evcc-error",
            "status": r.status_code,
            "body": r.text
        }), r.status_code)

    _mark_changed(lp_id, mode)
    return jsonify({"lp": lp_id, "mode": mode, "evcc": r.text})

# Aliases (go through the throttle)
@app.post("/start")
def start():  return set_mode.__wrapped__("now")   # type: ignore
@app.post("/stop")
def stop():   return set_mode.__wrapped__("off")   # type: ignore
@app.post("/pv")
def pv():     return set_mode.__wrapped__("pv")    # type: ignore
@app.post("/minpv")
def minpv():  return set_mode.__wrapped__("minpv") # type: ignore

@app.post("/maxcurrent/<int:amps>")
def maxcurrent(amps):
    lp_id = lp()
    r = sess.post(evcc(f"loadpoints/{lp_id}/maxcurrent/{amps}"), timeout=5)
    if r.status_code >= 400:
        return make_response(jsonify({
            "error": "evcc-error",
            "status": r.status_code,
            "body": r.text
        }), r.status_code)
    return jsonify({"lp": lp_id, "maxcurrent": amps, "evcc": r.text})

# ---------- Web UI ----------
@app.get("/")
def ui():
    # Single-file HTML UI with inline CSS+JS
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>evcc Control Panel</title>
  <style>
    :root {{ --card:#ffffff; --bg:#0f172a; --muted:#64748b; --ok:#16a34a; --warn:#ea580c; --err:#dc2626; --accent:#2563eb; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Arial; background:var(--bg); color:#e5e7eb; }}
    header {{ padding:16px 20px; display:flex; gap:12px; align-items:center; border-bottom:1px solid #1f2937; }}
    h1 {{ font-size:18px; margin:0; font-weight:600; }}
    main {{ padding:20px; display:grid; gap:16px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
    .card {{ background:var(--card); color:#0b1220; border-radius:14px; padding:16px; box-shadow: 0 6px 22px rgba(0,0,0,.18); }}
    .row {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
    .grow {{ flex:1 1 auto; }}
    label {{ font-size:12px; color:var(--muted); display:block; margin-bottom:6px; }}
    select,input,button {{ border:1px solid #e5e7eb; border-radius:10px; padding:10px 12px; font-size:14px; background:white; color:#0b1220; }}
    button.primary {{ background:var(--accent); color:white; border-color:transparent; }}
    button.ghost {{ background:white; }}
    button:disabled {{ opacity:.6; cursor:not-allowed; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
    .kv {{ display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px dashed #e5e7eb; }}
    .pill {{ font-size:12px; padding:4px 8px; border-radius:999px; background:#eef2ff; color:#3730a3; }}
    .status-ok {{ color:var(--ok); }}
    .status-warn {{ color:var(--warn); }}
    .status-err {{ color:var(--err); }}
    .small {{ font-size:12px; color:var(--muted); }}
    footer {{ text-align:center; color:#94a3b8; font-size:12px; padding:18px; }}
    .spacer {{ height:8px; }}
  </style>
</head>
<body>
  <header>
    <h1>evcc Control Panel</h1>
    <span id="siteTitle" class="small"></span>
    <div class="grow"></div>
    <span class="small">Cooldown window: <strong id="cooldownWindow">{CHANGE_COOLDOWN}s</strong></span>
  </header>

  <main>
    <section class="card">
      <div class="row">
        <div class="grow">
          <label>Loadpoint</label>
          <select id="lpSelect"></select>
        </div>
        <div>
          <label>Cooldown</label>
          <div><span id="cooldownPill" class="pill">calculating…</span></div>
        </div>
      </div>

      <div class="spacer"></div>

      <div class="row">
        <button class="primary" id="btnStart">Start (now)</button>
        <button class="ghost" id="btnStop">Stop (off)</button>
        <button class="ghost" id="btnPV">PV</button>
        <button class="ghost" id="btnMinPV">MinPV</button>
      </div>

      <div class="spacer"></div>

      <div class="row">
        <div>
          <label>Max current (A)</label>
          <div class="row">
            <input id="amps" type="number" min="6" max="32" value="16" style="width:100px"/>
            <button id="btnSetAmps">Set</button>
          </div>
        </div>
        <div class="grow"></div>
      </div>
    </section>

    <section class="card">
      <h3 style="margin-top:0;">Live status</h3>
      <div class="grid">
        <div class="kv"><span>LP Title</span><strong id="lpTitle">—</strong></div>
        <div class="kv"><span>Mode</span><strong id="lpMode">—</strong></div>
        <div class="kv"><span>Enabled</span><strong id="lpEnabled">—</strong></div>
        <div class="kv"><span>Charging</span><strong id="lpCharging">—</strong></div>
        <div class="kv"><span>Connected</span><strong id="lpConnected">—</strong></div>
        <div class="kv"><span>Offer Current</span><strong id="lpOffer">—</strong></div>
        <div class="kv"><span>Max/Min Current</span><strong id="lpCurrents">—</strong></div>
        <div class="kv"><span>Power</span><strong id="lpPower">—</strong></div>
        <div class="kv"><span>Vehicle</span><strong id="lpVehicle">—</strong></div>
        <div class="kv"><span>Grid Power</span><strong id="gridPower">—</strong></div>
        <div class="kv"><span>PV Power</span><strong id="pvPower">—</strong></div>
        <div class="kv"><span>Home Power</span><strong id="homePower">—</strong></div>
      </div>
      <div class="small" id="lastUpdated">—</div>
    </section>
  </main>

  <footer>Backend: {EVCC_BASE}</footer>

<script>
const el = id => document.getElementById(id);
let lpId = {DEFAULT_LP};

function prettyBool(v) {{
  if (v === true) return '<span class="status-ok">yes</span>';
  if (v === false) return '<span class="status-err">no</span>';
  return '—';
}}

async function fetchJSON(url, opts={{}}) {{
  const r = await fetch(url, opts);
  const ct = r.headers.get('content-type') || '';
  const isJSON = ct.includes('application/json');
  if (!r.ok) {{
    const text = await r.text();
    throw new Error(text || ('HTTP '+r.status));
  }}
  return isJSON ? r.json() : r.text();
}}

async function refreshStatus() {{
  try {{
    const data = await fetchJSON('/status');
    el('siteTitle').textContent = data.siteTitle || '';
    const lps = data.loadpoints || [];
    // build LP selector once
    const sel = el('lpSelect');
    if (!sel.dataset.built) {{
      sel.innerHTML = lps.map((lp, i) => `<option value="${{i+1}}">${{i+1}} — ${{lp.title || 'LP ' + (i+1)}}</option>`).join('');
      sel.value = String(lpId);
      sel.dataset.built = '1';
      sel.addEventListener('change', () => {{
        lpId = parseInt(sel.value, 10);
        refreshStatus();
        refreshCooldown();
      }});
    }}
    const lp = lps[(lpId-1)] || {{}};

    el('lpTitle').textContent = lp.title ?? '—';
    el('lpMode').textContent = lp.mode ?? '—';
    el('lpEnabled').innerHTML = prettyBool(lp.enabled);
    el('lpCharging').innerHTML = prettyBool(lp.charging);
    el('lpConnected').innerHTML = prettyBool(lp.connected);
    el('lpOffer').textContent = (lp.offeredCurrent ?? 0) + ' A';
    el('lpCurrents').textContent = (lp.maxCurrent ?? '—') + ' / ' + (lp.minCurrent ?? '—') + ' A';
    el('lpPower').textContent = (lp.chargePower ?? 0).toFixed(1) + ' W';
    el('lpVehicle').textContent = (lp.vehicleTitle || lp.vehicleName || '—');

    el('gridPower').textContent = (data.grid?.power ?? 0).toFixed(1) + ' W';
    el('pvPower').textContent   = (data.pvPower ?? 0).toFixed(1) + ' W';
    el('homePower').textContent = (data.homePower ?? 0).toFixed(1) + ' W';
    el('lastUpdated').textContent = 'Last updated: ' + new Date().toLocaleTimeString();

  }} catch (e) {{
    console.error(e);
  }}
}}

async function refreshCooldown() {{
  try {{
    const cd = await fetchJSON('/cooldown?lp=' + lpId);
    const rem = cd.remaining || 0;
    const pill = el('cooldownPill');
    if (rem > 0) {{
      pill.textContent = rem + 's remaining';
      pill.style.background = '#fef3c7';
      pill.style.color = '#9a3412';
    }} else {{
      pill.textContent = 'ready';
      pill.style.background = '#dcfce7';
      pill.style.color = '#14532d';
    }}
  }} catch (e) {{ console.error(e); }}
}}

async function callMode(mode) {{
  try {{
    const r = await fetch('/mode/' + mode + '?lp=' + lpId, {{ method: 'POST' }});
    if (r.status === 429) {{
      const j = await r.json();
      alert('Cooldown: ' + (j.detail || 'Try again later.'));
    }} else if (!r.ok) {{
      const t = await r.text();
      alert('Error: ' + t);
    }}
  }} catch (e) {{ alert('Network error: ' + e.message); }}
  finally {{
    refreshCooldown();
    setTimeout(refreshStatus, 500);
  }}
}}

async function setAmps() {{
  const a = parseInt(el('amps').value, 10);
  if (isNaN(a) || a <= 0) return;
  try {{
    const r = await fetch('/maxcurrent/' + a + '?lp=' + lpId, {{ method: 'POST' }});
    if (!r.ok) {{
      const t = await r.text();
      alert('Error: ' + t);
    }}
  }} catch (e) {{ alert('Network error: ' + e.message); }}
  finally {{
    setTimeout(refreshStatus, 500);
  }}
}}

function wire() {{
  el('btnStart').addEventListener('click', () => callMode('now'));
  el('btnStop').addEventListener('click', () => callMode('off'));
  el('btnPV').addEventListener('click', () => callMode('pv'));
  el('btnMinPV').addEventListener('click', () => callMode('minpv'));
  el('btnSetAmps').addEventListener('click', setAmps);
  refreshStatus();
  refreshCooldown();
  setInterval(refreshStatus, 5000);
  setInterval(refreshCooldown, 1000);
}}
document.addEventListener('DOMContentLoaded', wire);
</script>
</body>
</html>"""
    return Response(html, mimetype="text/html")

if __name__ == "__main__":
    app.run(host=os.getenv("FLASK_HOST", "0.0.0.0"),
            port=int(os.getenv("FLASK_PORT", "5080")))
