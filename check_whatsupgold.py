"""
check_whatsupgold.py
--------------------
Módulo del Checklist Automatizado - Pecom Energía

Captura como evidencia los dos widgets del dashboard de WhatsUp Gold que se
adjuntan en el reporte diario:
    - Down Active Monitors  (dashboard viewId=859)
    - Disk Utilization       (dashboard viewId=863)

Enfoque:
    - Playwright con perfil persistente de Microsoft Edge (Netskope + sesión SSO/WUG).
    - Primer uso: se abre Edge y hay que loguearse manualmente una vez.
    - Corridas siguientes: reutiliza la sesión guardada en 'perfil_wug/'.
    - Los IDs 'reportpanel-XXXX' de ExtJS son dinámicos, por eso ubicamos los
      widgets por el texto del título (estable) y subimos al ancestro
      'reportpanel-*' con XPath.

Retorna:
    - True  si capturó las dos evidencias sin errores.
    - False si algún widget falló o hubo timeout / login pendiente.
"""

from pathlib import Path
from datetime import datetime
import re
import unicodedata
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# ============================================================
#                       CONFIGURACIÓN
# ============================================================

BASE_DIR = Path(__file__).parent.resolve()
PROFILE_DIR = BASE_DIR / "perfil_wug"
EVIDENCIAS_DIR = BASE_DIR / "evidencias_whatsupgold"

# Dashboards a recorrer. Si el día de mañana se agrega uno más,
# alcanza con sumar otro dict a esta lista.
DASHBOARDS = [
    {
        "nombre": "down_active_monitors",
        "titulo": "Down Active Monitors",
        "url": (
            "https://monitoreo.pecomenergia.com.ar/NmConsole/"
            "#v=Wug_view_dashboard_Home/p=%7B%22viewId%22%3A859%7D"
        ),
    },
    {
        "nombre": "disk_utilization",
        "titulo": "Disk Utilization",
        "url": (
            "https://monitoreo.pecomenergia.com.ar/NmConsole/"
            "#v=Wug_view_dashboard_Home/p=%7B%22viewId%22%3A863%7D"
        ),
    },
]

# Timeouts
TIMEOUT_NAVEGACION_MS = 60_000   # 60s para cargar la página
TIMEOUT_PANEL_MS      = 30_000   # 30s para que aparezca el panel
ESPERA_RENDER_MS      = 4_000    # espera post-load para que ExtJS pinte los datos AJAX
ESPERA_SCROLL_MS      = 500

# --- Configuración del mail ---
DESTINATARIOS_MAIL = ["lucasabad80@gmail.com"]
ASUNTO_MAIL        = "WhatsUp Gold - Reporte Diario"
# True  = abre el mail en Outlook para revisión manual (no lo envía) → útil para pruebas
# False = lo manda solo con .Send() (comportamiento normal, igual que el resto de módulos)
MODO_PREVIEW_MAIL  = False

# --- Umbrales de análisis ---
# En WUG los discos amarillos son "warning" (por debajo del umbral crítico)
# y los rojos son los que están efectivamente por encima del umbral crítico.
# El corte visual en el dashboard es 90%. Si en el futuro cambia, se ajusta acá.
DISK_UMBRAL_PCT = 90.0

# Categorías Unicode que descartamos al limpiar texto de celdas:
#   Cf = Format          (ZWSP \u200b, ZWJ, BOM, LRM/RLM, etc)
#   Co = Private Use     (glifos de fuentes de íconos tipo Font Awesome de ExtJS)
#   Cs = Surrogates      (no debería aparecer en Unicode válido)
#   Cn = Unassigned      (idem)
# Se conservan letras (L*), dígitos (N*), puntuación (P*), símbolos (S*) y espacios (Zs).
CATEGORIAS_UNICODE_A_DESCARTAR = {"Cf", "Co", "Cs", "Cn"}


# ============================================================
#           ESTADO DE LA ÚLTIMA CORRIDA (para integraciones)
# ============================================================
# Se popula al final de check_whatsupgold() para que otros módulos
# (como el dashboard) puedan armar reportes que incluyan las evidencias.

_ultima_corrida = {
    "evidencias": {},   # {titulo: {"path": Path, "resumen_html": str}}
    "timestamp": None,  # datetime
}


def obtener_ultima_corrida() -> dict:
    """Devuelve las evidencias capturadas en la última ejecución (copia superficial)."""
    return dict(_ultima_corrida)


def render_secciones_html(image_src_resolver, incluir_encabezado: bool = True) -> str:
    """
    Devuelve HTML con las secciones de widgets de la última corrida.
    Pensado para embeber en otros mails o en previews.

    Args:
        image_src_resolver: función (indice, titulo, Path) -> str.
            Devuelve el valor a usar como src del <img>. Ejemplos:
              - Para preview web:  lambda i,t,r: f"/evidencia?dir=evidencias_whatsupgold&name={r.name}"
              - Para email inline: lambda i,t,r: f"cid:wug_widget_{i}"
        incluir_encabezado: si True, arriba pone un <h2> "WhatsUp Gold - Detalle".

    Returns:
        HTML como string. Si no hay evidencias todavía, devuelve "".
    """
    evidencias = _ultima_corrida.get("evidencias") or {}
    if not evidencias:
        return ""

    partes = []
    if incluir_encabezado:
        partes.append(
            '<h2 style="font-family:Segoe UI,sans-serif;color:#1a2942;'
            'border-bottom:2px solid #6cc24a;padding-bottom:6px;'
            'margin-top:32px;font-size:18px;">'
            'WhatsUp Gold — Detalle del Monitoreo</h2>'
        )

    for i, (titulo, info) in enumerate(evidencias.items()):
        ruta = info["path"]
        resumen = info.get("resumen_html", "")
        img_src = image_src_resolver(i, titulo, ruta)

        partes.append(
            f'<h3 style="font-family:Segoe UI,sans-serif;color:#1a2942;'
            f'margin-top:20px;font-size:15px;">{titulo}</h3>'
            f'<p style="font-family:Segoe UI,sans-serif;font-size:13px;'
            f'color:#333;margin:8px 0 12px 0;">{resumen}</p>'
            f'<img src="{img_src}" style="max-width:100%;border:1px solid #ddd;">'
        )

    return "\n".join(partes)


# ============================================================
#                       HELPERS
# ============================================================

def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _detectar_login(page) -> bool:
    """
    Detecta si la página redirigió al login de WhatsUp Gold.
    WUG clásico tiene un formulario con campos 'Username' / 'Password'.
    """
    try:
        return page.locator(
            "input[name='Username'], input#Username, "
            "input[name='sUsername'], form[name='login']"
        ).count() > 0
    except Exception:
        return False


def _capturar_panel(page, titulo_panel: str, ruta_salida: Path):
    """
    Localiza el reportpanel de ExtJS por el texto de su título y captura
    solo el div del panel (sin la barra del navegador ni el resto de la página).

    Estrategia del selector:
        1. Buscar el <div class="x-title-text-report-panel-framed"> con el texto exacto.
        2. Subir al ancestro raíz del widget: aquel cuyo id sea 'reportpanel-N'
           SIN sub-sufijos (los sub-componentes de ExtJS tienen '_' en el id,
           por ejemplo 'reportpanel-2049_header', que sería solo la barra del título).
        3. Ese ancestro raíz es el contenedor completo del widget (header + body + grilla).

    Devuelve el Locator del panel para poder extraer datos adicionales (filas del grid).
    """
    selector = (
        "xpath=//div[contains(@class, 'x-title-text-report-panel-framed') "
        f"and normalize-space(text())='{titulo_panel}']"
        "/ancestor::div[starts-with(@id, 'reportpanel-') "
        "and not(contains(@id, '_'))][1]"
    )

    panel = page.locator(selector).first
    panel.wait_for(state="visible", timeout=TIMEOUT_PANEL_MS)

    # Margen para que ExtJS termine de traer los datos por AJAX
    page.wait_for_timeout(ESPERA_RENDER_MS)

    # Aseguramos que esté en viewport antes de capturar
    panel.scroll_into_view_if_needed()
    page.wait_for_timeout(ESPERA_SCROLL_MS)

    panel.screenshot(path=str(ruta_salida))
    return panel


def _limpiar_texto(s: str) -> str:
    """
    Limpia texto de una celda del grid quitando:
      - Whitespace estándar en los bordes (.strip()).
      - Caracteres invisibles/no-imprimibles según su categoría Unicode:
          Cf (formato: ZWSP, BOM, ...), Co (private use: íconos de Font Awesome),
          Cs (surrogates), Cn (no asignados).
      - Duplicación de texto por accesibilidad: cuando WUG mete el mismo valor
        dos veces separado por \\n (texto visible + label para screen readers),
        se detecta y se conserva una sola copia. Ejemplo: "93.6%\\n93.6%" → "93.6%".

    Preserva letras, dígitos, puntuación, símbolos y espacios normales.
    """
    if not s:
        return ""
    limpio = "".join(
        ch for ch in s
        if unicodedata.category(ch) not in CATEGORIAS_UNICODE_A_DESCARTAR
    )

    # Manejar celdas multi-línea (WUG duplica valores para accesibilidad).
    if "\n" in limpio:
        lineas = [l.strip() for l in limpio.split("\n") if l.strip()]
        if len(set(lineas)) == 1:
            # Todas las líneas iguales → dejamos una sola
            limpio = lineas[0] if lineas else ""
        else:
            # Líneas distintas → las unimos con espacio (raro en este contexto)
            limpio = " ".join(lineas)

    return limpio.strip()


def _parsear_porcentaje(s: str):
    """
    Extrae un número de un texto tipo '93.6%' o '93,6 %'.
    Devuelve float o None si no puede parsear.
    """
    if not s:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _extraer_filas_grid(panel) -> list:
    """
    Extrae las filas del grid ExtJS dentro del panel.
    Devuelve una lista de listas de strings: [[col1, col2, ...], [col1, col2, ...], ...]

    Es 'best effort': si la extracción falla por cualquier motivo, devuelve []
    y el mail sale igual solo con las imágenes.
    """
    filas = []
    try:
        # ExtJS 6.x: rows son .x-grid-item, cells son .x-grid-cell
        rows = panel.locator(".x-grid-item").all()
        if not rows:
            # Fallback por si la versión usa otra convención
            rows = panel.locator(".x-grid-row").all()

        for row in rows:
            celdas_raw = row.locator(".x-grid-cell").all_inner_texts()
            # Limpieza agresiva: strip + caracteres invisibles Unicode
            celdas = [_limpiar_texto(c) for c in celdas_raw]
            # Descartamos las que quedaron realmente vacías (columnas de íconos/acciones)
            celdas = [c for c in celdas if c]
            if celdas:
                filas.append(celdas)
    except Exception as e:
        print(f"[WUG] Warning: no se pudieron extraer filas del grid: {e}")

    return filas


def _generar_resumen_widget(nombre_dashboard: str, filas: list) -> str:
    """
    Genera un texto HTML descriptivo con lo que trae el widget.
    Se inserta en el mail arriba de cada imagen.

    'nombre_dashboard' es el 'nombre' del dict DASHBOARDS
    (por ejemplo 'down_active_monitors' o 'disk_utilization').
    """
    if not filas:
        return "<i>Sin registros para reportar.</i>"

    if nombre_dashboard == "down_active_monitors":
        # Estructura esperada por fila (post-limpieza): [Device, Count, Status]
        devices = [f[0] for f in filas if len(f) >= 1 and f[0]]
        if not devices:
            return "<i>Sin monitores caídos.</i>"
        return (
            f"Se detectaron <b>{len(devices)}</b> "
            f"{'monitor caído' if len(devices) == 1 else 'monitores caídos'}: "
            f"{', '.join(devices)}."
        )

    if nombre_dashboard == "disk_utilization":
        # Estructura esperada por fila (post-limpieza): [Device, Disk, Size, % Used]
        # Solo cuentan los que superan el umbral crítico (los "rojos" en el dashboard).
        criticos = []
        for f in filas:
            if len(f) >= 4:
                pct = _parsear_porcentaje(f[-1])  # % Used = última columna
                if pct is not None and pct >= DISK_UMBRAL_PCT:
                    criticos.append(f"{f[0]} ({f[1]}) — <b>{f[-1]}</b>")

        total = len(criticos)
        if total == 0:
            return (
                f"<i>Sin discos por encima del umbral crítico "
                f"({DISK_UMBRAL_PCT:.0f}%).</i>"
            )

        texto = (
            f"<b>{total}</b> "
            f"{'disco' if total == 1 else 'discos'} "
            f"por encima del umbral crítico ({DISK_UMBRAL_PCT:.0f}%)."
        )
        top = criticos[:5]
        sufijo = " Top 5: " if total > 5 else " Detalle: "
        texto += sufijo + "; ".join(top) + "."
        return texto

    # Default genérico si más adelante agregamos otro widget
    return f"<b>{len(filas)}</b> registro(s) en el widget."


def _enviar_reporte_mail(evidencias: dict, destinatarios: list, preview: bool = False) -> bool:
    """
    Envía por Outlook (COM) un mail HTML con las evidencias embebidas inline.

    - Usa el cliente Outlook desktop ya autenticado localmente (la ruta confiable
      para Pecom, ya que O365 SMTP Basic Auth está deshabilitado a nivel tenant).
    - Cada imagen se adjunta y se le asigna un CID vía PR_ATTACH_CONTENT_ID,
      para poder referenciarla con <img src="cid:..."> y que quede embebida
      en el cuerpo (no como attachment al final).

    Args:
        evidencias:    dict {titulo_widget: {"path": Path, "resumen_html": str}}.
        destinatarios: lista de emails.
        preview:       True = .Display() (abre el mail sin enviarlo).
                       False = .Send() (envía directamente).

    Returns:
        True si se envió/mostró OK, False si falló.
    """
    if not evidencias:
        print("[WUG][MAIL] Sin evidencias para enviar. Se omite el mail.")
        return False

    try:
        import win32com.client as win32
    except ImportError:
        print("[WUG][MAIL] ERROR: pywin32 no está instalado (pip install pywin32).")
        return False

    # PR_ATTACH_CONTENT_ID de MAPI (schema URL) → permite embebido inline.
    PR_ATTACH_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"

    try:
        outlook = win32.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = olMailItem

        mail.To = "; ".join(destinatarios)
        mail.Subject = f"{ASUNTO_MAIL} - {datetime.now().strftime('%d/%m/%Y')}"

        html_secciones = []
        for i, (titulo, info) in enumerate(evidencias.items()):
            ruta = info["path"]
            resumen = info.get("resumen_html", "")

            cid = f"widget_{i}"
            attachment = mail.Attachments.Add(str(Path(ruta).resolve()))
            # Marcar la imagen como inline con su CID
            attachment.PropertyAccessor.SetProperty(PR_ATTACH_CONTENT_ID, cid)

            html_secciones.append(
                f'<h3 style="font-family:Segoe UI,sans-serif;color:#1a2942;'
                f'border-bottom:2px solid #6cc24a;padding-bottom:4px;'
                f'margin-top:24px;">{titulo}</h3>'
                f'<p style="font-family:Segoe UI,sans-serif;font-size:13px;'
                f'color:#333;margin:8px 0 12px 0;">{resumen}</p>'
                f'<img src="cid:{cid}" style="max-width:100%;border:1px solid #ddd;">'
            )

        mail.HTMLBody = f"""
        <html>
        <body style="font-family:Segoe UI,sans-serif;color:#333;font-size:13px;">
          <p>Buenos días,</p>
          <p>Reporte automático de <b>WhatsUp Gold</b> generado el
             <b>{datetime.now().strftime('%d/%m/%Y a las %H:%M hs')}</b>.</p>
          {''.join(html_secciones)}
          <p style="color:#888;font-size:11px;margin-top:24px;">
            — Generado automáticamente por Checklist-Automatizado
            (IT &amp; Innovación · Pecom Energía).
          </p>
        </body>
        </html>
        """

        if preview:
            mail.Display()
            print("[WUG][MAIL] Preview: mail abierto en Outlook para revisión manual "
                  "(no se envió).")
        else:
            mail.Send()
            print(f"[WUG][MAIL] OK - Mail enviado a: {', '.join(destinatarios)}")

        return True

    except Exception as e:
        print(f"[WUG][MAIL] ERROR al armar/enviar el mail: {type(e).__name__}: {e}")
        return False


# ============================================================
#                       FUNCIÓN PRINCIPAL
# ============================================================

def check_whatsupgold(enviar_mail: bool = True, preview_mail: bool = None) -> bool:
    """
    Recorre los dashboards configurados, guarda una screenshot recortada
    de cada widget y (opcionalmente) envía un mail HTML con las evidencias
    embebidas inline.

    Args:
        enviar_mail:  True dispara el envío al terminar. False lo omite
                      (útil cuando lo llama el orquestador checklist.py y
                      el reporte se manda consolidado desde ahí).
        preview_mail: True/False fuerza el modo preview. None respeta
                      MODO_PREVIEW_MAIL configurado arriba.
    """
    EVIDENCIAS_DIR.mkdir(exist_ok=True)
    ts = _timestamp()

    ok_global = True
    evidencias_capturadas = {}   # {titulo: Path} → se pasa al mail al final

    print("=" * 60)
    print("[WUG] Iniciando verificación de WhatsUp Gold")
    print("=" * 60)

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="msedge",
            headless=False,
            viewport={"width": 1600, "height": 900},
        )

        page = contexto.pages[0] if contexto.pages else contexto.new_page()

        try:
            for dash in DASHBOARDS:
                nombre = dash["nombre"]
                titulo = dash["titulo"]
                url = dash["url"]

                print(f"\n[WUG] Abriendo dashboard: {titulo}")
                try:
                    page.goto(url, wait_until="domcontentloaded",
                              timeout=TIMEOUT_NAVEGACION_MS)
                    # Damos margen a que ExtJS termine de renderizar
                    page.wait_for_timeout(ESPERA_RENDER_MS)

                    if _detectar_login(page):
                        print("[WUG] ATENCIÓN: apareció pantalla de login de WhatsUp Gold.")
                        print("[WUG] Logueate manualmente en la ventana de Edge que se abrió.")
                        print("[WUG] La sesión queda guardada en el perfil para próximas corridas.")
                        # Damos tiempo para que loguee manualmente si está mirando
                        page.wait_for_timeout(30_000)
                        # Reintento después del login manual
                        if _detectar_login(page):
                            ok_global = False
                            continue

                    ruta_evidencia = EVIDENCIAS_DIR / f"{nombre}_{ts}.png"
                    panel = _capturar_panel(page, titulo, ruta_evidencia)
                    print(f"[WUG] OK - Evidencia guardada: {ruta_evidencia.name}")

                    # Extraemos los datos del grid para armar un resumen en el mail
                    filas = _extraer_filas_grid(panel)
                    resumen_html = _generar_resumen_widget(nombre, filas)
                    print(f"[WUG] Resumen ({len(filas)} filas): "
                          f"{resumen_html.replace('<b>','').replace('</b>','').replace('<i>','').replace('</i>','')}")

                    evidencias_capturadas[titulo] = {
                        "path": ruta_evidencia,
                        "resumen_html": resumen_html,
                    }

                except PlaywrightTimeout as e:
                    print(f"[WUG] TIMEOUT en '{titulo}': {e}")
                    ok_global = False
                except Exception as e:
                    print(f"[WUG] ERROR en '{titulo}': {type(e).__name__}: {e}")
                    ok_global = False

        finally:
            contexto.close()

    # ---- Guardar estado de la corrida para consumo por otras integraciones ----
    # (dashboard, orquestador, etc). Se guarda incluso si algún widget falló:
    # queremos exponer lo que sí se capturó.
    _ultima_corrida["evidencias"] = evidencias_capturadas
    _ultima_corrida["timestamp"] = datetime.now()

    # ---- Envío del reporte por mail ----
    if enviar_mail and evidencias_capturadas:
        print("\n[WUG] Enviando reporte por Outlook...")
        modo_preview = MODO_PREVIEW_MAIL if preview_mail is None else preview_mail
        mail_ok = _enviar_reporte_mail(
            evidencias=evidencias_capturadas,
            destinatarios=DESTINATARIOS_MAIL,
            preview=modo_preview,
        )
        if not mail_ok:
            ok_global = False
    elif enviar_mail and not evidencias_capturadas:
        print("\n[WUG] No se envía mail porque no se capturó ninguna evidencia.")
        ok_global = False

    print("\n" + "=" * 60)
    print(f"[WUG] Resultado: {'OK' if ok_global else 'CON ERRORES'}")
    print("=" * 60)

    return ok_global


# ============================================================
#                   PUNTO DE ENTRADA STANDALONE
# ============================================================

if __name__ == "__main__":
    resultado = check_whatsupgold()
    exit(0 if resultado else 1)