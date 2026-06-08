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

# Códigos que se consideran "OK"
CODIGOS_OK = {200, 201, 202, 301, 302, 304}

# ─────────────────────────────────────────────
#  DETECCIÓN AUTOMÁTICA DE PROXY CORPORATIVO
#  Lee la config de proxy que ya usa Windows/Edge
# ─────────────────────────────────────────────

def detectar_proxy():
    """
    Lee el proxy del sistema operativo (el mismo que usa Edge y Chrome).
    Si Pecom tiene proxy configurado vía GPO o PAC, lo detecta automáticamente.
    """
    try:
        proxies = urllib.request.getproxies()
        if proxies:
            return proxies
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
    presenta su propio certificado SSL (inspeccion de trafico).
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

        if resp.status_code in CODIGOS_OK:
            resultado["estado"]  = "OK"
            resultado["detalle"] = f"Respuesta normal ({latencia_ms} ms)"
        elif 300 <= resp.status_code < 400:
            resultado["estado"]  = "OK"
            resultado["detalle"] = f"Redireccion {resp.status_code} -> {resp.url[:55]}"
        elif resp.status_code == 401:
            resultado["estado"]  = "ADVERTENCIA"
            resultado["detalle"] = "401 No autorizado — login requerido (sitio activo)"
        elif resp.status_code == 403:
            resultado["estado"]  = "ADVERTENCIA"
            resultado["detalle"] = "403 Prohibido — acceso denegado (sitio activo)"
        elif resp.status_code == 404:
            resultado["estado"]  = "ERROR"
            resultado["detalle"] = "404 No encontrado"
        elif resp.status_code == 500:
            resultado["estado"]  = "ERROR"
            resultado["detalle"] = "500 Error interno del servidor"
        elif resp.status_code == 503:
            resultado["estado"]  = "ERROR"
            resultado["detalle"] = "503 Servicio no disponible"
        else:
            resultado["estado"]  = "ADVERTENCIA"
            resultado["detalle"] = f"Codigo inesperado: {resp.status_code}"

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
        proxy_str = list(PROXIES.values())[0]
        print(f"  Proxy detectado: {proxy_str}")
    else:
        print("  Sin proxy (conexion directa)")
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
    lineas.append(f"  {'OK:':<32} {len(ok)}")
    lineas.append(f"  {'Advertencias:':<32} {len(adverti)}")
    lineas.append(f"  {'Errores:':<32} {len(errores)}")
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
        lineas.append("  SITIOS CON ERRORES — Requieren atencion")
        lineas.append("-" * 62)
        for r in errores:
            lineas.append(f"    * {r['nombre']}")
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

    # Bitacora acumulativa del dia
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

    # Resumen limpio del dia (sobreescribe con la ultima corrida)
    resumen_path = CARPETA_LOGS / f"resumen_{fecha_str}.txt"
    with open(resumen_path, "w", encoding="utf-8") as f:
        f.write(resumen)

    print(f"\n  Bitacora:  {log_path}")
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