"""
Script de prueba: envía un mail usando el Outlook de escritorio
ya autenticado en la PC. No requiere passwords.

Requisitos:
    - Outlook instalado y abierto (o al menos configurado con una cuenta)
    - Paquete pywin32:  pip install pywin32

Uso:
    python enviar_mail_outlook.py
"""

import time
from datetime import datetime

import win32com.client


# ============ CONFIGURACIÓN ============
DESTINATARIO = "tickets@pecomenergia.com.ar"
ASUNTO       = "Prueba de envío automático"
CUERPO       = """Hola,

Este es un mail de prueba 

Saludos.
"""
# =======================================


def enviar():
    print("Conectando con Outlook...")
    mail = None
    for intento in range(5):
        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
            mail = outlook.CreateItem(0)   # 0 = olMailItem
            break
        except Exception:
            time.sleep(2)
    if mail is None:
        raise RuntimeError("No se pudo inicializar Outlook después de 5 intentos")
    mail.To      = DESTINATARIO
    mail.Subject = ASUNTO
    mail.Body    = CUERPO          # usá .HTMLBody si querés mandar HTML

    print(f"Enviando mail a {DESTINATARIO} ...")
    mail.Send()
    print("✓ Mail enviado (se procesará desde la bandeja de salida de Outlook)")


def enviar_mail_tickets() -> tuple[bool, dict]:
    """Wrapper de enviar() que devuelve (ok, info) para el reporte diario."""
    info = {
        "destinatario": DESTINATARIO,
        "asunto": ASUNTO,
        "timestamp": datetime.now(),
        "error": None,
    }
    try:
        enviar()
        return True, info
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        return False, info


if __name__ == "__main__":
    try:
        enviar()
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")