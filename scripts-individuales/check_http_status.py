"""
=============================================================
  CHECK HTTP STATUS — Módulo de verificación de sitios web
  Proyecto: Checklist automatizado Pecom
  Descripción: Verifica el código de respuesta HTTP de cada
               sitio configurado y genera una bitácora diaria
               en formato .log y resumen en .txt
=============================================================
"""

import requests
import datetime
import os
import socket
import urllib.request
import warnings
from pathlib import Path

# Suprimir advertencias de SSL cuando hay proxy corporativo con certificado propio
from urllib3.exceptions import InsecureRequestWarning
warnings.filterwarnings("ignore", category=InsecureRequestWarning)

# ─────────────────────────────────────────────
#  CONFIGURACIÓN — editá esta sección
# ─────────────────────────────────────────────

SITIOS = [
    # (nombre_visible, url)
    ("Invgate Service Desk",    "https://pecom.invgate.net"),
    ("SAP Fiori",               "https://fiori.pecom.com.ar"),
    ("Humand",                  "https://app.humand.com"),
    ("Drive Pecom",             "https://drive.pecom.com.ar"),
    ("Google Drive",            "https://drive.google.com"),
    ("Microsoft 365 Portal",    "https://portal.office.com"),
    ("Azure Portal",            "https://portal.azure.com"),
    # ── Agregá más sitios acá ────────────────
    # ("Mi Sitio",              "https://mi-sitio.com"),
]

# Carpeta donde se guardan los logs (se crea sola si no existe)
CARPETA_LOGS = Path("logs_http")

# Tiempo máximo de espera por sitio en segundos
TIMEOUT_SEG = 15

# Códigos que se consideran "servidor operativo" (aunque pida login o redirija)
#   200-399 : respuesta normal o redirect
#   401,403 : pide autenticación, pero el servidor está vivo
#   500     : error interno, pero respondió (el proceso web funciona)
#   502,503 : gateway/servicio no disponible, pero el servidor respondió
CODIGOS_OPERATIVO = set(range(200, 400)) | {401, 403, 500, 502, 503}

# ─────────────────────────────────────────────
#  DETECCIÓN AUTOMÁTICA DE PROXY CORPORATIVO
# ─────────────────────────────────────────────

def detectar_proxy():
    """
    Intenta detectar el proxy corporativo de varias fuentes:
    1. Variables de entorno (HTTP_PROXY / HTTPS_PROXY)
    2. Configuración del sistema operativo (registro de Windows / PAC)
    3. urllib.request.getproxies() que lee ambas
    """
    try:
        proxies = urllib.request.getproxies()
        # getproxies() puede devolver {'http': '...', 'https': '...', 'ftp': '...'}
        # Filtrar entradas vacías y el entry 'no' (no_proxy)
        proxies_limpios = {k: v for k, v in proxies.items()
                          if k in ("http", "https") and v}
        if proxies_limpios:
            return proxies_limpios
    except Exception:
        pass

    # Fallback: leer del registro de Windows directamente
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            habilitado, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if habilitado:
                servidor, _ = winreg.QueryValueEx(key, "ProxyServer")
                if servidor:
                    if not servidor.startswith("http"):
                        servidor = f"http://{servidor}"
                    return {"http": servidor, "https": servidor}
    except Exception:
        pass

    return None

PROXIES = detectar_proxy()

# ─────────────────────────────────────────────
#  FUNCIONES
# ─────────────────────────────────────────────

def obtener_ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "No disponible"


def verificar_sitio(nombre: str, url: str) -> dict:
    """
    Hace un GET al sitio usando el proxy del sistema si existe.
    verify=False necesario porque el proxy corporativo de Pecom
    presenta su propio certificado SSL (inspección de tráfico).

    Criterio de estado:
      OK          → respuesta 2xx/3xx, sitio funciona normalmente
      ADVERTENCIA → servidor respondió pero con código atípico (401/403/5xx)
                    Esto significa que el servidor ESTÁ OPERATIVO aunque no
                    devuelva contenido (puede requerir login, estar en
                    mantenimiento, etc.)
      ERROR       → no hubo respuesta: CONN_ERROR, TIMEOUT, SSL_ERROR
                    El servidor no es alcanzable.
    """
    resultado = {
        "nombre":   nombre,
        "url":      url,
        "codigo":   None,
        "estado":   None,
        "latencia": None,
        "detalle":  "",
    }
    try:
        inicio = datetime.datetime.now()
        resp = requests.get(
            url,
            timeout=TIMEOUT_SEG,
            allow_redirects=True,
            verify=False,           # Proxy corporativo usa cert propio — OK en red interna
            proxies=PROXIES,        # Usa el proxy que ya tiene configurado Windows
            headers={"User-Agent": "Mozilla/5.0 (ChecklistPecom/2.0)"}
        )
        latencia_ms = int((datetime.datetime.now() - inicio).total_seconds() * 1000)

        resultado["codigo"]   = resp.status_code
        resultado["latencia"] = latencia_ms

        if 200 <= resp.status_code < 300:
            resultado["estado"]  = "OK"
            resultado["detalle"] = f"Respuesta normal ({latencia_ms} ms)"
        elif 300 <= resp.status_code < 400:
            resultado["estado"]  = "OK"
            resultado["detalle"] = f"Redirección → {resp.url[:55]} ({latencia_ms} ms)"
        elif resp.status_code == 401:
            resultado["estado"]  = "OK"
            resultado["detalle"] = f"Requiere login — servidor operativo ({latencia_ms} ms)"
        elif resp.status_code == 403:
            resultado["estado"]  = "OK"
            resultado["detalle"] = f"Acceso restringido — servidor operativo ({latencia_ms} ms)"
        elif resp.status_code in (500, 502, 503):
            resultado["estado"]  = "ADVERTENCIA"
            resultado["detalle"] = (f"{resp.status_code} — servidor respondió pero con error "
                                    f"({latencia_ms} ms)")
        elif resp.status_code == 404:
            resultado["estado"]  = "ADVERTENCIA"
            resultado["detalle"] = f"404 Página no encontrada ({latencia_ms} ms)"
        else:
            resultado["estado"]  = "ADVERTENCIA"
            resultado["detalle"] = f"Código inesperado: {resp.status_code} ({latencia_ms} ms)"

    except requests.exceptions.SSLError as e:
        resultado["estado"]  = "ERROR"
        resultado["codigo"]  = "SSL_ERROR"
        resultado["detalle"] = f"Error SSL: {str(e)[:70]}"
    except requests.exceptions.ConnectionError:
        resultado["estado"]  = "ERROR"
        resultado["codigo"]  = "CONN_ERROR"
        resultado["detalle"] = "No se pudo conectar al servidor"
    except requests.exceptions.Timeout:
        resultado["estado"]  = "ERROR"
        resultado["codigo"]  = "TIMEOUT"
        resultado["detalle"] = f"Sin respuesta en {TIMEOUT_SEG} segundos"
    except Exception as e:
        resultado["estado"]  = "ERROR"
        resultado["codigo"]  = "UNKNOWN"
        resultado["detalle"] = f"Error inesperado: {str(e)[:70]}"

    return resultado


def icono(estado: str) -> str:
    return {"OK": "v", "ADVERTENCIA": "!", "ERROR": "x"}.get(estado, "?")


def correr_verificacion() -> list:
    print("\n" + "=" * 62)
    print("  VERIFICACION HTTP — Checklist Pecom")
    if PROXIES:
        proxy_mostrar = list(PROXIES.values())[0]
        print(f"  Proxy detectado: {proxy_mostrar}")
    else:
        print("  Sin proxy (conexión directa)")
    print("=" * 62)

    resultados = []
    for nombre, url in SITIOS:
        print(f"  -> {nombre} ...", end="", flush=True)
        r = verificar_sitio(nombre, url)
        resultados.append(r)
        print(f"\r  {icono(r['estado'])} [{str(r['codigo']):^10}]  {nombre:<30}  {r['detalle']}")

    return resultados


def generar_resumen(resultados: list) -> str:
    ahora   = datetime.datetime.now()
    ok      = [r for r in resultados if r["estado"] == "OK"]
    adverti = [r for r in resultados if r["estado"] == "ADVERTENCIA"]
    errores = [r for r in resultados if r["estado"] == "ERROR"]

    lineas = []
    lineas.append("=" * 62)
    lineas.append(f"  INFORME DIARIO — ESTADO DE SITIOS WEB")
    lineas.append(f"  Fecha:    {ahora.strftime('%d/%m/%Y')}")
    lineas.append(f"  Hora:     {ahora.strftime('%H:%M:%S')}")
    lineas.append(f"  Equipo:   {socket.gethostname()}  |  IP: {obtener_ip_local()}")
    lineas.append("=" * 62)
    lineas.append("")
    lineas.append(f"  RESUMEN GENERAL")
    lineas.append(f"  {'Total sitios verificados:':<32} {len(resultados)}")
    lineas.append(f"  {'Operativos (OK):':<32} {len(ok)}")
    lineas.append(f"  {'Advertencias (responde con error):':<32} {len(adverti)}")
    lineas.append(f"  {'Sin conexión (ERROR):':<32} {len(errores)}")
    lineas.append("")
    lineas.append("-" * 62)
    lineas.append(f"  {'SITIO':<30} {'CODIGO':^10}  DETALLE")
    lineas.append("-" * 62)

    for r in resultados:
        lineas.append(
            f"  {icono(r['estado'])} {r['nombre']:<29} "
            f"{str(r['codigo']):^10}  {r['detalle']}"
        )

    if errores:
        lineas.append("")
        lineas.append("-" * 62)
        lineas.append("  SITIOS INALCANZABLES — Requieren atención")
        lineas.append("-" * 62)
        for r in errores:
            lineas.append(f"    * {r['nombre']}")
            lineas.append(f"      URL:    {r['url']}")
            lineas.append(f"      Codigo: {r['codigo']}")
            lineas.append(f"      Motivo: {r['detalle']}")
            lineas.append("")

    if adverti:
        lineas.append("")
        lineas.append("-" * 62)
        lineas.append("  SITIOS CON ADVERTENCIA — Responden pero con código atípico")
        lineas.append("-" * 62)
        for r in adverti:
            lineas.append(f"    ! {r['nombre']}")
            lineas.append(f"      URL:    {r['url']}")
            lineas.append(f"      Codigo: {r['codigo']}")
            lineas.append(f"      Motivo: {r['detalle']}")
            lineas.append("")

    lineas.append("=" * 62)
    lineas.append(f"  Fin del informe — {ahora.strftime('%d/%m/%Y %H:%M:%S')}")
    lineas.append("=" * 62)

    return "\n".join(lineas)


def guardar_log(resumen: str, resultados: list):
    CARPETA_LOGS.mkdir(exist_ok=True)
    fecha_str = datetime.datetime.now().strftime("%Y%m%d")
    hora_str  = datetime.datetime.now().strftime("%H:%M:%S")

    # Bitácora acumulativa del día
    log_path = CARPETA_LOGS / f"checklist_{fecha_str}.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n[{hora_str}] === CORRIDA DE VERIFICACION ===\n")
        for r in resultados:
            f.write(
                f"[{hora_str}] {icono(r['estado'])} "
                f"{r['nombre']:<30} | codigo={str(r['codigo']):^10} | "
                f"{r['detalle']}\n"
            )
        ok_n  = sum(1 for r in resultados if r["estado"] == "OK")
        war_n = sum(1 for r in resultados if r["estado"] == "ADVERTENCIA")
        err_n = sum(1 for r in resultados if r["estado"] == "ERROR")
        f.write(f"[{hora_str}] TOTALES -> OK={ok_n} | WARN={war_n} | ERR={err_n}\n")
        f.write("-" * 62 + "\n")

    # Resumen limpio del día (sobreescribe con la última corrida)
    resumen_path = CARPETA_LOGS / f"resumen_{fecha_str}.txt"
    with open(resumen_path, "w", encoding="utf-8") as f:
        f.write(resumen)

    print(f"\n  Bitácora:  {log_path}")
    print(f"  Resumen:   {resumen_path}")


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    resultados = correr_verificacion()
    resumen    = generar_resumen(resultados)

    print("\n")
    print(resumen)

    guardar_log(resumen, resultados)

    errores = [r for r in resultados if r["estado"] == "ERROR"]
    exit(1 if errores else 0)