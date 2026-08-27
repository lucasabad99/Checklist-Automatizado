"""
check_whatsupgold.py
--------------------
Módulo del Checklist Automatizado - Pecom Energía

Captura como evidencia los widgets del dashboard de WhatsUp Gold que se
adjuntan en el reporte diario:
    - Down Active Monitors  (dashboard viewId=859)
    - Disk Utilization       (dashboard viewId=863)
    - Memory Utilization     (dashboard viewId=863, mismo dashboard que Disk)

Enfoque:
    - Playwright con perfil persistente de Microsoft Edge (Netskope + sesión SSO/WUG).
    - Primer uso: se abre Edge y hay que loguearse manualmente una vez.
    - Corridas siguientes: reutiliza la sesión guardada en 'perfil_wug/'.
    - Login de WUG (usuario/clave propios de la app, no el SSO/Netskope):
      si se configuran WUG_USER / WUG_PASS en .env, se autocompleta solo
      cuando aparece la pantalla de login. Sin esas variables, sigue
      pidiendo login manual como siempre (ver _intentar_login_wug).
    - Los IDs 'reportpanel-XXXX' de ExtJS son dinámicos, por eso ubicamos los
      widgets por el texto del título (estable) y subimos al ancestro
      'reportpanel-*' con XPath.
    - Cuando varios widgets viven en el mismo dashboard, cargamos la URL una
      sola vez y capturamos cada panel navegando por scroll.
    - Antes de mandar el mail, las evidencias PNG se optimizan a JPEG en un
      subfolder aparte para no reventar el límite de 102KB de Gmail
      (los PNG originales quedan intactos como evidencia oficial).

Retorna:
    - True  si capturó todas las evidencias sin errores.
    - False si algún widget falló o hubo timeout / login pendiente.
"""

import os
from pathlib import Path
from datetime import datetime
import re
import unicodedata
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

load_dotenv()


# ============================================================
#                       CONFIGURACIÓN
# ============================================================

BASE_DIR = Path(__file__).parent.resolve()
PROFILE_DIR = BASE_DIR / "perfil_wug"
EVIDENCIAS_DIR = BASE_DIR / "evidencias_whatsupgold"

# Login de WhatsUp Gold (no es el SSO/Netskope, que ya viaja con la cookie de
# sesión del perfil de Edge — esto es el usuario/clave propios de WUG que hoy
# se tipean a mano cada vez que se abre). Opcional: si no están seteados en
# .env, se mantiene el comportamiento de siempre (esperar login manual).
#   WUG_USER=tu_usuario
#   WUG_PASS=tu_clave
WUG_USER = os.getenv("WUG_USER")
WUG_PASS = os.getenv("WUG_PASS")

# Dashboards a recorrer. Cada dashboard puede tener uno o más widgets;
# la URL se carga UNA sola vez por dashboard y después se capturan
# todos los widgets navegando por scroll (así no recargamos ExtJS
# innecesariamente cuando hay varios widgets en la misma vista).
#
# Para sumar widgets más adelante (ej. Interface Utilization),
# solo hay que agregar otro dict al array 'widgets' del dashboard correspondiente.
DASHBOARDS = [
    {
        "url": (
            "https://monitoreo.pecomenergia.com.ar/NmConsole/"
            "#v=Wug_view_dashboard_Home/p=%7B%22viewId%22%3A859%7D"
        ),
        "widgets": [
            {"nombre": "down_active_monitors", "titulo": "Down Active Monitors"},
        ],
    },
    {
        "url": (
            "https://monitoreo.pecomenergia.com.ar/NmConsole/"
            "#v=Wug_view_dashboard_Home/p=%7B%22viewId%22%3A863%7D"
        ),
        "widgets": [
            {"nombre": "disk_utilization",   "titulo": "Disk Utilization"},
            {"nombre": "memory_utilization", "titulo": "Memory Utilization"},
        ],
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
# En WUG los ítems amarillos son "warning" (por debajo del umbral crítico)
# y los rojos son los que están efectivamente por encima del umbral crítico.
# El corte visual en los dashboards es 90%. Si en el futuro cambia, se ajusta acá.
DISK_UMBRAL_PCT   = 90.0
MEMORY_UMBRAL_PCT = 90.0   # RAM: subir a 92/95 si genera demasiados falsos positivos

# --- Optimización de imágenes para el mail ---
# Gmail corta ("Message clipped") los mails cuyo MIME body supera ~102KB.
# Outlook, al adjuntar imágenes inline vía CID (PR_ATTACH_CONTENT_ID), las
# embebe en el body como base64 dentro de un multipart/related, así que 3-4
# PNGs de dashboards ExtJS a 1600px fácil superan el límite.
# Solución: redimensionar + convertir a JPEG antes de adjuntar.
# Los PNG originales quedan intactos en EVIDENCIAS_DIR como evidencia oficial;
# las versiones optimizadas van a un subfolder aparte.
# NOTA: Outlook desktop no tiene este límite, esto es solo para Gmail y
# clientes web modernos con límites similares.
OPTIMIZAR_IMAGENES_MAIL = True
IMG_ANCHO_MAX_PX        = 1000   # ancho máximo en px (mantiene ratio)
IMG_CALIDAD_JPEG        = 80     # calidad JPEG 1-95 (80 es buen balance nitidez/peso)

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


def _intentar_login_wug(page) -> bool:
    """
    Completa usuario/clave en el formulario de login de WUG y confirma.
    Devuelve True si el login se completó (ya no se detecta la pantalla de
    login), False si no se pudo (credenciales no configuradas, selector no
    encontrado, o el login falló).

    OJO: los selectores de campo/botón son la mejor estimación a partir del
    formulario clásico de WUG (input#Username / input#Password) — todavía no
    se validó contra el login real en producción. Si no matchean, revisar con
    el DevTools del navegador (F12 → inspeccionar el campo) y ajustar acá.
    """
    if not WUG_USER or not WUG_PASS:
        return False

    try:
        campo_usuario = page.locator(
            "input[name='Username'], input#Username, input[name='sUsername']"
        ).first
        campo_clave = page.locator(
            "input[name='Password'], input#Password, input[name='sPassword'], "
            "input[type='password']"
        ).first

        campo_usuario.fill(WUG_USER)
        campo_clave.fill(WUG_PASS)

        boton_login = page.locator(
            "button[type='submit'], input[type='submit'], "
            "button:has-text('Log'), button:has-text('Ingresar')"
        ).first
        if boton_login.count() > 0:
            boton_login.click()
        else:
            campo_clave.press("Enter")

        page.wait_for_timeout(4_000)
        return not _detectar_login(page)

    except Exception as e:
        print(f"[WUG] No se pudo autocompletar el login: {type(e).__name__}: {e}")
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


def _generar_resumen_widget(nombre_dashboard: str, filas: list) -> tuple[str, int, list]:
    """
    Genera un texto HTML descriptivo con lo que trae el widget (se inserta en
    el mail arriba de cada imagen), la cantidad de items críticos detectados
    (caídos / por encima del umbral) para KPIs numéricos, y la lista plana de
    esos items críticos (sin HTML) para consumidores que arman su propia
    interfaz en vez de parsear el resumen_html ya formateado para mail —
    ver dashboard_reporte_diario.py / tablero.py.

    'nombre_dashboard' es el 'nombre' del widget en DASHBOARDS
    (por ejemplo 'down_active_monitors', 'disk_utilization', 'memory_utilization').

    Devuelve (resumen_html, cantidad_criticos, items_criticos).
    'items_criticos' es una lista de {"nombre": str, "valor": str}.
    """
    if not filas:
        return "<i>Sin registros para reportar.</i>", 0, []

    if nombre_dashboard == "down_active_monitors":
        # Estructura esperada por fila (post-limpieza): [Device, Count, Status]
        devices = [f[0] for f in filas if len(f) >= 1 and f[0]]
        if not devices:
            return "<i>Sin monitores caídos.</i>", 0, []
        texto = (
            f"Se detectaron <b>{len(devices)}</b> "
            f"{'monitor caído' if len(devices) == 1 else 'monitores caídos'}: "
            f"{', '.join(devices)}."
        )
        items = [{"nombre": d, "valor": "CAÍDO"} for d in devices]
        return texto, len(devices), items

    if nombre_dashboard == "disk_utilization":
        # Estructura esperada por fila (post-limpieza): [Device, Disk, Size, % Used]
        # Solo cuentan los que superan el umbral crítico (los "rojos" en el dashboard).
        criticos = []
        for f in filas:
            if len(f) >= 4:
                pct = _parsear_porcentaje(f[-1])  # % Used = última columna
                if pct is not None and pct >= DISK_UMBRAL_PCT:
                    criticos.append({"nombre": f"{f[0]} ({f[1]})", "valor": f[-1]})

        total = len(criticos)
        if total == 0:
            return (
                f"<i>Sin discos por encima del umbral crítico "
                f"({DISK_UMBRAL_PCT:.0f}%).</i>", 0, []
            )

        texto = (
            f"<b>{total}</b> "
            f"{'disco' if total == 1 else 'discos'} "
            f"por encima del umbral crítico ({DISK_UMBRAL_PCT:.0f}%)."
        )
        top = [f"{c['nombre']} — <b>{c['valor']}</b>" for c in criticos[:5]]
        sufijo = " Top 5: " if total > 5 else " Detalle: "
        texto += sufijo + "; ".join(top) + "."
        return texto, total, criticos

    if nombre_dashboard == "memory_utilization":
        # Estructura esperada por fila (post-limpieza): [Device, Description, Size, % Avg]
        # Description viene "Physical Memory (N)" o "Virtual Memory (N)".
        # Contamos como crítico cualquier fila (física o virtual) que supere el umbral.
        criticos = []
        for f in filas:
            if len(f) >= 4:
                pct = _parsear_porcentaje(f[-1])  # % Avg = última columna
                if pct is not None and pct >= MEMORY_UMBRAL_PCT:
                    # Mostramos Device + tipo de memoria (Physical/Virtual) para distinguir
                    criticos.append({"nombre": f"{f[0]} — {f[1]}", "valor": f[-1]})

        total = len(criticos)
        if total == 0:
            return (
                f"<i>Sin memorias por encima del umbral crítico "
                f"({MEMORY_UMBRAL_PCT:.0f}%).</i>", 0, []
            )

        texto = (
            f"<b>{total}</b> "
            f"{'memoria' if total == 1 else 'memorias'} "
            f"por encima del umbral crítico ({MEMORY_UMBRAL_PCT:.0f}%)."
        )
        top = [f"{c['nombre']} — <b>{c['valor']}</b>" for c in criticos[:5]]
        sufijo = " Top 5: " if total > 5 else " Detalle: "
        texto += sufijo + "; ".join(top) + "."
        return texto, total, criticos

    # Default genérico si más adelante agregamos otro widget
    return f"<b>{len(filas)}</b> registro(s) en el widget.", len(filas), []


def _optimizar_imagen_para_mail(ruta_original: Path) -> Path:
    """
    Genera una copia optimizada de la imagen para embebido inline en el mail:
      - Redimensiona a IMG_ANCHO_MAX_PX si es más ancha (mantiene ratio).
      - Convierte a JPEG con IMG_CALIDAD_JPEG.

    Esto es necesario porque Gmail corta ("[Mensaje acortado]") mails cuyo
    MIME body supera ~102KB, y Outlook al usar CID inline mete las imágenes
    base64-encodeadas dentro del multipart/related del body.

    Los PNG originales quedan intactos como evidencia oficial en EVIDENCIAS_DIR;
    las copias optimizadas van a un subfolder aparte.

    Si Pillow no está instalado o si OPTIMIZAR_IMAGENES_MAIL=False, devuelve
    la ruta original y el mail se manda con las imágenes tal cual (arriesgando
    clipping en Gmail).
    """
    if not OPTIMIZAR_IMAGENES_MAIL:
        return ruta_original

    try:
        from PIL import Image
    except ImportError:
        print("[WUG][MAIL] Warning: Pillow no está instalado, no se optimizan "
              "las imágenes (pueden quedar cortadas en Gmail). "
              "Instalá con: pip install Pillow")
        return ruta_original

    try:
        dir_optimizadas = ruta_original.parent / "optimizadas_mail"
        dir_optimizadas.mkdir(exist_ok=True)
        ruta_opt = dir_optimizadas / (ruta_original.stem + ".jpg")

        with Image.open(ruta_original) as img:
            # PNG de screenshots suelen tener canal alpha. Los aplanamos
            # sobre fondo blanco antes de pasar a JPEG (que no soporta alpha).
            if img.mode == "RGBA":
                fondo = Image.new("RGB", img.size, (255, 255, 255))
                fondo.paste(img, mask=img.split()[-1])
                img = fondo
            elif img.mode == "LA":
                fondo = Image.new("RGB", img.size, (255, 255, 255))
                fondo.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                img = fondo
            elif img.mode == "P":
                img = img.convert("RGBA")
                fondo = Image.new("RGB", img.size, (255, 255, 255))
                fondo.paste(img, mask=img.split()[-1])
                img = fondo
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Redimensionar si supera el ancho máximo (manteniendo ratio)
            if img.width > IMG_ANCHO_MAX_PX:
                nuevo_alto = int(img.height * IMG_ANCHO_MAX_PX / img.width)
                img = img.resize((IMG_ANCHO_MAX_PX, nuevo_alto), Image.LANCZOS)

            img.save(ruta_opt, "JPEG", quality=IMG_CALIDAD_JPEG, optimize=True)

        peso_orig_kb = ruta_original.stat().st_size / 1024
        peso_opt_kb  = ruta_opt.stat().st_size / 1024
        print(f"[WUG][MAIL] Optimizado {ruta_original.name}: "
              f"{peso_orig_kb:.1f}KB → {peso_opt_kb:.1f}KB")

        return ruta_opt

    except Exception as e:
        print(f"[WUG][MAIL] Warning: falló optimización de {ruta_original.name}: "
              f"{type(e).__name__}: {e}. Se usa el original.")
        return ruta_original


def _enviar_reporte_mail(evidencias: dict, destinatarios: list, preview: bool = False) -> bool:
    """
    Envía por Outlook (COM) un mail HTML con las evidencias embebidas inline.

    - Usa el cliente Outlook desktop ya autenticado localmente (la ruta confiable
      para Pecom, ya que O365 SMTP Basic Auth está deshabilitado a nivel tenant).
    - Cada imagen se optimiza (redimensiona + JPEG) para no reventar el límite
      de 102KB de Gmail, y después se adjunta con CID vía PR_ATTACH_CONTENT_ID
      para poder referenciarla con <img src="cid:..."> embebida en el cuerpo.

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
        peso_total_kb = 0.0

        for i, (titulo, info) in enumerate(evidencias.items()):
            ruta = Path(info["path"])
            resumen = info.get("resumen_html", "")

            # Optimizar antes de adjuntar (evita el clipping de Gmail).
            ruta_para_mail = _optimizar_imagen_para_mail(ruta)
            peso_total_kb += ruta_para_mail.stat().st_size / 1024

            cid = f"widget_{i}"
            attachment = mail.Attachments.Add(str(ruta_para_mail.resolve()))
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

        # Base64 agrega ~33% de overhead al peso real de los archivos.
        # Si el peso proyectado del body supera 90KB, avisamos para poder
        # ajustar IMG_ANCHO_MAX_PX o IMG_CALIDAD_JPEG a la baja.
        peso_body_estimado_kb = peso_total_kb * 1.33
        print(f"[WUG][MAIL] Peso total imágenes: {peso_total_kb:.1f}KB "
              f"(≈{peso_body_estimado_kb:.1f}KB en base64 dentro del mail)")
        if peso_body_estimado_kb > 90:
            print("[WUG][MAIL] ⚠  El peso proyectado se acerca al límite de "
                  "Gmail (102KB). Considerá bajar IMG_ANCHO_MAX_PX o "
                  "IMG_CALIDAD_JPEG en la configuración.")

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

def check_whatsupgold(enviar_mail: bool = True, preview_mail: bool = None,
                       headless: bool = False) -> bool:
    """
    Recorre los dashboards configurados, guarda una screenshot recortada
    de cada widget y (opcionalmente) envía un mail HTML con las evidencias
    embebidas inline.

    Si un dashboard contiene varios widgets (ej. Disk + Memory en viewId=863),
    solo se carga la URL una vez y después se capturan todos los widgets
    aprovechando la misma sesión de ExtJS.

    Args:
        enviar_mail:  True dispara el envío al terminar. False lo omite
                      (útil cuando lo llama el orquestador checklist.py y
                      el reporte se manda consolidado desde ahí).
        preview_mail: True/False fuerza el modo preview. None respeta
                      MODO_PREVIEW_MAIL configurado arriba.
        headless:     True = sin ventana visible. Requiere que la sesión ya
                      esté guardada en PROFILE_DIR (si Netskope/SSO piden
                      login, headless no lo puede completar solo). Pensado
                      para el refresco automático de programador_reporte.py;
                      todavía sin validar en producción — si en headless
                      empieza a devolver FALLA sistemáticamente, hay que
                      volver a False.
    """
    EVIDENCIAS_DIR.mkdir(exist_ok=True)
    ts = _timestamp()

    ok_global = True
    evidencias_capturadas = {}   # {titulo: {...}} → se pasa al mail al final

    print("=" * 60)
    print("[WUG] Iniciando verificación de WhatsUp Gold")
    print("=" * 60)

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="msedge",
            headless=headless,
            viewport={"width": 1600, "height": 900},
        )

        page = contexto.pages[0] if contexto.pages else contexto.new_page()

        try:
            for dash in DASHBOARDS:
                url = dash["url"]
                widgets = dash["widgets"]

                # Descriptivo para el log: nombres de los widgets que vamos a levantar
                titulos_widgets = ", ".join(w["titulo"] for w in widgets)
                print(f"\n[WUG] Abriendo dashboard con: {titulos_widgets}")

                try:
                    page.goto(url, wait_until="domcontentloaded",
                              timeout=TIMEOUT_NAVEGACION_MS)
                    # Damos margen a que ExtJS termine de renderizar
                    page.wait_for_timeout(ESPERA_RENDER_MS)

                    if _detectar_login(page):
                        print("[WUG] Apareció pantalla de login de WhatsUp Gold.")

                        if WUG_USER and WUG_PASS:
                            print("[WUG] Completando usuario/clave automáticamente (WUG_USER/WUG_PASS)...")
                            logueado = _intentar_login_wug(page)
                            if logueado:
                                print("[WUG] Login automático OK.")
                                # Recargamos el dashboard: el login pudo haber
                                # redirigido a una página distinta a la del widget.
                                page.goto(url, wait_until="domcontentloaded",
                                          timeout=TIMEOUT_NAVEGACION_MS)
                                page.wait_for_timeout(ESPERA_RENDER_MS)
                            else:
                                print("[WUG] El login automático no funcionó — revisar "
                                      "WUG_USER/WUG_PASS en .env o los selectores del "
                                      "formulario (ver _intentar_login_wug).")
                        else:
                            print("[WUG] Logueate manualmente en la ventana de Edge que se abrió "
                                  "(o configurá WUG_USER/WUG_PASS en .env para que sea automático).")
                            print("[WUG] La sesión queda guardada en el perfil para próximas corridas.")
                            # Damos tiempo para que loguee manualmente si está mirando
                            page.wait_for_timeout(30_000)

                        # Reintento final después del login (automático o manual)
                        if _detectar_login(page):
                            ok_global = False
                            continue

                except PlaywrightTimeout as e:
                    print(f"[WUG] TIMEOUT cargando dashboard: {e}")
                    ok_global = False
                    continue
                except Exception as e:
                    print(f"[WUG] ERROR cargando dashboard: {type(e).__name__}: {e}")
                    ok_global = False
                    continue

                # Dashboard cargado y logueado: ahora capturamos cada widget.
                # Si uno falla, seguimos con el siguiente (no cortamos toda la corrida).
                for widget in widgets:
                    nombre = widget["nombre"]
                    titulo = widget["titulo"]

                    ruta_evidencia = EVIDENCIAS_DIR / f"{nombre}_{ts}.png"

                    try:
                        panel = _capturar_panel(page, titulo, ruta_evidencia)
                        print(f"[WUG] OK - Evidencia guardada: {ruta_evidencia.name}")

                        # Extraemos los datos del grid para armar un resumen en el mail
                        filas = _extraer_filas_grid(panel)
                        resumen_html, criticos_count, items_criticos = _generar_resumen_widget(nombre, filas)
                        resumen_plain = (
                            resumen_html
                            .replace('<b>', '').replace('</b>', '')
                            .replace('<i>', '').replace('</i>', '')
                        )
                        print(f"[WUG] Resumen '{titulo}' ({len(filas)} filas): "
                              f"{resumen_plain}")

                        evidencias_capturadas[titulo] = {
                            "path": ruta_evidencia,
                            "resumen_html": resumen_html,
                            "criticos": criticos_count,
                            "items_criticos": items_criticos,
                        }

                    except PlaywrightTimeout as e:
                        print(f"[WUG] TIMEOUT en widget '{titulo}': {e}")
                        ok_global = False
                    except Exception as e:
                        print(f"[WUG] ERROR en widget '{titulo}': "
                              f"{type(e).__name__}: {e}")
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