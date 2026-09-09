"""
red_utils.py
------------
Detecta a qué red(es) de la oficina está conectada esta PC, comparando las
IPs de TODOS los adaptadores de red contra los rangos conocidos en
redes_oficina.json (raíz del repo). Es normal estar conectado a varias a la
vez -- ej. Wifi de cortesía + Ethernet de dominio simultáneamente, que es
justo el caso que necesita WhatsUp Gold (ver sección 1.1 del README y
docs/redes_oficina_guia.pdf).

Este módulo NO bloquea ni decide si un check corre o no -- cada check sigue
funcionando exactamente igual que antes. Es solo diagnóstico: mostrarle a
quien corre el reporte, ANTES de arrancar, qué red le falta si algo va a
fallar por eso -- en vez de que lo descubra recién cuando el check se cuelga
a mitad de camino.

Para sumar una red nueva u office nueva más adelante: no hace falta tocar
este archivo, solo agregar una entrada en redes_oficina.json.
"""

import json
import socket
from pathlib import Path
from typing import Dict, List

try:
    import psutil
except ImportError:
    psutil = None

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_REDES = BASE_DIR / "redes_oficina.json"

# Fallback si redes_oficina.json no está (no debería pasar, está en git,
# pero mejor no romper el reporte por esto).
_DEFAULT = {
    "corporativa": {
        "prefijos": ["172.16."],
        "descripcion": "PecomEnergía Wifi / Ethernet de dominio",
    },
    "cortesia": {
        "prefijos": ["192.168.11."],
        "descripcion": "PC Wifi (red de invitados)",
    },
}


def _cargar_config() -> dict:
    if CONFIG_REDES.exists():
        try:
            return json.loads(CONFIG_REDES.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _DEFAULT


def _ips_locales() -> List[str]:
    """Todas las IPv4 de todos los adaptadores (así se ven a la vez la IP de
    cortesía y la corporativa, si la PC está conectada a las dos)."""
    ips = []
    if psutil is not None:
        try:
            for _iface, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if a.family == socket.AF_INET and a.address:
                        ips.append(a.address)
            if ips:
                return ips
        except Exception:
            pass
    # Sin psutil (o falló): mejor esfuerzo con la IP de salida a Internet
    # -- solo ve UNA red, no sirve para detectar conexión simultánea.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
    except Exception:
        pass
    finally:
        s.close()
    return ips


def redes_conectadas() -> Dict[str, bool]:
    """{'corporativa': True/False, 'cortesia': True/False, ...} según los
    prefijos de redes_oficina.json contra las IPs detectadas ahora mismo."""
    cfg = _cargar_config()
    ips = _ips_locales()
    return {
        nombre: any(ip.startswith(p) for ip in ips for p in datos.get("prefijos", []))
        for nombre, datos in cfg.items()
        if not nombre.startswith("_")
    }


def resumen_texto() -> str:
    """Línea corta para consola, ej: 'Red detectada: ✓ corporativa | ✗ cortesia'."""
    cfg = _cargar_config()
    estado = redes_conectadas()
    partes = [f"{'✓' if ok else '✗'} {nombre}" for nombre, ok in estado.items()]
    return "Red detectada: " + " | ".join(partes) if partes else "Red detectada: (sin datos)"


def avisos_preflight() -> List[str]:
    """Advertencias en texto plano si falta alguna red que algún check
    necesita -- para mostrar ANTES de correr el reporte, no después."""
    estado = redes_conectadas()
    avisos = []
    if not estado.get("cortesia", True):
        avisos.append(
            "⚠ No se detecta la red de cortesía (PC Wifi) -- WhatsUp Gold "
            "probablemente no cargue: necesita cortesía + VPN al mismo "
            "tiempo (ver sección 1.1 del README)."
        )
    if not estado.get("corporativa", True):
        avisos.append(
            "⚠ No se detecta la red corporativa / de dominio -- Email "
            "Helpdesk, URLs Corporativas y Llamadas 3CX probablemente fallen."
        )
    return avisos


if __name__ == "__main__":
    import sys
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print(resumen_texto())
    avisos = avisos_preflight()
    if avisos:
        for a in avisos:
            print(a)
    else:
        print("Sin advertencias -- se detectan todas las redes conocidas.")
