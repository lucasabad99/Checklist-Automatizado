"""
Verifica el acceso a Remote Desktop Connection via Citrix de Pecom.

Versión v10:
- Detectado: el "Remote Desktop Connection" es un mstsc PUBLICADO por Citrix
    (corre en el servidor Citrix, no local), así que el cmdkey local NO aplica y
    el prompt 'Windows Security' aparece siempre. Ese diálogo suele estar a mayor
    nivel de integridad: si el proceso NO corre ELEVADO, Windows (UIPI) descarta
    el tipeo sintético (a mano entra, automático no -> campo queda vacío).
- Aviso al arranque de si la consola corre como Administrador.
- Tras el Enter, se verifica si 'Windows Security' se cerró (credencial aceptada)
    o sigue abierto (el tipeo no entró), para no esperar 45s al pedo y dar la
    causa probable en el acto.

Versión v9:
- Carpeta de evidencias DEDICADA y específica: "evidencias_citrix/".
- FIX credenciales del RDP:
    * RDP_PASS ahora se lee CRUDO del .env (sin interpolación de dotenv), así un
      password con '$' (ej: 'Sd20241217**$$') no se rompe solo. dotenv expande
      $VAR / ${VAR} en valores SIN comillas y puede comerse parte de la clave.
    * Diagnóstico SEGURO al arrancar: imprime de qué variable salió RDP_PASS
      (CITRIX_RDP_PASS vs fallback al portal) y un "fingerprint" sin revelar la
      clave (largo, cantidad de letras/dígitos/especiales, si tiene $ y *), para
      detectar de una si falta la clave admin o si dotenv la mutiló.

Versión v8:
- FIX pantalla al 200%: el proceso ahora se marca PER-MONITOR DPI-AWARE, así
    win32/pygetwindow y pyautogui hablan en el MISMO sistema de píxeles. Antes
    win32 reportaba píxeles físicos (ventana 3846x2166) y pyautogui clickeaba en
    lógicos (1920x1080); la mezcla mandaba el click a (1920,0) = esquina sup. der.
    y disparaba el fail-safe de pyautogui justo antes de tipear el servidor.
- Click seguro con clamp a la pantalla virtual (red de seguridad anti fail-safe).

Versión v7:
- El campo "Computer" del dialog mstsc se clickeaba en el lugar equivocado
    (caía sobre el logo del header), así que el servidor nunca se escribía.
    Ahora se usa la posición correcta (configurable por fracción).
- Foco robusto: truco ALT + AttachThreadInput + verificación (igual que 3CX).
- Botón Connect por fracción de la ventana (no píxeles fijos).
- Screenshot de verificación después de tipear el servidor.

Pre-requisitos:
    pip install playwright python-dotenv pyautogui pygetwindow pillow pywin32
    playwright install msedge

    .env con:
        CITRIX_URL=https://citrix.pecomenergia.com.ar
        CITRIX_USER=ARGENTINA\tu_usuario
        CITRIX_PASS=tu_password

Uso:
    python check_citrix.py
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime

# ── DPI awareness ─────────────────────────────────────────────────────────────
# Pantalla al 200%: win32/pygetwindow reporta píxeles FÍSICOS (ventana 3846x2166)
# pero pyautogui, si el proceso NO es DPI-aware, clickea en píxeles LÓGICOS
# (1920x1080). Esa mezcla hacía caer el click en (1920,0) = esquina sup. derecha
# de la pantalla lógica -> fail-safe. Marcando el proceso per-monitor DPI-aware,
# los dos hablan en píxeles físicos y las fracciones de ventana vuelven a cerrar.
# Tiene que correr ANTES de importar/usar pyautogui y de abrir cualquier ventana.
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()    # fallback
    except Exception:
        pass

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import pyautogui
import pygetwindow as gw

# pywin32 para manipular ventanas a bajo nivel
try:
    import win32gui
    import win32con
    WIN32_OK = True
except ImportError:
    WIN32_OK = False
    print("⚠ Instalá pywin32: pip install pywin32")

load_dotenv()


# ── Helpers .env (anti-interpolación) y diagnóstico seguro de password ─────────
def _ruta_env():
    return Path(__file__).parent / ".env"


def _leer_valor_env_crudo(clave):
    """Lee el valor LITERAL de una clave del .env, SIN la interpolación de dotenv.

    dotenv expande $VAR / ${VAR} en valores que NO están entre comillas, lo que
    puede comerse parte de un password con '$' (ej: '...**$$' o '...$algo').
    Esto devuelve el texto tal cual está escrito en el archivo (sacando solo las
    comillas envolventes si las hubiera). Devuelve None si no encuentra la clave.
    """
    try:
        for linea in _ruta_env().read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, _, v = linea.partition("=")
            if k.strip() != clave:
                continue
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            return v
    except Exception:
        pass
    return None


def _fingerprint_pass(p):
    """Descripción SEGURA de un password (no revela la clave): largo, clases de
    caracteres y si contiene $ y *. Sirve para detectar si falta la clave admin
    o si dotenv mutiló los caracteres especiales."""
    p = p or ""
    letras     = sum(c.isalpha() for c in p)
    digitos    = sum(c.isdigit() for c in p)
    especiales = sum((not c.isalnum()) for c in p)
    return (f"len={len(p)} letras={letras} digitos={digitos} "
            f"especiales={especiales} tiene_$={'$' in p} tiene_*={'*' in p}")


def _es_admin():
    """True si el proceso corre con privilegios de Administrador. El diálogo
    'Windows Security' del RDP suele estar a mayor integridad: sin elevar, UIPI
    descarta el tipeo sintético (a mano entra, automático no)."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ============ CONFIGURACIÓN ============
SITIO_NOMBRE = "Citrix-RDP"
URL          = os.getenv("CITRIX_URL", "https://citrix.pecomenergia.com.ar")
USUARIO      = os.getenv("CITRIX_USER")
PASSWORD     = os.getenv("CITRIX_PASS")

# Password para el prompt de Windows Security del RDP. El RDP suele necesitar la
# clave ADMIN (distinta a la del portal): definila en el .env como
#   CITRIX_RDP_PASS='Sd20241217**$$'   (¡con comillas simples por el $!)
# Leemos el valor CRUDO del .env para esquivar la interpolación de dotenv (que en
# valores sin comillas se come los '$'). Si no está, caemos al portal (CITRIX_PASS).
_rdp_pass_crudo = _leer_valor_env_crudo("CITRIX_RDP_PASS")
if _rdp_pass_crudo:
    RDP_PASS = _rdp_pass_crudo
    ORIGEN_RDP_PASS = "CITRIX_RDP_PASS (.env crudo)"
else:
    _portal_crudo = _leer_valor_env_crudo("CITRIX_PASS")
    RDP_PASS = _portal_crudo or PASSWORD
    ORIGEN_RDP_PASS = "CITRIX_PASS — FALLBACK al portal (¿falta CITRIX_RDP_PASS?)"

# Diálogo "Windows Security" (prompt de credenciales del RDP)
SEG_ANTES_PASSWORD     = 3.0    # espera tras detectar el diálogo, para que cargue bien
SEG_ANTES_DE_TIPEAR    = 1.0    # pausa extra entre enfocar el campo y empezar a escribir
DELAY_ENTRE_CHARS_PASS = 0.08   # delay entre cada carácter al tipear la clave
# Cómo enfocar el campo Password antes de escribir:
#   "nada"  = confiar en el foco por defecto (el cursor ya arranca en el campo)
#   "click" = click en las coordenadas del campo (CAMPO_PASS_FRAC_*)
#   "tab"   = mandar Tab(s) desde el foco inicial (idea de Lucas, plan B)
ESTRATEGIA_FOCO    = "nada"
TABS_ANTES         = 1       # cuántos Tab mandar si ESTRATEGIA_FOCO == "tab"
SHIFT_TAB          = False   # usar Shift+Tab en vez de Tab
CAMPO_PASS_FRAC_X  = 0.40    # posición del campo Password (solo si ESTRATEGIA_FOCO == "click")
CAMPO_PASS_FRAC_Y  = 0.43
METODO_PASSWORD    = "unicode"  # "unicode" (recomendado) | "paste" | (fallback typewrite)

RDP_SERVIDOR = "ar-cen-s-0057"   # nombre del servidor Remote Desktop (HARDCODEADO)

# Usuario para el login del RDP (el que muestra el diálogo: ARGENTINA\54044306ASD).
# Si es distinto al del portal, definí CITRIX_RDP_USER en el .env.
RDP_USER = os.getenv("CITRIX_RDP_USER") or USUARIO

# Guardar la credencial con cmdkey ANTES de conectar, así mstsc la usa sola y el
# prompt "Windows Security" NO aparece (ese campo rechaza las teclas inyectadas,
# por eso escribir ahí por automatización no funciona). Es la forma correcta.
USAR_CMDKEY = True

# ── Posiciones dentro del dialog mstsc (Remote Desktop Connection) ────────────
# Como FRACCIÓN del tamaño de la ventana (0.0 a 1.0). El dialog estándar abre
# colapsado ("Show Options"): el campo "Computer" está al centro y el botón
# "Connect" abajo a la derecha.
#   - Si el click al campo no entra, mirá el screenshot "_2b_tipeo_..." y ajustá.
CAMPO_COMPUTER_FRAC_X = 0.50
CAMPO_COMPUTER_FRAC_Y = 0.50
BTN_CONNECT_FRAC_X    = 0.67
BTN_CONNECT_FRAC_Y    = 0.89

SELECTOR_USUARIO  = "#username"
SELECTOR_PASSWORD = "#password"
SELECTORES_BOTON_LOGIN = [
    "button:has-text('Iniciar sesión')",
    "input[type='submit']",
    "button[type='submit']",
]

SELECTORES_PORTAL_LISTO = [
    "text=Aplicaciones",
    "text=Apps",
    "text=Escritorios",
    "text=Remote Desktop Connection",
]

SELECTORES_ICONO_RDP = [
    "text=Remote Desktop Connection",
    "[title*='Remote Desktop']",
]

SELECTORES_BOTON_ABRIR = [
    "text=Abrir",
    "a:has-text('Abrir')",
    "[aria-label='Abrir']",
    "[title='Abrir']",
]

# Títulos: cualquier ventana que matchee
TITULOS_VENTANA_RDP = [
    "remote desktop connection",
    "conexión a escritorio remoto",
    "ar-cen-s-0057",
    "ar-cen-s-",
]

TITULO_VENTANA_WINDOWS_SEC = "windows security"

TITULOS_VENTANA_DESKTOP_REMOTO = [
    "ar-cen-s-0057",
    "ar-cen-s-",
    " - remote desktop",
    " - conexión a escritorio remoto",
]

TIMEOUT_MS              = 30000
TIMEOUT_DETECCION_MS    = 10000
TIMEOUT_PORTAL_MS       = 20000
POLL_INTERVAL_MS        = 200

SEG_ESPERAR_PANEL_ABRIR    = 8
SEG_ESPERAR_VENTANA_RDP    = 120  # Citrix Workspace en frío puede tardar bastante
SEG_ESPERAR_VENTANA_SEC    = 30
SEG_ESPERAR_DESKTOP_REMOTO = 45

PROFILE_DIR    = Path(__file__).parent / "edge_profile_citrix"
DESCARGAS_DIR  = Path(__file__).parent / "descargas_rdp"
# Carpeta de evidencias DEDICADA a este check (no se mezcla con las de otros módulos)
EVIDENCIA_DIR  = Path(__file__).parent / "evidencias_citrix"
DESCARGAS_DIR.mkdir(exist_ok=True)
EVIDENCIA_DIR.mkdir(exist_ok=True)
# =======================================


def _click_seguro(x, y):
    """Clampea (x,y) a la pantalla virtual con 2px de margen para no tocar las
    esquinas (que disparan el fail-safe de pyautogui), y clickea.

    Red de seguridad complementaria al fix de DPI: si por geometría rara la
    coordenada se va de la pantalla, en vez de crashear queda pegada al borde.
    Devuelve las coordenadas finales (ya clampeadas)."""
    try:
        vx = ctypes.windll.user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        vy = ctypes.windll.user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        vw = ctypes.windll.user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        vh = ctypes.windll.user32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        x = max(vx + 2, min(x, vx + vw - 2))
        y = max(vy + 2, min(y, vy + vh - 2))
    except Exception:
        pass
    pyautogui.click(x, y)
    return x, y


def intentar_click(pagina, selectores):
    for sel in selectores:
        try:
            elemento = pagina.locator(sel).first
            if elemento.count() and elemento.is_visible():
                elemento.click()
                return sel
        except Exception:
            continue
    return None


def esperar_y_clickear(pagina, selectores, timeout_seg):
    inicio = time.time()
    while time.time() - inicio < timeout_seg:
        for sel in selectores:
            try:
                elemento = pagina.locator(sel).first
                if elemento.count() and elemento.is_visible():
                    elemento.click()
                    return sel
            except Exception:
                continue
        pagina.wait_for_timeout(POLL_INTERVAL_MS)
    return None


def detectar_estado(pagina, timeout_ms):
    inicio = time.time()
    while (time.time() - inicio) * 1000 < timeout_ms:
        try:
            usuario = pagina.locator(SELECTOR_USUARIO).first
            if usuario.count() and usuario.is_visible():
                return "login"
        except Exception:
            pass
        for sel in SELECTORES_PORTAL_LISTO:
            try:
                elemento = pagina.locator(sel).first
                if elemento.count() and elemento.is_visible():
                    return "portal"
            except Exception:
                continue
        pagina.wait_for_timeout(POLL_INTERVAL_MS)
    return None


def buscar_ventana_por_titulos(titulos_substring, timeout_seg, excluir=None, progreso=False):
    if excluir is None:
        excluir = ["visual studio code", "vscode", "powershell", "terminal", ".py",
                   "explorer", "microsoft edge", "chrome", "firefox", "teams", "claude"]

    inicio = time.time()
    ultimo_print = 0
    while time.time() - inicio < timeout_seg:
        for w in gw.getAllWindows():
            titulo = w.title.lower().strip()
            if not titulo:
                continue
            if any(ex in titulo for ex in excluir):
                continue
            if any(t in titulo for t in titulos_substring):
                return w
        if progreso:
            transcurrido = int(time.time() - inicio)
            if transcurrido - ultimo_print >= 10:
                ultimo_print = transcurrido
                print(f"[{SITIO_NOMBRE}]   ...sigo esperando la ventana "
                      f"({transcurrido}s/{int(timeout_seg)}s)")
        time.sleep(0.5)
    return None


def screenshot_ventana(ventana, path):
    try:
        region = (ventana.left, ventana.top, ventana.width, ventana.height)
        pyautogui.screenshot(str(path), region=region)
    except Exception:
        pyautogui.screenshot(str(path))


def forzar_ventana_al_frente(ventana, usar_alt=True):
    """
    Forza una ventana al frente y VERIFICA que realmente quedó en foreground.

    SetForegroundWindow() por sí solo casi nunca alcanza en Windows (la ventana
    parpadea pero no toma el foco, y las teclas van a parar a otro lado). Por eso
    sumamos el truco de mandar un ALT y, si hace falta, AttachThreadInput.

    OJO: en diálogos (ej. Windows Security) el ALT activa el modo menú/acelerador
    y las letras empiezan a disparar botones (O→OK, C→Cancel) en vez de entrar al
    campo. Para esos casos llamar con usar_alt=False (usa solo AttachThreadInput,
    que no manda ninguna tecla).

    Devuelve True solo si la ventana quedó efectivamente al frente.
    """
    if not WIN32_OK:
        print(f"[{SITIO_NOMBRE}]   ⚠ pywin32 no disponible, usando fallback")
        try:
            ventana.minimize()
            time.sleep(0.3)
            ventana.restore()
            time.sleep(0.5)
        except Exception:
            pass
        return False

    try:
        import win32process
        import win32api
        import win32com.client
    except Exception:
        win32process = None
        win32api = None

    try:
        hwnd = ventana._hWnd
    except Exception:
        return False

    def _es_frente():
        try:
            return win32gui.GetForegroundWindow() == hwnd
        except Exception:
            return False

    # 1) Restaurar si está minimizada
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.3)
    except Exception:
        pass

    # 2) Truco ALT — destraba la restricción de foreground de Windows.
    #    Se omite en diálogos (usar_alt=False) para no activar el modo menú.
    if usar_alt:
        try:
            win32com.client.Dispatch("WScript.Shell").SendKeys('%')
        except Exception:
            pass

    # 3) Intento directo
    try:
        win32gui.SetForegroundWindow(hwnd)
        win32gui.BringWindowToTop(hwnd)
    except Exception:
        pass
    time.sleep(0.2)

    # 4) Respaldo con AttachThreadInput si todavía no quedó al frente
    if not _es_frente() and win32process and win32api:
        try:
            fg     = win32gui.GetForegroundWindow()
            remoto = win32process.GetWindowThreadProcessId(fg)[0]
            propio = win32api.GetCurrentThreadId()
            if remoto and remoto != propio:
                win32process.AttachThreadInput(propio, remoto, True)
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.BringWindowToTop(hwnd)
                finally:
                    win32process.AttachThreadInput(propio, remoto, False)
        except Exception as e:
            print(f"[{SITIO_NOMBRE}]   ⚠ AttachThreadInput falló: {e}")
        time.sleep(0.3)

    ok = _es_frente()
    if not ok:
        print(f"[{SITIO_NOMBRE}]   ⚠ La ventana NO quedó al frente.")
    return ok


def _tipear_unicode(texto, delay=0.02):
    """Tipea texto con SendInput usando KEYEVENTF_UNICODE.

    Manda el código unicode de cada carácter directamente al sistema, así:
      - NO depende del layout del teclado (los * y $ entran perfectos), y
      - funciona en campos donde el PEGADO (Ctrl+V) está bloqueado, como el
        prompt de credenciales de Windows Security del RDP.
    """
    import ctypes

    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP   = 0x0002
    INPUT_KEYBOARD    = 1

    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort),
                    ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong),
                    ("dwExtraInfo", PUL)]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong),
                    ("u", _INPUTunion)]

    def _send(code, flags):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki = KEYBDINPUT(0, code, flags, 0, None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    for ch in texto:
        code = ord(ch)
        _send(code, KEYEVENTF_UNICODE)                       # key down
        _send(code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)     # key up
        time.sleep(delay)


def _set_clipboard(texto):
    """Copia texto al portapapeles (con reintentos: a veces está ocupado)."""
    try:
        import win32clipboard
    except Exception as e:
        print(f"[{SITIO_NOMBRE}]   ⚠ win32clipboard no disponible: {e}")
        return False
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(texto, win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return True
        except Exception:
            time.sleep(0.2)
    return False


def pegar_password(password):
    """Ingresa el password en el campo enfocado.

    Método principal: SendInput Unicode (_tipear_unicode), que funciona aunque
    el campo bloquee el pegado y NO rompe los caracteres especiales. Si se
    configura METODO_PASSWORD='paste', usa portapapeles.
    """
    print(f"[{SITIO_NOMBRE}]   (largo del password leído: {len(password or '')} caracteres)")

    # Limpiar el campo por si quedó algo
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    time.sleep(0.1)

    # Pausa extra antes de empezar a escribir (a veces el campo tarda en "aceptar")
    time.sleep(SEG_ANTES_DE_TIPEAR)

    if METODO_PASSWORD == "paste":
        if _set_clipboard(password):
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.4)
            print(f"[{SITIO_NOMBRE}]   Password pegado vía portapapeles.")
            _set_clipboard("")
            return
        print(f"[{SITIO_NOMBRE}]   ⚠ Portapapeles no disponible, paso a Unicode...")

    # Método por defecto: tipeo Unicode (layout-independiente, no bloqueable)
    try:
        _tipear_unicode(password, delay=DELAY_ENTRE_CHARS_PASS)
        print(f"[{SITIO_NOMBRE}]   Password tipeado vía SendInput Unicode.")
    except Exception as e:
        print(f"[{SITIO_NOMBRE}]   ⚠ Unicode falló ({e}), fallback a typewrite...")
        pyautogui.typewrite(password, interval=0.03)
        time.sleep(0.3)


def tipear_servidor_en_rdp(ventana, servidor, screenshot_path=None):
    """
    Click en el campo Computer del dialog mstsc, borra lo que haya, y tipea el
    nombre del servidor. La posición del campo se calcula por fracción de la
    ventana (CAMPO_COMPUTER_FRAC_*), que en el dialog estándar cae en el centro.
    """
    campo_x = ventana.left + int(ventana.width  * CAMPO_COMPUTER_FRAC_X)
    campo_y = ventana.top  + int(ventana.height * CAMPO_COMPUTER_FRAC_Y)
    print(f"[{SITIO_NOMBRE}]   Click en campo Computer ({campo_x}, {campo_y})  "
          f"[ventana: left={ventana.left} top={ventana.top} "
          f"w={ventana.width} h={ventana.height}]")
    campo_x, campo_y = _click_seguro(campo_x, campo_y)
    time.sleep(0.4)

    # Limpiar cualquier contenido previo del campo
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.15)
    pyautogui.press("delete")
    time.sleep(0.15)

    pyautogui.typewrite(servidor, interval=0.06)
    time.sleep(0.4)
    print(f"[{SITIO_NOMBRE}]   Servidor tipeado: {servidor}")

    if screenshot_path:
        try:
            region = (ventana.left, ventana.top, ventana.width, ventana.height)
            pyautogui.screenshot(str(screenshot_path), region=region)
            print(f"[{SITIO_NOMBRE}]   Screenshot POST-TIPEO "
                  f"(verificá que diga '{servidor}'): {screenshot_path}")
        except Exception:
            pass


def guardar_credencial_rdp(servidor, usuario, password):
    """Guarda la credencial del RDP en el Administrador de credenciales de Windows
    con cmdkey. Así, al conectar a TERMSRV/<servidor>, mstsc la toma sola y el
    diálogo 'Windows Security' NO aparece (evitamos el campo que rechaza el tipeo).
    """
    target = f"TERMSRV/{servidor}"
    try:
        # args como lista (sin shell): los caracteres especiales del pass (* $)
        # pasan literales, sin que los toque la shell.
        r = subprocess.run(
            ["cmdkey", f"/generic:{target}", f"/user:{usuario}", f"/pass:{password}"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            print(f"[{SITIO_NOMBRE}]   ✓ Credencial guardada para {target} (user: {usuario})")
            return True
        print(f"[{SITIO_NOMBRE}]   ⚠ cmdkey devolvió código {r.returncode}: {r.stdout.strip()} {r.stderr.strip()}")
        return False
    except Exception as e:
        print(f"[{SITIO_NOMBRE}]   ⚠ No se pudo guardar la credencial: {e}")
        return False


def borrar_credencial_rdp(servidor):
    """Borra la credencial temporal que guardamos (limpieza de seguridad)."""
    target = f"TERMSRV/{servidor}"
    try:
        subprocess.run(["cmdkey", f"/delete:{target}"], capture_output=True, text=True)
        print(f"[{SITIO_NOMBRE}]   Credencial temporal borrada ({target}).")
    except Exception:
        pass


def cancelar_modo_menu():
    """Manda un ALT para SALIR del modo menú/acelerador que el truco de foco deja
    activo. El ALT toggea: el primero (en forzar_ventana_al_frente) entra al modo
    menú; este segundo lo apaga. Sin esto, las letras disparan botones (O→OK)."""
    try:
        import win32com.client
        win32com.client.Dispatch("WScript.Shell").SendKeys('%')
        time.sleep(0.2)
    except Exception:
        pass


def enfocar_campo_password(ventana):
    """Enfoca el campo Password según ESTRATEGIA_FOCO ('nada' | 'click' | 'tab')."""
    if ESTRATEGIA_FOCO == "click":
        px = ventana.left + int(ventana.width  * CAMPO_PASS_FRAC_X)
        py = ventana.top  + int(ventana.height * CAMPO_PASS_FRAC_Y)
        print(f"[{SITIO_NOMBRE}]   Foco por CLICK en ({px}, {py})  "
              f"[ventana: left={ventana.left} top={ventana.top} "
              f"w={ventana.width} h={ventana.height}]")
        _click_seguro(px, py)
        time.sleep(0.4)
    elif ESTRATEGIA_FOCO == "tab":
        print(f"[{SITIO_NOMBRE}]   Foco por TAB x{TABS_ANTES} (shift={SHIFT_TAB})")
        for _ in range(TABS_ANTES):
            if SHIFT_TAB:
                pyautogui.hotkey("shift", "tab")
            else:
                pyautogui.press("tab")
            time.sleep(0.2)
    else:
        print(f"[{SITIO_NOMBRE}]   Sin click/tab: confío en el foco por defecto del campo.")


def dialog_rdp_blanco_abierto():
    """Devuelve la ventana del diálogo mstsc EN BLANCO (sin conectar) si sigue
    abierto, o None. La sesión ya conectada incluye 'ar-cen-s-...' o ' - ' en el
    título, así que esas se descartan para no clickear sobre el escritorio remoto."""
    for w in gw.getAllWindows():
        t = w.title.lower().strip()
        if not t:
            continue
        if "ar-cen-s" in t or " - " in t:
            continue
        if "remote desktop connection" in t or "conexión a escritorio remoto" in t:
            return w
    return None


def click_connect_directo(ventana):
    """Click en el botón Connect, calculando la posición por fracción de la ventana."""
    x = ventana.left + int(ventana.width  * BTN_CONNECT_FRAC_X)
    y = ventana.top  + int(ventana.height * BTN_CONNECT_FRAC_Y)
    print(f"[{SITIO_NOMBRE}]   Click en Connect ({x}, {y})...")
    _click_seguro(x, y)


def check_citrix_rdp():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_portal   = EVIDENCIA_DIR / f"{SITIO_NOMBRE}_1_portal_{timestamp}.png"
    screenshot_rdp_dlg  = EVIDENCIA_DIR / f"{SITIO_NOMBRE}_2_rdp_dialog_{timestamp}.png"
    screenshot_rdp_typed= EVIDENCIA_DIR / f"{SITIO_NOMBRE}_2b_tipeo_{timestamp}.png"
    screenshot_winsec   = EVIDENCIA_DIR / f"{SITIO_NOMBRE}_3_winsec_{timestamp}.png"
    screenshot_winsec_typed = EVIDENCIA_DIR / f"{SITIO_NOMBRE}_3b_winsec_pass_{timestamp}.png"
    screenshot_winsec_click = EVIDENCIA_DIR / f"{SITIO_NOMBRE}_3a_winsec_click_{timestamp}.png"
    screenshot_desktop  = EVIDENCIA_DIR / f"{SITIO_NOMBRE}_4_desktop_{timestamp}.png"

    if not USUARIO or not PASSWORD:
        print(f"[{SITIO_NOMBRE}] ✗ FAIL — Faltan credenciales en .env")
        return False

    print(f"[{SITIO_NOMBRE}] Iniciando verificación completa de RDP via Citrix...")
    if _es_admin():
        print(f"[{SITIO_NOMBRE}] ✓ Consola corriendo como ADMINISTRADOR.")
    else:
        print(f"[{SITIO_NOMBRE}] ⚠ La consola NO corre como Administrador. El diálogo 'Windows")
        print(f"[{SITIO_NOMBRE}]   Security' del RDP puede ignorar el tipeo automático (UIPI). Si la")
        print(f"[{SITIO_NOMBRE}]   clave no entra, cerrá y volvé a abrir la consola 'como Administrador'.")
    print(f"[{SITIO_NOMBRE}] RDP_PASS origen: {ORIGEN_RDP_PASS}")
    print(f"[{SITIO_NOMBRE}] RDP_PASS huella (SIN revelar la clave): {_fingerprint_pass(RDP_PASS)}")
    t0 = time.time()

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="msedge",
            headless=False,
            args=[
                "--start-maximized",
                "--disable-features=Translate",
                "--lang=es",
            ],
            accept_downloads=True,
            locale="es-AR",
        )

        pagina = contexto.new_page()

        try:
            # ===== FASE 1: Login =====
            print(f"[{SITIO_NOMBRE}] [1/5] Navegando al portal...")
            pagina.goto(URL, timeout=TIMEOUT_MS, wait_until="domcontentloaded")

            estado = detectar_estado(pagina, TIMEOUT_DETECCION_MS)
            print(f"[{SITIO_NOMBRE}]   ({time.time()-t0:.1f}s) Estado: {estado}")

            if estado == "login":
                pagina.locator(SELECTOR_USUARIO).fill(USUARIO)
                pagina.locator(SELECTOR_PASSWORD).fill(PASSWORD)
                if not intentar_click(pagina, SELECTORES_BOTON_LOGIN):
                    pagina.locator(SELECTOR_PASSWORD).press("Enter")
                print(f"[{SITIO_NOMBRE}]   ({time.time()-t0:.1f}s) Login enviado")

                inicio = time.time()
                portal_listo = False
                while time.time() - inicio < TIMEOUT_PORTAL_MS / 1000:
                    for sel in SELECTORES_PORTAL_LISTO:
                        try:
                            elem = pagina.locator(sel).first
                            if elem.count() and elem.is_visible():
                                portal_listo = True
                                break
                        except Exception:
                            continue
                    if portal_listo:
                        break
                    pagina.wait_for_timeout(POLL_INTERVAL_MS)

                if not portal_listo:
                    print(f"[{SITIO_NOMBRE}] ✗ FAIL — Portal no cargó")
                    return False
            elif estado != "portal":
                print(f"[{SITIO_NOMBRE}] ✗ FAIL — Estado desconocido")
                return False

            print(f"[{SITIO_NOMBRE}]   ({time.time()-t0:.1f}s) ✓ Portal accesible")
            pagina.wait_for_timeout(1500)
            pagina.screenshot(path=str(screenshot_portal), full_page=True)

            # ===== FASE 2: Click en ícono RDP =====
            print(f"[{SITIO_NOMBRE}] [2/5] Click en ícono 'Remote Desktop Connection'...")
            if not intentar_click(pagina, SELECTORES_ICONO_RDP):
                print(f"[{SITIO_NOMBRE}] ✗ FAIL — No se encontró el ícono")
                return False

            # ===== FASE 3: Click en "Abrir" + descarga =====
            print(f"[{SITIO_NOMBRE}] [3/5] Buscando 'Abrir'...")
            pagina.wait_for_timeout(1000)

            try:
                with pagina.expect_download(timeout=20000) as download_info:
                    sel_abrir = esperar_y_clickear(pagina, SELECTORES_BOTON_ABRIR, SEG_ESPERAR_PANEL_ABRIR)
                    if not sel_abrir:
                        print(f"[{SITIO_NOMBRE}] ✗ FAIL — No se encontró 'Abrir'")
                        return False
                download = download_info.value
                archivo_rdp = DESCARGAS_DIR / download.suggested_filename
                download.save_as(str(archivo_rdp))
                print(f"[{SITIO_NOMBRE}]   ({time.time()-t0:.1f}s) ✓ Descargado: {archivo_rdp.name}")
            except Exception as e:
                print(f"[{SITIO_NOMBRE}] ✗ FAIL — Descarga: {e}")
                return False

            # ===== FASE 4: Abrir archivo + ventana RDP + Connect =====
            # Guardamos la credencial ANTES de conectar: así mstsc la usa sola y
            # el prompt de Windows Security no aparece.
            if USAR_CMDKEY:
                print(f"[{SITIO_NOMBRE}] Guardando credencial RDP con cmdkey (largo pass: {len(RDP_PASS or '')})...")
                guardar_credencial_rdp(RDP_SERVIDOR, RDP_USER, RDP_PASS)

            print(f"[{SITIO_NOMBRE}] [4/5] Abriendo archivo .ica con Citrix Workspace...")
            os.startfile(str(archivo_rdp))

            print(f"[{SITIO_NOMBRE}]   Esperando ventana RDP (hasta {SEG_ESPERAR_VENTANA_RDP}s)...")
            print(f"[{SITIO_NOMBRE}]   (si Citrix Workspace pide iniciar sesión, completalo a mano esta vez)")
            ventana_rdp = buscar_ventana_por_titulos(
                TITULOS_VENTANA_RDP,
                SEG_ESPERAR_VENTANA_RDP,
                progreso=True,
            )

            if not ventana_rdp:
                print(f"[{SITIO_NOMBRE}] ✗ FAIL — No apareció ventana RDP")
                print(f"[{SITIO_NOMBRE}]   Ventanas abiertas en este momento:")
                for w in gw.getAllWindows():
                    if w.title.strip():
                        print(f"[{SITIO_NOMBRE}]     '{w.title}'")
                return False

            print(f"[{SITIO_NOMBRE}]   ({time.time()-t0:.1f}s) ✓ Ventana RDP: '{ventana_rdp.title}'")
            print(f"[{SITIO_NOMBRE}]   Estado: minimized={ventana_rdp.isMinimized}, pos=({ventana_rdp.left},{ventana_rdp.top})")

            # ⚡ FORZAR la ventana al frente (foco robusto + verificación)
            print(f"[{SITIO_NOMBRE}]   Forzando ventana al frente con win32...")
            forzar_ventana_al_frente(ventana_rdp)
            time.sleep(1)

            # Re-localizar para tener pos actualizada
            ventana_rdp = buscar_ventana_por_titulos(TITULOS_VENTANA_RDP, 3) or ventana_rdp
            print(f"[{SITIO_NOMBRE}]   Pos final: ({ventana_rdp.left},{ventana_rdp.top}) Tam: {ventana_rdp.width}x{ventana_rdp.height}")

            screenshot_ventana(ventana_rdp, screenshot_rdp_dlg)
            print(f"    Screenshot: {screenshot_rdp_dlg.name}")

            # Re-forzar el foco JUSTO antes de escribir y tipear el servidor
            forzar_ventana_al_frente(ventana_rdp)
            time.sleep(0.5)
            tipear_servidor_en_rdp(ventana_rdp, RDP_SERVIDOR, screenshot_rdp_typed)

            # Conectar: Enter primero (lo más confiable). El click a Connect SOLO
            # se hace si el diálogo en blanco sigue abierto (si no, evitamos un
            # click perdido que ensucia la interfaz una vez que ya está conectando).
            print(f"[{SITIO_NOMBRE}]   Conectando (Enter)...")
            pyautogui.press("enter")
            time.sleep(1.0)
            dlg_aun = dialog_rdp_blanco_abierto()
            if dlg_aun:
                print(f"[{SITIO_NOMBRE}]   El diálogo sigue abierto, clickeo Connect de respaldo...")
                forzar_ventana_al_frente(dlg_aun)
                time.sleep(0.3)
                click_connect_directo(dlg_aun)
            else:
                print(f"[{SITIO_NOMBRE}]   Diálogo ya cerrado (Enter conectó), sin click extra.")

            # ===== FASE 5: Windows Security =====
            print(f"[{SITIO_NOMBRE}] [5/5] Esperando 'Windows Security'...")
            ventana_winsec = buscar_ventana_por_titulos(
                [TITULO_VENTANA_WINDOWS_SEC],
                SEG_ESPERAR_VENTANA_SEC,
            )

            if not ventana_winsec:
                print(f"[{SITIO_NOMBRE}] ⚠ No apareció Windows Security en {SEG_ESPERAR_VENTANA_SEC}s")
            else:
                print(f"[{SITIO_NOMBRE}]   ({time.time()-t0:.1f}s) ✓ Windows Security detectado")
                # Foreground CON ALT (es lo que sí trae la ventana al frente)...
                forzar_ventana_al_frente(ventana_winsec, usar_alt=True)
                # ...y enseguida cancelamos el modo menú que dejó ese ALT.
                cancelar_modo_menu()
                print(f"[{SITIO_NOMBRE}]   Esperando {SEG_ANTES_PASSWORD}s a que el diálogo cargue bien...")
                time.sleep(SEG_ANTES_PASSWORD)
                ventana_winsec = buscar_ventana_por_titulos([TITULO_VENTANA_WINDOWS_SEC], 3) or ventana_winsec
                forzar_ventana_al_frente(ventana_winsec, usar_alt=True)
                cancelar_modo_menu()
                time.sleep(0.4)
                screenshot_ventana(ventana_winsec, screenshot_winsec)
                print(f"    Screenshot: {screenshot_winsec.name}")

                # Enfocar el campo (por defecto 'nada': el cursor ya arranca ahí)
                enfocar_campo_password(ventana_winsec)
                try:
                    screenshot_ventana(ventana_winsec, screenshot_winsec_click)
                    print(f"[{SITIO_NOMBRE}]   Screenshot PRE-ESCRITURA "
                          f"(¿el cursor está en el campo?): {screenshot_winsec_click.name}")
                except Exception:
                    pass

                print(f"[{SITIO_NOMBRE}]   Ingresando password...")
                pegar_password(RDP_PASS)
                time.sleep(0.5)

                # Screenshot ANTES del Enter: el campo debería tener los puntitos.
                try:
                    screenshot_ventana(ventana_winsec, screenshot_winsec_typed)
                    print(f"[{SITIO_NOMBRE}]   Screenshot POST-ESCRITURA "
                          f"(verificá que el campo tenga puntitos): {screenshot_winsec_typed.name}")
                except Exception:
                    pass

                pyautogui.press("enter")

                # ¿El diálogo se cerró (login OK) o sigue abierto (el tipeo no entró)?
                time.sleep(2.0)
                winsec_sigue = buscar_ventana_por_titulos([TITULO_VENTANA_WINDOWS_SEC], 3)
                if winsec_sigue:
                    print(f"[{SITIO_NOMBRE}] ✗ 'Windows Security' SIGUE ABIERTO tras el Enter:")
                    print(f"[{SITIO_NOMBRE}]   el password inyectado NO fue aceptado por el campo.")
                    if not _es_admin():
                        print(f"[{SITIO_NOMBRE}]   >> Causa más probable: la consola NO está ELEVADA y Windows")
                        print(f"[{SITIO_NOMBRE}]      (UIPI) descarta el tipeo sintético en ese diálogo. Corré la")
                        print(f"[{SITIO_NOMBRE}]      consola 'como Administrador' y reintentá (a mano entra porque")
                        print(f"[{SITIO_NOMBRE}]      el teclado real no pasa por ese filtro).")
                    else:
                        print(f"[{SITIO_NOMBRE}]   >> Estás elevado, así que NO es UIPI. Probá METODO_PASSWORD='paste'")
                        print(f"[{SITIO_NOMBRE}]      o ESTRATEGIA_FOCO='click' (con CAMPO_PASS_FRAC_*) y avisame.")
                    try:
                        screenshot_ventana(winsec_sigue, screenshot_winsec_typed)
                        print(f"[{SITIO_NOMBRE}]   Screenshot del diálogo aún abierto: {screenshot_winsec_typed.name}")
                    except Exception:
                        pass
                else:
                    print(f"[{SITIO_NOMBRE}]   ✓ El diálogo se cerró tras el Enter (credencial aceptada).")

            # ===== FASE 6: Desktop remoto =====
            print(f"[{SITIO_NOMBRE}] Esperando escritorio remoto (hasta {SEG_ESPERAR_DESKTOP_REMOTO}s)...")
            ventana_desktop = buscar_ventana_por_titulos(
                TITULOS_VENTANA_DESKTOP_REMOTO,
                SEG_ESPERAR_DESKTOP_REMOTO,
            )

            if not ventana_desktop:
                print(f"[{SITIO_NOMBRE}] ✗ FAIL — Desktop no cargó en {SEG_ESPERAR_DESKTOP_REMOTO}s")
                pyautogui.screenshot(str(screenshot_desktop))
                return False

            print(f"[{SITIO_NOMBRE}]   ({time.time()-t0:.1f}s) ✓ Desktop: '{ventana_desktop.title}'")
            time.sleep(3)
            forzar_ventana_al_frente(ventana_desktop)
            screenshot_ventana(ventana_desktop, screenshot_desktop)

            print()
            print(f"[{SITIO_NOMBRE}] ✓ OK ({time.time()-t0:.1f}s) — RDP funcionando")
            print(f"    Screenshot final: {screenshot_desktop.name}")
            print()
            print(f"[{SITIO_NOMBRE}] >> Todo abierto. Cerralo manualmente.")
            return True

        except Exception as e:
            print(f"[{SITIO_NOMBRE}] ✗ ERROR: {type(e).__name__}: {e}")
            try:
                pyautogui.screenshot(str(screenshot_desktop))
            except Exception:
                pass
            return False

        finally:
            if USAR_CMDKEY:
                borrar_credencial_rdp(RDP_SERVIDOR)
            contexto.close()


if __name__ == "__main__":
    resultado = check_citrix_rdp()
    print()
    sys.exit(0 if resultado else 1)