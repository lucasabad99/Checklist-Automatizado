"""
check_urls_corporativas.py
Verifica URLs corporativas + certificados SSL + envio de reporte por mail.

- HTTP <400, 401 o 403 => OK (401/403 = pagina responde pero pide login)
- ignorar_estado=True por URL: no cuenta como falla para el resultado global
- Cert SSL: doble intento (verificado / no verificado) para leer datos aunque
  la CA interna no valide contra el trust store de Python.
- Estado global con 3 niveles: OK / PARCIAL / FALLA (segun cantidad de caidas)
- Envia reporte HTML por mail via Outlook COM al finalizar.

Requiere: playwright, pywin32, cryptography
    pip install cryptography

Uso standalone:
    python check_urls_corporativas.py

Uso como modulo:
    from check_urls_corporativas import verificar_urls_corporativas
    ok, resultados = verificar_urls_corporativas(headless=False, enviar_mail=False)
"""

import os
import ssl
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
EVIDENCIAS_DIR = BASE_DIR / "evidencias_urls"
EVIDENCIAS_DIR.mkdir(exist_ok=True)

EDGE_PROFILE_DIR = os.getenv(
    "EDGE_PROFILE_DIR",
    str(BASE_DIR / "edge_profile")
)

TIMEOUT_NAVEGACION = 30_000        # ms
TIMEOUT_POST_CARGA = 2_000         # ms
TIMEOUT_CERT = 10                  # segundos

DIAS_ALERTA_CERT = 30
STATUS_OK_EXTRA = {401, 403}

# Umbral para considerar el resultado global como "PARCIAL" en lugar de "FALLA"
# Si la cantidad de URLs caidas es <= este numero, el estado es PARCIAL (no FALLA)
UMBRAL_PARCIAL = 3

# Email
EMAIL_DESTINATARIO = "lucasabad80@gmail.com"


# ---------------------------------------------------------------------------
# Lista de URLs
# ---------------------------------------------------------------------------
URLS_CORPORATIVAS = [
    {"nombre": "Invgate Helpdesk",              "url": "https://helpdesk.pecomenergia.com.ar/"},
    {"nombre": "Nodo Virtual Netskope",         "url": "http://10.16.10.175"},
    {"nombre": "PAD (SuccessFactors)",          "url": "https://hcm19.sapsf.com/sf/home?bplte_company=pecomservi"},
    {"nombre": "Invgate Insight",               "url": "https://insight.pecomenergia.com.ar/"},
    {"nombre": "Drive Pecom",                   "url": "https://drive.pecomenergia.com.ar/"},
    {"nombre": "Portal Beneficios",             "url": "https://beneficios.pecomenergia.com.ar/login.aspx?ReturnUrl=%2f"},
    {"nombre": "Portal Tarjeta TOP",            "url": "http://www.iquality.com.ar/pecom/top/tarjetas/topadd.aspx"},
    {"nombre": "TuRecibo.com",                  "url": "https://pecom.turecibo.com.ar/login.php?ref=Lw%3D%3D"},
    {"nombre": "Humand",                        "url": "https://app.humand.co/feed"},
    {"nombre": "SAP Liberaciones Inteligentes", "url": "https://liberaciones.pecomenergia.com.ar/#/users/sign_in"},
    {"nombre": "C&C - Contrataciones y Compras","url": "https://cyc.pecomenergia.com.ar/"},
    {"nombre": "Plataforma de Facilities",      "url": "https://facilities.pecomenergia.com.ar/summary/enduser"},
    {"nombre": "Logistica",                     "url": "https://logistica.pecomenergia.com.ar"},
    {"nombre": "Compras",                       "url": "https://compras.pecomenergia.com.ar"},
    {"nombre": "ISOTools",                      "url": "https://pecom.esginnova.com/login/acceso.cfm"},
    {"nombre": "Field Voolks",                  "url": "https://field.voolks.com/"},
    {"nombre": "SAP Concur",                    "url": "https://www.concursolutions.com/"},
    {"nombre": "SIMA Almacenes",                "url": "https://almacenes.pecomenergia.com.ar/"},
    {"nombre": "SGPQ",                          "url": "https://sgpq.pecomenergia.com.ar"},
    {"nombre": "Sistema Fabril",                "url": "https://sfb.pecomenergia.com.ar"},
    {"nombre": "Sitrack",                       "url": "https://sitrack.pecomenergia.com.ar/"},
    {"nombre": "Bombas Mecanicas Web",          "url": "https://sbc.pecomenergia.com.ar/servlet/hlog001"},
    {"nombre": "Lex-IA (Legales)",              "url": "https://energ-ia.pecomenergia.com.ar"},
    {"nombre": "Ingen-IA (Ingenieria)",         "url": "https://ingen-ia.pecomenergia.com.ar/"},
    {"nombre": "n8n (Agentes IA)",              "url": "https://n8n.pecomenergia.com.ar"},
    {"nombre": "INVGATE People Service",        "url": "https://peopleservicecenter.pecomenergia.com.ar/"},
    {"nombre": "Office 365 - Portal",           "url": "https://www.office.com/"},
    {"nombre": "Outlook Web (O365)",            "url": "https://outlook.office.com/"},
    {"nombre": "Citrix Portal (externo)",       "url": "https://citrix.pecomenergia.com.ar/"},
    {"nombre": "Citrix Portal 2 (externo)",     "url": "https://citrix2.pecomenergia.com.ar/"} ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sanitizar_nombre(nombre: str) -> str:
    limpio = "".join(c if c.isalnum() else "_" for c in nombre)
    while "__" in limpio:
        limpio = limpio.replace("__", "_")
    return limpio.strip("_")


def _log(msg: str) -> None:
    print(msg, flush=True)


def _clasificar_estado_global(fail_count: int) -> tuple[str, str]:
    """
    Devuelve (estado_texto, detalle) segun la cantidad de fallas.
    Estados: OK / PARCIAL / FALLA
    """
    if fail_count == 0:
        return "OK", "Todos los servicios operativos"
    if fail_count <= UMBRAL_PARCIAL:
        palabra = "servicio" if fail_count == 1 else "servicios"
        return "PARCIAL", f"{fail_count} {palabra} con inconvenientes"
    return "FALLA", f"{fail_count} servicios caidos"


def _extraer_emisor_dict(cert: dict) -> str | None:
    """Del dict de getpeercert() extrae el nombre del emisor."""
    issuer = cert.get("issuer", ())
    campos = {}
    for parte in issuer:
        for llave, valor in parte:
            campos[llave] = valor
    return campos.get("organizationName") or campos.get("commonName")


def _parsear_cert_der(cert_bin: bytes) -> dict:
    """
    Parsea un certificado DER (bytes) a un dict compatible con getpeercert().
    Se usa cuando la verificacion falla y solo tenemos el cert binario.
    """
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend

    cert = x509.load_der_x509_certificate(cert_bin, default_backend())

    # Compatible con cryptography < 42 (naive) y >= 42 (aware)
    try:
        not_after = cert.not_valid_after_utc  # type: ignore[attr-defined]
    except AttributeError:
        not_after = cert.not_valid_after.replace(tzinfo=timezone.utc)  # type: ignore[deprecated]

    not_after_str = not_after.strftime("%b %d %H:%M:%S %Y GMT")

    issuer_parts = []
    for attr in cert.issuer:
        try:
            oid_name = attr.oid._name
        except AttributeError:
            oid_name = str(attr.oid)
        issuer_parts.append(((oid_name, str(attr.value)),))

    return {
        "notAfter": not_after_str,
        "issuer": tuple(issuer_parts),
    }


def _obtener_certificado_ssl(url: str, timeout: int = TIMEOUT_CERT) -> dict:
    """
    Obtiene datos del certificado SSL. Hace un doble intento:
    1) contexto verificado (para CAs publicos)
    2) contexto sin verificar (para CAs internas)
    """
    resultado = {
        "aplica": False,
        "valido": False,
        "verificado": False,
        "fecha_vencimiento": None,
        "dias_restantes": None,
        "emisor": None,
        "alerta": False,
        "vencido": False,
        "error": None,
    }

    parsed = urlparse(url)
    if parsed.scheme != "https":
        return resultado

    resultado["aplica"] = True

    host = parsed.hostname
    port = parsed.port or 443
    if not host:
        resultado["error"] = "URL sin hostname"
        return resultado

    cert_dict = None
    verificado = False

    # --- Intento 1: contexto verificado -> devuelve dict directo ---
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert_dict = ssock.getpeercert()
        verificado = True
    except (ssl.SSLCertVerificationError, ssl.SSLError):
        cert_dict = None  # vamos al intento 2
    except (socket.timeout, TimeoutError):
        resultado["error"] = "Timeout de conexion"
        return resultado
    except Exception as e:
        resultado["error"] = f"{type(e).__name__}: {e}"

    # --- Intento 2: sin verificacion, cert en binario -> parseamos con cryptography ---
    if not cert_dict:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    cert_bin = ssock.getpeercert(binary_form=True)
            cert_dict = _parsear_cert_der(cert_bin)
            resultado["error"] = None
        except Exception as e:
            resultado["error"] = f"{type(e).__name__}: {e}"
            return resultado

    if not cert_dict:
        resultado["error"] = resultado["error"] or "No se pudo obtener el certificado"
        return resultado

    try:
        not_after_str = cert_dict["notAfter"]
        fecha_venc = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
        fecha_venc = fecha_venc.replace(tzinfo=timezone.utc)
        dias_restantes = (fecha_venc - datetime.now(timezone.utc)).days

        resultado["valido"] = True
        resultado["verificado"] = verificado
        resultado["fecha_vencimiento"] = fecha_venc
        resultado["dias_restantes"] = dias_restantes
        resultado["emisor"] = _extraer_emisor_dict(cert_dict)
        resultado["vencido"] = dias_restantes < 0
        resultado["alerta"] = dias_restantes < DIAS_ALERTA_CERT
    except Exception as e:
        resultado["error"] = f"Parse error: {e}"

    return resultado


def _formatear_cert_log(cert: dict) -> str:
    if not cert["aplica"]:
        return "N/A (http://)"
    if not cert["valido"]:
        return f"ERROR - {cert['error']}"

    fecha = cert["fecha_vencimiento"].strftime("%Y-%m-%d")
    dias = cert["dias_restantes"]
    emisor = cert["emisor"] or "?"
    marca_verif = "" if cert["verificado"] else " [CA interna]"

    if cert["vencido"]:
        prefijo = "VENCIDO"
    elif cert["alerta"]:
        prefijo = f"ALERTA (<{DIAS_ALERTA_CERT}d)"
    else:
        prefijo = "OK"

    return f"{prefijo} - vence {fecha} ({dias} dias) - {emisor}{marca_verif}"


# ---------------------------------------------------------------------------
# Generacion del reporte HTML
# ---------------------------------------------------------------------------
_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_es(dt: datetime) -> str:
    return f"{dt.day} de {_MESES_ES[dt.month - 1]} de {dt.year}"


def _cert_texto_email(cert: dict) -> str:
    if not cert["aplica"]:
        return "N/A"
    if not cert["valido"]:
        return f"Error: {cert['error'] or 'sin info'}"

    fecha = _fecha_es(cert["fecha_vencimiento"])
    dias = cert["dias_restantes"]
    emisor = cert["emisor"] or "?"
    detalle = f"{fecha} ({dias} dias) - {emisor}"
    if not cert["verificado"]:
        detalle += " [CA interna]"
    return detalle


def _generar_html_reporte(resultados: list[dict], exito_global: bool) -> str:
    ok_count = sum(1 for r in resultados if r["ok"])
    fail_count = len(resultados) - ok_count
    total = len(resultados)
    alertas_cert = [r for r in resultados
                    if r["cert"].get("aplica") and r["cert"].get("valido")
                    and r["cert"].get("alerta") and not r["cert"].get("vencido")]
    vencidos = [r for r in resultados
                if r["cert"].get("aplica") and r["cert"].get("valido")
                and r["cert"].get("vencido")]

    ahora = datetime.now()
    fecha_str = ahora.strftime("%d/%m/%Y")
    hora_str = ahora.strftime("%H:%M")

    color_ok = "#16a34a"
    color_fail = "#dc2626"
    color_warning = "#d97706"
    color_muted = "#6b7280"
    color_header = "#1e3a8a"
    color_border = "#e5e7eb"

    # ---- Estado global con 3 niveles ----
    estado_texto, estado_detalle = _clasificar_estado_global(fail_count)
    if estado_texto == "OK":
        estado_color = color_ok
    elif estado_texto == "PARCIAL":
        estado_color = color_warning
    else:
        estado_color = color_fail

    # ---- Filas de la tabla ----
    filas_html = []
    for r in resultados:
        cert = r["cert"]

        if r["ok"]:
            if r["ignorar_estado"] and not r["status_ok"]:
                badge = f'<span style="display:inline-block;padding:3px 10px;border-radius:12px;background:#f3f4f6;color:{color_muted};font-size:12px;font-weight:600;">IGNORADO</span>'
            else:
                badge = f'<span style="display:inline-block;padding:3px 10px;border-radius:12px;background:#dcfce7;color:{color_ok};font-size:12px;font-weight:600;">OK</span>'
        else:
            badge = f'<span style="display:inline-block;padding:3px 10px;border-radius:12px;background:#fee2e2;color:{color_fail};font-size:12px;font-weight:600;">FALLA</span>'

        cert_texto = _cert_texto_email(cert)
        if not cert["aplica"]:
            cert_color = color_muted
        elif not cert["valido"]:
            cert_color = color_fail
        elif cert["vencido"]:
            cert_color = color_fail
        elif cert["alerta"]:
            cert_color = color_warning
        else:
            cert_color = "#111827"

        detalle_error = ""
        if not r["ok"] and r["error"]:
            err_short = r["error"].split("\n")[0][:120]
            detalle_error = f'<div style="font-size:12px;color:{color_fail};margin-top:2px;">{err_short}</div>'

        filas_html.append(f"""
        <tr style="border-bottom:1px solid {color_border};">
            <td style="padding:10px 12px;vertical-align:top;">{badge}</td>
            <td style="padding:10px 12px;vertical-align:top;">
                <div style="font-weight:600;color:#111827;">{r['nombre']}</div>
                <div style="font-size:12px;color:{color_muted};word-break:break-all;">
                    <a href="{r['url']}" style="color:{color_muted};text-decoration:none;">{r['url']}</a>
                </div>
                {detalle_error}
            </td>
            <td style="padding:10px 12px;vertical-align:top;color:{cert_color};font-size:13px;">{cert_texto}</td>
        </tr>
        """)

    # ---- Bloque de alertas de cert ----
    bloque_alertas = ""
    if alertas_cert or vencidos:
        items = []
        for r in vencidos:
            c = r["cert"]
            fecha = _fecha_es(c["fecha_vencimiento"])
            items.append(f'<li style="color:{color_fail};"><strong>{r["nombre"]}</strong>: VENCIDO el {fecha} (hace {-c["dias_restantes"]} dias)</li>')
        for r in alertas_cert:
            c = r["cert"]
            fecha = _fecha_es(c["fecha_vencimiento"])
            items.append(f'<li style="color:{color_warning};"><strong>{r["nombre"]}</strong>: vence el {fecha} ({c["dias_restantes"]} dias restantes)</li>')

        bloque_alertas = f"""
        <div style="margin:20px 0;padding:16px;border-left:4px solid {color_warning};background:#fffbeb;border-radius:4px;">
            <div style="font-weight:700;color:{color_warning};margin-bottom:8px;">Certificados que requieren atencion</div>
            <ul style="margin:0;padding-left:20px;">
                {''.join(items)}
            </ul>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>Verificacion URLs Corporativas</title>
</head>
<body style="margin:0;padding:20px;font-family:Segoe UI, Arial, sans-serif;background:#f9fafb;color:#111827;">

    <div style="max-width:900px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">

        <!-- Header -->
        <div style="background:{color_header};color:#ffffff;padding:24px 28px;">
            <div style="font-size:12px;opacity:0.85;letter-spacing:1px;text-transform:uppercase;">Checklist IT - Verificacion Diaria</div>
            <h1 style="margin:6px 0 0 0;font-size:22px;font-weight:600;">URLs Corporativas</h1>
            <div style="margin-top:6px;font-size:13px;opacity:0.9;">{fecha_str} - {hora_str} hs</div>
        </div>

        <!-- Summary -->
        <div style="padding:20px 28px;background:#f9fafb;border-bottom:1px solid {color_border};">
            <table style="width:100%;border-collapse:collapse;">
                <tr>
                    <td style="width:33%;text-align:center;padding:8px;">
                        <div style="font-size:11px;color:{color_muted};text-transform:uppercase;letter-spacing:0.5px;">Resultado</div>
                        <div style="font-size:24px;font-weight:700;color:{estado_color};margin-top:4px;">{estado_texto}</div>
                        <div style="font-size:11px;color:{color_muted};margin-top:4px;">{estado_detalle}</div>
                    </td>
                    <td style="width:33%;text-align:center;padding:8px;border-left:1px solid {color_border};">
                        <div style="font-size:11px;color:{color_muted};text-transform:uppercase;letter-spacing:0.5px;">URLs verificadas</div>
                        <div style="font-size:24px;font-weight:700;color:#111827;margin-top:4px;">{ok_count}<span style="font-size:16px;color:{color_muted};">/{total}</span></div>
                        <div style="font-size:11px;color:{color_muted};margin-top:4px;">operativas</div>
                    </td>
                    <td style="width:33%;text-align:center;padding:8px;border-left:1px solid {color_border};">
                        <div style="font-size:11px;color:{color_muted};text-transform:uppercase;letter-spacing:0.5px;">Certificados en alerta</div>
                        <div style="font-size:24px;font-weight:700;color:{color_warning if (alertas_cert or vencidos) else color_ok};margin-top:4px;">{len(alertas_cert) + len(vencidos)}</div>
                        <div style="font-size:11px;color:{color_muted};margin-top:4px;">requieren atencion</div>
                    </td>
                </tr>
            </table>
        </div>

        <!-- Contenido -->
        <div style="padding:20px 28px;">

            {bloque_alertas}

            <table style="width:100%;border-collapse:collapse;margin-top:8px;">
                <thead>
                    <tr style="background:#f3f4f6;">
                        <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:{color_muted};letter-spacing:0.5px;">Estado</th>
                        <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:{color_muted};letter-spacing:0.5px;">Servicio</th>
                        <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:{color_muted};letter-spacing:0.5px;">Certificado SSL</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(filas_html)}
                </tbody>
            </table>

            <!-- Notas -->
            <div style="margin-top:24px;padding:14px 16px;background:#f9fafb;border-radius:6px;font-size:12px;color:{color_muted};line-height:1.6;">
                <div><strong>Notas:</strong></div>
                <div>- Codigos HTTP 401/403 se consideran OK: la pagina responde pero requiere login.</div>
                <div>- "[CA interna]" indica que el certificado es de la CA interna de Pecom (no verificable contra el trust store publico, pero valido en el ambiente corporativo).</div>
                <div>- URLs marcadas como IGNORADO tienen fallas conocidas que no afectan el resultado global; el certificado se chequea igual.</div>
                <div>- Estado PARCIAL: hasta {UMBRAL_PARCIAL} servicios con inconvenientes. Estado FALLA: mas de {UMBRAL_PARCIAL} servicios caidos.</div>
            </div>

        </div>

        <!-- Footer -->
        <div style="padding:14px 28px;background:#f3f4f6;font-size:11px;color:{color_muted};text-align:center;border-top:1px solid {color_border};">
            Reporte generado automaticamente por Checklist-Automatizado - {fecha_str} {hora_str}
        </div>

    </div>

</body>
</html>"""

    return html


# ---------------------------------------------------------------------------
# Envio de email via Outlook COM
# ---------------------------------------------------------------------------
def enviar_reporte_email(resultados: list[dict], exito_global: bool,
                          destinatario: str = EMAIL_DESTINATARIO) -> None:
    """Envia el reporte HTML por Outlook COM al destinatario indicado."""
    try:
        import win32com.client
    except ImportError:
        raise RuntimeError("Se necesita pywin32 (pip install pywin32)")

    html = _generar_html_reporte(resultados, exito_global)

    fail_count = sum(1 for r in resultados if not r["ok"])
    estado, _ = _clasificar_estado_global(fail_count)

    ahora = datetime.now()
    fecha_str = ahora.strftime("%d/%m/%Y")
    asunto = f"[Checklist IT] URLs Corporativas - {estado} - {fecha_str}"

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # olMailItem
    mail.To = destinatario
    mail.Subject = asunto
    mail.HTMLBody = html
    mail.Send()


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------
def verificar_urls_corporativas(headless: bool = False,
                                 enviar_mail: bool = True) -> tuple[bool, list[dict]]:
    """
    Verifica URLs corporativas + certificados SSL.

    Args:
        headless: True para ocultar el navegador
        enviar_mail: True para enviar el reporte por Outlook al finalizar

    Returns:
        (exito_global, resultados)
        exito_global es True si NO hay fallas (estado OK).
        Estado PARCIAL o FALLA devuelven False.
    """
    resultados: list[dict] = []
    timestamp_run = datetime.now().strftime("%Y%m%d_%H%M%S")

    _log("")
    _log("=" * 70)
    _log(f"Verificacion de URLs Corporativas - {timestamp_run}")
    _log(f"Total: {len(URLS_CORPORATIVAS)} URLs")
    _log(f"Perfil Edge: {EDGE_PROFILE_DIR}")
    _log(f"Evidencias: {EVIDENCIAS_DIR}")
    _log("=" * 70)
    _log("")

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

        for idx, item in enumerate(URLS_CORPORATIVAS, 1):
            nombre = item["nombre"]
            url = item["url"]
            ignorar_estado = item.get("ignorar_estado", False)

            resultado = {
                "nombre": nombre,
                "url": url,
                "ok": False,
                "status": None,
                "status_ok": False,
                "ignorar_estado": ignorar_estado,
                "evidencia": None,
                "error": None,
                "duracion_ms": None,
                "cert": {},
            }

            _log(f"[{idx:02d}/{len(URLS_CORPORATIVAS)}] {nombre}")
            _log(f"       URL: {url}")
            if ignorar_estado:
                _log("       (estado HTTP ignorado para el resultado global)")

            inicio = datetime.now()

            # ---- Navegacion ----
            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=TIMEOUT_NAVEGACION,
                )
                page.wait_for_timeout(TIMEOUT_POST_CARGA)

                status = response.status if response else None
                resultado["status"] = status

                if status is not None and (status < 400 or status in STATUS_OK_EXTRA):
                    resultado["status_ok"] = True
                    nota = " (requiere login)" if status in STATUS_OK_EXTRA else ""
                    _log(f"       Status: {status} -> OK{nota}")
                else:
                    resultado["error"] = f"HTTP {status}"
                    marca = "IGNORADO" if ignorar_estado else "FALLA"
                    _log(f"       Status: {status} -> {marca}")

            except PlaywrightTimeoutError:
                resultado["error"] = f"Timeout ({TIMEOUT_NAVEGACION // 1000}s)"
                marca = "IGNORADO" if ignorar_estado else "ERROR"
                _log(f"       {marca}: timeout")

            except Exception as e:
                err_line = str(e).split("\n")[0]
                resultado["error"] = f"{type(e).__name__}: {err_line}"
                marca = "IGNORADO" if ignorar_estado else "ERROR"
                _log(f"       {marca}: {resultado['error']}")

            # ---- Certificado SSL ----
            cert = _obtener_certificado_ssl(url)
            resultado["cert"] = cert
            _log(f"       Cert:   {_formatear_cert_log(cert)}")

            # ---- Screenshot ----
            try:
                marca_fail = "" if (resultado["status_ok"] or ignorar_estado) else "_FAIL"
                filename = f"{timestamp_run}_{idx:02d}_{_sanitizar_nombre(nombre)}{marca_fail}.png"
                path_evidencia = EVIDENCIAS_DIR / filename
                page.screenshot(path=str(path_evidencia), full_page=False)
                resultado["evidencia"] = str(path_evidencia)
                _log(f"       Evidencia: {filename}")
            except Exception as e:
                _log(f"       (No se pudo capturar screenshot: {e})")

            resultado["ok"] = resultado["status_ok"] or ignorar_estado
            resultado["duracion_ms"] = int(
                (datetime.now() - inicio).total_seconds() * 1000
            )
            resultados.append(resultado)
            _log("")

        context.close()

    # -----------------------------------------------------------------------
    # Resumen consola
    # -----------------------------------------------------------------------
    ok_count = sum(1 for r in resultados if r["ok"])
    fail_count = len(resultados) - ok_count
    ignoradas_count = sum(1 for r in resultados if r["ignorar_estado"])
    alertas_cert = [r for r in resultados
                    if r["cert"].get("valido") and r["cert"].get("alerta") and not r["cert"].get("vencido")]
    vencidos = [r for r in resultados if r["cert"].get("valido") and r["cert"].get("vencido")]
    cert_error = [r for r in resultados if r["cert"].get("aplica") and not r["cert"].get("valido")]
    cert_ca_interna = [r for r in resultados if r["cert"].get("valido") and not r["cert"].get("verificado")]

    exito_global = fail_count == 0
    estado_texto, estado_detalle = _clasificar_estado_global(fail_count)

    _log("=" * 70)
    _log("RESUMEN")
    _log("=" * 70)
    _log(f"OK:                {ok_count}/{len(resultados)}")
    _log(f"FALLA:             {fail_count}/{len(resultados)}")
    _log(f"Ignorados:         {ignoradas_count} (contaron como OK)")
    _log(f"Cert alertas:      {len(alertas_cert)} (vencen en <{DIAS_ALERTA_CERT} dias)")
    _log(f"Cert vencidos:     {len(vencidos)}")
    _log(f"Cert CA interna:   {len(cert_ca_interna)} (leido sin verificar)")
    _log(f"Cert error total:  {len(cert_error)}")

    if fail_count:
        _log("")
        _log("URLs con problemas:")
        for r in resultados:
            if not r["ok"]:
                _log(f"   - {r['nombre']}: {r.get('error', 'desconocido')}")

    if alertas_cert:
        _log("")
        _log(f"Certificados que vencen en <{DIAS_ALERTA_CERT} dias:")
        for r in alertas_cert:
            c = r["cert"]
            fecha = c["fecha_vencimiento"].strftime("%Y-%m-%d")
            _log(f"   - {r['nombre']}: {fecha} ({c['dias_restantes']} dias)")

    if vencidos:
        _log("")
        _log("Certificados VENCIDOS:")
        for r in vencidos:
            c = r["cert"]
            fecha = c["fecha_vencimiento"].strftime("%Y-%m-%d")
            _log(f"   - {r['nombre']}: vencido el {fecha} (hace {-c['dias_restantes']} dias)")

    _log("=" * 70)
    _log(f"Resultado global: {estado_texto} - {estado_detalle}")
    _log("=" * 70)
    _log("")

    # -----------------------------------------------------------------------
    # Envio de email
    # -----------------------------------------------------------------------
    if enviar_mail:
        try:
            _log(f"Enviando reporte a {EMAIL_DESTINATARIO}...")
            enviar_reporte_email(resultados, exito_global)
            _log("Email enviado OK.")
        except Exception as e:
            _log(f"ERROR enviando email: {e}")
        _log("")

    return exito_global, resultados


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    headless = "--headless" in sys.argv
    no_mail = "--no-mail" in sys.argv
    exito, _ = verificar_urls_corporativas(headless=headless, enviar_mail=not no_mail)
    sys.exit(0 if exito else 1)