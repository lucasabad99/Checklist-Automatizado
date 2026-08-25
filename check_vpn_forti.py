"""
descubrir_vpn.py
Mini-script de descubrimiento para el modulo de VPN Forticlient.
Nos dice: procesos Forti corriendo, si responde ping/TCP a hosts internos,
que IP local tenemos.

Uso:
    python descubrir_vpn.py
"""
import socket
import subprocess
import sys
from datetime import datetime


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# 1) Procesos Fortinet corriendo
# ---------------------------------------------------------------------------
def descubrir_procesos_forti() -> None:
    log("")
    log("=" * 60)
    log("1) PROCESOS FORTINET CORRIENDO")
    log("=" * 60)

    try:
        import psutil
    except ImportError:
        log("ERROR: psutil no instalado. Instalar con: pip install psutil")
        return

    encontrados = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            nombre = proc.info["name"] or ""
            if "forti" in nombre.lower():
                encontrados.append((proc.info["pid"], nombre))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if encontrados:
        log(f"Encontrados {len(encontrados)} procesos Fortinet:")
        for pid, nombre in encontrados:
            log(f"   - PID {pid}: {nombre}")
    else:
        log("NO se encontraron procesos con 'forti' en el nombre.")
        log("Probable que la VPN no este corriendo, o el proceso tenga otro nombre.")


# ---------------------------------------------------------------------------
# 2) Ping a hosts internos
# ---------------------------------------------------------------------------
def ping_host(host: str, timeout_ms: int = 3000) -> tuple[bool, str]:
    """Hace un ping (1 paquete) usando el ping de Windows. Retorna (ok, salida)."""
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), host],
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000 + 2,
            encoding="cp850",  # Windows CMD suele usar esta codificacion
            errors="replace",
        )
        # "TTL=" aparece si el ping fue exitoso
        ok = "TTL=" in result.stdout or "ttl=" in result.stdout
        return ok, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT en subprocess"
    except Exception as e:
        return False, f"ERROR: {e}"


def descubrir_pings() -> None:
    log("")
    log("=" * 60)
    log("2) PING A HOSTS INTERNOS")
    log("=" * 60)

    hosts = [
        ("SAP Server (mensajes)",     "laerpprd.argentina.org"),
        ("WhatsUp Gold",              "monitoreo.pecomenergia.com.ar"),
        ("Helpdesk (referencia)",     "helpdesk.pecomenergia.com.ar"),
    ]

    for etiqueta, host in hosts:
        log(f"\n   Ping a {etiqueta} ({host})...")
        ok, salida = ping_host(host)
        estado = "OK - responde" if ok else "NO responde"
        log(f"   Resultado: {estado}")
        # Mostramos solo la primera linea util
        for linea in salida.split("\n"):
            l = linea.strip()
            if l and ("bytes" in l.lower() or "tiempo" in l.lower() or "ttl" in l.lower()
                     or "no se puede" in l.lower() or "host de destino" in l.lower()
                     or "tiempo de espera" in l.lower()):
                log(f"      > {l}")
                break


# ---------------------------------------------------------------------------
# 3) TCP connect a puertos conocidos
# ---------------------------------------------------------------------------
def tcp_connect(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    """Intenta un TCP connect al host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "conecta"
    except socket.timeout:
        return False, "timeout"
    except socket.gaierror as e:
        return False, f"DNS falla: {e}"
    except ConnectionRefusedError:
        return False, "conexion rechazada (puerto cerrado)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def descubrir_tcp() -> None:
    log("")
    log("=" * 60)
    log("3) TCP CONNECT A PUERTOS INTERNOS")
    log("=" * 60)

    pruebas = [
        ("SAP mensajes (instancia 01)", "laerpprd.argentina.org", 3601),
        ("SAP dispatcher (instancia 01)", "laerpprd.argentina.org", 3201),
        ("SAP gateway (instancia 01)",  "laerpprd.argentina.org", 3301),
        ("WhatsUp Gold HTTPS",           "monitoreo.pecomenergia.com.ar", 443),
        ("Helpdesk HTTPS",               "helpdesk.pecomenergia.com.ar", 443),
    ]

    for etiqueta, host, port in pruebas:
        ok, detalle = tcp_connect(host, port)
        estado = "OK" if ok else "FALLA"
        log(f"   {estado} - {etiqueta} ({host}:{port}) -> {detalle}")


# ---------------------------------------------------------------------------
# 4) IPs locales
# ---------------------------------------------------------------------------
def descubrir_ips_locales() -> None:
    log("")
    log("=" * 60)
    log("4) IPs LOCALES DE ESTA PC")
    log("=" * 60)

    try:
        import psutil
    except ImportError:
        log("ERROR: psutil no instalado.")
        return

    for interfaz, direcciones in psutil.net_if_addrs().items():
        ipv4s = [d.address for d in direcciones if d.family == socket.AF_INET]
        if not ipv4s:
            continue
        # Filtramos loopback
        ipv4s = [ip for ip in ipv4s if not ip.startswith("127.")]
        if not ipv4s:
            continue
        # Marcamos las que parecen ser de VPN (rango tipico corporativo)
        for ip in ipv4s:
            marca = ""
            if ip.startswith("10.") or ip.startswith("172.") or ip.startswith("192.168."):
                marca = " [red privada / posible VPN]"
            log(f"   {interfaz}: {ip}{marca}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log(f"\n>>> Descubrimiento VPN - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} <<<")
    descubrir_procesos_forti()
    descubrir_pings()
    descubrir_tcp()
    descubrir_ips_locales()
    log("")
    log("=" * 60)
    log("Descubrimiento terminado. Pasame la salida completa.")
    log("=" * 60)
    log("")