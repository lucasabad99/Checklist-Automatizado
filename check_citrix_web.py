"""
descubrir_citrix.py
Mini-script de descubrimiento para el modulo de Citrix apps.
Abre el portal, saca screenshot, imprime titulos de todas las apps
disponibles para el usuario logueado.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).parent
EDGE_PROFILE_DIR = os.getenv(
    "EDGE_PROFILE_DIR",
    str(BASE_DIR / "edge_profile")
)
CITRIX_URL = "https://citrix.pecomenergia.com.ar/"


def log(msg: str) -> None:
    print(msg, flush=True)


def descubrir():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log("")
    log("=" * 60)
    log(f"Descubrimiento Citrix - {timestamp}")
    log(f"Portal: {CITRIX_URL}")
    log(f"Perfil Edge: {EDGE_PROFILE_DIR}")
    log("=" * 60)
    log("")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            EDGE_PROFILE_DIR,
            channel="msedge",
            headless=False,  # queremos verlo
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(60_000)

        log(f"Abriendo {CITRIX_URL}...")
        page.goto(CITRIX_URL, wait_until="domcontentloaded")
        log(f"Titulo inicial de la pagina: {page.title()}")
        log(f"URL actual: {page.url}")
        log("")

        log("Esperando 10 segundos por si redirige a login o carga StoreFront...")
        page.wait_for_timeout(10_000)

        log(f"URL despues de esperar: {page.url}")
        log(f"Titulo despues de esperar: {page.title()}")
        log("")

        # Screenshot inicial
        path_ss = BASE_DIR / f"descubrir_citrix_{timestamp}_inicial.png"
        page.screenshot(path=str(path_ss), full_page=True)
        log(f"Screenshot guardado en: {path_ss}")
        log("")

        # Intentamos detectar elementos de StoreFront/Workspace
        log("Buscando elementos comunes de Citrix StoreFront:")
        log("-" * 60)

        # Los distintos selectores que puede tener Citrix segun la version
        candidatos = [
            ("Titulos de aplicaciones (workspace)", "[data-testid*='app']"),
            ("Botones de app (viejo storefront)", ".storeapp-name"),
            ("Nombres de app (nuevo Workspace)", ".appName"),
            ("Iconos de escritorios virtuales", "[data-testid*='desktop']"),
            ("Cualquier link/boton clickeable", "a, button"),
        ]

        for etiqueta, selector in candidatos:
            try:
                elementos = page.query_selector_all(selector)
                if elementos:
                    log(f"\n>>> {etiqueta}: {len(elementos)} encontrados con selector '{selector}'")
                    # Mostramos los primeros 15 con texto
                    mostrados = 0
                    for el in elementos:
                        try:
                            texto = el.inner_text().strip()
                            if texto and len(texto) < 100:
                                log(f"     - {texto!r}")
                                mostrados += 1
                                if mostrados >= 15:
                                    log(f"     ... y {len(elementos) - 15} mas")
                                    break
                        except Exception:
                            continue
            except Exception as e:
                log(f"     ERROR con '{selector}': {e}")

        log("")
        log("-" * 60)
        log("Investigacion terminada.")
        log("Miralo bien en el browser antes de cerrar - ¿ves el StoreFront con las apps?")
        log("Presiona Enter en la consola cuando quieras cerrar.")
        input()

        context.close()


if __name__ == "__main__":
    descubrir()