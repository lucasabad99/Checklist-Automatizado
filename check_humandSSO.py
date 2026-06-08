"""
Verifica el acceso SSO a Humand usando Playwright + perfil dedicado de Edge.

Cómo funciona:
- Usa un perfil de Edge propio del script (guardado en ./edge_profile_check).
- La PRIMERA vez que lo corras, vas a tener que loguearte con SSO manualmente
  (incluyendo MFA si corresponde). Después la sesión queda guardada y los
  próximos días entra solo.
- Verifica que llegue a una URL/elemento esperado post-login.
- Espera a que el feed termine de renderizar (no solo que terminen los redirects).
- Saca un screenshot como evidencia.

Requisitos:
    pip install playwright
    playwright install msedge

Uso:
    python check_humandSSO.py
"""

from playwright.sync_api import sync_playwright
from pathlib import Path
from datetime import datetime

# ============ CONFIGURACIÓN ============
SITIO_NOMBRE   = "Humand"
URL            = "https://app.humand.co/feed"

# Después del SSO, ¿qué tiene que aparecer para considerar "OK"?
URL_ESPERADA_CONTIENE = "humand.co/feed"   # la URL final debe contener esto

# Selector / texto que aparece solo cuando el feed ya cargó (no durante el splash).
SELECTOR_FEED_LISTO = [
    "text=Novedades",       # título principal del feed
    "text=Comunicados",     # ítem del sidebar
    "text=Grupos",          # ítem del sidebar
]

TIMEOUT_MS            = 30000   # 30 seg para que cargue todo
TIMEOUT_FEED_MS       = 20000   # 20 seg adicionales esperando el feed

# Carpeta donde se guarda el perfil de Edge (queda logueado entre ejecuciones)
PROFILE_DIR = Path(__file__).parent / "edge_profile_check"

# Carpeta de evidencias (screenshots)
EVIDENCIA_DIR = Path(__file__).parent / "evidencias"
EVIDENCIA_DIR.mkdir(exist_ok=True)
# =======================================


def check_sso():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = EVIDENCIA_DIR / f"{SITIO_NOMBRE}_{timestamp}.png"

    with sync_playwright() as p:
        print(f"[{SITIO_NOMBRE}] Abriendo Edge con perfil dedicado...")
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="msedge",
            headless=False,
            args=["--start-maximized"],
        )

        pagina = contexto.new_page()

        try:
            print(f"[{SITIO_NOMBRE}] Navegando a {URL}")
            pagina.goto(URL, timeout=TIMEOUT_MS, wait_until="domcontentloaded")

            # Esperar a que el SSO termine de hacer sus redirects
            print(f"[{SITIO_NOMBRE}] Esperando redirects de SSO...")
            pagina.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)

            url_final = pagina.url
            print(f"[{SITIO_NOMBRE}] URL final: {url_final}")

            # Verificación 1: la URL final debe contener lo esperado
            if URL_ESPERADA_CONTIENE not in url_final:
                print(f"[{SITIO_NOMBRE}] ✗ FAIL — La URL final no contiene "
                      f"'{URL_ESPERADA_CONTIENE}'. Probablemente quedó en login.")
                pagina.screenshot(path=str(screenshot_path), full_page=True)
                print(f"    Screenshot: {screenshot_path}")
                return False

            # Verificación 2: esperar a que el feed termine de renderizar
            print(f"[{SITIO_NOMBRE}] Esperando que el feed renderice...")
            feed_listo = False
            for selector in SELECTOR_FEED_LISTO:
                try:
                    pagina.locator(selector).first.wait_for(
                        state="visible",
                        timeout=TIMEOUT_FEED_MS,
                    )
                    print(f"[{SITIO_NOMBRE}]   ✓ Detectado '{selector}'")
                    feed_listo = True
                    break
                except Exception:
                    print(f"[{SITIO_NOMBRE}]   - No apareció '{selector}', probando siguiente...")
                    continue

            if not feed_listo:
                print(f"[{SITIO_NOMBRE}] ✗ FAIL — El feed no terminó de cargar "
                      f"(se quedó en el loader 'hu' o similar)")
                pagina.screenshot(path=str(screenshot_path), full_page=True)
                print(f"    Screenshot: {screenshot_path}")
                return False

            # Pequeño margen extra para que terminen de pintar los componentes
            pagina.wait_for_timeout(4000)

            # Si llegó hasta acá, todo OK
            pagina.screenshot(path=str(screenshot_path), full_page=True)
            print(f"[{SITIO_NOMBRE}] ✓ OK — Acceso SSO funcionando")
            print(f"    Screenshot: {screenshot_path}")
            return True

        except Exception as e:
            print(f"[{SITIO_NOMBRE}] ✗ ERROR: {type(e).__name__}: {e}")
            try:
                pagina.screenshot(path=str(screenshot_path), full_page=True)
                print(f"    Screenshot del error: {screenshot_path}")
            except:
                pass
            return False

        finally:
            contexto.close()


if __name__ == "__main__":
    resultado = check_sso()
    exit(0 if resultado else 1)