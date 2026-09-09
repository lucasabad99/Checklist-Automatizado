"""
Verifica el certificado SSL de una URL:
- Si es válido (no vencido)
- Cuántos días faltan para que venza
- Quién lo emitió

Lee el certificado en formato binario (DER) y lo parsea con cryptography.
Esto evita problemas con cadenas de CAs intermedias defectuosas
(error "CA cert does not include key usage extension") porque no validamos
la cadena, solo leemos el cert del servidor.

Requiere:
    pip install cryptography

Uso:
    python check_cert.py
"""

import ssl
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.backends import default_backend


# ============ SITIOS DE PRUEBA ============
URLS = [
    "https://app.humand.co/feed",
    "https://helpdesk.pecomenergia.com.ar/",
    "https://drive.pecomenergia.com.ar/",
    "https://compras.pecomenergia.com.ar",
    "https://www.google.com",
]

DIAS_ALERTA = 30   # alertar si vence en menos de N días
# ==========================================


def _nombre_a_dict(name: x509.Name) -> dict:
    """Convierte un x509.Name en un dict {nombre_atributo: valor}."""
    resultado = {}
    for attr in name:
        resultado[attr.oid._name] = attr.value
    return resultado


def check_certificado(url: str) -> dict:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 443

    if parsed.scheme != "https":
        return {"host": host, "ok": False, "error": "No es HTTPS"}

    # Contexto sin verificación: queremos LEER el cert, no validar la cadena.
    # La validación estricta ya la hace el navegador en producción; acá solo
    # nos importa la fecha de vencimiento.
    contexto = ssl.create_default_context()
    contexto.check_hostname = False
    contexto.verify_mode = ssl.CERT_NONE

    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            with contexto.wrap_socket(sock, server_hostname=host) as ssock:
                # En binario sí lo devuelve aunque no haya verificación
                der = ssock.getpeercert(binary_form=True)

        if not der:
            return {"host": host, "ok": False, "error": "No se obtuvo el certificado"}

        cert = x509.load_der_x509_certificate(der, default_backend())

        # Fecha de vencimiento (timezone-aware UTC)
        vence = cert.not_valid_after_utc
        ahora = datetime.now(timezone.utc)
        dias_restantes = (vence - ahora).days

        # Emisor
        emisor_dict = _nombre_a_dict(cert.issuer)
        emisor = (emisor_dict.get("organizationName")
                  or emisor_dict.get("commonName")
                  or "Desconocido")

        # Sujeto (a quién se emitió)
        sujeto_dict = _nombre_a_dict(cert.subject)
        cn = sujeto_dict.get("commonName", host)

        return {
            "host": host,
            "ok": True,
            "vence": vence.strftime("%d/%m/%Y"),
            "dias_restantes": dias_restantes,
            "emisor": emisor,
            "cn": cn,
            "vencido": dias_restantes < 0,
            "alerta": 0 <= dias_restantes < DIAS_ALERTA,
        }

    except socket.gaierror:
        return {"host": host, "ok": False, "error": "DNS no resuelve"}
    except socket.timeout:
        return {"host": host, "ok": False, "error": "Timeout (10s)"}
    except ConnectionRefusedError:
        return {"host": host, "ok": False, "error": "Conexión rechazada"}
    except Exception as e:
        return {"host": host, "ok": False, "error": f"{type(e).__name__}: {e}"}


def imprimir_resultado(r: dict):
    if not r["ok"]:
        print(f"  ✗ {r['host']:<45} ERROR: {r['error']}")
        return

    if r["vencido"]:
        icono = "✗ "
        estado = "VENCIDO   "
    elif r["alerta"]:
        icono = "⚠ "
        estado = "POR VENCER"
    else:
        icono = "✓ "
        estado = "OK        "

    print(f"  {icono}{r['host']:<45} {estado}  vence {r['vence']}  "
          f"({r['dias_restantes']:>4} días)  emisor: {r['emisor']}")


def main():
    print(f"\nVerificando {len(URLS)} certificados...\n")
    print("=" * 120)

    for url in URLS:
        r = check_certificado(url)
        imprimir_resultado(r)

    print("=" * 120 + "\n")


if __name__ == "__main__":
    main()