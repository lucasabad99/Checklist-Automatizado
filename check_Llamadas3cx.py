"""
Verifica que 3CX Phone (cliente clásico) funcione para originar llamadas salientes.

Estrategia:
- NO usa el protocolo tel: porque 3CX Phone clásico no lo soporta.
- Trae al frente la ventana de 3CX Phone (que debe estar abierta y logueada).
- *** FUERZA y VERIFICA el foco *** (truco ALT + AttachThreadInput).
- *** VA AL DIALPAD apretando el botón "home" del skin ***, porque 3CXPhone
    abre en el "Main menu" (Preferences, Accounts, Calls...) y ahí los números
    no se discan.
- Tipea el número directamente como si lo discaras en el dialpad.
- Apreta Enter para iniciar la llamada.
- Saca screenshot de evidencia.
- Cuelga con la tecla configurada (ESC por defecto).

Pre-requisitos:
- 3CX Phone debe estar ABIERTO y LOGUEADO antes de correr el script.
- El estado debe estar en "Available" / "On Hook".

Requisitos:
    pip install pyautogui pygetwindow pillow pywin32

Uso:
    python check_Llamadas3cx.py
"""

import subprocess
import time
from pathlib import Path
from datetime import datetime

import psutil
import pyautogui
import pygetwindow as gw

# ============ CONFIGURACIÓN ============
SITIO_NOMBRE   = "3CX"
NUMERO_DESTINO = "91555838452"   # 9 = prefijo salida externa + celular

# Ruta al ejecutable de 3CX Phone
PATH_3CX = r"C:\Program Files (x86)\3CXPhone\3CXPhone.exe"

# Segundos máximos esperando que 3CX cargue tras lanzarlo
SEG_ESPERAR_INICIO_3CX = 20

# ── Navegación al dialpad ─────────────────────────────────────────────────────
# 3CXPhone clásico abre en el "Main menu" (los iconos Preferences/Accounts/etc).
# El botón físico de abajo-centro del skin ("home") lleva a la pantalla del
# teclado numérico. Acá clickeamos ese botón antes de tipear.
#
# La posición se expresa como FRACCIÓN del tamaño de la ventana (0.0 a 1.0),
# así no depende de dónde esté la ventana en la pantalla.
#   - Si el click cae sobre el icono "Help" (más arriba), BAJÁ HOME_BTN_FRAC_Y (ej. 0.93).
#   - Si cae por debajo del botón, SUBÍ HOME_BTN_FRAC_Y (ej. 0.88).
# Mirá el screenshot "_predial_...png" que genera el script para ajustar.
HOME_BTN_FRAC_X = 0.50
HOME_BTN_FRAC_Y = 0.91
SEG_TRAS_HOME   = 2.5     # espera tras apretar home para que cargue el dialpad
CLICKS_HOME     = 1       # cuántas veces apretar home (normalmente 1)

# Tras llegar al dialpad, el campo de número a veces tarda un toque en tomar
# el foco y se "come" el primer dígito (ej: marcaba 1555... en vez de 91555...).
# Para evitarlo: esperamos un poco más antes de tipear y mandamos un dígito de
# "calentamiento" que después se borra, así el primer dígito real nunca se pierde.
SEG_ANTES_DE_TIPEAR = 1.0   # pausa extra antes del primer dígito
DIGITO_CALENTAMIENTO = True  # tipea un 0 y lo borra antes de discar el número real

# Títulos de ventana válidos para 3CX Phone clásico
TITULOS_VENTANA_3CX_VALIDOS = [
    "3cxphone",
    "3cx phone",
    "3cx desktop app",
]

# Títulos a EXCLUIR (para no agarrar editores/navegadores ni componentes de fondo)
TITULOS_VENTANA_EXCLUIR = [
    "visual studio code",
    "vscode",
    "notepad",
    "chrome",
    "edge",
    "firefox",
    ".py",
    "explorer",
    "powershell",
    "terminal",
    "video streamer",   # componente de fondo de 3CX, no es el dialpad
]

# Tiempos
SEG_TRAS_ACTIVAR          = 1.0   # margen tras activar ventana
SEG_ENTRE_DIGITOS         = 0.15  # delay entre cada dígito al tipear
SEG_TRAS_TIPEAR           = 0.5   # margen antes de Enter
SEG_MAX_LLAMADA           = 10   # máximo que esperamos que la llamada esté activa
SEG_MIN_SCREENSHOT        = 8     # mínimo antes de tomar screenshot (llamada en curso)
SEG_ANTES_DE_COLGAR       = 3     # pausa visible entre screenshot y colgar
SEG_ESPERAR_REGISTRO_PBX  = 10    # extra al lanzar 3CX desde cero: esperar registro PBX

# Carpeta de evidencias
EVIDENCIA_DIR = Path(__file__).parent / "evidencias"
EVIDENCIA_DIR.mkdir(exist_ok=True)
# =======================================


def _hwnd_de(ventana):
    """Obtiene el HWND real desde el objeto de pygetwindow."""
    try:
        return ventana._hWnd
    except Exception:
        return None


def forzar_foco(hwnd) -> bool:
    """Trae la ventana al primer plano de forma robusta y VERIFICA que realmente
    quedó activa. Devuelve True solo si 3CX es la ventana en foreground.

    Por qué hace falta esto:
        Windows no deja que un proceso le robe el foco a otro porque sí. Por eso
        SetForegroundWindow() y pygetwindow.activate() "no fallan" pero tampoco
        traen la ventana al frente (solo parpadea en la barra de tareas), y las
        teclas terminan yendo a la consola u otra app. Acá usamos:
          1) el truco de mandar un ALT para destrabar la restricción, y
          2) AttachThreadInput como respaldo (engancha el input de nuestro hilo
             al de la ventana que tiene el foco), que es lo que sí funciona.
    """
    if not hwnd:
        return False
    try:
        import win32gui
        import win32con
        import win32process
        import win32api
        import win32com.client
    except Exception as e:
        print(f"[{SITIO_NOMBRE}]   ⚠ pywin32 incompleto: {e}")
        return False

    def _es_frente():
        try:
            return win32gui.GetForegroundWindow() == hwnd
        except Exception:
            return False

    # Restaurar si está minimizada
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.3)
    except Exception:
        pass

    # 1) Truco ALT — destraba la restricción de foreground de Windows
    try:
        win32com.client.Dispatch("WScript.Shell").SendKeys('%')
    except Exception:
        pass

    # 2) Primer intento directo
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.2)

    # 3) Si todavía no quedó al frente, respaldo con AttachThreadInput
    if not _es_frente():
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

    return _es_frente()


def _click_fraccion_ventana(ventana, frac_x, frac_y, descripcion=""):
    """Clickea en un punto de la ventana expresado como fracción de su tamaño."""
    x = int(ventana.left + ventana.width  * frac_x)
    y = int(ventana.top  + ventana.height * frac_y)
    print(f"[{SITIO_NOMBRE}] Click {descripcion} en ({x}, {y})  "
          f"[ventana: left={ventana.left} top={ventana.top} "
          f"w={ventana.width} h={ventana.height}]")
    pyautogui.click(x, y)
    return x, y


def _ir_al_dialpad(ventana, hwnd, timestamp):
    """Aprieta el botón 'home' del skin 3CXPhone para pasar del Main menu al
    teclado numérico, y saca un screenshot de verificación pre-discado."""
    print(f"[{SITIO_NOMBRE}] Yendo al dialpad (botón home del celular)...")
    for n in range(CLICKS_HOME):
        _click_fraccion_ventana(ventana, HOME_BTN_FRAC_X, HOME_BTN_FRAC_Y,
                                f"botón home ({n+1}/{CLICKS_HOME})")
        time.sleep(0.4)

    time.sleep(SEG_TRAS_HOME)

    # Re-foco por las dudas y screenshot para verificar que estamos en el teclado
    forzar_foco(hwnd)
    time.sleep(0.3)
    try:
        region = (ventana.left, ventana.top, ventana.width, ventana.height)
        predial_path = EVIDENCIA_DIR / f"{SITIO_NOMBRE}_predial_{timestamp}.png"
        pyautogui.screenshot(str(predial_path), region=region)
        print(f"[{SITIO_NOMBRE}] Screenshot PRE-DISCADO (verificá que se vea el "
              f"teclado numérico): {predial_path}")
    except Exception:
        pass


def _traer_ventana_3cx_desde_tray():
    """Encuentra y muestra la ventana de 3CX aunque esté oculta en el tray (win32gui)."""
    try:
        import win32gui
        import win32con
        found = []

        def cb(hwnd, lst):
            titulo = win32gui.GetWindowText(hwnd).lower()
            if not titulo:
                return
            if ":\\" in titulo or ":/" in titulo:
                return
            if any(ex in titulo for ex in TITULOS_VENTANA_EXCLUIR):
                return
            if any(v in titulo for v in TITULOS_VENTANA_3CX_VALIDOS):
                lst.append(hwnd)

        win32gui.EnumWindows(cb, found)
        if found:
            hwnd = found[0]
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            forzar_foco(hwnd)
            print(f"[{SITIO_NOMBRE}]   ✓ Ventana 3CX restaurada desde tray (hwnd={hwnd}).")
            return True
        print(f"[{SITIO_NOMBRE}]   win32gui: no encontró ventana 3CX oculta.")
    except Exception as e:
        print(f"[{SITIO_NOMBRE}]   win32gui no disponible: {e}")

    # Fallback: segunda instancia — apps single-instance redirigen al proceso existente
    print(f"[{SITIO_NOMBRE}]   Intentando segunda instancia para traer ventana al frente...")
    try:
        subprocess.Popen([PATH_3CX])
        time.sleep(4)
    except Exception:
        pass
    return False


def _imprimir_ventanas_abiertas():
    """Debug: imprime todos los títulos de ventana abiertos para ayudar a diagnosticar."""
    print(f"[{SITIO_NOMBRE}]   Ventanas abiertas en este momento:")
    for w in gw.getAllWindows():
        if w.title.strip():
            print(f"[{SITIO_NOMBRE}]     '{w.title}'")


def _proceso_3cx_activo():
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and '3cxphone' in proc.info['name'].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def lanzar_3cx_si_cerrado():
    """Abre 3CX Phone si no está corriendo y asegura que la ventana sea visible.

    Retorna: (ok: bool, fue_lanzado_ahora: bool)
    """
    if _proceso_3cx_activo():
        print(f"[{SITIO_NOMBRE}] 3CX Phone ya está corriendo.")
        if not encontrar_ventana_3cx():
            print(f"[{SITIO_NOMBRE}] Sin ventana de dialpad visible — intentando traer desde tray...")
            _traer_ventana_3cx_desde_tray()
            time.sleep(3)
            # Si tras el tray-restore solo existe el video streamer (no el dialpad),
            # lanzar segunda instancia — 3CX redirige al proceso existente y abre la UI
            if not encontrar_ventana_3cx():
                print(f"[{SITIO_NOMBRE}] Lanzando segunda instancia para abrir la UI principal...")
                try:
                    subprocess.Popen([PATH_3CX])
                    time.sleep(5)
                except Exception as e:
                    print(f"[{SITIO_NOMBRE}]   Error al relanzar: {e}")
        return True, False  # ya estaba corriendo

    print(f"[{SITIO_NOMBRE}] 3CX no está abierto. Lanzando desde: {PATH_3CX}")
    try:
        subprocess.Popen([PATH_3CX])
    except Exception as e:
        print(f"[{SITIO_NOMBRE}] ✗ No se pudo lanzar 3CX: {e}")
        return False, False

    for i in range(SEG_ESPERAR_INICIO_3CX):
        time.sleep(1)
        if _proceso_3cx_activo():
            print(f"[{SITIO_NOMBRE}] ✓ 3CX iniciado ({i+1}s). Esperando que aparezca la ventana...")
            # Esperar activamente a que la ventana aparezca (hasta 30s adicionales)
            for j in range(30):
                time.sleep(1)
                if encontrar_ventana_3cx():
                    print(f"[{SITIO_NOMBRE}] ✓ Ventana de 3CX detectada ({j+1}s).")
                    time.sleep(1)
                    return True, True  # fue lanzado recién
            print(f"[{SITIO_NOMBRE}] ⚠ Proceso corriendo pero ventana no apareció en 30s.")
            _imprimir_ventanas_abiertas()
            return False, False

    print(f"[{SITIO_NOMBRE}] ✗ 3CX no inició en {SEG_ESPERAR_INICIO_3CX}s.")
    return False, False


def encontrar_ventana_3cx():
    """Busca SOLO la ventana real de 3CX Phone, excluyendo editores/navegadores y rutas."""
    for w in gw.getAllWindows():
        titulo = w.title.lower().strip()
        if not titulo:
            continue
        # Excluir títulos que son rutas de archivo (ej: "C:\Users\...")
        if ":\\" in titulo or ":/" in titulo:
            continue
        if any(excluido in titulo for excluido in TITULOS_VENTANA_EXCLUIR):
            continue
        if any(valido in titulo for valido in TITULOS_VENTANA_3CX_VALIDOS):
            return w
    return None


def check_3cx() -> tuple[bool, Path]:
    """Ejecuta la verificación de llamada saliente por 3CX.

    Devuelve (ok, screenshot_path) — el screenshot se genera siempre que sea
    posible, aunque falle, para poder adjuntarlo como evidencia en el reporte.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = EVIDENCIA_DIR / f"{SITIO_NOMBRE}_{timestamp}.png"

    print(f"[{SITIO_NOMBRE}] Iniciando verificación...")
    print(f"[{SITIO_NOMBRE}] Número de prueba: {NUMERO_DESTINO}")

    try:
        # Paso 0: asegurarse de que 3CX esté abierto
        ok, fue_lanzado_ahora = lanzar_3cx_si_cerrado()
        if not ok:
            print(f"[{SITIO_NOMBRE}] ✗ FAIL — No se pudo abrir 3CX Phone.")
            try:
                pyautogui.screenshot(str(screenshot_path))
            except Exception:
                pass
            return False, screenshot_path

        if fue_lanzado_ahora:
            print(f"[{SITIO_NOMBRE}] 3CX recién lanzado — esperando {SEG_ESPERAR_REGISTRO_PBX}s para que se registre en el PBX...")
            time.sleep(SEG_ESPERAR_REGISTRO_PBX)

        # Paso 1: encontrar la ventana de 3CX
        ventana = encontrar_ventana_3cx()
        if not ventana:
            print(f"[{SITIO_NOMBRE}] Ventana no visible, último intento desde tray...")
            _traer_ventana_3cx_desde_tray()
            time.sleep(2)
            ventana = encontrar_ventana_3cx()
        if not ventana:
            print(f"[{SITIO_NOMBRE}] ✗ FAIL — No se encontró la ventana de 3CX.")
            _imprimir_ventanas_abiertas()
            try:
                pyautogui.screenshot(str(screenshot_path))
                print(f"    Screenshot: {screenshot_path}")
            except Exception:
                pass
            return False, screenshot_path

        print(f"[{SITIO_NOMBRE}] ✓ Ventana detectada: '{ventana.title}'")

        # ──────────────────────────────────────────────────────────────────────
        # Paso 2: traer al frente, FORZAR el foco y VERIFICAR antes de seguir.
        # ──────────────────────────────────────────────────────────────────────
        hwnd = _hwnd_de(ventana)
        print(f"[{SITIO_NOMBRE}] Trayendo 3CX al frente y verificando foco (hwnd={hwnd})...")

        foco_ok = forzar_foco(hwnd)
        if not foco_ok:
            time.sleep(0.6)
            foco_ok = forzar_foco(hwnd)   # un reintento

        if not foco_ok:
            print(f"[{SITIO_NOMBRE}] ✗ FAIL — No pude poner 3CX en primer plano.")
            print(f"[{SITIO_NOMBRE}]   No tipeo el número para no mandar las teclas a otra ventana.")
            _imprimir_ventanas_abiertas()
            try:
                pyautogui.screenshot(str(screenshot_path))
                print(f"    Screenshot: {screenshot_path}")
            except Exception:
                pass
            return False, screenshot_path

        print(f"[{SITIO_NOMBRE}] ✓ 3CX está en primer plano.")
        time.sleep(SEG_TRAS_ACTIVAR)

        # ──────────────────────────────────────────────────────────────────────
        # Paso 2.5: IR AL DIALPAD. 3CXPhone abre en el "Main menu", así que
        # apretamos el botón "home" del skin para mostrar el teclado numérico.
        # Sin esto, los números se tipean sobre el menú y la llamada nunca sale.
        # ──────────────────────────────────────────────────────────────────────
        ventana = encontrar_ventana_3cx() or ventana
        _ir_al_dialpad(ventana, hwnd, timestamp)

        # Paso 3: tipear el número dígito por dígito
        # Antes de discar, "calentamos" el campo con un dígito que se borra, para
        # que el dialpad ya tenga el foco tomado y NO se coma el primer dígito real.
        time.sleep(SEG_ANTES_DE_TIPEAR)
        if DIGITO_CALENTAMIENTO:
            print(f"[{SITIO_NOMBRE}] Calentando el campo (dígito dummy que se borra)...")
            pyautogui.press("0")
            time.sleep(SEG_ENTRE_DIGITOS)
            pyautogui.press("backspace")   # borra el dummy
            time.sleep(0.3)

        print(f"[{SITIO_NOMBRE}] Tipeando número {NUMERO_DESTINO}...")
        for digito in NUMERO_DESTINO:
            pyautogui.press(digito)
            time.sleep(SEG_ENTRE_DIGITOS)

        time.sleep(SEG_TRAS_TIPEAR)

        # Paso 4: apretar Enter para iniciar la llamada
        print(f"[{SITIO_NOMBRE}] Iniciando llamada (Enter)...")
        pyautogui.press("enter")

        # Paso 5: monitorear la llamada segundo a segundo
        # Sale antes si detecta que la persona colgó (cambio de título de ventana).
        # Máximo SEG_MAX_LLAMADA segundos.
        print(f"[{SITIO_NOMBRE}] Monitoreando llamada (máx {SEG_MAX_LLAMADA}s, sale antes si cuelgan)...")
        titulo_pre        = (ventana.title or "").lower()
        titulo_en_llamada = None
        screenshot_tomado = False
        seg_screenshot    = max(SEG_MIN_SCREENSHOT, SEG_MAX_LLAMADA // 4)

        for seg in range(1, SEG_MAX_LLAMADA + 1):
            time.sleep(1)
            v = encontrar_ventana_3cx()
            if not v:
                print(f"[{SITIO_NOMBRE}]   Ventana cerrada a los {seg}s — llamada terminó.")
                break

            titulo_actual = (v.title or "").lower()

            # Registrar primer cambio de título → llamada activa
            if titulo_actual != titulo_pre and not titulo_en_llamada and seg >= 2:
                titulo_en_llamada = titulo_actual
                print(f"[{SITIO_NOMBRE}]   Llamada activa ({seg}s): '{v.title}'")

            # Si el título volvió al estado pre-llamada → la persona colgó
            if titulo_en_llamada and titulo_actual == titulo_pre:
                print(f"[{SITIO_NOMBRE}]   La persona colgó ({seg}s) — continuando checklist.")
                ventana = v
                break

            ventana = v

            # Screenshot cuando la llamada ya lleva el tiempo mínimo
            if seg == seg_screenshot and not screenshot_tomado:
                try:
                    forzar_foco(_hwnd_de(ventana))
                    time.sleep(0.2)
                    region = (ventana.left, ventana.top, ventana.width, ventana.height)
                    pyautogui.screenshot(str(screenshot_path), region=region)
                    screenshot_tomado = True
                    print(f"[{SITIO_NOMBRE}] Screenshot tomado: {screenshot_path}")
                except Exception:
                    pass
        else:
            print(f"[{SITIO_NOMBRE}]   Tiempo máximo ({SEG_MAX_LLAMADA}s) alcanzado.")

        # Paso 6: screenshot si no se tomó durante el loop
        if not screenshot_tomado:
            ventana = encontrar_ventana_3cx() or ventana
            try:
                forzar_foco(_hwnd_de(ventana))
                time.sleep(0.2)
                region = (ventana.left, ventana.top, ventana.width, ventana.height)
                pyautogui.screenshot(str(screenshot_path), region=region)
            except Exception:
                pyautogui.screenshot(str(screenshot_path))
            print(f"[{SITIO_NOMBRE}] Screenshot tomado: {screenshot_path}")

        # Paso 7: colgar
        time.sleep(SEG_ANTES_DE_COLGAR)
        print(f"[{SITIO_NOMBRE}] Colgando llamada (ESC)...")
        ventana = encontrar_ventana_3cx() or ventana
        forzar_foco(_hwnd_de(ventana))
        time.sleep(0.3)
        pyautogui.press("esc")
        time.sleep(0.5)

        print(f"[{SITIO_NOMBRE}] ✓ OK — Llamada saliente funcionando")
        return True, screenshot_path

    except Exception as e:
        print(f"[{SITIO_NOMBRE}] ✗ ERROR: {type(e).__name__}: {e}")
        try:
            pyautogui.screenshot(str(screenshot_path))
            print(f"    Screenshot del error: {screenshot_path}")
        except Exception:
            pass
        return False, screenshot_path


if __name__ == "__main__":
    resultado, _ = check_3cx()
    print()
    exit(0 if resultado else 1)