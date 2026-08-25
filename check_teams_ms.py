"""
check_teams.py
Verifica el estado de Microsoft Teams:
- Proceso ms-teams.exe corriendo localmente
- Teams Web responde (https://teams.microsoft.com/)

Uso standalone:
    python check_teams.py

Uso como modulo:
    from check_teams import verificar_teams
    ok, resultado = verificar_teams(headless=False, enviar_mail=False)
"""

import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
EVIDENCIAS_DIR = BASE_DIR / "evidencias_teams"
EVIDENCIAS_DIR.mkdir(exist_ok=True)

EDGE_PROFILE_DIR = os.getenv(
    "EDGE_PROFILE_DIR",
    str(BASE_DIR / "edge_profile")
)

TIMEOUT_NAVEGACION = 30_000  # ms
TIMEOUT_POST_CARGA = 2_000   # ms

# Proceso critico de Teams (nuevo Teams)
PROCESO_CRITICO = "ms-teams.exe"

# URL de Teams Web
URL_TEAMS_WEB = "https://teams.microsoft.com/"

STATUS_OK_EXTRA = {401, 403}

# Email
EMAIL_DESTINATARIO = "lucasabad80@gmail.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:
    print(msg, flush=True)


def _sanitizar_nombre(nombre: str) -> str:
    limpio = "".join(c if c.isalnum() else "_" for c in nombre)
    while "__" in limpio:
        limpio = limpio.replace("__", "_")
    return limpio.strip("_")


# ---------------------------------------------------------------------------
# Check 1: Proceso local
# ---------------------------------------------------------------------------
def _detectar_proceso_teams() -> dict:
    resultado = {
        "corriendo": False,
        "instancias": 0,
        "pids": [],
        "error": None,
    }
    try:
        import psutil
    except ImportError:
        resultado["error"] = "psutil no instalado"
        return resultado

    try:
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                nombre = proc.info["name"] or ""
                if nombre.lower() == PROCESO_CRITICO.lower():
                    resultado["pids"].append(proc.info["pid"])
                    resultado["instancias"] += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        resultado["corriendo"] = resultado["instancias"] > 0
    except Exception as e:
        resultado["error"] = f"{type(e).__name__}: {e}"

    return resultado


# ---------------------------------------------------------------------------
# Check 2: Teams Web con Playwright
# ---------------------------------------------------------------------------
def _chequear_teams_web(headless: bool, timestamp_run: str) -> dict:
    resultado = {
        "nombre": "Teams Web",
        "url": URL_TEAMS_WEB,
        "ok": False,
        "status": None,
        "evidencia": None,
        "error": None,
    }

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            EDGE_PROFILE_DIR,
            channel="msedge",
            headless=headless,
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_NAVEGACION)

        try:
            response = page.goto(URL_TEAMS_WEB, wait_until="domcontentloaded",
                                 timeout=TIMEOUT_NAVEGACION)
            page.wait_for_timeout(TIMEOUT_POST_CARGA)

            status = response.status if response else None
            resultado["status"] = status

            if status is not None and (status < 400 or status in STATUS_OK_EXTRA):
                resultado["ok"] = True
            else:
                resultado["error"] = f"HTTP {status}"

        except PlaywrightTimeoutError:
            resultado["error"] = f"Timeout ({TIMEOUT_NAVEGACION // 1000}s)"
        except Exception as e:
            err_line = str(e).split("\n")[0]
            resultado["error"] = f"{type(e).__name__}: {err_line}"

        # Screenshot
        try:
            sufijo = "" if resultado["ok"] else "_FAIL"
            filename = f"{timestamp_run}_teams_web{sufijo}.png"
            path_evidencia = EVIDENCIAS_DIR / filename
            page.screenshot(path=str(path_evidencia), full_page=False)
            resultado["evidencia"] = str(path_evidencia)
        except Exception:
            pass

        context.close()

    return resultado


# ---------------------------------------------------------------------------
# Verificacion principal
# ---------------------------------------------------------------------------
def verificar_teams(headless: bool = False,
                    enviar_mail: bool = True) -> tuple[bool, dict]:
    timestamp_run = datetime.now().strftime("%Y%m%d_%H%M%S")

    _log("")
    _log("=" * 70)
    _log(f"Verificacion Microsoft Teams - {timestamp_run}")
    _log("=" * 70)
    _log("")

    detalle = {
        "timestamp": datetime.now().isoformat(),
        "proceso": {},
        "web": {},
    }

    # --- Check 1: Proceso local ---
    _log("[1/2] Chequeando proceso local de Teams...")
    proc = _detectar_proceso_teams()
    detalle["proceso"] = proc

    if proc["error"]:
        _log(f"       ERROR: {proc['error']}")
    elif proc["corriendo"]:
        _log(f"       OK - {PROCESO_CRITICO} corriendo ({proc['instancias']} instancias)")
    else:
        _log(f"       FALLA - {PROCESO_CRITICO} NO esta corriendo")
    _log("")

    # --- Check 2: Teams Web ---
    _log("[2/2] Chequeando Teams Web con Playwright...")
    web = _chequear_teams_web(headless, timestamp_run)
    detalle["web"] = web

    if web["ok"]:
        _log(f"       OK - {web['nombre']} (status {web['status']})")
    else:
        _log(f"       FALLA - {web['nombre']}: {web['error']}")
    _log("")

    # --- Evaluacion global ---
    check_proceso_ok = proc.get("corriendo", False)
    check_web_ok = web.get("ok", False)
    ok_global = check_proceso_ok and check_web_ok

    _log("=" * 70)
    _log("RESUMEN")
    _log("=" * 70)
    _log(f"Proceso local ({PROCESO_CRITICO}): {'OK' if check_proceso_ok else 'FALLA'}")
    _log(f"Teams Web: {'OK' if check_web_ok else 'FALLA'}")
    _log("")
    _log(f"Resultado global: {'OK' if ok_global else 'FALLA'}")
    _log("=" * 70)
    _log("")

    if enviar_mail:
        try:
            _log(f"Enviando reporte a {EMAIL_DESTINATARIO}...")
            enviar_reporte_email(detalle, ok_global)
            _log("Email enviado OK.")
        except Exception as e:
            _log(f"ERROR enviando email: {e}")
        _log("")

    return ok_global, detalle


# ---------------------------------------------------------------------------
# Reporte HTML
# ---------------------------------------------------------------------------
def _generar_html_reporte(detalle: dict, ok_global: bool) -> str:
    ahora = datetime.now()
    fecha_str = ahora.strftime("%d/%m/%Y")
    hora_str = ahora.strftime("%H:%M")

    color_ok = "#16a34a"
    color_fail = "#dc2626"
    color_muted = "#6b7280"
    color_header = "#1e3a8a"
    color_border = "#e5e7eb"

    estado_texto = "OK" if ok_global else "FALLA"
    estado_color = color_ok if ok_global else color_fail
    estado_detalle = "Teams operativo (cliente local y web)" if ok_global else "Revisar detalles abajo"

    def _fila(label: str, ok: bool, extra: str = "") -> str:
        badge_bg = "#dcfce7" if ok else "#fee2e2"
        badge_color = color_ok if ok else color_fail
        badge_text = "OK" if ok else "FALLA"
        extra_html = f'<div style="font-size:12px;color:{color_muted};margin-top:2px;">{extra}</div>' if extra else ""
        return f"""
        <tr style="border-bottom:1px solid {color_border};">
            <td style="padding:10px 12px;vertical-align:top;">
                <span style="display:inline-block;padding:3px 10px;border-radius:12px;background:{badge_bg};color:{badge_color};font-size:12px;font-weight:600;">{badge_text}</span>
            </td>
            <td style="padding:10px 12px;vertical-align:top;">
                <div style="font-weight:600;color:#111827;">{label}</div>
                {extra_html}
            </td>
        </tr>
        """

    filas = []

    # Proceso local
    proc = detalle["proceso"]
    if proc.get("corriendo"):
        extra = f"{PROCESO_CRITICO} activo ({proc['instancias']} instancias)"
    else:
        extra = f"{PROCESO_CRITICO} no esta corriendo - iniciar Microsoft Teams"
    filas.append(_fila("Teams cliente desktop", proc.get("corriendo", False), extra))

    # Web
    web = detalle["web"]
    if web.get("ok"):
        extra = f"{web['url']} - Status {web['status']}"
    else:
        extra = f"{web['url']} - {web.get('error', 'error desconocido')}"
    filas.append(_fila("Teams Web", web.get("ok", False), extra))

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>Verificacion Microsoft Teams</title>
</head>
<body style="margin:0;padding:20px;font-family:Segoe UI, Arial, sans-serif;background:#f9fafb;color:#111827;">

    <div style="max-width:800px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">

        <div style="background:{color_header};color:#ffffff;padding:24px 28px;">
            <div style="font-size:12px;opacity:0.85;letter-spacing:1px;text-transform:uppercase;">Checklist IT - Verificacion Diaria</div>
            <h1 style="margin:6px 0 0 0;font-size:22px;font-weight:600;">Microsoft Teams</h1>
            <div style="margin-top:6px;font-size:13px;opacity:0.9;">{fecha_str} - {hora_str} hs</div>
        </div>

        <div style="padding:20px 28px;background:#f9fafb;border-bottom:1px solid {color_border};">
            <div style="text-align:center;padding:8px;">
                <div style="font-size:11px;color:{color_muted};text-transform:uppercase;letter-spacing:0.5px;">Resultado</div>
                <div style="font-size:28px;font-weight:700;color:{estado_color};margin-top:4px;">{estado_texto}</div>
                <div style="font-size:12px;color:{color_muted};margin-top:6px;">{estado_detalle}</div>
            </div>
        </div>

        <div style="padding:20px 28px;">
            <table style="width:100%;border-collapse:collapse;margin-top:8px;">
                <thead>
                    <tr style="background:#f3f4f6;">
                        <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:{color_muted};letter-spacing:0.5px;">Estado</th>
                        <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:{color_muted};letter-spacing:0.5px;">Verificacion</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(filas)}
                </tbody>
            </table>

            <div style="margin-top:24px;padding:14px 16px;background:#f9fafb;border-radius:6px;font-size:12px;color:{color_muted};line-height:1.6;">
                <div><strong>Como se valida Teams:</strong></div>
                <div>1. Proceso <code>{PROCESO_CRITICO}</code> corriendo -> cliente desktop activo.</div>
                <div>2. Teams Web responde -> servicio web disponible.</div>
                <div style="margin-top:6px;">Teams Mobile requiere validacion manual desde el celular del operador.</div>
            </div>
        </div>

        <div style="padding:14px 28px;background:#f3f4f6;font-size:11px;color:{color_muted};text-align:center;border-top:1px solid {color_border};">
            Reporte generado automaticamente por Checklist-Automatizado - {fecha_str} {hora_str}
        </div>

    </div>

</body>
</html>"""

    return html


def enviar_reporte_email(detalle: dict, ok_global: bool,
                         destinatario: str = EMAIL_DESTINATARIO) -> None:
    try:
        import win32com.client
    except ImportError:
        raise RuntimeError("Se necesita pywin32 (pip install pywin32)")

    html = _generar_html_reporte(detalle, ok_global)

    ahora = datetime.now()
    fecha_str = ahora.strftime("%d/%m/%Y")
    estado = "OK" if ok_global else "FALLA"
    asunto = f"[Checklist IT] Microsoft Teams - {estado} - {fecha_str}"

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = destinatario
    mail.Subject = asunto
    mail.HTMLBody = html
    mail.Send()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    headless = "--headless" in sys.argv
    no_mail = "--no-mail" in sys.argv
    ok, _ = verificar_teams(headless=headless, enviar_mail=not no_mail)
    sys.exit(0 if ok else 1)