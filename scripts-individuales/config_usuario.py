"""
config_usuario.py
------------------
Config liviana POR PERSONA (no por check): nombre y email corporativo de
quien corre el script en esta PC. Vive en config_usuario.json, en la raíz
del repo, y (como perfil_wug/, edge_profile/ o .env) NO se sube a git --
es específica de cada compañero. La crea/actualiza setup_inicial.py.

Para qué se usa:
    - Elegir la cuenta de Outlook correcta al mandar mails
      (mail.SendUsingAccount), por si esa persona tiene más de una cuenta
      configurada en su perfil de Outlook. Si no hay config, no coincide
      ninguna cuenta, o algo falla: no pasa nada, Outlook manda con la
      cuenta default de siempre -- mismo comportamiento que hoy.

Todo lo DEMÁS (las URLs corporativas, el número de 3CX, los dashboards de
WhatsUp Gold, a quién se le manda el reporte) es config COMPARTIDA para
todo el equipo y sigue viviendo hardcodeada en cada check_*.py -- no hace
falta ni conviene que cada persona la toque.
"""

import json
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config_usuario.json"


def existe() -> bool:
    return CONFIG_PATH.exists()


def cargar() -> Optional[dict]:
    if not CONFIG_PATH.exists():
        return None
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def guardar(nombre: str, email: str) -> None:
    CONFIG_PATH.write_text(
        json.dumps(
            {"nombre": nombre.strip(), "email": email.strip()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def email_usuario() -> Optional[str]:
    cfg = cargar()
    return cfg.get("email") if cfg else None


def elegir_cuenta_outlook(outlook):
    """Si hay un email guardado en config_usuario.json y coincide con
    alguna cuenta del perfil de Outlook de esta PC, devuelve ese objeto
    Account (para asignarlo a mail.SendUsingAccount antes de .Send()).

    Sin config, sin coincidencia, o si algo falla por lo que sea: devuelve
    None -- el llamador simplemente no toca SendUsingAccount y Outlook manda
    con la cuenta default, igual que siempre. Nunca frena un envío por esto.
    """
    email = email_usuario()
    if not email:
        return None
    try:
        for account in outlook.Session.Accounts:
            if account.SmtpAddress.lower() == email.lower():
                return account
    except Exception:
        pass
    return None
