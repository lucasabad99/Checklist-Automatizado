"""
dashboard.py — Interfaz web local para el Checklist Automatizado Pecom Energía

Levanta un mini servidor web en tu propia máquina y abre un panel con un botón
"Ejecutar Checklist". Al apretarlo, corre los 7 módulos de tu checklist.py EN VIVO,
mostrando el estado de cada uno (Pendiente → En ejecución → OK/Fallo), la evidencia
generada y un preview del reporte de email.

NO modifica checklist.py: lo importa y reutiliza sus funciones paso_*() y _resultados.

──────────────────────────────────────────────────────────────────────────────
USO
──────────────────────────────────────────────────────────────────────────────
1) Instalá Flask una sola vez (en la terminal de VS Code, dentro de tu carpeta Python):

       pip install flask

2) Dejá este archivo en la MISMA carpeta que checklist.py
   (C:\\Users\\leabadc\\OneDrive - Pecom\\Escritorio\\Python\\)

3) Corré:

       python dashboard.py

4) Abrí el navegador en:  http://127.0.0.1:5000

IMPORTANTE: dejá la terminal de VS Code abierta mientras hacés la demo. Los módulos
que usan pyautogui / 3CX / Citrix necesitan la sesión de escritorio visible y
desbloqueada, y si algún paso pide "presioná Enter", lo pide en la terminal.
"""

import os
import sys
import json
import time
import socket
import threading
from pathlib import Path
from datetime import datetime

# Windows a veces arranca este proceso con la consola/salida en un codepage
# que no soporta ✓/✗/→ ni tildes (típico si se redirige la salida a un
# archivo o se lanza sin una consola UTF-8). Forzamos UTF-8 acá para que
# ningún print() de los módulos que importamos pueda tirar abajo una corrida.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from flask import Flask, Response, send_file, jsonify, request, abort

# Importamos TU checklist tal cual. El bloque `if __name__ == "__main__"` de
# checklist.py NO se ejecuta al importarlo, así que es seguro.
import checklist as cl

# Módulo WhatsUp Gold — captura los widgets del dashboard de monitoreo y
# envía su propio reporte por Outlook con las evidencias embebidas inline.
import check_whatsupgold as wug

app = Flask(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Tablero de TV — estado en vivo para consumo remoto (ver tablero.py)
# ══════════════════════════════════════════════════════════════════════════════
# Certificados SSL es el único check 100% headless (sockets puros, sin
# navegador ni automatización de escritorio), así que es el único que se
# re-ejecuta solo en segundo plano. El resto de los pasos (3CX, Citrix, SAP,
# Portales SSO, Humand, WhatsUp Gold) requieren pantalla/mouse visibles o
# abren una ventana real de Edge, así que el tablero solo muestra el
# resultado de la última corrida MANUAL del checklist completo.

CERTS_REFRESH_SEGUNDOS = 15 * 60   # cada cuánto se refrescan solos los certificados
ESTADO_JSON_PATH = Path("estado_actual.json")

_estado_certs = {"timestamp": None, "ok": None, "detalle": "", "items": []}
_estado_certs_lock = threading.Lock()
_ultima_corrida_ts = None   # datetime de la última corrida MANUAL completa


def _refrescar_certificados():
    """Vuelve a chequear los certificados SSL y actualiza _estado_certs.
    Aislado de cl._resultados a propósito: no debe pisar ni interferir con
    una corrida manual del checklist completo que esté en curso."""
    from check_certificados import check_certificado, URLS

    items, vencidos, alertas, errores = [], [], [], []
    for url in URLS:
        r = check_certificado(url)
        items.append(r)
        if not r["ok"]:
            errores.append(r["host"])
        elif r.get("vencido"):
            vencidos.append(r["host"])
        elif r.get("alerta"):
            alertas.append(r["host"])

    if vencidos:
        ok, detalle = False, f"VENCIDOS: {', '.join(vencidos)}"
    elif errores:
        ok, detalle = False, f"Sin acceso: {', '.join(errores)}"
    elif alertas:
        ok, detalle = True, f"Por vencer pronto: {', '.join(alertas)}"
    else:
        ok, detalle = True, f"{len(URLS)} certificados válidos"

    with _estado_certs_lock:
        _estado_certs.update({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "ok": ok,
            "detalle": detalle,
            "items": items,
        })
    _persistir_estado()
    print(f"[TABLERO] Certificados SSL actualizados automáticamente — {detalle}")


def _certs_loop():
    while True:
        try:
            _refrescar_certificados()
        except Exception as e:
            print(f"[TABLERO] Error refrescando certificados: {type(e).__name__}: {e}")
        time.sleep(CERTS_REFRESH_SEGUNDOS)


def _construir_estado_dict() -> dict:
    """Arma el JSON que consume tablero.py: los resultados de la última
    corrida manual, con el item de Certificados SSL siempre reemplazado por
    la versión más fresca (auto-refrescada en segundo plano)."""
    with _estado_certs_lock:
        certs = dict(_estado_certs)

    items = []
    vistos_certs = False
    for r in cl._resultados:
        if r["nombre"] == "Certificados SSL":
            vistos_certs = True
            items.append({
                "nombre": "Certificados SSL",
                "ok": certs.get("ok"),
                "detalle": certs.get("detalle", ""),
                "items": certs.get("items", []),
                "auto": True,
                "timestamp": certs.get("timestamp"),
            })
        else:
            items.append({
                "nombre": r["nombre"],
                "ok": r["ok"],
                "detalle": r.get("detalle", ""),
                "auto": False,
            })

    # Si todavía no corrió el checklist completo pero ya hay certificados
    # auto-refrescados, los mostramos igual (mejor que un tablero vacío).
    if not vistos_certs and certs.get("timestamp"):
        items.insert(0, {
            "nombre": "Certificados SSL",
            "ok": certs.get("ok"),
            "detalle": certs.get("detalle", ""),
            "items": certs.get("items", []),
            "auto": True,
            "timestamp": certs.get("timestamp"),
        })

    ok_n = sum(1 for i in items if i["ok"])
    fail_n = len(items) - ok_n

    return {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "ultima_corrida_manual": _ultima_corrida_ts.isoformat(timespec="seconds") if _ultima_corrida_ts else None,
        "ok": ok_n,
        "fail": fail_n,
        "total": len(items),
        "items": items,
    }


def _persistir_estado():
    try:
        ESTADO_JSON_PATH.write_text(
            json.dumps(_construir_estado_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[TABLERO] Error persistiendo estado: {type(e).__name__}: {e}")


def _cargar_estado_inicial():
    """Restaura el último estado conocido al arrancar dashboard.py, para que
    un reinicio del proceso no deje el tablero en blanco hasta la próxima
    corrida manual."""
    if not ESTADO_JSON_PATH.exists():
        return
    try:
        data = json.loads(ESTADO_JSON_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[TABLERO] No se pudo leer estado previo: {type(e).__name__}: {e}")
        return

    global _ultima_corrida_ts
    ts = data.get("ultima_corrida_manual")
    if ts:
        try:
            _ultima_corrida_ts = datetime.fromisoformat(ts)
        except ValueError:
            pass

    cl._resultados.clear()
    for it in data.get("items", []):
        cl._resultados.append({
            "nombre": it["nombre"],
            "ok": it["ok"],
            "detalle": it.get("detalle", ""),
            "items": it.get("items", []) if it.get("nombre") == "Certificados SSL" else [],
        })
        if it.get("nombre") == "Certificados SSL" and it.get("auto"):
            with _estado_certs_lock:
                _estado_certs.update({
                    "timestamp": it.get("timestamp"),
                    "ok": it.get("ok"),
                    "detalle": it.get("detalle", ""),
                    "items": it.get("items", []),
                })
    print(f"[TABLERO] Estado previo restaurado ({len(cl._resultados)} items, "
          f"última corrida manual: {ts or 'nunca'})")


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


@app.route("/estado.json")
def estado_json():
    resp = jsonify(_construir_estado_dict())
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


# ── Wrapper del módulo WhatsUp Gold para integrarlo al dashboard ──────────────
# Traduce la firma bool → resultado registrado en cl._resultados, igual que
# los otros pasos. Ejecutado desde el dashboard, el módulo también manda su
# propio mail dedicado con las capturas (comportamiento controlado por
# MODO_PREVIEW_MAIL dentro de check_whatsupgold.py).
def paso_whatsupgold():
    nombre = "WhatsUp Gold — Down Monitors + Disk Utilization"
    try:
        # enviar_mail=False: el mail de WUG NO se manda por separado acá.
        # Las evidencias se inyectan en el reporte consolidado y se envían
        # juntas cuando se aprieta "Enviar por email" (ver email_send()).
        ok = wug.check_whatsupgold(enviar_mail=False)
        detalle = (
            "Evidencias capturadas y reporte enviado por Outlook"
            if ok else
            "Con errores — revisar consola (login, timeout o extracción)"
        )
        cl._reg(nombre, ok, detalle)
    except Exception as e:
        cl._reg(nombre, False, f"{type(e).__name__}: {e}")

# ── Pasos: (función de checklist.py, nombre visible) ──────────────────────────
# El orden y los nombres coinciden con los que usa _reg() en checklist.py.
STEPS = [
    (cl.paso_certificados,   "Certificados SSL"),
    (cl.paso_3cx,            "Telefonía IP — 3CX"),
    (cl.paso_citrix_rdp,     "Citrix / Remote Desktop"),
    (cl.paso_sap,            "SAP ECC Producción"),
    (cl.paso_sso_portales,   "Portales Internos (Facilities + Compras)"),
    (cl.paso_humand_sso,     "Acceso SSO — Humand"),
    (cl.paso_email_helpdesk, "Email Helpdesk (Outlook)"),
    (paso_whatsupgold,       "WhatsUp Gold — Monitoreo"),
]
STEP_NAMES = [n for _, n in STEPS]

# Carpetas de evidencia que genera el checklist
EVID_DIRS = [
    "evidencias",
    "evidencias_citrix",
    "evidencias_sso_portales",
    "evidencias_whatsupgold",
]
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")


# ══════════════════════════════════════════════════════════════════════════════
#  SSE — ejecución en vivo
# ══════════════════════════════════════════════════════════════════════════════

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _run_stream():
    """Corre los pasos uno por uno y va emitiendo eventos al navegador."""
    cl._resultados.clear()  # reseteamos para que cada corrida arranque limpia
    inicio = time.time()
    yield _sse("start", {"steps": STEP_NAMES})

    for i, (fn, nombre) in enumerate(STEPS):
        yield _sse("step_start", {"index": i, "name": nombre})
        antes = len(cl._resultados)
        try:
            fn()
        except SystemExit as e:
            # Algunos módulos hacen sys.exit; lo tratamos como resultado del paso.
            if len(cl._resultados) == antes:
                cl._reg(nombre, getattr(e, "code", 1) in (0, None))
        except Exception as e:
            if len(cl._resultados) == antes:
                cl._reg(nombre, False, f"{type(e).__name__}: {e}")

        # Leemos el resultado que el paso acaba de registrar
        if len(cl._resultados) > antes:
            r = cl._resultados[-1]
        else:
            r = {"nombre": nombre, "ok": False, "detalle": "Sin resultado registrado"}

        yield _sse("step_done", {
            "index": i,
            "name": r.get("nombre", nombre),
            "ok": bool(r.get("ok")),
            "detalle": r.get("detalle", ""),
        })

    ok_n = sum(1 for r in cl._resultados if r["ok"])
    fail_n = len(cl._resultados) - ok_n

    global _ultima_corrida_ts
    _ultima_corrida_ts = datetime.now()
    _persistir_estado()

    yield _sse("done", {
        "ok": ok_n,
        "fail": fail_n,
        "total": len(cl._resultados),
        "segundos": int(time.time() - inicio),
    })


@app.route("/run")
def run():
    return Response(
        _run_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Evidencias (capturas de pantalla)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/evidencias")
def evidencias():
    out = []
    for d in EVID_DIRS:
        p = Path(d)
        if not p.exists():
            continue
        imgs = [f for f in p.glob("*") if f.suffix.lower() in IMG_EXT]
        imgs.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        for f in imgs[:8]:
            out.append({
                "dir": d,
                "name": f.name,
                "url": f"/evidencia?dir={d}&name={f.name}",
                "mtime": int(f.stat().st_mtime),
            })
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify(out)


@app.route("/evidencia")
def evidencia():
    d = request.args.get("dir", "")
    name = request.args.get("name", "")
    if d not in EVID_DIRS:
        abort(404)
    base = Path(d).resolve()
    f = (base / name).resolve()
    if not str(f).startswith(str(base) + os.sep) or not f.exists():
        abort(404)  # evita path traversal
    return send_file(str(f))


# ══════════════════════════════════════════════════════════════════════════════
#  Reporte por email (preview + envío manual)
#  → Enriquecemos el reporte consolidado con las secciones de WhatsUp Gold
#    (imágenes de widgets + resumen textual) capturadas por check_whatsupgold.
# ══════════════════════════════════════════════════════════════════════════════

def _inyectar_widgets_wug_html(html_base: str, image_src_resolver) -> str:
    """
    Toma el HTML del reporte consolidado y le injecta la sección de WhatsUp Gold
    ANTES del cierre del reporte (línea horizontal + Saludos). Si no hay widgets
    capturados aún, devuelve el HTML tal cual.

    Estrategia: probamos varios marcadores en orden de preferencia, para que la
    inyección funcione con distintos formatos posibles del HTML de checklist.py.

    image_src_resolver: función (i, titulo, Path) -> str, define cómo referenciar
                        cada imagen (URL http para preview, cid: para email).
    """
    import re as _re

    seccion = wug.render_secciones_html(image_src_resolver)
    if not seccion:
        return html_base

    # Envolvemos la sección en un contenedor de tabla-friendly para que si el
    # HTML base es un template de tabla no se rompa la estructura.
    seccion_envuelta = (
        '<div style="font-family:Segoe UI,sans-serif;'
        'max-width:700px;margin:24px auto;">'
        + seccion +
        '</div>'
    )

    # 1) Antes del tag de apertura que contiene "Saludos"
    #    (ej: <p>Saludos,</p> → inyecta antes de <p>)
    # NOTA: no usamos el primer <hr> del documento como marcador porque cada
    # sección del detalle (SSL, 3CX, Citrix, ...) tiene su propio <hr> debajo
    # del título (ver _seccion_header en checklist.py) — buscar "el primer
    # <hr>" siempre caía dentro de la primera sección (Certificados SSL) en
    # vez de antes de la firma.
    m = _re.search(r"<(p|div|td|tr|table|section)[^>]*>\s*Saludos", html_base, _re.IGNORECASE)
    if m:
        idx = m.start()
        return html_base[:idx] + seccion_envuelta + "\n" + html_base[idx:]

    # 2) Antes de la palabra "Saludos" (fallback text-only)
    idx = html_base.find("Saludos")
    if idx != -1:
        return html_base[:idx] + seccion_envuelta + "\n" + html_base[idx:]

    # 3) Antes de </body> o </html>
    for marker in ("</body>", "</html>"):
        idx = html_base.lower().find(marker.lower())
        if idx != -1:
            print(f"[DASHBOARD] Advertencia: se inyectó WhatsUp Gold antes de {marker} "
                  "porque no se encontró 'Saludos' ni <hr> en el HTML consolidado.")
            return html_base[:idx] + seccion_envuelta + "\n" + html_base[idx:]

    # 4) Último recurso: pegar al final
    print("[DASHBOARD] Advertencia: no se encontró un marcador de inyección; "
          "sección de WhatsUp Gold se agregó al final del HTML.")
    return html_base + "\n" + seccion_envuelta


def _enviar_reporte_consolidado_con_widgets():
    """
    Envía el reporte consolidado por Outlook COM incluyendo las secciones de
    widgets de WhatsUp Gold embebidas inline con CID.

    Solo se llama si hay evidencias capturadas en esta sesión — si no,
    caemos al cl.enviar_reporte_email() original en el endpoint.
    """
    import win32com.client as win32
    from datetime import datetime as _dt

    PR_ATTACH_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"

    # 1) HTML base del checklist consolidado
    html_base = cl.generar_html_email()

    # 2) Preparar CIDs y HTML enriquecido
    cids_a_adjuntar = {}  # {cid: Path}
    def _img_resolver_cid(i, titulo, ruta):
        cid = f"wug_widget_{i}"
        cids_a_adjuntar[cid] = ruta
        return f"cid:{cid}"

    html_completo = _inyectar_widgets_wug_html(html_base, _img_resolver_cid)

    # 3) Construir el mail vía Outlook COM
    outlook = win32.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # olMailItem

    mail.To = cl.MAIL_DESTINATARIO

    # Subject: si checklist.py expone una variable con el asunto la respetamos;
    # si no, armamos uno con formato estándar.
    asunto = None
    for nombre_var in ("MAIL_ASUNTO", "ASUNTO_MAIL", "MAIL_SUBJECT"):
        val = getattr(cl, nombre_var, None)
        if val:
            asunto = val
            break
    if not asunto:
        asunto = f"Reporte Checklist Diario - {_dt.now().strftime('%d/%m/%Y')}"
    mail.Subject = asunto

    # 4) Adjuntar cada imagen con su CID
    for cid, ruta in cids_a_adjuntar.items():
        attachment = mail.Attachments.Add(str(Path(ruta).resolve()))
        attachment.PropertyAccessor.SetProperty(PR_ATTACH_CONTENT_ID, cid)

    # 5) Cuerpo HTML y envío
    mail.HTMLBody = html_completo
    mail.Send()


@app.route("/email/preview")
def email_preview():
    # Reutiliza tu generador de HTML y le suma las secciones de widgets de WUG.
    # Para el preview referenciamos las imágenes por el endpoint /evidencia del dashboard.
    def _img_resolver_url(i, titulo, ruta):
        return f"/evidencia?dir=evidencias_whatsupgold&name={ruta.name}"

    html_base = cl.generar_html_email()
    html_completo = _inyectar_widgets_wug_html(html_base, _img_resolver_url)
    return Response(html_completo, mimetype="text/html")


@app.route("/email/send", methods=["POST"])
def email_send():
    import pythoncom
    # Flask corre cada request en un hilo nuevo (threaded=True) y COM exige
    # CoInitialize() en CADA hilo antes de tocar Outlook.Application; sin esto
    # win32com tira "CoInitialize no ha sido llamado" (CO_E_NOTINITIALIZED)
    # justo al armar el mail.
    pythoncom.CoInitialize()
    try:
        ultima = wug.obtener_ultima_corrida()
        if ultima.get("evidencias"):
            # Hay widgets capturados en esta sesión → mail enriquecido
            _enviar_reporte_consolidado_con_widgets()
        else:
            # Sin widgets → comportamiento original
            cl.enviar_reporte_email()
        return jsonify({"ok": True, "to": cl.MAIL_DESTINATARIO})
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
<title>Checklist Automatizado — Pecom Energía</title>
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
  .wrap{max-width:920px; margin:0 auto; padding:0 18px 60px;}

  /* Header */
  header{background:linear-gradient(180deg,var(--navy) 0%,var(--navy-2) 100%); color:#fff;}
  .hd{max-width:920px; margin:0 auto; padding:24px 18px; display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap;}
  .brand .logo{font-size:30px; font-weight:800; letter-spacing:3px; line-height:1;}
  .brand .sub{font-size:11px; letter-spacing:3px; color:#86b3da; margin-top:1px;}
  .brand .ttl{font-size:14px; color:#bcd6ee; margin-top:9px;}
  .clock{text-align:right;}
  .clock .d{font-size:20px; font-weight:700;}
  .clock .t{font-size:13px; color:#9bc0e4; margin-top:2px;}

  /* Control panel */
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
  .spacer{flex:1;}
  .elapsed{font-variant-numeric:tabular-nums; color:var(--muted); font-size:13px;}

  /* Progress bar */
  .bar{height:8px; background:#e4e9f1; border-radius:99px; overflow:hidden; margin-top:18px;}
  .bar > i{display:block; height:100%; width:0%; background:var(--navy); transition:width .4s ease;}

  /* Banner */
  .banner{display:none; margin-top:18px; padding:15px 18px; border-radius:10px; color:#fff;}
  .banner.ok{background:var(--green);} .banner.fail{background:var(--red);}
  .banner .b1{font-size:16px; font-weight:700;}
  .banner .b2{font-size:13px; opacity:.92; margin-top:3px;}

  /* Steps */
  .steps{margin-top:22px; display:grid; gap:10px;}
  .step{background:var(--card); border:1px solid var(--line); border-left:4px solid #c3cbd8;
        border-radius:10px; padding:13px 16px; display:flex; align-items:center; gap:14px;
        transition:border-color .2s, background .2s;}
  .step .num{width:26px; height:26px; flex:none; border-radius:50%; background:#eef2f8; color:var(--navy);
             font-weight:700; font-size:13px; display:flex; align-items:center; justify-content:center;}
  .step .info{flex:1; min-width:0;}
  .step .name{font-weight:600;}
  .step .det{font-size:12.5px; color:var(--muted); margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
  .pill{flex:none; font-size:12px; font-weight:700; padding:4px 12px; border-radius:99px; letter-spacing:.3px;}
  .pill.pend{background:#eceff4; color:#8a93a2;}
  .pill.run{background:#e7f0fb; color:var(--blue);}
  .pill.ok{background:var(--green-soft); color:var(--green);}
  .pill.fail{background:var(--red-soft); color:var(--red);}

  .step.s-run{border-left-color:var(--blue); background:#fafcff;}
  .step.s-ok{border-left-color:var(--green);}
  .step.s-fail{border-left-color:var(--red); background:#fffafa;}

  .dot{display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--blue);
       margin-right:6px; animation:blink 1s infinite;}
  @keyframes blink{0%,100%{opacity:1;} 50%{opacity:.25;}}

  /* Section titles */
  .sect{margin:30px 0 12px; font-size:12px; font-weight:700; letter-spacing:1.5px;
        color:var(--navy); text-transform:uppercase;}

  /* Evidence */
  .gallery{display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:12px;}
  .thumb{background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; cursor:pointer;}
  .thumb img{width:100%; height:104px; object-fit:cover; display:block; background:#f1f4f9;}
  .thumb .cap{font-size:11px; color:var(--muted); padding:7px 9px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
  .empty{color:var(--muted); font-size:13px;}

  /* Modal / lightbox */
  .modal{display:none; position:fixed; inset:0; background:rgba(15,25,45,.72); z-index:50;
         align-items:center; justify-content:center; padding:24px;}
  .modal.show{display:flex;}
  .modal-box{background:#fff; border-radius:12px; width:min(760px,100%); max-height:88vh; overflow:hidden; display:flex; flex-direction:column;}
  .modal-hd{padding:13px 18px; background:var(--navy); color:#fff; display:flex; justify-content:space-between; align-items:center;}
  .modal-hd b{font-size:14px;}
  .modal-x{background:rgba(255,255,255,.16); color:#fff; border-radius:7px; padding:5px 11px; font-size:14px;}
  .modal-box iframe{border:none; width:100%; height:70vh; background:#edf0f5;}
  .modal-box img{max-width:100%; max-height:80vh; display:block; margin:0 auto; background:#222;}

  /* Toast */
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
      <div class="ttl">Checklist Automatizado de Sistemas IT</div>
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
      <button class="btn-run" id="btnRun">▶  Ejecutar Checklist</button>
      <button class="btn-sec" id="btnReporte" disabled>Ver reporte</button>
      <button class="btn-sec" id="btnEmail" disabled>Enviar por email</button>
      <button class="btn-sec" id="btnEvid">Actualizar evidencias</button>
      <span class="spacer"></span>
      <span class="elapsed" id="elapsed"></span>
    </div>
    <div class="bar"><i id="barFill"></i></div>
    <div class="banner" id="banner">
      <div class="b1" id="bannerT"></div>
      <div class="b2" id="bannerS"></div>
    </div>
  </div>

  <div class="steps" id="steps"></div>

  <div class="sect">Evidencia capturada</div>
  <div class="gallery" id="gallery"><div class="empty">Todavía no se cargaron capturas.</div></div>

</div>

<!-- Modal reporte email -->
<div class="modal" id="mReport">
  <div class="modal-box">
    <div class="modal-hd"><b>Vista previa del reporte por email</b>
      <button class="modal-x" data-close="mReport">Cerrar ✕</button></div>
    <iframe id="reportFrame"></iframe>
  </div>
</div>

<!-- Modal imagen -->
<div class="modal" id="mImg">
  <div class="modal-box">
    <div class="modal-hd"><b id="imgCap">Evidencia</b>
      <button class="modal-x" data-close="mImg">Cerrar ✕</button></div>
    <img id="imgFull" src="" alt="">
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const STEP_NAMES = """ + json.dumps(STEP_NAMES, ensure_ascii=False) + r""";
const $ = s => document.querySelector(s);

// Reloj
function tick(){
  const n = new Date();
  $("#fecha").textContent = n.toLocaleDateString("es-AR");
  $("#hora").textContent  = n.toLocaleTimeString("es-AR") + " hs";
}
tick(); setInterval(tick, 1000);

// Render inicial de pasos
function renderSteps(){
  const c = $("#steps"); c.innerHTML = "";
  STEP_NAMES.forEach((name, i) => {
    const el = document.createElement("div");
    el.className = "step"; el.id = "step-" + i;
    el.innerHTML = `
      <div class="num">${i+1}</div>
      <div class="info">
        <div class="name">${name}</div>
        <div class="det" id="det-${i}"></div>
      </div>
      <div class="pill pend" id="pill-${i}">Pendiente</div>`;
    c.appendChild(el);
  });
}
renderSteps();

function setStep(i, state, detalle){
  const step = $("#step-"+i), pill = $("#pill-"+i), det = $("#det-"+i);
  step.classList.remove("s-run","s-ok","s-fail");
  pill.className = "pill";
  if(state === "run"){
    step.classList.add("s-run"); pill.classList.add("run");
    pill.innerHTML = '<span class="dot"></span>En ejecución';
  } else if(state === "ok"){
    step.classList.add("s-ok"); pill.classList.add("ok"); pill.textContent = "OK";
  } else if(state === "fail"){
    step.classList.add("s-fail"); pill.classList.add("fail"); pill.textContent = "FALLO";
  } else {
    pill.classList.add("pend"); pill.textContent = "Pendiente";
  }
  if(detalle !== undefined) det.textContent = detalle || "";
}

// Ejecución
let es = null, t0 = 0, timer = null;
function fmt(s){ return Math.floor(s/60)+"m "+String(s%60).padStart(2,"0")+"s"; }

$("#btnRun").addEventListener("click", () => {
  if(es){ es.close(); }
  // reset UI
  renderSteps();
  $("#banner").style.display = "none";
  $("#barFill").style.width = "0%";
  $("#btnRun").disabled = true;
  $("#btnReporte").disabled = true;
  $("#btnEmail").disabled = true;
  t0 = Date.now();
  clearInterval(timer);
  timer = setInterval(() => { $("#elapsed").textContent = "⏱ " + fmt(Math.floor((Date.now()-t0)/1000)); }, 1000);

  let total = STEP_NAMES.length, done = 0;
  es = new EventSource("/run");

  es.addEventListener("start", e => {
    const d = JSON.parse(e.data); total = d.steps.length;
  });
  es.addEventListener("step_start", e => {
    const d = JSON.parse(e.data); setStep(d.index, "run");
  });
  es.addEventListener("step_done", e => {
    const d = JSON.parse(e.data);
    setStep(d.index, d.ok ? "ok" : "fail", d.detalle);
    done++; $("#barFill").style.width = Math.round(done/total*100) + "%";
  });
  es.addEventListener("done", e => {
    const d = JSON.parse(e.data);
    es.close(); es = null;
    clearInterval(timer);
    $("#elapsed").textContent = "⏱ " + fmt(d.segundos);
    $("#btnRun").disabled = false;
    $("#btnReporte").disabled = false;
    $("#btnEmail").disabled = false;
    const b = $("#banner");
    b.style.display = "block";
    b.className = "banner " + (d.fail === 0 ? "ok" : "fail");
    $("#bannerT").textContent = d.fail === 0
      ? "✓  Todas las verificaciones: OK" : `✗  ${d.fail} verificación(es) con FALLO`;
    $("#bannerS").textContent = `${d.ok} de ${d.total} verificaciones completadas con éxito · ${fmt(d.segundos)}`;
    loadEvid();
  });
  es.onerror = () => {
    if(es){ es.close(); es = null; }
    clearInterval(timer);
    $("#btnRun").disabled = false;
    toast("Se interrumpió la conexión con el servidor.", "err");
  };
});

// Reporte
$("#btnReporte").addEventListener("click", () => {
  $("#reportFrame").src = "/email/preview?ts=" + Date.now();
  openModal("mReport");
});

// Envío de email (manual, controlado por vos durante la demo)
$("#btnEmail").addEventListener("click", () => {
  if(!confirm("¿Enviar el reporte por Outlook al destinatario configurado?")) return;
  $("#btnEmail").disabled = true;
  fetch("/email/send", {method:"POST"})
    .then(r => r.json())
    .then(j => {
      if(j.ok) toast("✓ Reporte enviado a " + j.to, "ok");
      else toast("Error al enviar: " + j.error, "err");
    })
    .catch(() => toast("No se pudo contactar al servidor.", "err"))
    .finally(() => { $("#btnEmail").disabled = false; });
});

// Evidencias
$("#btnEvid").addEventListener("click", loadEvid);
function loadEvid(){
  fetch("/evidencias").then(r => r.json()).then(list => {
    const g = $("#gallery");
    if(!list.length){ g.innerHTML = '<div class="empty">No se encontraron capturas todavía.</div>'; return; }
    g.innerHTML = "";
    list.forEach(it => {
      const d = document.createElement("div");
      d.className = "thumb";
      d.innerHTML = `<img src="${it.url}" loading="lazy" alt=""><div class="cap">${it.dir}/${it.name}</div>`;
      d.addEventListener("click", () => {
        $("#imgFull").src = it.url; $("#imgCap").textContent = it.dir + "/" + it.name; openModal("mImg");
      });
      g.appendChild(d);
    });
  }).catch(() => {});
}
loadEvid();

// Modales
function openModal(id){ $("#"+id).classList.add("show"); }
document.querySelectorAll("[data-close]").forEach(b =>
  b.addEventListener("click", () => $("#"+b.dataset.close).classList.remove("show")));
document.querySelectorAll(".modal").forEach(m =>
  m.addEventListener("click", e => { if(e.target === m) m.classList.remove("show"); }));

// Toast
let toastT = null;
function toast(msg, kind){
  const t = $("#toast"); t.textContent = msg; t.className = "toast show " + (kind||"");
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 4000);
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    _cargar_estado_inicial()
    threading.Thread(target=_certs_loop, daemon=True).start()

    ip = _ip_local()
    print("\n" + "=" * 60)
    print("  Dashboard Checklist Pecom corriendo en:  http://127.0.0.1:5000")
    print(f"  Estado en vivo para el tablero de TV:    http://{ip}:5000/estado.json")
    print("  (usá esa IP como EJECUTOR_URL en tablero.py)")
    print("  (Ctrl+C para detener)")
    print("=" * 60 + "\n")
    # threaded=True para que el SSE no bloquee el resto de las rutas.
    # use_reloader=False para no importar checklist.py dos veces.
    app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False, debug=False)