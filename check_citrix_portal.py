"""
Verifica el acceso al PORTAL de Citrix de Pecom (login) y guarda una evidencia
(screenshot) de que cargó correctamente.

A diferencia de check_citrix.py (que además abre el ícono "Remote Desktop
Connection", descarga el .ica, resuelve el prompt de Windows Security y entra
al escritorio remoto), este script CORTA después del login al portal: solo
entra, confirma que el portal está accesible y saca la captura. Pensado para
dejar la prueba de "Remote Desktop" en manos de otra persona (ej. el jefe
probándolo él mismo) sin que el automatismo la dispare.

Pre-requisitos:
    pip install playwright python-dotenv
    playwright install msedge

    .env con:
        CITRIX_URL=https://citrix.pecomenergia.com.ar
        CITRIX_USER=ARGENTINA\\tu_usuario
        CITRIX_PASS=tu_password

Uso:
    python check_citrix_portal.py
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

# ============ CONFIGURACIÓN ============
SITIO_NOMBRE = "Citrix-Portal"
URL          = os.getenv("CITRIX_URL", "https://citrix.pecomenergia.com.ar")
USUARIO      = os.getenv("CITRIX_USER")
PASSWORD     = os.getenv("CITRIX_PASS")

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

TIMEOUT_MS           = 30000
TIMEOUT_DETECCION_MS = 10000
TIMEOUT_PORTAL_MS    = 20000
POLL_INTERVAL_MS     = 200

# Reutiliza el mismo perfil de Edge que check_citrix.py, así la sesión
# guardada (cookies / MFA recordado) sirve para los dos scripts.
PROFILE_DIR   = Path(__file__).parent / "edge_profile_citrix"
# Evidencias separadas para no mezclarlas con las de la corrida completa.
EVIDENCIA_DIR = Path(__file__).parent / "evidencias_citrix_portal"
EVIDENCIA_DIR.mkdir(exist_ok=True)
# =======================================


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


def check_citrix_portal():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_portal = EVIDENCIA_DIR / f"{SITIO_NOMBRE}_{timestamp}.png"

    if not USUARIO or not PASSWORD:
        print(f"[{SITIO_NOMBRE}] ✗ FAIL — Faltan credenciales en .env")
        return False

    print(f"[{SITIO_NOMBRE}] Verificando acceso al portal Citrix...")
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
            locale="es-AR",
        )
        pagina = contexto.new_page()

        try:
            print(f"[{SITIO_NOMBRE}] [1/2] Navegando al portal...")
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

            # ===== [2/2] Evidencia — y CORTE (no se abre Remote Desktop) =====
            # Espera fija de 5s con el portal ya cargado, para que se alcance a
            # ver en pantalla antes de la captura (antes eran 1.5s y quedaba
            # muy fugaz, entraba y cerraba casi de inmediato).
            pagina.wait_for_timeout(5000)
            pagina.screenshot(path=str(screenshot_portal), full_page=True)
            print(f"[{SITIO_NOMBRE}]   Screenshot: {screenshot_portal.name}")

            print()
            print(f"[{SITIO_NOMBRE}] ✓ OK ({time.time()-t0:.1f}s) — Portal Citrix accesible")
            print(f"[{SITIO_NOMBRE}] >> Corte acá: no se abre Remote Desktop Connection.")
            return True

        except Exception as e:
            print(f"[{SITIO_NOMBRE}] ✗ ERROR: {type(e).__name__}: {e}")
            return False

        finally:
            contexto.close()


if __name__ == "__main__":
    resultado = check_citrix_portal()
    print()
    sys.exit(0 if resultado else 1)
