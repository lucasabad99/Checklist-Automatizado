"""
dashboard_reporte_diario.py — Panel de control del Reporte Diario (Pecom Energía)

Es un panel DISTINTO de dashboard.py: dashboard.py corre el checklist completo
de 8 pasos (3CX, Citrix, SAP, Portales SSO, Humand, Email, WhatsUp Gold,
Certificados). Este panel corre específicamente check_reporte_diario.py, que
es el flujo de 4 pasos (WhatsUp Gold, Email Helpdesk, URLs Corporativas, 3CX)
que ya se le mostró al jefe.

Control manual, a propósito: "Generar Reporte Diario" arma el reporte y NO
manda nada. Recién con el botón "Enviar por email" (aparte, después de
revisar el preview) se dispara el envío real a los destinatarios configurados
abajo. Así, si algo salió mal en la corrida, nunca se manda con errores.

Uso:
    python dashboard_reporte_diario.py
    → abrí http://127.0.0.1:5010
"""

import os
import sys
import queue
import socket
import threading
from pathlib import Path
from datetime import datetime

# Windows a veces arranca este proceso con la consola/salida en un codepage
# que no soporta ✓/✗/→ ni tildes (típico si se redirige la salida a un
# archivo o se lanza sin una consola UTF-8). Forzamos UTF-8 acá para que
# ningún print() de los módulos que importamos (WhatsUp Gold, 3CX, URLs
# Corporativas...) pueda tirar abajo una corrida por esto.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from flask import Flask, Response, jsonify, request, abort, send_file

import check_reporte_diario as rep
import programador_reporte

app = Flask(__name__)


# ═════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN — editá esta sección
# ═════════════════════════════════════════════════════════════════════════════

# Destinatario principal — Santiago (gerente). Outlook resuelve el nombre
# contra la libreta de direcciones igual que si se tipeara a mano (ver
# validación de destinatarios en check_reporte_diario._enviar_mail_consolidado).
DESTINATARIO_PRINCIPAL = "Castiñeiras, Santiago Hernan"

# Copias (CC)
MAIL_CC: list[str] = [
    "operaciones-it@pecomenergia.com.ar",
    "Ciberseguridad@pecomenergia.com.ar",
    "Agustin.BrunoTouzon@pecomenergia.com.ar",
    "USRS-ServiceDelivery@pecomenergia.com.ar",
    "Karina.Alfonsin@pecomenergia.com.ar",
    "Juan.Grosso@pecomenergia.com.ar",
    "sergio.vilar@pecomenergia.com.ar",
    "Gonzalo.Fresch@pecomenergia.com.ar",
]

# True = URLs Corporativas corre sin abrir ventanas de navegador visibles.
HEADLESS = False

PUERTO = 5010

# ═════════════════════════════════════════════════════════════════════════════

EVIDENCIAS_DIR = "evidencias_whatsupgold"

_corriendo = {"activo": False}


# ══════════════════════════════════════════════════════════════════════════════
#  Ejecución en segundo plano + SSE
# ══════════════════════════════════════════════════════════════════════════════

def _sse(event: str, data: dict) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _hilo_run(q: queue.Queue, headless: bool):
    # Varios pasos (Email Helpdesk vía Outlook) usan win32com; cada hilo
    # nuevo necesita su propio CoInitialize antes de tocar COM.
    import pythoncom
    pythoncom.CoInitialize()
    try:
        rep.correr_reporte_diario(headless=headless, progress_queue=q)
    except RuntimeError as e:
        # Choque con el programador automático (o con otra corrida manual) —
        # no es un error de la corrida en sí, solo hay que esperar.
        q.put(f"[REPORTE] {e}")
    except Exception as e:
        q.put(f"[REPORTE] ERROR fatal: {type(e).__name__}: {e}")
    finally:
        pythoncom.CoUninitialize()
        q.put(None)   # centinela: fin de la corrida


@app.route("/run")
def run():
    def stream():
        if _corriendo["activo"]:
            yield _sse("error", {"mensaje": "Ya hay una corrida en curso."})
            return

        _corriendo["activo"] = True
        q: queue.Queue = queue.Queue()
        t = threading.Thread(target=_hilo_run, args=(q, HEADLESS), daemon=True)
        t.start()

        yield _sse("start", {})
        try:
            while True:
                msg = q.get()
                if msg is None:
                    break
                yield _sse("log", {"linea": msg})
        finally:
            _corriendo["activo"] = False

        data = rep.obtener_ultima_corrida_reporte()
        ts = data["timestamp"].isoformat(timespec="seconds") if data.get("timestamp") else None
        yield _sse("done", {"estado_global": data.get("estado_global"), "timestamp": ts})

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Evidencias (para que el preview en navegador pueda mostrar las imágenes)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/evidencia")
def evidencia():
    name = request.args.get("name", "")
    base = Path(EVIDENCIAS_DIR).resolve()
    f = (base / name).resolve()
    if not str(f).startswith(str(base) + os.sep) or not f.exists():
        abort(404)
    return send_file(str(f))


# ══════════════════════════════════════════════════════════════════════════════
#  Reporte: preview + envío manual
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/email/preview")
def email_preview():
    def resolver(i, titulo, ruta):
        return f"/evidencia?name={ruta.name}"

    try:
        html = rep.construir_html_preview(resolver)
    except RuntimeError:
        html = (
            "<div style='font-family:Segoe UI,sans-serif;padding:60px;"
            "text-align:center;color:#8a93a2;'>"
            "Todavía no se generó ningún reporte en esta sesión.<br>"
            "Corré el reporte diario primero.</div>"
        )
    return Response(html, mimetype="text/html")


@app.route("/destinatarios")
def destinatarios():
    return jsonify({"to": DESTINATARIO_PRINCIPAL, "cc": MAIL_CC})


# ══════════════════════════════════════════════════════════════════════════════
#  Estado para el tablero de TV (ver tablero.py)
# ══════════════════════════════════════════════════════════════════════════════
# A diferencia del checklist viejo, acá NINGÚN paso se re-ejecuta solo en
# segundo plano: WhatsUp Gold abre una ventana real, Email Helpdesk manda un
# ticket real, y 3CX origina una llamada real — ninguno de los tres es seguro
# para correr desatendido en un timer. El tablero muestra siempre el
# resultado de la última corrida MANUAL ("Generar Reporte Diario").

@app.route("/estado.json")
def estado_json():
    items = rep.obtener_items_tablero()
    data = rep.obtener_ultima_corrida_reporte()
    ts = data["timestamp"].isoformat(timespec="seconds") if data.get("timestamp") else None

    # El contador global (el "N/M" del banner) solo cuenta verificaciones
    # reales — las 2 tarjetas informativas (Accesos Remotos, Otros Sistemas)
    # siempre son OK porque no tienen chequeo automatizado detrás, y las
    # incluiríamos acá diluiría el número si hay fallas reales.
    items_reales = [i for i in items if not i.get("informativo")]
    ok_n = sum(1 for i in items_reales if i["ok"])
    total_reales = len(items_reales)

    resp = jsonify({
        "generado": datetime.now().isoformat(timespec="seconds"),
        # Nombre histórico "ultima_corrida_manual" pisado a propósito: con el
        # programador automático esto ya no es necesariamente manual — es la
        # última vez que CUALQUIER sección se actualizó (manual o automática).
        "ultima_actualizacion": ts,
        "estado_global": data.get("estado_global"),
        "ok": ok_n,
        "fail": total_reales - ok_n,
        "total": total_reales,
        "items": items,
    })
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def _ip_local() -> str:
    """Mejor esfuerzo para mostrar la IP LAN de esta PC (la que hay que
    poner en EJECUTOR_URL dentro de tablero.py)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


@app.route("/email/send", methods=["POST"])
def email_send():
    import pythoncom
    pythoncom.CoInitialize()
    try:
        ok = rep.enviar_ultimo_reporte(
            destinatarios=[DESTINATARIO_PRINCIPAL],
            cc=MAIL_CC,
            preview=False,
        )
        return jsonify({"ok": ok, "to": DESTINATARIO_PRINCIPAL, "cc": MAIL_CC})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"})
    finally:
        pythoncom.CoUninitialize()


# ══════════════════════════════════════════════════════════════════════════════
#  Frontend
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")


HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Reporte Diario — Pecom Energía</title>
<style>
  :root{
    --navy:#1B3F6B; --navy-2:#16365d; --green:#1a7340; --green-soft:#e8f3ec;
    --red:#C62828; --red-soft:#fceaea; --amber:#E65100; --amber-soft:#fff4e8;
    --bg:#edf0f5; --card:#ffffff; --line:#d7dce5; --ink:#222; --muted:#6a7280;
    --blue:#2563a8;
  }
  *{box-sizing:border-box;}
  body{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:"Segoe UI",Calibri,system-ui,Arial,sans-serif; font-size:15px;
  }
  .wrap{max-width:900px; margin:0 auto; padding:0 18px 60px;}

  header{background:linear-gradient(180deg,var(--navy) 0%,var(--navy-2) 100%); color:#fff;}
  .hd{max-width:900px; margin:0 auto; padding:24px 18px; display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap;}
  .brand .logo{font-size:30px; font-weight:800; letter-spacing:3px; line-height:1;}
  .brand .sub{font-size:11px; letter-spacing:3px; color:#86b3da; margin-top:1px;}
  .brand .ttl{font-size:14px; color:#bcd6ee; margin-top:9px;}
  .clock{text-align:right;}
  .clock .d{font-size:20px; font-weight:700;}
  .clock .t{font-size:13px; color:#9bc0e4; margin-top:2px;}

  .panel{background:var(--card); border:1px solid var(--line); border-radius:12px;
         margin-top:22px; padding:20px; box-shadow:0 1px 3px rgba(20,40,80,.06);}
  .controls{display:flex; align-items:center; gap:12px; flex-wrap:wrap;}
  button{font-family:inherit; cursor:pointer; border:none; border-radius:8px; font-weight:600;}
  .btn-run{background:var(--green); color:#fff; font-size:16px; padding:13px 26px;
           box-shadow:0 2px 6px rgba(26,115,64,.3); transition:filter .15s;}
  .btn-run:hover:not(:disabled){filter:brightness(1.07);}
  .btn-run:disabled{background:#9bb6a6; cursor:not-allowed; box-shadow:none;}
  .btn-sec{background:#eef2f8; color:var(--navy); border:1px solid var(--line); font-size:14px; padding:11px 16px;}
  .btn-sec:hover:not(:disabled){background:#e2e9f3;}
  .btn-sec:disabled{opacity:.45; cursor:not-allowed;}
  .btn-send{background:var(--navy); color:#fff; font-size:14px; padding:11px 18px;}
  .btn-send:hover:not(:disabled){filter:brightness(1.1);}
  .btn-send:disabled{background:#9aa8bd; cursor:not-allowed;}
  .spacer{flex:1;}
  .elapsed{font-variant-numeric:tabular-nums; color:var(--muted); font-size:13px;}

  .banner{margin-top:18px; padding:15px 18px; border-radius:10px; color:#fff;}
  .banner.ok{background:var(--green);} .banner.fail{background:var(--red);}
  .banner.parcial{background:var(--amber);} .banner.idle{background:#8a93a2;}
  .banner .b1{font-size:16px; font-weight:700;}
  .banner .b2{font-size:13px; opacity:.92; margin-top:3px;}

  .console{margin-top:18px; background:#0e1726; border-radius:10px; padding:14px 16px;
           font-family:"Cascadia Code","Consolas",monospace; font-size:12.5px; color:#c6d5e8;
           height:260px; overflow-y:auto; white-space:pre-wrap; line-height:1.6;
           display:none;}
  .console.show{display:block;}
  .console .ln{opacity:0; animation:fadein .2s forwards;}
  @keyframes fadein{to{opacity:1;}}

  .sect{margin:30px 0 12px; font-size:12px; font-weight:700; letter-spacing:1.5px;
        color:var(--navy); text-transform:uppercase;}
  .hint{font-size:13px; color:var(--muted); margin-top:6px;}

  .modal{display:none; position:fixed; inset:0; background:rgba(15,25,45,.72); z-index:50;
         align-items:center; justify-content:center; padding:24px;}
  .modal.show{display:flex;}
  .modal-box{background:#fff; border-radius:12px; width:min(820px,100%); max-height:88vh; overflow:hidden; display:flex; flex-direction:column;}
  .modal-hd{padding:13px 18px; background:var(--navy); color:#fff; display:flex; justify-content:space-between; align-items:center;}
  .modal-hd b{font-size:14px;}
  .modal-x{background:rgba(255,255,255,.16); color:#fff; border-radius:7px; padding:5px 11px; font-size:14px;}
  .modal-box iframe{border:none; width:100%; height:74vh; background:#edf0f5;}

  .toast{position:fixed; bottom:24px; left:50%; transform:translateX(-50%) translateY(20px);
         background:#222; color:#fff; padding:12px 20px; border-radius:9px; font-size:14px;
         opacity:0; pointer-events:none; transition:all .25s; z-index:60; max-width:90%;}
  .toast.show{opacity:1; transform:translateX(-50%) translateY(0);}
  .toast.ok{background:var(--green);} .toast.err{background:var(--red);}
</style>
</head>
<body>
<header>
  <div class="hd">
    <div class="brand">
      <div class="logo">PECOM</div>
      <div class="sub">ENERGÍA</div>
      <div class="ttl">Reporte Diario IT — Panel de Control</div>
    </div>
    <div class="clock">
      <div class="d" id="fecha">—</div>
      <div class="t" id="hora">—</div>
    </div>
  </div>
</header>

<div class="wrap">

  <div class="panel">
    <div class="controls">
      <button class="btn-run" id="btnRun">▶  Generar Reporte Diario</button>
      <button class="btn-sec" id="btnReporte" disabled>Ver reporte</button>
      <button class="btn-send" id="btnEmail" disabled>✉  Enviar por email</button>
      <span class="spacer"></span>
      <span class="elapsed" id="elapsed"></span>
    </div>
    <div class="banner idle" id="banner">
      <div class="b1" id="bannerT">Todavía no se generó ningún reporte</div>
      <div class="b2" id="bannerS">Apretá "Generar Reporte Diario" para correr WhatsUp Gold, Email Helpdesk, URLs Corporativas y 3CX.</div>
    </div>
    <div class="console" id="console"></div>
  </div>

  <div class="hint">
    El envío es manual a propósito: primero se corre y arma el reporte, después lo revisás con
    "Ver reporte", y recién ahí "Enviar por email" lo manda a los destinatarios configurados
    (te va a mostrar exactamente a quién antes de confirmar).
  </div>

</div>

<div class="modal" id="mReport">
  <div class="modal-box">
    <div class="modal-hd"><b>Vista previa del reporte diario</b>
      <button class="modal-x" data-close="mReport">Cerrar ✕</button></div>
    <iframe id="reportFrame"></iframe>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const $ = s => document.querySelector(s);

function tick(){
  const n = new Date();
  $("#fecha").textContent = n.toLocaleDateString("es-AR");
  $("#hora").textContent  = n.toLocaleTimeString("es-AR") + " hs";
}
tick(); setInterval(tick, 1000);

function fmt(s){ return Math.floor(s/60)+"m "+String(s%60).padStart(2,"0")+"s"; }

let es = null, t0 = 0, timer = null, huboReporte = false;

$("#btnRun").addEventListener("click", () => {
  if(es){ es.close(); }
  $("#btnRun").disabled = true;
  $("#btnReporte").disabled = true;
  $("#btnEmail").disabled = true;

  const cons = $("#console");
  cons.innerHTML = ""; cons.classList.add("show");

  const b = $("#banner");
  b.className = "banner idle";
  $("#bannerT").textContent = "Corriendo…";
  $("#bannerS").textContent = "WhatsUp Gold → Email Helpdesk → URLs Corporativas → 3CX";

  t0 = Date.now();
  clearInterval(timer);
  timer = setInterval(() => { $("#elapsed").textContent = "⏱ " + fmt(Math.floor((Date.now()-t0)/1000)); }, 1000);

  es = new EventSource("/run");

  es.addEventListener("log", e => {
    const d = JSON.parse(e.data);
    const line = document.createElement("div");
    line.className = "ln";
    line.textContent = d.linea;
    cons.appendChild(line);
    cons.scrollTop = cons.scrollHeight;
  });

  es.addEventListener("error", e => {
    let msg = "Se interrumpió la conexión con el servidor.";
    try{ msg = JSON.parse(e.data).mensaje || msg; }catch(_){}
    toast(msg, "err");
    es.close(); es = null;
    clearInterval(timer);
    $("#btnRun").disabled = false;
  });

  es.addEventListener("done", e => {
    const d = JSON.parse(e.data);
    es.close(); es = null;
    clearInterval(timer);
    $("#btnRun").disabled = false;
    $("#btnReporte").disabled = false;

    const estado = d.estado_global || "FALLA";
    huboReporte = true;
    $("#btnEmail").disabled = false;

    const clase = estado === "OK" ? "ok" : (estado === "PARCIAL" ? "parcial" : "fail");
    b.className = "banner " + clase;
    $("#bannerT").textContent = estado === "OK"
      ? "✓  Reporte generado — todo OK"
      : (estado === "PARCIAL" ? "⚠  Reporte generado — con alertas parciales" : "✗  Reporte generado — con fallas");
    $("#bannerS").textContent = `Revisalo con "Ver reporte" antes de enviarlo · ${fmt(Math.floor((Date.now()-t0)/1000))}`;
  });

  es.onerror = () => {
    if(es){ es.close(); es = null; }
    clearInterval(timer);
    $("#btnRun").disabled = false;
  };
});

$("#btnReporte").addEventListener("click", () => {
  $("#reportFrame").src = "/email/preview?ts=" + Date.now();
  openModal("mReport");
});

$("#btnEmail").addEventListener("click", () => {
  if(!huboReporte) return;
  fetch("/destinatarios").then(r => r.json()).then(d => {
    const ccTxt = (d.cc && d.cc.length) ? d.cc.join(", ") : "(sin copias configuradas)";
    const msg = `¿Enviar el reporte por Outlook?\n\nPara: ${d.to}\nCC: ${ccTxt}`;
    if(!confirm(msg)) return;
    $("#btnEmail").disabled = true;
    fetch("/email/send", {method:"POST"})
      .then(r => r.json())
      .then(j => {
        if(j.ok) toast("✓ Reporte enviado a " + j.to, "ok");
        else toast("Error al enviar: " + (j.error || "desconocido"), "err");
      })
      .catch(() => toast("No se pudo contactar al servidor.", "err"))
      .finally(() => { $("#btnEmail").disabled = false; });
  });
});

function openModal(id){ $("#"+id).classList.add("show"); }
document.querySelectorAll("[data-close]").forEach(b =>
  b.addEventListener("click", () => $("#"+b.dataset.close).classList.remove("show")));
document.querySelectorAll(".modal").forEach(m =>
  m.addEventListener("click", e => { if(e.target === m) m.classList.remove("show"); }));

let toastT = null;
function toast(msg, kind){
  const t = $("#toast"); t.textContent = msg; t.className = "toast show " + (kind||"");
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 4500);
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    rep.cargar_estado_reporte()
    programador_reporte.iniciar()

    ip = _ip_local()
    print("\n" + "=" * 60)
    print("  Panel de Reporte Diario corriendo en:  http://127.0.0.1:%d" % PUERTO)
    print(f"  Estado en vivo para el tablero de TV:  http://{ip}:{PUERTO}/estado.json")
    print("  (usá esa IP como EJECUTOR_URL en tablero.py)")
    print(f"  Destinatario principal: {DESTINATARIO_PRINCIPAL}")
    print(f"  CC: {', '.join(MAIL_CC) if MAIL_CC else '(sin copias configuradas)'}")
    print("  (editá DESTINATARIO_PRINCIPAL / MAIL_CC arriba en este archivo)")
    print("  (Ctrl+C para detener)")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=PUERTO, threaded=True, use_reloader=False, debug=False)
