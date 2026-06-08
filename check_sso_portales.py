"""
Verifica el acceso a los dos portales internos de Pecom.

    - Facilities : https://facilities.pecomenergia.com.ar  (login directo user/pass)
    - Compras    : https://compras.pecomenergia.com.ar      (SSO Microsoft)

Flujo por portal (contexto de Edge independiente):
    1. Abre Edge con perfil dedicado y navega al login.
    2. Facilities: llena usuario + password + click "Ingresar".
       Compras:    click SSO → selecciona cuenta Pecom → login Microsoft si hace falta.
    3. Verifica que el dashboard cargó (título o URL post-login).
    4. Screenshot de evidencia en evidencias_sso_portales/.
    5. Cierra ese contexto y abre el siguiente portal.

Pre-requisitos:
    pip install playwright python-dotenv pillow
    playwright install msedge

    .env con:
        FACILITIES_USER=LEABADC
        FACILITIES_PASS='tu_password'
        SSO_USER=Lucas.Abad@pecomenergia.com.ar
        SSO_PASS='tu_password_microsoft'

Uso:
    python check_sso_portales.py
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

load_dotenv()

# ============ CONFIGURACIÓN ============
SITIO_NOMBRE = "SSO-Portales"

# Facilities — login directo
FACILITIES_USER = os.getenv("FACILITIES_USER", "")
FACILITIES_PASS = os.getenv("FACILITIES_PASS", "")

# Compras — SSO Microsoft
SSO_USER = os.getenv("SSO_USER", "")
SSO_PASS = os.getenv("SSO_PASS", "")

PORTALES = [
    {
        "nombre":     "Facilities",
        "url":        "https://facilities.pecomenergia.com.ar/auth/login",
        "tipo":       "directo",      # login con user/pass propio
        "titulo_ok":  "facilities",
        "url_ok":     "facilities.pecomenergia.com.ar",
    },
    {
        "nombre":     "Compras",
        "url":        "https://compras.pecomenergia.com.ar/auth/login",
        "tipo":       "sso",          # login via SSO Microsoft
        "titulo_ok":  "compras",
        "url_ok":     "compras.pecomenergia.com.ar",
    },
]

# Botón SSO en Compras
SELECTORES_BTN_SSO = [
    "button:has-text('Iniciar sesión')",
    "a:has-text('Iniciar sesión')",
    "button:has-text('Microsoft')",
    "[class*='sso']",
]

# Campos Microsoft
SEL_MS_USER = "input[type='email'], input[name='loginfmt']"
SEL_MS_PASS = "input[type='password'], input[name='passwd']"
SEL_MS_NEXT = "input[type='submit'], button[type='submit']"

# Elementos que confirman dashboard cargado (fallback al título)
SELECTORES_DASHBOARD = [
    "[class*='layout--loaded']",
    "[class*='dashboard']",
    "[class*='home']",
    "nav",
    "header",
]

TIMEOUT_MS           = 30_000
TIMEOUT_DASHBOARD_MS = 25_000
POLL_MS              = 300

PROFILE_DIR   = Path(__file__).parent / "edge_profile_sso_portales"
EVIDENCIA_DIR = Path(__file__).parent / "evidencias_sso_portales"
EVIDENCIA_DIR.mkdir(exist_ok=True)
# =======================================


def _log(portal, msg):
    print(f"[{SITIO_NOMBRE}][{portal}] {msg}")


def _esperar_dashboard(pagina, portal, timeout_ms):
    """Espera a que cargue el dashboard. Devuelve descripción del criterio o None."""
    titulo_ok = portal["titulo_ok"].lower()
    url_ok    = portal["url_ok"].lower()
    inicio    = time.time()

    while (time.time() - inicio) * 1000 < timeout_ms:
        try:
            titulo = (pagina.title() or "").lower()
            url    = pagina.url.lower()

            if titulo_ok and titulo_ok in titulo:
                return f"título: '{pagina.title()}'"

            if url_ok in url and "/auth/" not in url:
                for sel in SELECTORES_DASHBOARD:
                    try:
                        if pagina.locator(sel).first.is_visible():
                            return f"url+layout"
                    except Exception:
                        continue
        except Exception:
            pass
        pagina.wait_for_timeout(POLL_MS)

    return None


def _login_directo(pagina, nombre):
    """Login directo con usuario y password (Facilities)."""
    _log(nombre, "  Completando login directo (usuario + password)...")
    try:
        # Campo usuario — busca input de texto visible
        sel_user = "input[type='text'], input[name='username'], input[name='user'], input:not([type='password'])"
        pagina.wait_for_selector(sel_user, timeout=6000)
        pagina.locator(sel_user).first.fill(FACILITIES_USER)

        # Campo password
        pagina.locator("input[type='password']").first.fill(FACILITIES_PASS)

        # Botón Ingresar
        for sel in ["button:has-text('Ingresar')", "input[type='submit']", "button[type='submit']"]:
            try:
                elem = pagina.locator(sel).first
                if elem.count() and elem.is_visible():
                    elem.click()
                    _log(nombre, f"  Click en '{sel}'")
                    break
            except Exception:
                continue

        pagina.wait_for_timeout(1500)

    except Exception as e:
        _log(nombre, f"  ⚠ Error en login directo: {e}")


def _seleccionar_cuenta_microsoft(pagina, nombre):
    """Si aparece 'Selección de la cuenta', elige la de Pecom."""
    try:
        pagina.wait_for_selector("text=Selección de la cuenta", timeout=6000)
        _log(nombre, "  Pantalla de selección de cuenta — eligiendo Pecom...")
        dominio = SSO_USER.split("@")[-1]
        try:
            pagina.get_by_text(SSO_USER, exact=False).first.click(timeout=4000)
            _log(nombre, f"  ✓ Cuenta seleccionada: {SSO_USER}")
        except Exception:
            pagina.get_by_text(dominio, exact=False).first.click(timeout=4000)
            _log(nombre, f"  ✓ Cuenta seleccionada (dominio: {dominio})")
        pagina.wait_for_timeout(2000)
    except PWTimeout:
        pass


def _login_microsoft_si_pide(pagina, nombre):
    """Completa usuario + password de Microsoft si no hay sesión cacheada."""
    try:
        pagina.wait_for_selector(SEL_MS_USER, timeout=5000)
        _log(nombre, "  Prompt Microsoft — completando login...")
        pagina.locator(SEL_MS_USER).first.fill(SSO_USER)
        pagina.locator(SEL_MS_NEXT).first.click()
        pagina.wait_for_timeout(1500)

        pagina.wait_for_selector(SEL_MS_PASS, timeout=8000)
        pagina.locator(SEL_MS_PASS).first.fill(SSO_PASS)
        pagina.locator(SEL_MS_NEXT).first.click()
        pagina.wait_for_timeout(1500)

        try:
            pagina.wait_for_selector("input[type='submit']", timeout=5000)
            pagina.locator("input[type='submit']").first.click()
        except PWTimeout:
            pass

    except PWTimeout:
        _log(nombre, "  (sin prompt Microsoft — sesión cacheada)")


def verificar_portal(portal, timestamp, playwright):
    """Abre Edge, verifica el portal y cierra. Devuelve True/False."""
    nombre  = portal["nombre"]
    tipo    = portal["tipo"]
    t0      = time.time()
    path_ss = EVIDENCIA_DIR / f"SSO_{nombre}_{timestamp}.png"
    perfil  = PROFILE_DIR / nombre.lower()
    perfil.mkdir(parents=True, exist_ok=True)

    print()
    print(f"{'─'*55}")
    _log(nombre, f"Iniciando  [{tipo.upper()}]  →  {portal['url']}")
    print(f"{'─'*55}")

    contexto = playwright.chromium.launch_persistent_context(
        user_data_dir=str(perfil),
        channel="msedge",
        headless=False,
        args=["--start-maximized", "--disable-features=Translate", "--lang=es"],
        locale="es-AR",
    )
    pagina = contexto.new_page()
    ok = False

    try:
        # ── 1. Navegar ────────────────────────────────────────────────────────
        pagina.goto(portal["url"], timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        pagina.wait_for_timeout(1500)

        # ¿Ya está en el dashboard? (sesión cacheada)
        resultado = _esperar_dashboard(pagina, portal, 3000)
        if resultado:
            _log(nombre, f"  Sesión cacheada — ya en dashboard ({resultado})")
            pagina.screenshot(path=str(path_ss), full_page=False)
            _log(nombre, f"✓ OK ({time.time()-t0:.1f}s) — {path_ss.name}")
            return True

        # ── 2. Login según tipo ───────────────────────────────────────────────
        if tipo == "directo":
            _login_directo(pagina, nombre)

        elif tipo == "sso":
            # Click en botón SSO
            btn = None
            for sel in SELECTORES_BTN_SSO:
                try:
                    elem = pagina.locator(sel).first
                    if elem.count() and elem.is_visible():
                        elem.click()
                        btn = sel
                        _log(nombre, f"  Click en botón SSO ({sel})")
                        break
                except Exception:
                    continue
            if not btn:
                _log(nombre, "✗ FAIL — No se encontró el botón SSO.")
                pagina.screenshot(path=str(path_ss))
                return False

            pagina.wait_for_timeout(1500)
            _seleccionar_cuenta_microsoft(pagina, nombre)
            _login_microsoft_si_pide(pagina, nombre)

        # ── 3. Esperar dashboard ──────────────────────────────────────────────
        resultado = _esperar_dashboard(pagina, portal, TIMEOUT_DASHBOARD_MS)
        if not resultado:
            _log(nombre, f"✗ FAIL — Dashboard no cargó en {TIMEOUT_DASHBOARD_MS//1000}s "
                         f"(título: '{pagina.title()}')")
            pagina.screenshot(path=str(path_ss))
            _log(nombre, f"  Screenshot: {path_ss.name}")
            return False

        # ── 4. Screenshot de evidencia ────────────────────────────────────────
        _log(nombre, f"  ({time.time()-t0:.1f}s) ✓ Dashboard OK — {resultado}")
        pagina.wait_for_timeout(800)
        pagina.screenshot(path=str(path_ss), full_page=False)
        _log(nombre, f"✓ OK ({time.time()-t0:.1f}s) — Screenshot: {path_ss.name}")
        ok = True

    except Exception as e:
        _log(nombre, f"✗ ERROR: {type(e).__name__}: {e}")
        try:
            pagina.screenshot(path=str(path_ss))
        except Exception:
            pass

    finally:
        contexto.close()
        _log(nombre, "  Edge cerrado.")

    return ok


def check_sso_portales():
    # Validar credenciales
    faltantes = []
    if not FACILITIES_USER or not FACILITIES_PASS:
        faltantes.append("FACILITIES_USER / FACILITIES_PASS")
    if not SSO_USER or not SSO_PASS:
        faltantes.append("SSO_USER / SSO_PASS")
    if faltantes:
        print(f"[{SITIO_NOMBRE}] ✗ FAIL — Faltan en el .env: {', '.join(faltantes)}")
        return False

    print(f"[{SITIO_NOMBRE}] Verificando {len(PORTALES)} portales...")
    print(f"[{SITIO_NOMBRE}] Facilities user : {FACILITIES_USER}")
    print(f"[{SITIO_NOMBRE}] SSO user        : {SSO_USER}")

    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    resultados = {}
    t_global   = time.time()

    with sync_playwright() as p:
        for portal in PORTALES:
            resultados[portal["nombre"]] = verificar_portal(portal, timestamp, p)

    # ── Resumen ────────────────────────────────────────────────────────────────
    ok_total = sum(1 for v in resultados.values() if v)
    total    = len(resultados)
    print()
    print("=" * 55)
    print(f"[{SITIO_NOMBRE}] RESUMEN ({time.time()-t_global:.0f}s) — {ok_total}/{total} portales OK")
    print("=" * 55)
    for nombre, ok in resultados.items():
        print(f"  {'✓' if ok else '✗'}  {nombre}")
    print("=" * 55)
    print()

    return ok_total == total


if __name__ == "__main__":
    resultado = check_sso_portales()
    sys.exit(0 if resultado else 1)