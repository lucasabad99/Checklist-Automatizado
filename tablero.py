"""
tablero.py — Tablero de estado en vivo para pantalla de oficina (Pecom Energía)

Pensado para dejarlo abierto en una TV/monitor de la oficina en pantalla
completa. NO ejecuta ningún check ni toca mouse/teclado: solo consulta por
HTTP el endpoint /estado.json que expone dashboard_reporte_diario.py (esa sí
corre los checks, en tu PC) y redibuja las tarjetas cada REFRESH_SEGUNDOS.

Muestra el Reporte Diario (WhatsUp Gold, Email Helpdesk, URLs Corporativas,
3CX) — no el checklist viejo de 8 pasos. Ninguno de esos 4 checks se
re-ejecuta solo: WhatsUp Gold abre una ventana real, el mail a Helpdesk es
un ticket real, y 3CX origina una llamada real, así que el tablero siempre
muestra el resultado de la última corrida MANUAL ("Generar Reporte Diario"
en el panel).

──────────────────────────────────────────────────────────────────────────────
CÓMO USARLO
──────────────────────────────────────────────────────────────────────────────
1) En la PC de IT (la que genera el reporte), dejá corriendo:

       python dashboard_reporte_diario.py

   Al arrancar te va a imprimir algo como:
       Estado en vivo para el tablero de TV:  http://192.168.1.50:5010/estado.json

2) Copiá esa IP y pegala en EJECUTOR_URL más abajo (sin el /estado.json).

3) En la PC/TV que solo va a MOSTRAR el tablero, corré:

       python tablero.py

   Abrí el navegador en http://127.0.0.1:5050 y ponelo en pantalla completa
   (F11). Se va a ir actualizando solo.

NOTA: para que esto funcione, ambas PCs tienen que estar en la misma red y
el firewall de Windows de la PC de IT tiene que permitir conexiones
entrantes al puerto 5010 (si no lo permitís, va a mostrar "Sin conexión").
"""

import json
import urllib.request
from datetime import datetime

from flask import Flask, Response, jsonify

# ═════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN — editá esta sección
# ═════════════════════════════════════════════════════════════════════════════

EJECUTOR_URL     = "http://127.0.0.1:5010"      # ← IP de la PC donde corre dashboard_reporte_diario.py (127.0.0.1 = misma PC)
REFRESH_SEGUNDOS = 30                            # cada cuánto se refresca el tablero
PUERTO_LOCAL     = 5050

# ═════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)


@app.route("/proxy_estado.json")
def proxy_estado():
    """
    Pide el estado al Ejecutor desde el servidor (Python), no desde el
    navegador de la TV — así evitamos líos de CORS y timeouts largos
    colgando la pestaña.
    """
    try:
        with urllib.request.urlopen(f"{EJECUTOR_URL}/estado.json", timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        data["_conexion"] = "ok"
        return jsonify(data)
    except Exception as e:
        return jsonify({"_conexion": "error", "_error": f"{type(e).__name__}: {e}"})


@app.route("/")
def index():
    return Response(HTML.replace("__REFRESH_MS__", str(REFRESH_SEGUNDOS * 1000)),
                     mimetype="text/html")


HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tablero — Pecom Energía</title>
<style>
  :root{
    --navy:#1B3F6B; --navy-2:#16365d; --green:#1a7340; --green-soft:#e8f3ec;
    --red:#C62828; --red-soft:#fceaea; --amber:#E65100; --amber-soft:#fff4e8;
    --bg:#0e1726; --card:#ffffff; --line:#d7dce5; --ink:#222; --muted:#6a7280;
  }
  *{box-sizing:border-box;}
  html,body{height:100%;}
  body{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:"Segoe UI",Calibri,system-ui,Arial,sans-serif;
    overflow:hidden;
  }
  .wrap{height:100vh; display:flex; flex-direction:column;}

  /* Header */
  header{background:linear-gradient(180deg,var(--navy) 0%,var(--navy-2) 100%); color:#fff; flex:none;}
  .hd{padding:22px 40px; display:flex; align-items:center; justify-content:space-between; gap:24px;}
  .brand .logo{font-size:34px; font-weight:800; letter-spacing:4px; line-height:1;}
  .brand .sub{font-size:12px; letter-spacing:4px; color:#86b3da; margin-top:2px;}
  .brand .ttl{font-size:15px; color:#bcd6ee; margin-top:10px;}
  .clock{text-align:right;}
  .clock .d{font-size:22px; font-weight:700; text-transform:capitalize;}
  .clock .t{font-size:28px; font-weight:800; color:#9bc0e4; font-variant-numeric:tabular-nums;}
  .conn{display:flex; align-items:center; gap:8px; font-size:13px; color:#bcd6ee; margin-top:8px; justify-content:flex-end;}
  .conn .dot{width:9px; height:9px; border-radius:50%; background:#6cc24a;}
  .conn.err .dot{background:#ff6b6b; animation:blink 1s infinite;}
  @keyframes blink{0%,100%{opacity:1;} 50%{opacity:.3;}}

  /* Banner global */
  .banner{flex:none; padding:18px 40px; color:#fff; display:flex; align-items:center; justify-content:space-between;}
  .banner.ok{background:linear-gradient(135deg,var(--green) 0%,#155c34 100%);}
  .banner.fail{background:linear-gradient(135deg,var(--red) 0%,#9e1f1f 100%);}
  .banner.warn{background:linear-gradient(135deg,var(--amber) 0%,#b23c00 100%);}
  .banner.empty{background:#3a4a5f;}
  .banner .b-left{display:flex; align-items:center; gap:18px;}
  .banner .b-icon{width:46px; height:46px; flex:none; display:flex; align-items:center;
                   justify-content:center; background:rgba(255,255,255,.16); border-radius:13px;}
  .banner .b-icon svg{width:26px; height:26px;}
  .banner .b1{font-size:25px; font-weight:800; letter-spacing:.3px;}
  .banner .b2{font-size:14px; opacity:.9; margin-top:3px;}
  .banner .big{font-size:42px; font-weight:800; font-variant-numeric:tabular-nums;}

  /* Grid de tarjetas */
  main{flex:1; padding:26px 40px; overflow:hidden;}
  .grid{
    height:100%;
    display:grid;
    grid-template-columns:repeat(auto-fit, minmax(270px, 1fr));
    grid-auto-rows:1fr;
    gap:22px;
  }
  .card{
    position:relative; overflow:hidden;
    background:var(--card); border:1px solid var(--line); border-radius:18px;
    padding:22px 24px; display:flex; flex-direction:column;
    box-shadow:0 8px 20px rgba(15,25,45,.14);
    border-left-width:8px;
  }
  .card.ok{border-left-color:var(--green); background:linear-gradient(165deg,#ffffff 0%,#f2faf5 100%);}
  .card.warn{border-left-color:var(--amber); background:linear-gradient(165deg,#ffffff 0%,#fff8ef 100%);}
  .card.fail{border-left-color:var(--red); background:linear-gradient(165deg,#ffffff 0%,#fdf3f3 100%);}

  /* Ícono grande y tenue de fondo, decorativo — llena el espacio vacío de la tarjeta */
  .card .wm{position:absolute; right:-20px; bottom:-24px; width:148px; height:148px;
            opacity:.07; pointer-events:none;}
  .card.ok .wm{color:var(--green);} .card.warn .wm{color:var(--amber);} .card.fail .wm{color:var(--red);}

  .card .top{display:flex; justify-content:space-between; align-items:flex-start; gap:12px; position:relative; z-index:1;}
  .card .titlewrap{display:flex; align-items:center; gap:13px; min-width:0;}
  .icon-badge{width:40px; height:40px; border-radius:12px; display:flex; align-items:center;
              justify-content:center; flex:none;}
  .icon-badge svg{width:21px; height:21px;}
  .icon-badge.ok{background:var(--green-soft); color:var(--green);}
  .icon-badge.warn{background:var(--amber-soft); color:var(--amber);}
  .icon-badge.fail{background:var(--red-soft); color:var(--red);}
  .card .nombre{font-size:18px; font-weight:700; color:var(--navy); line-height:1.28;}

  .pill{flex:none; font-size:13px; font-weight:800; padding:6px 14px; border-radius:99px;
        letter-spacing:.4px; display:flex; align-items:center; gap:6px;}
  .pill svg{width:14px; height:14px;}
  .pill.ok{background:var(--green-soft); color:var(--green);}
  .pill.warn{background:var(--amber-soft); color:var(--amber);}
  .pill.fail{background:var(--red-soft); color:var(--red);}

  .card .body{flex:1; display:flex; align-items:center; position:relative; z-index:1; padding:16px 0;}
  .card .detalle{font-size:17px; color:#374151; line-height:1.5; font-weight:500;
                  display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical; overflow:hidden;}

  /* Desglose (ej. WhatsUp Gold por widget): más claro que una sola frase */
  .desglose{width:100%;}
  .desglose-cap{font-size:13px; color:var(--muted); font-weight:700; margin-bottom:10px;}
  .d-row{display:flex; justify-content:space-between; align-items:center;
         padding:9px 2px; border-bottom:1px solid #eef1f6;}
  .d-row:last-child{border-bottom:none;}
  .d-label{font-size:14.5px; color:#374151; font-weight:600;}
  .d-val{font-size:15px; font-weight:800; padding:3px 12px; border-radius:8px; letter-spacing:.3px;}
  .d-val.ok{background:var(--green-soft); color:var(--green);}
  .d-val.warn{background:var(--amber-soft); color:var(--amber);}
  .d-val.fail{background:var(--red-soft); color:var(--red);}

  /* Sub-filas indentadas: el detalle puntual debajo de su categoría
     (ej. cada equipo caído debajo de "Down Active Monitors") */
  .d-row.indent{padding:5px 2px 5px 18px; border-bottom:none;}
  .d-row.indent .d-label{font-size:12.5px; color:var(--muted); font-weight:500;}
  .d-row.indent .d-label::before{content:"– "; opacity:.7;}
  .d-row.indent .d-val{font-size:11.5px; font-weight:700; padding:2px 9px;}

  .card .foot{font-size:13px; color:var(--muted); margin-top:auto; padding-top:14px;
              border-top:1px solid #eef1f6; display:flex; align-items:center; gap:7px;
              position:relative; z-index:1;}
  .card .foot svg{width:14px; height:14px; flex:none; opacity:.65;}
  .foot-auto{color:#2563a8; font-weight:700;}
  .foot-manual{color:#5b3aa8; font-weight:700;}
  .foot-info{color:#6a7280; font-weight:700;}

  .empty-state{
    color:#bcd6ee; text-align:center; margin:auto; font-size:20px;
  }

  footer{flex:none; padding:10px 40px; color:#7f8ea3; font-size:12px; text-align:center;}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="hd">
      <div class="brand">
        <div class="logo">PECOM</div>
        <div class="sub">ENERGÍA</div>
        <div class="ttl">Tablero de Sistemas IT — Estado en Vivo</div>
      </div>
      <div class="clock">
        <div class="d" id="fecha">—</div>
        <div class="t" id="hora">—</div>
        <div class="conn" id="conn"><span class="dot"></span><span id="connTxt">Conectando…</span></div>
      </div>
    </div>
  </header>

  <div class="banner empty" id="banner">
    <div class="b-left">
      <div class="b-icon" id="bannerIcon"></div>
      <div>
        <div class="b1" id="bannerT">Esperando datos…</div>
        <div class="b2" id="bannerS">Ejecutá el checklist desde el dashboard para ver resultados acá.</div>
      </div>
    </div>
    <div class="big" id="bannerBig"></div>
  </div>

  <main>
    <div class="grid" id="grid">
      <div class="empty-state">Sin datos todavía.</div>
    </div>
  </main>

  <footer id="footerTxt">Actualiza cada """ + "__REFRESH_MS__" + r"""ms</footer>
</div>

<script>
const REFRESH_MS = __REFRESH_MS__;
const $ = s => document.querySelector(s);
let ultimoBueno = null;

// Íconos monolínea, inline (sin dependencias externas). ICONS guarda solo
// los <path>/<circle> internos; svg() arma el <svg> alrededor.
const ICONS = {
  activity: '<path d="M3 12h4l3 8 4-16 3 8h4"/>',
  mail:     '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
  globe:    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18"/>',
  phone:    '<path d="M5 4h3.5l1.8 4.5-2.1 2.1a12 12 0 0 0 5.2 5.2l2.1-2.1L20 15.5V19a1.5 1.5 0 0 1-1.6 1.5A15.5 15.5 0 0 1 4 5.6 1.5 1.5 0 0 1 5 4z"/>',
  server:   '<rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><circle cx="7.3" cy="7" r="0.8" fill="currentColor" stroke="none"/><circle cx="7.3" cy="17" r="0.8" fill="currentColor" stroke="none"/>',
  clock:    '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 3.2"/>',
  check:    '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.6 2.6L16 9.5"/>',
  alert:    '<path d="M12 3.5l9.3 16.1a1 1 0 0 1-.87 1.5H3.57a1 1 0 0 1-.87-1.5L12 3.5z"/><path d="M12 10v4.2"/><path d="M12 17.3v.1"/>',
  x:        '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
  info:     '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.7v.1"/>',
  shield:   '<path d="M12 3.3l7 2.7v5.6c0 4.6-3 7.9-7 9.1-4-1.2-7-4.5-7-9.1V6l7-2.7z"/>',
  grid:     '<rect x="3" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.6"/>',
};
function svg(key){
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">${ICONS[key] || ICONS.server}</svg>`;
}
function iconoPara(nombre){
  const n = (nombre || "").toLowerCase();
  if(n.includes("whatsup")) return "activity";
  if(n.includes("email") || n.includes("mail")) return "mail";
  if(n.includes("url")) return "globe";
  if(n.includes("3cx") || n.includes("llamada") || n.includes("telefon")) return "phone";
  if(n.includes("acceso") || n.includes("remoto") || n.includes("hes")) return "shield";
  if(n.includes("otros sistemas")) return "grid";
  return "server";
}

function tick(){
  const n = new Date();
  $("#fecha").textContent = n.toLocaleDateString("es-AR", {weekday:"long", day:"numeric", month:"long"});
  $("#hora").textContent  = n.toLocaleTimeString("es-AR");
}
tick(); setInterval(tick, 1000);

function haceCuanto(iso){
  if(!iso) return "sin datos";
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.floor(ms/60000);
  if(min < 1) return "hace instantes";
  if(min < 60) return `hace ${min} min`;
  const h = Math.floor(min/60);
  return `hace ${h} h ${min % 60} min`;
}

function render(data){
  const items = data.items || [];

  if(!items.length){
    $("#grid").innerHTML = '<div class="empty-state">Sin datos todavía — generá el reporte diario desde el panel.</div>';
    $("#banner").className = "banner empty";
    $("#bannerIcon").innerHTML = svg("clock");
    $("#bannerT").textContent = "Esperando datos…";
    $("#bannerS").textContent = "Generá el reporte diario desde el panel de control para ver resultados acá.";
    $("#bannerBig").textContent = "";
    return;
  }

  const ok = data.ok, fail = data.fail, total = data.total;
  // estado_global (OK/PARCIAL/FALLA) viene del reporte diario y es más preciso
  // que un simple conteo ok/fail (distingue "alertas" de "fallo duro").
  const eg = data.estado_global;
  const claseBanner = eg ? {OK:"ok", PARCIAL:"warn", FALLA:"fail"}[eg] || "fail" : (fail === 0 ? "ok" : "fail");
  const iconoBanner = claseBanner === "ok" ? "check" : (claseBanner === "warn" ? "alert" : "x");
  const b = $("#banner");
  b.className = "banner " + claseBanner;
  $("#bannerIcon").innerHTML = svg(iconoBanner);
  $("#bannerT").textContent = claseBanner === "ok" ? "TODAS LAS VERIFICACIONES OK"
    : claseBanner === "warn" ? "REPORTE CON ALERTAS PARCIALES"
    : `${fail} VERIFICACIÓN(ES) CON FALLO`;
  $("#bannerS").textContent = data.ultima_corrida_manual
    ? `Última corrida manual completa: ${haceCuanto(data.ultima_corrida_manual)}`
    : "Todavía no se generó el reporte diario manualmente.";
  $("#bannerBig").textContent = `${ok}/${total}`;

  // Los items del reporte diario no traen timestamp propio (solo los "auto"
  // del checklist viejo lo tenían) — usamos el de la última corrida global.
  const tsManualTxt = data.ultima_corrida_manual ? haceCuanto(data.ultima_corrida_manual) : "sin corridas";

  const grid = $("#grid");
  grid.innerHTML = "";
  items.forEach(it => {
    const estado = it.estado || (it.ok ? "ok" : "fail");
    const etiqueta = estado === "ok" ? "OK" : (estado === "warn" ? "ALERTA" : "FALLO");
    const pillIcono = estado === "ok" ? "check" : (estado === "warn" ? "alert" : "x");
    const icono = iconoPara(it.nombre);
    const card = document.createElement("div");
    card.className = "card " + estado;
    const foot = it.informativo
      ? `${svg("info")}<span class="foot-info">Informativo</span>&nbsp;· sin chequeo automatizado`
      : it.auto
        ? `${svg("clock")}<span class="foot-auto">Auto</span>&nbsp;· ${haceCuanto(it.timestamp)}`
        : `${svg("clock")}<span class="foot-manual">Manual</span>&nbsp;· ${tsManualTxt}`;

    // Si el item trae desglose (ej. WhatsUp Gold por widget, o los problemas
    // de URLs Corporativas), lo mostramos como una mini-lista clara en vez
    // de una sola frase — pensado para leerse de lejos en cartelería. La
    // frase corta de "detalle" queda arriba como leyenda de contexto.
    const cuerpo = (it.desglose && it.desglose.length)
      ? `<div class="desglose">
           ${it.detalle ? `<div class="desglose-cap">${it.detalle}</div>` : ""}
           ${it.desglose.map(d => `
             <div class="d-row${d.indent ? ' indent' : ''}">
               <div class="d-label">${d.etiqueta}</div>
               ${d.valor ? `<div class="d-val ${d.estado}">${d.valor}</div>` : ""}
             </div>`).join("")}
         </div>`
      : `<div class="detalle">${it.detalle || "Sin detalle."}</div>`;

    card.innerHTML = `
      <div class="wm">${svg(icono)}</div>
      <div class="top">
        <div class="titlewrap">
          <div class="icon-badge ${estado}">${svg(icono)}</div>
          <div class="nombre">${it.nombre}</div>
        </div>
        <div class="pill ${estado}">${svg(pillIcono)}${etiqueta}</div>
      </div>
      <div class="body">${cuerpo}</div>
      <div class="foot">${foot}</div>`;
    grid.appendChild(card);
  });
}

function setConexion(ok){
  const c = $("#conn");
  c.className = "conn" + (ok ? "" : " err");
  $("#connTxt").textContent = ok ? "En vivo" : "Sin conexión — mostrando últimos datos";
}

function refrescar(){
  fetch("/proxy_estado.json", {cache:"no-store"})
    .then(r => r.json())
    .then(data => {
      if(data._conexion === "ok"){
        setConexion(true);
        ultimoBueno = data;
        render(data);
      } else {
        setConexion(false);
        if(ultimoBueno) render(ultimoBueno);
      }
    })
    .catch(() => {
      setConexion(false);
      if(ultimoBueno) render(ultimoBueno);
    });
}

refrescar();
setInterval(refrescar, REFRESH_MS);
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Tablero de TV corriendo en:  http://127.0.0.1:%d" % PUERTO_LOCAL)
    print(f"  Consultando datos de:        {EJECUTOR_URL}/estado.json")
    print("  Abrí esa URL en el navegador de la TV y poné pantalla completa (F11).")
    print("  (Ctrl+C para detener)")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=PUERTO_LOCAL, threaded=True, use_reloader=False, debug=False)
