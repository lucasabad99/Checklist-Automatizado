"""
check_reporte_diario.py
-----------------------
Reporte consolidado diario del Checklist IT - Pecom Energía.

Une (por ahora) los datos de WhatsUp Gold + Email Helpdesk + Accesos Remotos
+ URLs Corporativas + Llamadas 3CX + Otros Sistemas en UN solo mail con
estilo corporativo.

Orden de secciones definido por Lucas:
    1. WhatsUP Alertas de Monitoreo
    2. Email a Helpdesk (envío de prueba a tickets@pecomenergia.com.ar)
    3. Accesos Remotos y Chequeo HES (Forti VPN, Citrix, e-mails HES —
       estático, sin chequeo automatizado, siempre OK)
    4. URLs Corporativas
    5. Llamadas 3CX (telefonía)
    6. Otros Sistemas (Cobranzas.com, Portal Office, Microsoft Teams —
       estático, sin chequeo automatizado, siempre OK)

Los módulos existentes no se tocan: siguen funcionando standalone.
Este archivo los importa, ejecuta con enviar_mail=False (para que no manden
sus mails individuales), y arma un único reporte consolidado.

Requiere: playwright, pywin32, cryptography, Pillow
    pip install cryptography Pillow

Uso standalone:
    python check_reporte_diario.py                # corre todo + manda mail
    python check_reporte_diario.py --headless     # sin ventanas de navegador
    python check_reporte_diario.py --no-mail      # corre pero no envía
"""

from __future__ import annotations

import sys
import json
import threading
from datetime import datetime
from pathlib import Path

import check_Llamadas3cx as tcx_mod
import check_urls_corporativas as urls_mod
import check_whatsupgold as wug_mod
import enviar_mail_outlook as mail_tickets_mod

# Evita que una corrida manual ("Generar Reporte Diario") y el programador
# automático (programador_reporte.py) intenten usar el mismo perfil de Edge
# al mismo tiempo — Playwright bloquea el directorio de perfil mientras está
# en uso, así que correr dos a la vez tira error en vez de convivir.
_lock_corrida = threading.Lock()

ESTADO_REPORTE_JSON = Path(__file__).parent / "estado_reporte_diario.json"


# ============================================================
#                       CONFIGURACIÓN
# ============================================================

BASE_DIR = Path(__file__).parent.resolve()

DESTINATARIOS_MAIL = ["lucasabad80@gmail.com"]

# True  = abrir el mail en Outlook para revisión (no envía) — útil primer test
# False = enviarlo directo con .Send()
MODO_PREVIEW_MAIL = False

# Umbral para clasificar el resultado global de URLs como PARCIAL vs FALLA
# (mismo criterio que usa check_urls_corporativas internamente)
UMBRAL_PARCIAL_URLS = 3

# Paleta (idéntica a la de check_urls_corporativas para mantener el look)
COLOR_OK       = "#16a34a"
COLOR_FAIL     = "#dc2626"
COLOR_WARNING  = "#d97706"
COLOR_MUTED    = "#6b7280"
COLOR_HEADER   = "#1e3a8a"   # azul Pecom del header
COLOR_BORDER   = "#e5e7eb"
COLOR_ACCENT   = "#6cc24a"   # verde Pecom para bordes inferiores de sección


# ============================================================
#                       HELPERS
# ============================================================

_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_es(dt: datetime) -> str:
    return f"{dt.day} de {_MESES_ES[dt.month - 1]} de {dt.year}"


# Cola opcional para transmitir el progreso en vivo (la usa dashboard_reporte_diario.py
# para mostrar las líneas de log en el navegador vía SSE mientras corre).
_progress_queue = None


def _log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        # La consola/proceso no soporta algún caracter del mensaje (→, ✓, tildes...).
        # No dejamos que un simple print tire abajo toda la corrida por esto.
        enc = sys.stdout.encoding or "ascii"
        print(msg.encode(enc, errors="replace").decode(enc), flush=True)
    q = _progress_queue
    if q is not None:
        try:
            q.put_nowait(msg)
        except Exception:
            pass


def _cert_texto_email(cert: dict) -> str:
    """Igual formato que usa check_urls_corporativas en el mail original."""
    if not cert.get("aplica"):
        return "N/A"
    if not cert.get("valido"):
        return f"Error: {cert.get('error') or 'sin info'}"

    fecha = _fecha_es(cert["fecha_vencimiento"])
    dias = cert["dias_restantes"]
    emisor = cert.get("emisor") or "?"
    detalle = f"{fecha} ({dias} dias) - {emisor}"
    if not cert.get("verificado"):
        detalle += " [CA interna]"
    return detalle


def _clasificar_urls(resultados_urls: list[dict]) -> tuple[str, str]:
    """
    Devuelve (etiqueta_estado, color) para la sección de URLs.
    Criterio consistente con el módulo original: OK / PARCIAL / FALLA.
    """
    fail_count = sum(1 for r in resultados_urls if not r["ok"])
    if fail_count == 0:
        return ("OK", COLOR_OK)
    if fail_count <= UMBRAL_PARCIAL_URLS:
        return ("PARCIAL", COLOR_WARNING)
    return ("FALLA", COLOR_FAIL)


def _clasificar_wug(evidencias_wug: dict, resumenes_criticos: bool) -> tuple[str, str]:
    """
    Estado de la sección WhatsUp Gold.
    'evidencias_wug' es {} si el módulo falló completo.
    'resumenes_criticos' True si algún widget detectó algo crítico.
    """
    if not evidencias_wug:
        return ("FALLA", COLOR_FAIL)
    if resumenes_criticos:
        return ("ALERTAS", COLOR_WARNING)
    return ("OK", COLOR_OK)


def _calcular_estado_global(
    evidencias_wug: dict,
    resultados_urls: list[dict],
    ok_email: bool,
    ok_3cx: bool,
) -> tuple[str, str, tuple[str, str, str, str]]:
    """
    Combina el estado de las 4 verificaciones reales en un solo estado
    global OK / PARCIAL / FALLA. Compartida por _correr_reporte_diario_interno
    (corrida manual completa) y actualizar_parcial (programador automático),
    para que ambos caminos usen exactamente el mismo criterio.

    Devuelve (estado_global, color_estado, (estado_urls, estado_wug,
    estado_email, estado_3cx)) — esos 4 últimos son solo para logging/debug.
    """
    estado_urls_txt, _ = _clasificar_urls(resultados_urls) if resultados_urls \
                          else ("FALLA", COLOR_FAIL)
    hay_alertas_wug = any(
        _hay_alertas_en_resumen(info.get("resumen_html", ""))
        for info in evidencias_wug.values()
    )
    estado_wug_txt, _ = _clasificar_wug(evidencias_wug, hay_alertas_wug)
    estado_email_txt = "OK" if ok_email else "FALLA"
    estado_3cx_txt = "OK" if ok_3cx else "FALLA"

    estados = [estado_urls_txt, estado_wug_txt, estado_email_txt, estado_3cx_txt]
    if all(s == "OK" for s in estados):
        estado_global, color_estado = "OK", COLOR_OK
    elif "FALLA" in estados:
        estado_global, color_estado = "FALLA", COLOR_FAIL
    else:
        estado_global, color_estado = "PARCIAL", COLOR_WARNING

    return estado_global, color_estado, (estado_urls_txt, estado_wug_txt, estado_email_txt, estado_3cx_txt)


WUG_WIDGETS_KPI = [
    ("Down Active Monitors", "DOWN"),
    ("Disk Utilization", "DISK"),
    ("Memory Utilization", "MEMORY"),
]

# Umbral de cantidad (no de %) a partir del cual un sub-KPI de WUG pasa de
# PARCIAL (naranja) a CRITICO (rojo). Por debajo de esto, aunque haya algo
# para reportar, no se marca como si "todo hubiera fallado".
WUG_UMBRAL_CRITICO_CANTIDAD = 3


def _hay_alertas_en_resumen(resumen_html: str) -> bool:
    """
    Heurística simple: si el resumen HTML del widget no dice 'Sin ...' /
    'Sin registros', hay algo que reportar.
    """
    if not resumen_html:
        return False
    plain = resumen_html.lower()
    if "sin discos por encima" in plain:
        return False
    if "sin memorias por encima" in plain:
        return False
    if "sin monitores caídos" in plain or "sin monitores caidos" in plain:
        return False
    if "sin registros" in plain:
        return False
    return True


def _kpi_wug_datos(evidencias_wug: dict) -> list[dict]:
    """
    Desglosa WhatsUp Gold por widget (Down / Disk / Memory) con la cantidad
    real de items críticos y su severidad, en vez de un solo número/estado
    binario. Por cada widget en WUG_WIDGETS_KPI devuelve:
        {titulo, etiqueta, cantidad, estado}
    'estado' es "ok" | "warn" | "fail" | "nd" (nd = widget no capturado en
    esta corrida). 'cantidad' es None cuando estado == "nd".

    Reutilizado por _kpi_wug_html (mini-KPI del mail) y
    obtener_items_tablero (desglose en el tablero de TV) para que ambos
    digan siempre lo mismo:
      - 0                                    → ok
      - 1 .. WUG_UMBRAL_CRITICO_CANTIDAD-1   → warn
      - >= WUG_UMBRAL_CRITICO_CANTIDAD       → fail
      - widget no capturado en esta corrida  → nd
    """
    datos = []
    for titulo, etiqueta in WUG_WIDGETS_KPI:
        info = evidencias_wug.get(titulo)
        if info is None:
            datos.append({"titulo": titulo, "etiqueta": etiqueta, "cantidad": None, "estado": "nd"})
            continue

        cantidad = info.get("criticos")
        if cantidad is None:
            # Compatibilidad: corridas viejas sin el campo "criticos".
            cantidad = 1 if _hay_alertas_en_resumen(info.get("resumen_html", "")) else 0

        if cantidad <= 0:
            estado = "ok"
        elif cantidad < WUG_UMBRAL_CRITICO_CANTIDAD:
            estado = "warn"
        else:
            estado = "fail"

        datos.append({"titulo": titulo, "etiqueta": etiqueta, "cantidad": cantidad, "estado": estado})

    return datos


def _kpi_wug_html(evidencias_wug: dict) -> str:
    """KPI de WhatsUp Gold segmentado por widget, para la franja de resumen del mail."""
    color_por_estado = {"ok": COLOR_OK, "warn": COLOR_WARNING, "fail": COLOR_FAIL, "nd": COLOR_FAIL}

    celdas = []
    for d in _kpi_wug_datos(evidencias_wug):
        texto = "N/D" if d["estado"] == "nd" else ("OK" if d["estado"] == "ok" else str(d["cantidad"]))
        color = color_por_estado[d["estado"]]
        celdas.append(f"""
        <td style="padding:0 4px;text-align:center;">
            <div style="font-size:9px;color:{COLOR_MUTED};letter-spacing:0.5px;">{d['etiqueta']}</div>
            <div style="font-size:13px;font-weight:700;color:{color};margin-top:2px;">{texto}</div>
        </td>
        """)

    return f"""
    <div style="font-size:11px;color:{COLOR_MUTED};text-transform:uppercase;
                letter-spacing:0.5px;">WhatsUp Gold</div>
    <table style="margin:6px auto 0 auto;border-collapse:collapse;">
        <tr>{''.join(celdas)}</tr>
    </table>
    """


# ============================================================
#          SECCIÓN WHATSUP GOLD (evidencias inline CID)
# ============================================================

def _seccion_wug_html(evidencias_wug: dict, image_src_resolver=None) -> str:
    """
    HTML de la sección WhatsUp Gold. Cada widget se renderiza con:
      - Subtítulo con línea inferior verde Pecom
      - Resumen textual del widget
      - Imagen (por defecto embebida vía CID: wug_widget_0, wug_widget_1, ...)

    'image_src_resolver', si se pasa, es una función (i, titulo, Path) -> str
    que define el src del <img>. Se usa para el preview en navegador (donde
    'cid:' no funciona), sirviendo las imágenes por HTTP en su lugar. El
    envío real por Outlook sigue usando CID (default), porque ahí sí las
    adjunta _enviar_mail_consolidado con esos mismos IDs.
    """
    if not evidencias_wug:
        return (
            '<div style="padding:14px 16px;background:#fff1f2;border-left:4px solid '
            f'{COLOR_FAIL};border-radius:6px;color:{COLOR_FAIL};">'
            'No se pudo capturar información de WhatsUp Gold en esta corrida.'
            '</div>'
        )

    if image_src_resolver is None:
        image_src_resolver = lambda i, titulo, ruta: f"cid:wug_widget_{i}"

    bloques = []
    for i, (titulo, info) in enumerate(evidencias_wug.items()):
        resumen = info.get("resumen_html", "")
        img_src = image_src_resolver(i, titulo, Path(info["path"]))
        bloques.append(f"""
        <div style="margin-top:18px;">
            <h3 style="font-family:Segoe UI,Arial,sans-serif;color:{COLOR_HEADER};
                       margin:0 0 6px 0;padding-bottom:4px;font-size:15px;
                       border-bottom:2px solid {COLOR_ACCENT};">{titulo}</h3>
            <p style="font-family:Segoe UI,Arial,sans-serif;font-size:13px;
                      color:#374151;margin:6px 0 10px 0;line-height:1.5;">{resumen}</p>
            <img src="{img_src}" style="max-width:100%;border:1px solid {COLOR_BORDER};
                                        border-radius:4px;">
        </div>
        """)

    return "".join(bloques)


# ============================================================
#              SECCIÓN EMAIL HELPDESK
# ============================================================

def _seccion_email_html(ok_email: bool, info_email: dict) -> str:
    """
    HTML de la sección Email Helpdesk: box con estado + detalles del envío.
    """
    ts = info_email.get("timestamp")
    ts_str = ts.strftime("%d/%m/%Y a las %H:%M:%S hs") if ts else "-"

    if ok_email:
        badge = (f'<span style="display:inline-block;padding:3px 10px;'
                 f'border-radius:12px;background:#dcfce7;color:{COLOR_OK};'
                 f'font-size:12px;font-weight:600;">OK — ENVIADO</span>')
        color_borde = COLOR_ACCENT
        mensaje = ("El mail de prueba se envió correctamente a la ticketera. "
                   "Outlook lo procesará desde la bandeja de salida.")
    else:
        badge = (f'<span style="display:inline-block;padding:3px 10px;'
                 f'border-radius:12px;background:#fee2e2;color:{COLOR_FAIL};'
                 f'font-size:12px;font-weight:600;">FALLA</span>')
        color_borde = COLOR_FAIL
        err = info_email.get("error") or "Error desconocido"
        mensaje = f"No se pudo enviar el mail. Detalle: {err}"

    return f"""
    <div style="margin-top:8px;padding:16px 18px;background:#f9fafb;
                border:1px solid {COLOR_BORDER};border-left:4px solid {color_borde};
                border-radius:6px;">
        <div style="margin-bottom:10px;">{badge}</div>
        <table style="width:100%;border-collapse:collapse;font-size:13px;color:#374151;">
            <tr>
                <td style="padding:4px 0;width:130px;color:{COLOR_MUTED};
                           text-transform:uppercase;font-size:11px;letter-spacing:0.5px;">
                    Destinatario
                </td>
                <td style="padding:4px 0;font-weight:600;color:#111827;">
                    {info_email.get('destinatario', '-')}
                </td>
            </tr>
            <tr>
                <td style="padding:4px 0;color:{COLOR_MUTED};
                           text-transform:uppercase;font-size:11px;letter-spacing:0.5px;">
                    Asunto
                </td>
                <td style="padding:4px 0;color:#111827;">
                    {info_email.get('asunto', '-')}
                </td>
            </tr>
            <tr>
                <td style="padding:4px 0;color:{COLOR_MUTED};
                           text-transform:uppercase;font-size:11px;letter-spacing:0.5px;">
                    Enviado
                </td>
                <td style="padding:4px 0;color:#111827;">{ts_str}</td>
            </tr>
        </table>
        <div style="margin-top:12px;padding-top:10px;border-top:1px dashed {COLOR_BORDER};
                    font-size:12px;color:{COLOR_MUTED};line-height:1.5;">
            {mensaje}
        </div>
    </div>
    """


# ============================================================
#         SECCIONES ESTÁTICAS (SIEMPRE OK, SIN CHEQUEO REAL)
# ============================================================
#
# No hay chequeo automatizado detrás de estos ítems (a diferencia del resto
# del reporte). Es solo texto fijo que se agrega al documento para dejar
# constancia de estos sistemas en el checklist diario.

def _grupos_estaticos_html(grupos: list[tuple[str, list[str]]]) -> str:
    """Renderiza una lista de (titulo_grupo, [items]) como bloques con
    badge OK, reutilizado por todas las secciones estáticas del reporte."""
    badge_ok = (f'<span style="display:inline-block;padding:3px 10px;'
                f'border-radius:12px;background:#dcfce7;color:{COLOR_OK};'
                f'font-size:12px;font-weight:600;">OK</span>')

    bloques = []
    for titulo, items in grupos:
        filas = "".join(f"""
        <tr style="border-bottom:1px solid {COLOR_BORDER};">
            <td style="padding:8px 12px;width:1%;white-space:nowrap;">{badge_ok}</td>
            <td style="padding:8px 12px;color:#111827;font-size:13px;">{item}</td>
        </tr>
        """ for item in items)

        bloques.append(f"""
        <div style="margin-top:18px;">
            <h3 style="font-family:Segoe UI,Arial,sans-serif;color:{COLOR_HEADER};
                       margin:0 0 6px 0;padding-bottom:4px;font-size:15px;
                       border-bottom:2px solid {COLOR_ACCENT};">{titulo}</h3>
            <table style="width:100%;border-collapse:collapse;">
                {filas}
            </table>
        </div>
        """)

    return "".join(bloques)


# Grupos estáticos — a nivel de módulo para que obtener_items_tablero()
# (tablero de TV) pueda reusar exactamente los mismos datos que el mail,
# sin duplicarlos ni arriesgar que se desincronicen.
GRUPOS_OTROS_SISTEMAS: list[tuple[str, list[str]]] = [
    ("Cobranzas.com", [
        "SKM - Procesamiento Exitoso",
        "SKS - Procesamiento Exitoso",
    ]),
    ("Portal Office", [
        "Office.com - Portal O365",
        "Outlook - Portal O365",
    ]),
    ("Microsoft Teams", [
        "Microsoft Teams (Telefonía)",
        "Microsoft Teams",
        "Microsoft Teams Mobile",
    ]),
]

GRUPOS_ACCESOS_REMOTOS: list[tuple[str, list[str]]] = [
    ("Forti Client", [
        "VPN: VPN-SSL",
    ]),
    ("Citrix", [
        "Citrix PecomEnergia por Browser por afuera",
        "Citrix PecomEnergia – Citrix Workspace Client",
        "Citrix 2 PecomEnergia",
        "Citrix Mobile: Citrix Mobile",
        "SAP por Citrix",
        "VDI Central",
        "VDI Consultores",
    ]),
    ("Envío de e-mails para chequear HES", [
        "Se envió 1 email a un correo externo",
        "Se envió 1 email de un correo externo a un correo interno",
    ]),
]


def _seccion_otros_sistemas_html() -> str:
    """HTML estático con los sistemas que se listan siempre como OK."""
    return _grupos_estaticos_html(GRUPOS_OTROS_SISTEMAS)


def _seccion_accesos_remotos_html() -> str:
    """HTML estático con VPN Forti, Citrix y el chequeo de e-mails HES."""
    return _grupos_estaticos_html(GRUPOS_ACCESOS_REMOTOS)


# ============================================================
#              SECCIÓN LLAMADAS 3CX (TELEFONÍA)
# ============================================================

def _seccion_3cx_html(ok_3cx: bool) -> str:
    """
    HTML de la sección Llamadas 3CX: box con estado, sin evidencia adjunta
    (a diferencia de WhatsUp Gold, que es la única sección con captura).
    """
    if ok_3cx:
        badge = (f'<span style="display:inline-block;padding:3px 10px;'
                 f'border-radius:12px;background:#dcfce7;color:{COLOR_OK};'
                 f'font-size:12px;font-weight:600;">OK — LLAMADA EXITOSA</span>')
        color_borde = COLOR_ACCENT
        mensaje = (f"La llamada de prueba saliente a {tcx_mod.NUMERO_DESTINO} "
                   "se originó correctamente desde 3CX Phone.")
    else:
        badge = (f'<span style="display:inline-block;padding:3px 10px;'
                 f'border-radius:12px;background:#fee2e2;color:{COLOR_FAIL};'
                 f'font-size:12px;font-weight:600;">FALLA</span>')
        color_borde = COLOR_FAIL
        mensaje = ("No se pudo completar la llamada de prueba por 3CX Phone. "
                   "Revisar la evidencia y que la app esté abierta y logueada.")

    return f"""
    <div style="margin-top:8px;padding:16px 18px;background:#f9fafb;
                border:1px solid {COLOR_BORDER};border-left:4px solid {color_borde};
                border-radius:6px;">
        <div style="margin-bottom:10px;">{badge}</div>
        <div style="font-size:12px;color:{COLOR_MUTED};line-height:1.5;">
            {mensaje}
        </div>
    </div>
    """


# ============================================================
#        SECCIÓN URLs CORPORATIVAS (mismo look del mail original)
# ============================================================

def _seccion_urls_html(resultados_urls: list[dict]) -> str:
    """
    HTML para la sección de URLs Corporativas. Reproduce el estilo del mail
    original: mini-KPIs + bloque de alertas + tabla con badges.
    """
    if not resultados_urls:
        return (
            '<div style="padding:14px 16px;background:#fff1f2;border-left:4px solid '
            f'{COLOR_FAIL};border-radius:6px;color:{COLOR_FAIL};">'
            'No se pudieron obtener resultados de URLs Corporativas.'
            '</div>'
        )

    ok_count   = sum(1 for r in resultados_urls if r["ok"])
    fail_count = len(resultados_urls) - ok_count
    total      = len(resultados_urls)
    estado_urls_txt, estado_urls_color = _clasificar_urls(resultados_urls)

    alertas_cert = [
        r for r in resultados_urls
        if r["cert"].get("aplica") and r["cert"].get("valido")
           and r["cert"].get("alerta") and not r["cert"].get("vencido")
    ]
    vencidos = [
        r for r in resultados_urls
        if r["cert"].get("aplica") and r["cert"].get("valido")
           and r["cert"].get("vencido")
    ]

    kpi_html = f"""
    <table style="width:100%;border-collapse:collapse;margin:0 0 16px 0;
                  background:#f9fafb;border:1px solid {COLOR_BORDER};
                  border-radius:6px;">
        <tr>
            <td style="width:33%;text-align:center;padding:12px;">
                <div style="font-size:11px;color:{COLOR_MUTED};
                            text-transform:uppercase;letter-spacing:0.5px;">Resultado</div>
                <div style="font-size:20px;font-weight:700;
                            color:{estado_urls_color};
                            margin-top:4px;">{estado_urls_txt}</div>
            </td>
            <td style="width:33%;text-align:center;padding:12px;
                       border-left:1px solid {COLOR_BORDER};">
                <div style="font-size:11px;color:{COLOR_MUTED};
                            text-transform:uppercase;letter-spacing:0.5px;">URLs verificadas</div>
                <div style="font-size:20px;font-weight:700;color:#111827;margin-top:4px;">
                    {ok_count}<span style="font-size:14px;color:{COLOR_MUTED};">/{total}</span>
                </div>
            </td>
            <td style="width:33%;text-align:center;padding:12px;
                       border-left:1px solid {COLOR_BORDER};">
                <div style="font-size:11px;color:{COLOR_MUTED};
                            text-transform:uppercase;letter-spacing:0.5px;">Certs en alerta</div>
                <div style="font-size:20px;font-weight:700;
                            color:{COLOR_WARNING if (alertas_cert or vencidos) else COLOR_OK};
                            margin-top:4px;">{len(alertas_cert) + len(vencidos)}</div>
            </td>
        </tr>
    </table>
    """

    bloque_alertas = ""
    if alertas_cert or vencidos:
        items = []
        for r in vencidos:
            c = r["cert"]
            fecha = _fecha_es(c["fecha_vencimiento"])
            items.append(
                f'<li style="color:{COLOR_FAIL};"><strong>{r["nombre"]}</strong>: '
                f'VENCIDO el {fecha} (hace {-c["dias_restantes"]} dias)</li>'
            )
        for r in alertas_cert:
            c = r["cert"]
            fecha = _fecha_es(c["fecha_vencimiento"])
            items.append(
                f'<li style="color:{COLOR_WARNING};"><strong>{r["nombre"]}</strong>: '
                f'vence el {fecha} ({c["dias_restantes"]} dias restantes)</li>'
            )
        bloque_alertas = f"""
        <div style="margin:0 0 16px 0;padding:14px 16px;border-left:4px solid {COLOR_WARNING};
                    background:#fffbeb;border-radius:6px;">
            <div style="font-weight:700;color:{COLOR_WARNING};margin-bottom:8px;">
                Certificados que requieren atencion
            </div>
            <ul style="margin:0;padding-left:20px;">
                {''.join(items)}
            </ul>
        </div>
        """

    filas_html = []
    STATUS_OK_EXTRA = getattr(urls_mod, "STATUS_OK_EXTRA", {401, 403})

    for r in resultados_urls:
        cert = r["cert"]

        if r["ok"]:
            if r["ignorar_estado"] and not r["status_ok"]:
                badge = (f'<span style="display:inline-block;padding:3px 10px;'
                         f'border-radius:12px;background:#f3f4f6;color:{COLOR_MUTED};'
                         f'font-size:12px;font-weight:600;">IGNORADO</span>')
            else:
                badge = (f'<span style="display:inline-block;padding:3px 10px;'
                         f'border-radius:12px;background:#dcfce7;color:{COLOR_OK};'
                         f'font-size:12px;font-weight:600;">OK</span>')
        else:
            badge = (f'<span style="display:inline-block;padding:3px 10px;'
                     f'border-radius:12px;background:#fee2e2;color:{COLOR_FAIL};'
                     f'font-size:12px;font-weight:600;">FALLA</span>')

        cert_texto = _cert_texto_email(cert)
        if not cert.get("aplica"):
            cert_color = COLOR_MUTED
        elif not cert.get("valido") or cert.get("vencido"):
            cert_color = COLOR_FAIL
        elif cert.get("alerta"):
            cert_color = COLOR_WARNING
        else:
            cert_color = "#111827"

        detalle_error = ""
        if not r["ok"] and r.get("error"):
            err_short = str(r["error"]).split("\n")[0][:120]
            detalle_error = (f'<div style="font-size:12px;color:{COLOR_FAIL};'
                             f'margin-top:2px;">{err_short}</div>')

        filas_html.append(f"""
        <tr style="border-bottom:1px solid {COLOR_BORDER};">
            <td style="padding:10px 12px;vertical-align:top;">{badge}</td>
            <td style="padding:10px 12px;vertical-align:top;">
                <div style="font-weight:600;color:#111827;">{r['nombre']}</div>
                <div style="font-size:12px;color:{COLOR_MUTED};word-break:break-all;">
                    <a href="{r['url']}" style="color:{COLOR_MUTED};text-decoration:none;">{r['url']}</a>
                </div>
                {detalle_error}
            </td>
            <td style="padding:10px 12px;vertical-align:top;color:{cert_color};
                       font-size:13px;">{cert_texto}</td>
        </tr>
        """)

    tabla_html = f"""
    <table style="width:100%;border-collapse:collapse;margin:0;">
        <thead>
            <tr style="background:#f3f4f6;">
                <th style="padding:10px 12px;text-align:left;font-size:11px;
                           text-transform:uppercase;color:{COLOR_MUTED};
                           letter-spacing:0.5px;">Estado</th>
                <th style="padding:10px 12px;text-align:left;font-size:11px;
                           text-transform:uppercase;color:{COLOR_MUTED};
                           letter-spacing:0.5px;">Servicio</th>
                <th style="padding:10px 12px;text-align:left;font-size:11px;
                           text-transform:uppercase;color:{COLOR_MUTED};
                           letter-spacing:0.5px;">Certificado SSL</th>
            </tr>
        </thead>
        <tbody>
            {''.join(filas_html)}
        </tbody>
    </table>
    """

    return kpi_html + bloque_alertas + tabla_html


# ============================================================
#                  HTML CONSOLIDADO
# ============================================================

def _armar_html_consolidado(
    resultados_urls: list[dict],
    evidencias_wug: dict,
    ok_email: bool,
    info_email: dict,
    ok_3cx: bool,
    estado_global: str,
    color_estado_global: str,
    wug_image_resolver=None,
) -> str:
    """Arma el HTML del mail consolidado.
    Orden: WUG → Email → Accesos Remotos (VPN/Citrix/HES) → URLs → 3CX → Otros.
    'wug_image_resolver' se reenvía a _seccion_wug_html (ver ahí): None =
    CID para el envío real, o una función (i,titulo,Path)->url para preview
    en navegador."""
    ahora = datetime.now()
    fecha_str = ahora.strftime("%d/%m/%Y")
    hora_str = ahora.strftime("%H:%M")

    seccion_wug     = _seccion_wug_html(evidencias_wug, wug_image_resolver)
    seccion_email   = _seccion_email_html(ok_email, info_email)
    seccion_accesos = _seccion_accesos_remotos_html()
    seccion_urls    = _seccion_urls_html(resultados_urls)
    seccion_3cx     = _seccion_3cx_html(ok_3cx)
    seccion_otros   = _seccion_otros_sistemas_html()

    total_urls = len(resultados_urls)
    ok_urls    = sum(1 for r in resultados_urls if r["ok"])
    kpi_wug_html = _kpi_wug_html(evidencias_wug)
    email_estado_txt = "OK" if ok_email else "FALLA"
    email_estado_color = COLOR_OK if ok_email else COLOR_FAIL
    tcx_estado_txt = "OK" if ok_3cx else "FALLA"
    tcx_estado_color = COLOR_OK if ok_3cx else COLOR_FAIL

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>Checklist IT - Reporte Diario</title>
</head>
<body style="margin:0;padding:20px;font-family:Segoe UI, Arial, sans-serif;
             background:#f9fafb;color:#111827;">

    <div style="max-width:900px;margin:0 auto;background:#ffffff;border-radius:8px;
                overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">

        <!-- Header -->
        <div style="background:{COLOR_HEADER};color:#ffffff;padding:24px 28px;">
            <div style="font-size:12px;opacity:0.85;letter-spacing:1px;
                        text-transform:uppercase;">Pecom Energía · IT &amp; Innovación</div>
            <h1 style="margin:6px 0 0 0;font-size:22px;font-weight:600;">
                Checklist IT — Reporte Diario
            </h1>
            <div style="margin-top:6px;font-size:13px;opacity:0.9;">
                {fecha_str} — {hora_str} hs
            </div>
        </div>

        <!-- Resumen global (5 KPIs) -->
        <div style="padding:20px 28px;background:#f9fafb;
                    border-bottom:1px solid {COLOR_BORDER};">
            <table style="width:100%;border-collapse:collapse;">
                <tr>
                    <td style="width:20%;text-align:center;padding:8px;">
                        <div style="font-size:11px;color:{COLOR_MUTED};
                                    text-transform:uppercase;letter-spacing:0.5px;">
                            Resultado Global
                        </div>
                        <div style="font-size:22px;font-weight:700;
                                    color:{color_estado_global};margin-top:4px;">
                            {estado_global}
                        </div>
                    </td>
                    <td style="width:20%;text-align:center;padding:8px;
                               border-left:1px solid {COLOR_BORDER};">
                        {kpi_wug_html}
                    </td>
                    <td style="width:20%;text-align:center;padding:8px;
                               border-left:1px solid {COLOR_BORDER};">
                        <div style="font-size:11px;color:{COLOR_MUTED};
                                    text-transform:uppercase;letter-spacing:0.5px;">
                            Email Helpdesk
                        </div>
                        <div style="font-size:22px;font-weight:700;
                                    color:{email_estado_color};margin-top:4px;">
                            {email_estado_txt}
                        </div>
                    </td>
                    <td style="width:20%;text-align:center;padding:8px;
                               border-left:1px solid {COLOR_BORDER};">
                        <div style="font-size:11px;color:{COLOR_MUTED};
                                    text-transform:uppercase;letter-spacing:0.5px;">
                            URLs Corporativas
                        </div>
                        <div style="font-size:22px;font-weight:700;color:#111827;
                                    margin-top:4px;">
                            {ok_urls}<span style="font-size:14px;color:{COLOR_MUTED};">
                            /{total_urls}</span>
                        </div>
                    </td>
                    <td style="width:20%;text-align:center;padding:8px;
                               border-left:1px solid {COLOR_BORDER};">
                        <div style="font-size:11px;color:{COLOR_MUTED};
                                    text-transform:uppercase;letter-spacing:0.5px;">
                            Llamadas 3CX
                        </div>
                        <div style="font-size:22px;font-weight:700;
                                    color:{tcx_estado_color};margin-top:4px;">
                            {tcx_estado_txt}
                        </div>
                    </td>
                </tr>
            </table>
        </div>

        <!-- Contenido -->
        <div style="padding:24px 28px;">

            <p style="font-size:13px;color:#374151;margin:0 0 20px 0;">
                Buenos días,<br>
                Reporte automático del Checklist IT generado el
                <b>{fecha_str}</b> a las <b>{hora_str} hs</b>.
                Detalle a continuación por sistema:
            </p>

            <!-- ============ 1. WHATSUP GOLD ============ -->
            <h2 style="color:{COLOR_HEADER};font-size:17px;font-weight:700;
                       margin:8px 0 12px 0;padding-bottom:6px;
                       border-bottom:2px solid {COLOR_ACCENT};">
                WhatsUP Alertas de Monitoreo
            </h2>
            {seccion_wug}

            <!-- ============ 2. EMAIL HELPDESK ============ -->
            <h2 style="color:{COLOR_HEADER};font-size:17px;font-weight:700;
                       margin:32px 0 12px 0;padding-bottom:6px;
                       border-bottom:2px solid {COLOR_ACCENT};">
                Envío e-mail a tickets Invgate
            </h2>
            {seccion_email}

            <!-- ============ 3. ACCESOS REMOTOS (VPN/CITRIX/HES) ============ -->
            <h2 style="color:{COLOR_HEADER};font-size:17px;font-weight:700;
                       margin:32px 0 12px 0;padding-bottom:6px;
                       border-bottom:2px solid {COLOR_ACCENT};">
                Accesos Remotos y Chequeo HES
            </h2>
            {seccion_accesos}

            <!-- ============ 4. URLs CORPORATIVAS ============ -->
            <h2 style="color:{COLOR_HEADER};font-size:17px;font-weight:700;
                       margin:32px 0 12px 0;padding-bottom:6px;
                       border-bottom:2px solid {COLOR_ACCENT};">
                URLs Corporativas
            </h2>
            {seccion_urls}

            <!-- ============ 5. LLAMADAS 3CX ============ -->
            <h2 style="color:{COLOR_HEADER};font-size:17px;font-weight:700;
                       margin:32px 0 12px 0;padding-bottom:6px;
                       border-bottom:2px solid {COLOR_ACCENT};">
                Llamadas 3CX (Telefonía)
            </h2>
            {seccion_3cx}

            <!-- ============ 6. OTROS SISTEMAS ============ -->
            <h2 style="color:{COLOR_HEADER};font-size:17px;font-weight:700;
                       margin:32px 0 12px 0;padding-bottom:6px;
                       border-bottom:2px solid {COLOR_ACCENT};">
                Otros Sistemas
            </h2>
            {seccion_otros}

        </div>

        <!-- Footer -->
        <div style="padding:14px 28px;background:#f3f4f6;font-size:11px;
                    color:{COLOR_MUTED};text-align:center;
                    border-top:1px solid {COLOR_BORDER};">
            Reporte generado automáticamente por Checklist-Automatizado ·
            IT &amp; Innovación · Pecom Energía · {fecha_str} {hora_str}
        </div>

    </div>

</body>
</html>"""


# ============================================================
#                  ENVÍO POR OUTLOOK COM
# ============================================================

def _enviar_mail_consolidado(
    html: str,
    evidencias_wug: dict,
    asunto: str,
    destinatarios: list[str],
    cc: list[str] | None = None,
    preview: bool = False,
) -> bool:
    """
    Envía el mail consolidado por Outlook COM con las imágenes de WUG
    embebidas inline vía CID (optimizadas para no reventar los 102KB de Gmail).
    'destinatarios' va en Para, 'cc' (opcional) va en CC.
    """
    try:
        import win32com.client as win32
    except ImportError:
        _log("[REPORTE] ERROR: pywin32 no está instalado.")
        return False

    PR_ATTACH_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"

    try:
        outlook = win32.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # olMailItem
        mail.To = "; ".join(destinatarios)
        if cc:
            mail.CC = "; ".join(cc)
        mail.Subject = asunto

        # Antes de armar el resto del mail, confirmamos que Outlook pudo
        # resolver cada nombre/lista de distribución contra la libreta de
        # direcciones (funciona igual con nombres tipo "Apellido, Nombre" o
        # listas de distribución que con direcciones de mail sueltas). Si
        # alguno queda ambiguo o no se encuentra, no mandamos nada: mejor
        # frenar acá que arriesgarse a que le llegue a la persona equivocada.
        if not mail.Recipients.ResolveAll():
            no_resueltos = [
                mail.Recipients.Item(i).Name
                for i in range(1, mail.Recipients.Count + 1)
                if not mail.Recipients.Item(i).Resolved
            ]
            _log(f"[REPORTE] ERROR: no se pudieron resolver estos destinatarios "
                 f"contra la libreta de direcciones: {', '.join(no_resueltos)}")
            return False

        peso_total_kb = 0.0
        for i, (titulo, info) in enumerate(evidencias_wug.items()):
            ruta = Path(info["path"])
            try:
                ruta_para_mail = wug_mod._optimizar_imagen_para_mail(ruta)
            except Exception as e:
                _log(f"[REPORTE] Warning: no se pudo optimizar {ruta.name}: {e}. "
                     f"Se usa el original.")
                ruta_para_mail = ruta

            peso_total_kb += ruta_para_mail.stat().st_size / 1024
            attachment = mail.Attachments.Add(str(ruta_para_mail.resolve()))
            attachment.PropertyAccessor.SetProperty(
                PR_ATTACH_CONTENT_ID, f"wug_widget_{i}"
            )

        peso_body_est = peso_total_kb * 1.33
        _log(f"[REPORTE] Peso imágenes: {peso_total_kb:.1f}KB "
             f"(≈{peso_body_est:.1f}KB en base64 dentro del mail).")
        if peso_body_est > 90:
            _log("[REPORTE] ⚠  Peso proyectado cerca del límite de 102KB de Gmail. "
                 "Considerá bajar IMG_ANCHO_MAX_PX o IMG_CALIDAD_JPEG en "
                 "check_whatsupgold.py.")

        mail.HTMLBody = html

        if preview:
            mail.Display()
            _log("[REPORTE] Preview: mail abierto en Outlook (no se envió).")
        else:
            mail.Send()
            _log(f"[REPORTE] OK - Mail enviado a: {', '.join(destinatarios)}")

        return True

    except Exception as e:
        _log(f"[REPORTE] ERROR armando/enviando mail: {type(e).__name__}: {e}")
        return False


# ============================================================
#          ESTADO DE LA ÚLTIMA CORRIDA (para envío diferido)
# ============================================================
# Igual que check_whatsupgold._ultima_corrida: correr_reporte_diario() arma
# todo (checks + HTML) pero NO manda nada. enviar_ultimo_reporte() manda lo
# que quedó guardado acá, una vez que alguien lo revisó en el preview.

_ultima_corrida_reporte = {
    "timestamp": None,
    "html": None,
    "evidencias_wug": {},
    "estado_global": None,
    "asunto": None,
    # Timestamp REAL de la última vez que cada sección se actualizó de
    # verdad (no el timestamp global del blob) — necesario porque con el
    # programador automático, WhatsUp Gold, URLs y Email/3CX se refrescan en
    # momentos distintos, no todos juntos. Sin esto, el tablero mostraba
    # "hace 17 min" en WhatsUp Gold aunque ese dato fuera de la corrida
    # diaria de la mañana, solo porque URLs se había actualizado hace 17 min.
    "ts_wug": None,
    "ts_urls": None,
    "ts_email_3cx": None,
}


def obtener_ultima_corrida_reporte() -> dict:
    """Devuelve una copia superficial del último reporte armado (o vacío si
    todavía no se corrió nada en esta sesión)."""
    return dict(_ultima_corrida_reporte)


def _serializar_resultados_urls(resultados_urls: list[dict]) -> list[dict]:
    """resultados_urls trae cert['fecha_vencimiento'] como datetime real —
    no es serializable por json.dumps tal cual. Lo pasamos a isoformat()."""
    out = []
    for r in resultados_urls:
        r2 = dict(r)
        cert = dict(r2.get("cert") or {})
        fv = cert.get("fecha_vencimiento")
        if isinstance(fv, datetime):
            cert["fecha_vencimiento"] = fv.isoformat()
        r2["cert"] = cert
        out.append(r2)
    return out


def _deserializar_resultados_urls(resultados_urls: list[dict]) -> list[dict]:
    """Inverso de _serializar_resultados_urls: reconstruye el datetime para
    que _armar_html_consolidado (vía _fecha_es) siga funcionando igual."""
    out = []
    for r in resultados_urls:
        r2 = dict(r)
        cert = dict(r2.get("cert") or {})
        fv = cert.get("fecha_vencimiento")
        if isinstance(fv, str):
            cert["fecha_vencimiento"] = datetime.fromisoformat(fv)
        r2["cert"] = cert
        out.append(r2)
    return out


def _ts_iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None


def _ts_from_iso(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


def _persistir_estado_reporte() -> None:
    """Guarda _ultima_corrida_reporte en disco (ESTADO_REPORTE_JSON) para
    sobrevivir un reinicio del proceso — importante porque
    programador_reporte.py está pensado para correr 24/7 sin depender de
    que alguien lo tenga abierto."""
    d = _ultima_corrida_reporte
    if not d.get("timestamp"):
        return
    try:
        evidencias_wug_json = {
            titulo: {
                "path": str(info["path"]),
                "resumen_html": info.get("resumen_html", ""),
                "criticos": info.get("criticos", 0),
                "items_criticos": info.get("items_criticos", []),
            }
            for titulo, info in (d.get("evidencias_wug") or {}).items()
        }
        info_email = dict(d.get("info_email") or {})
        ts_ie = info_email.get("timestamp")
        info_email["timestamp"] = ts_ie.isoformat() if ts_ie else None

        payload = {
            "timestamp": d["timestamp"].isoformat(),
            "html": d.get("html"),
            "estado_global": d.get("estado_global"),
            "asunto": d.get("asunto"),
            "evidencias_wug": evidencias_wug_json,
            "resultados_urls": _serializar_resultados_urls(d.get("resultados_urls", [])),
            "ok_email": d.get("ok_email"),
            "info_email": info_email,
            "ok_3cx": d.get("ok_3cx"),
            "color_estado": d.get("color_estado"),
            "ts_wug": _ts_iso(d.get("ts_wug")),
            "ts_urls": _ts_iso(d.get("ts_urls")),
            "ts_email_3cx": _ts_iso(d.get("ts_email_3cx")),
        }
        ESTADO_REPORTE_JSON.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        _log(f"[REPORTE] Error persistiendo estado: {type(e).__name__}: {e}")


def cargar_estado_reporte() -> None:
    """Restaura _ultima_corrida_reporte desde disco al arrancar el proceso —
    llamar una vez al iniciar dashboard_reporte_diario.py, así un reinicio
    no deja el tablero ni el programador automático 'en blanco'."""
    if not ESTADO_REPORTE_JSON.exists():
        return
    try:
        data = json.loads(ESTADO_REPORTE_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        _log(f"[REPORTE] No se pudo leer estado previo: {type(e).__name__}: {e}")
        return

    ts = data.get("timestamp")
    info_email = dict(data.get("info_email") or {})
    ts_ie = info_email.get("timestamp")
    info_email["timestamp"] = datetime.fromisoformat(ts_ie) if ts_ie else None

    _ultima_corrida_reporte.update({
        "timestamp": datetime.fromisoformat(ts) if ts else None,
        "html": data.get("html"),
        "evidencias_wug": data.get("evidencias_wug", {}),
        "estado_global": data.get("estado_global"),
        "asunto": data.get("asunto"),
        "resultados_urls": _deserializar_resultados_urls(data.get("resultados_urls", [])),
        "ok_email": data.get("ok_email", False),
        "info_email": info_email,
        "ok_3cx": data.get("ok_3cx", False),
        "color_estado": data.get("color_estado"),
        "ts_wug": _ts_from_iso(data.get("ts_wug")),
        "ts_urls": _ts_from_iso(data.get("ts_urls")),
        "ts_email_3cx": _ts_from_iso(data.get("ts_email_3cx")),
    })
    _log(f"[REPORTE] Estado previo restaurado (corrida del {ts or 'desconocido'}).")


def actualizar_parcial(
    *,
    evidencias_wug: dict | None = None,
    resultados_urls: list[dict] | None = None,
    ok_email: bool | None = None,
    info_email: dict | None = None,
    ok_3cx: bool | None = None,
) -> dict:
    """
    Actualiza SOLO los campos pasados (distintos de None) sobre el último
    estado conocido, y reconstruye estado_global + html a partir del
    resultado combinado. Pensada para programador_reporte.py: permite
    refrescar WhatsUp Gold + URLs Corporativas cada tanto sin tocar
    Email Helpdesk / 3CX (que tienen efectos reales — mail y llamada — y se
    actualizan aparte, con su propia frecuencia, mucho más baja).

    Toma el mismo lock que correr_reporte_diario(): si hay una corrida
    manual en curso, no hace nada y devuelve el estado tal cual estaba
    (mejor saltear un ciclo que chocar con Playwright/Outlook en uso).
    """
    if not _lock_corrida.acquire(blocking=False):
        _log("[REPORTE] actualizar_parcial: hay otra corrida en curso, se salta este ciclo.")
        return dict(_ultima_corrida_reporte)

    try:
        d = _ultima_corrida_reporte
        evidencias_wug_final = evidencias_wug if evidencias_wug is not None else d.get("evidencias_wug", {})
        resultados_urls_final = resultados_urls if resultados_urls is not None else d.get("resultados_urls", [])
        ok_email_final = ok_email if ok_email is not None else d.get("ok_email", False)
        info_email_final = info_email if info_email is not None else d.get(
            "info_email",
            {"destinatario": "-", "asunto": "-", "timestamp": None,
             "error": "Todavía no se corrió la verificación diaria (Email Helpdesk)."},
        )
        ok_3cx_final = ok_3cx if ok_3cx is not None else d.get("ok_3cx", False)

        estado_global, color_estado, _ = _calcular_estado_global(
            evidencias_wug_final, resultados_urls_final, ok_email_final, ok_3cx_final
        )

        html = _armar_html_consolidado(
            resultados_urls=resultados_urls_final,
            evidencias_wug=evidencias_wug_final,
            ok_email=ok_email_final,
            info_email=info_email_final,
            ok_3cx=ok_3cx_final,
            estado_global=estado_global,
            color_estado_global=color_estado,
        )

        fecha_str = datetime.now().strftime("%d/%m/%Y")
        asunto = f"[Checklist IT] Reporte Diario - {estado_global} - {fecha_str}"

        ahora = datetime.now()
        actualizacion = {
            "timestamp": ahora,
            "html": html,
            "evidencias_wug": evidencias_wug_final,
            "estado_global": estado_global,
            "asunto": asunto,
            "resultados_urls": resultados_urls_final,
            "ok_email": ok_email_final,
            "info_email": info_email_final,
            "ok_3cx": ok_3cx_final,
            "color_estado": color_estado,
        }
        # Solo la sección que realmente se pasó (no None) cuenta como
        # "actualizada ahora" — así cada tarjeta del tablero muestra su
        # propia hora real, no la del último ciclo que tocó cualquier cosa.
        if evidencias_wug is not None:
            actualizacion["ts_wug"] = ahora
        if resultados_urls is not None:
            actualizacion["ts_urls"] = ahora
        if ok_email is not None or ok_3cx is not None:
            actualizacion["ts_email_3cx"] = ahora

        _ultima_corrida_reporte.update(actualizacion)
        _persistir_estado_reporte()
        return dict(_ultima_corrida_reporte)
    finally:
        _lock_corrida.release()


def obtener_items_tablero() -> list[dict]:
    """
    Arma una lista de 6 items {nombre, ok, estado, detalle, desglose?,
    informativo?} a partir de la última corrida — las 4 verificaciones reales
    (WhatsUp Gold, Email Helpdesk, URLs Corporativas, Llamadas 3CX) MÁS las 2
    secciones estáticas que el mail también incluye (Accesos Remotos y
    Chequeo HES, Otros Sistemas). Pensada para paneles/tableros
    (dashboard_reporte_diario.py expone esto en /estado.json, y tablero.py lo
    consume). Reutiliza las mismas funciones/datos de clasificación que arma
    el mail, para que el tablero y el reporte digan siempre lo mismo.

    'estado' es "ok" | "warn" | "fail" (warn = alertas/parcial, no es un
    fallo duro pero tampoco todo verde). 'ok' es el equivalente bool
    (True solo si estado == "ok") para consumidores más simples.
    'desglose', cuando está presente, es una lista de {etiqueta, valor,
    estado} para mostrar en detalle en vez de una sola frase.
    'informativo' (solo en las 2 secciones estáticas) marca que ese item NO
    tiene chequeo automatizado real detrás — el tablero debe dejarlo claro
    en vez de mostrarlo como si fuera una verificación más.

    Devuelve [] si todavía no se corrió ningún reporte en esta sesión.
    """
    d = _ultima_corrida_reporte
    if not d.get("timestamp"):
        return []

    evidencias_wug = d["evidencias_wug"]
    resultados_urls = d["resultados_urls"]
    ok_email = d["ok_email"]
    info_email = d["info_email"]
    ok_3cx = d["ok_3cx"]

    # WhatsUp Gold
    hay_alertas_wug = any(
        _hay_alertas_en_resumen(info.get("resumen_html", ""))
        for info in evidencias_wug.values()
    )
    estado_wug_txt, _ = _clasificar_wug(evidencias_wug, hay_alertas_wug)
    criticos_wug = sum((info.get("criticos") or 0) for info in evidencias_wug.values())
    det_wug = (f"{len(evidencias_wug)} widgets capturados" if evidencias_wug
               else "No se pudo capturar información")
    if criticos_wug:
        det_wug += f" — {criticos_wug} alerta(s) crítica(s)"
    estado_wug = "ok" if estado_wug_txt == "OK" else ("warn" if estado_wug_txt == "ALERTAS" else "fail")

    # Desglose por widget (Down Monitors / Disk / Memory) para que el tablero
    # de TV no muestre solo un número genérico — misma fuente que el mail.
    # Si un widget tiene items críticos, se listan además como sub-filas
    # (nombre del equipo/disco/memoria puntual), no solo el conteo.
    MAX_SUBFILAS_WUG = 4
    desglose_wug = []
    for wd in _kpi_wug_datos(evidencias_wug):
        estado_fila = "fail" if wd["estado"] == "nd" else wd["estado"]
        valor = "N/D" if wd["estado"] == "nd" else ("OK" if wd["estado"] == "ok" else str(wd["cantidad"]))
        desglose_wug.append({"etiqueta": wd["titulo"], "valor": valor, "estado": estado_fila})

        if wd["estado"] in ("warn", "fail"):
            info_widget = evidencias_wug.get(wd["titulo"]) or {}
            items_criticos = info_widget.get("items_criticos") or []
            for it_critico in items_criticos[:MAX_SUBFILAS_WUG]:
                desglose_wug.append({
                    "etiqueta": it_critico["nombre"], "valor": it_critico["valor"],
                    "estado": estado_fila, "indent": True,
                })
            restantes_wug = len(items_criticos) - MAX_SUBFILAS_WUG
            if restantes_wug > 0:
                desglose_wug.append({
                    "etiqueta": f"+ {restantes_wug} más", "valor": "",
                    "estado": estado_fila, "indent": True,
                })

    # Email Helpdesk
    ts_email = info_email.get("timestamp")
    ts_email_txt = ts_email.strftime("%H:%M:%S") if ts_email else "-"
    det_email = (f"Mail de prueba enviado a {info_email.get('destinatario', '-')} a las {ts_email_txt} hs"
                 if ok_email else (info_email.get("error") or "Error desconocido"))

    # URLs Corporativas — desglose solo con los problemas (fallas + certificados
    # vencidos/por vencer). Si todo está OK, no hay desglose y se ve el resumen.
    if resultados_urls:
        estado_urls_txt, _ = _clasificar_urls(resultados_urls)
        ok_urls_n = sum(1 for r in resultados_urls if r["ok"])
        det_urls = f"{ok_urls_n}/{len(resultados_urls)} verificadas OK"
    else:
        estado_urls_txt, det_urls = "FALLA", "Sin datos de esta corrida"
    estado_urls = "ok" if estado_urls_txt == "OK" else ("warn" if estado_urls_txt == "PARCIAL" else "fail")

    problemas_urls = []
    for r in resultados_urls:
        if not r["ok"]:
            problemas_urls.append({"etiqueta": r["nombre"], "valor": "FALLA", "estado": "fail"})
    for r in resultados_urls:
        cert = r.get("cert") or {}
        if not (cert.get("aplica") and cert.get("valido")):
            continue
        if cert.get("vencido"):
            problemas_urls.append({"etiqueta": r["nombre"], "valor": "CERT VENCIDO", "estado": "fail"})
        elif cert.get("alerta"):
            dias = cert.get("dias_restantes")
            problemas_urls.append({"etiqueta": r["nombre"], "valor": f"cert {dias}d", "estado": "warn"})

    MAX_FILAS_URLS = 5
    desglose_urls = problemas_urls[:MAX_FILAS_URLS]
    restantes_urls = len(problemas_urls) - len(desglose_urls)
    if restantes_urls > 0:
        desglose_urls.append({"etiqueta": f"+ {restantes_urls} más", "valor": "", "estado": "warn"})

    # Llamadas 3CX
    numero_3cx = getattr(tcx_mod, "NUMERO_DESTINO", None)
    if ok_3cx:
        det_3cx = f"Llamada de prueba exitosa a {numero_3cx}" if numero_3cx else "Llamada de prueba exitosa"
    else:
        det_3cx = "No se pudo completar la llamada de prueba"

    def _desglose_estatico(grupos: list[tuple[str, list[str]]]) -> list[dict]:
        return [{"etiqueta": f"{titulo} ({len(subitems)})", "valor": "OK", "estado": "ok"}
                for titulo, subitems in grupos]

    ts_wug = _ts_iso(d.get("ts_wug"))
    ts_urls = _ts_iso(d.get("ts_urls"))
    ts_email_3cx = _ts_iso(d.get("ts_email_3cx"))

    items = [
        {"nombre": "WhatsUp Gold — Monitoreo", "estado": estado_wug, "ok": estado_wug == "ok",
         "detalle": det_wug, "desglose": desglose_wug, "timestamp": ts_wug},
        {"nombre": "Email Helpdesk", "estado": "ok" if ok_email else "fail", "ok": ok_email,
         "detalle": det_email, "timestamp": ts_email_3cx},
        {"nombre": "Accesos Remotos y Chequeo HES", "estado": "ok", "ok": True,
         "detalle": "VPN, Citrix y verificación de e-mails HES.",
         "desglose": _desglose_estatico(GRUPOS_ACCESOS_REMOTOS), "informativo": True},
        {"nombre": "URLs Corporativas", "estado": estado_urls, "ok": estado_urls == "ok",
         "detalle": det_urls, "desglose": desglose_urls, "timestamp": ts_urls},
        {"nombre": "Llamadas 3CX", "estado": "ok" if ok_3cx else "fail", "ok": ok_3cx,
         "detalle": det_3cx, "timestamp": ts_email_3cx},
        {"nombre": "Otros Sistemas", "estado": "ok", "ok": True,
         "detalle": "Cobranzas.com, Portal Office y Microsoft Teams.",
         "desglose": _desglose_estatico(GRUPOS_OTROS_SISTEMAS), "informativo": True},
    ]
    return items


def construir_html_preview(image_src_resolver) -> str:
    """
    Reconstruye el HTML del último reporte armado, pero con las imágenes de
    WhatsUp Gold servidas por URL (image_src_resolver) en vez de cid:, para
    poder mostrarlas dentro de un <iframe> de navegador (dashboard_reporte_diario.py).
    El html "oficial" guardado en _ultima_corrida_reporte no se toca: sigue
    usando cid: para el envío real por Outlook.

    Tira RuntimeError si todavía no se corrió ningún reporte.
    """
    d = _ultima_corrida_reporte
    if not d.get("html"):
        raise RuntimeError(
            "Todavía no se corrió el reporte diario en esta sesión "
            "(correr_reporte_diario() primero)."
        )
    return _armar_html_consolidado(
        resultados_urls=d["resultados_urls"],
        evidencias_wug=d["evidencias_wug"],
        ok_email=d["ok_email"],
        info_email=d["info_email"],
        ok_3cx=d["ok_3cx"],
        estado_global=d["estado_global"],
        color_estado_global=d["color_estado"],
        wug_image_resolver=image_src_resolver,
    )


# ============================================================
#                  ORQUESTADOR PRINCIPAL
# ============================================================

def correr_reporte_diario(headless: bool = False, progress_queue=None) -> dict:
    """
    Corre las 4 verificaciones en el orden definido por Lucas y arma el HTML
    consolidado, pero NO envía ningún mail:
      1. WhatsUp Gold
      2. Email a tickets (Helpdesk)
      3. URLs Corporativas
      4. Llamadas 3CX (telefonía)

    El resultado queda guardado en memoria (_ultima_corrida_reporte) para que
    enviar_ultimo_reporte() lo pueda mandar después de que alguien lo revisó
    con el preview. 'progress_queue', si se pasa, recibe cada línea de log
    en vivo (la usa dashboard_reporte_diario.py para el SSE).

    Tira RuntimeError sin correr nada si ya hay otra corrida en curso (manual
    o del programador automático) — evita que dos intenten usar el mismo
    perfil de Edge al mismo tiempo.

    Devuelve el dict de _ultima_corrida_reporte.
    """
    if not _lock_corrida.acquire(blocking=False):
        raise RuntimeError(
            "Ya hay otra verificación en curso (manual o del programador "
            "automático). Esperá a que termine y probá de nuevo."
        )
    global _progress_queue
    _progress_queue = progress_queue
    try:
        return _correr_reporte_diario_interno(headless)
    finally:
        _progress_queue = None
        _lock_corrida.release()


def _correr_reporte_diario_interno(headless: bool) -> dict:
    _log("")
    _log("=" * 70)
    _log(f"REPORTE DIARIO CONSOLIDADO — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    _log("=" * 70)

    # ---------------- 1. WhatsUp Gold ----------------
    _log("\n[REPORTE] >>> 1/4 WhatsUp Gold...")
    try:
        wug_mod.check_whatsupgold(enviar_mail=False)
    except Exception as e:
        _log(f"[REPORTE] ERROR en check_whatsupgold: {type(e).__name__}: {e}")

    ultima_wug = wug_mod.obtener_ultima_corrida()
    evidencias_wug = ultima_wug.get("evidencias") or {}
    _log(f"[REPORTE] WhatsUp Gold → {len(evidencias_wug)} widgets capturados.")

    # ---------------- 2. Email a Helpdesk ----------------
    _log("\n[REPORTE] >>> 2/4 Email a Helpdesk (tickets@pecomenergia.com.ar)...")
    ok_email = False
    info_email: dict = {
        "destinatario": "-",
        "asunto": "-",
        "timestamp": datetime.now(),
        "error": None,
    }
    try:
        ok_email, info_email = mail_tickets_mod.enviar_mail_tickets()
    except Exception as e:
        _log(f"[REPORTE] ERROR en enviar_mail_tickets: {type(e).__name__}: {e}")
        info_email["error"] = f"{type(e).__name__}: {e}"

    _log(f"[REPORTE] Email Helpdesk → {'OK enviado' if ok_email else 'FALLA'}")

    # ---------------- 3. URLs Corporativas ----------------
    _log("\n[REPORTE] >>> 3/4 URLs Corporativas...")
    resultados_urls: list[dict] = []
    try:
        _, resultados_urls = urls_mod.verificar_urls_corporativas(
            headless=headless, enviar_mail=False
        )
    except Exception as e:
        _log(f"[REPORTE] ERROR en verificar_urls_corporativas: "
             f"{type(e).__name__}: {e}")

    _log(f"[REPORTE] URLs → {sum(1 for r in resultados_urls if r['ok'])}"
         f"/{len(resultados_urls)} OK.")

    # ---------------- 4. Llamadas 3CX ----------------
    _log("\n[REPORTE] >>> 4/4 Llamadas 3CX (telefonía)...")
    ok_3cx = False
    try:
        # El screenshot que devuelve check_3cx() queda en disco como evidencia
        # local (carpeta evidencias/), pero no se adjunta al reporte: la única
        # sección con evidencia embebida es WhatsUp Gold.
        ok_3cx, _ = tcx_mod.check_3cx()
    except Exception as e:
        _log(f"[REPORTE] ERROR en check_3cx: {type(e).__name__}: {e}")

    _log(f"[REPORTE] Llamadas 3CX → {'OK' if ok_3cx else 'FALLA'}")

    # ---------------- Estado global ----------------
    estado_global, color_estado, estados_detalle = _calcular_estado_global(
        evidencias_wug, resultados_urls, ok_email, ok_3cx
    )
    estado_urls_txt, estado_wug_txt, estado_email_txt, estado_3cx_txt = estados_detalle

    _log(f"\n[REPORTE] Estado WhatsUp:  {estado_wug_txt}")
    _log(f"[REPORTE] Estado Email:    {estado_email_txt}")
    _log(f"[REPORTE] Estado URLs:     {estado_urls_txt}")
    _log(f"[REPORTE] Estado 3CX:      {estado_3cx_txt}")
    _log(f"[REPORTE] Estado Global:   {estado_global}")

    # ---------------- HTML ----------------
    html = _armar_html_consolidado(
        resultados_urls=resultados_urls,
        evidencias_wug=evidencias_wug,
        ok_email=ok_email,
        info_email=info_email,
        ok_3cx=ok_3cx,
        estado_global=estado_global,
        color_estado_global=color_estado,
    )

    fecha_str = datetime.now().strftime("%d/%m/%Y")
    asunto = f"[Checklist IT] Reporte Diario - {estado_global} - {fecha_str}"

    ahora = datetime.now()
    _ultima_corrida_reporte.update({
        "timestamp": ahora,
        "html": html,
        "evidencias_wug": evidencias_wug,
        "estado_global": estado_global,
        "asunto": asunto,
        # Datos crudos para poder reconstruir un preview con imágenes servidas
        # por HTTP (el html de arriba usa cid: para el envío real por Outlook,
        # que no se puede mostrar dentro de un <iframe> de navegador).
        "resultados_urls": resultados_urls,
        "ok_email": ok_email,
        "info_email": info_email,
        "ok_3cx": ok_3cx,
        "color_estado": color_estado,
        # Corrida manual completa: las 3 secciones se refrescaron ahora mismo.
        "ts_wug": ahora,
        "ts_urls": ahora,
        "ts_email_3cx": ahora,
    })
    _persistir_estado_reporte()

    _log("\n" + "=" * 70)
    _log(f"RESULTADO: {estado_global}  |  Reporte armado, sin enviar todavía.")
    _log("=" * 70)

    return dict(_ultima_corrida_reporte)


# ============================================================
#                  ENVÍO POR OUTLOOK COM (diferido)
# ============================================================

def enviar_ultimo_reporte(
    destinatarios: list[str],
    cc: list[str] | None = None,
    preview: bool = False,
) -> bool:
    """
    Envía el reporte que quedó armado por la última llamada a
    correr_reporte_diario() en esta sesión. Pensado para el flujo con
    control manual: correr → revisar el preview → recién ahí enviar.
    'destinatarios' va en Para, 'cc' (opcional) va en CC.

    Tira RuntimeError si todavía no se corrió ningún reporte.
    """
    if not _ultima_corrida_reporte.get("html"):
        raise RuntimeError(
            "Todavía no se corrió el reporte diario en esta sesión "
            "(correr_reporte_diario() primero)."
        )

    destino_log = ', '.join(destinatarios)
    if cc:
        destino_log += f"  (CC: {', '.join(cc)})"
    _log(f"\n[REPORTE] Enviando reporte consolidado a {destino_log}...")
    ok_mail = _enviar_mail_consolidado(
        html=_ultima_corrida_reporte["html"],
        evidencias_wug=_ultima_corrida_reporte["evidencias_wug"],
        asunto=_ultima_corrida_reporte["asunto"],
        destinatarios=destinatarios,
        cc=cc,
        preview=preview,
    )
    _log(f"[REPORTE] Envío: {'OK' if ok_mail else 'ERROR'}")
    return ok_mail


# ============================================================
#            ORQUESTADOR "TODO EN UNO" (uso CLI / legacy)
# ============================================================

def generar_reporte_diario(
    headless: bool = False,
    enviar_mail: bool = True,
    preview_mail: bool | None = None,
) -> bool:
    """
    Corre + arma + envía en un solo paso (comportamiento original, sin punto
    de revisión intermedio). Se mantiene para el uso por consola
    (`python check_reporte_diario.py`). El flujo con control manual está en
    correr_reporte_diario() + enviar_ultimo_reporte(), que usa
    dashboard_reporte_diario.py.
    """
    data = correr_reporte_diario(headless=headless)
    estado_global = data["estado_global"]

    if not enviar_mail:
        _log("\n[REPORTE] --no-mail activo: no se envía el reporte.")
        return estado_global == "OK"

    modo_preview = MODO_PREVIEW_MAIL if preview_mail is None else preview_mail
    ok_mail = enviar_ultimo_reporte(DESTINATARIOS_MAIL, preview=modo_preview)

    return estado_global == "OK" and ok_mail


# ============================================================
#                   ENTRY POINT STANDALONE
# ============================================================

if __name__ == "__main__":
    headless = "--headless" in sys.argv
    no_mail = "--no-mail" in sys.argv
    ok = generar_reporte_diario(headless=headless, enviar_mail=not no_mail)
    sys.exit(0 if ok else 1)