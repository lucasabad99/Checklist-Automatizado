"""
setup_inicial.py
-----------------
Asistente de primera configuración para un compañero nuevo que va a correr
el Reporte Diario en su propia PC por primera vez. Se corre UNA sola vez por
persona/PC -- después queda todo guardado y las corridas normales
(dashboard_reporte_diario.py) no vuelven a pedir nada de esto.

Qué hace:
    1. Pide nombre y email corporativo → se guardan en config_usuario.json
       (NO se sube a git, es específico de cada persona, como perfil_wug/ o
       el .env). Se usa para que el mail del reporte salga de LA CUENTA de
       Outlook correcta, si esa persona tiene más de una cuenta configurada.
    2. Revisa a qué red(es) de la oficina está conectada esta PC ahora mismo
       (ver docs/redes_oficina_guia.pdf) y avisa si falta alguna.
    3. Abre WhatsUp Gold en una ventana de Edge VISIBLE para completar el
       login manual (SSO/Netskope + usuario propio de WUG) una sola vez --
       de ahí en adelante la sesión queda guardada en perfil_wug/ y no
       vuelve a pedirse (ver sección 1.3 del README).

Todo lo DEMÁS (las ~30 URLs corporativas, el número al que llama 3CX, a
quién se le manda el reporte) es configuración COMPARTIDA para todo el
equipo: ya viene lista en el repo, no hay que tocar nada por persona.

Uso:
    python setup_inicial.py
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "scripts-individuales"))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config_usuario
import red_utils


def _pedir(msg: str, obligatorio: bool = True) -> str:
    while True:
        valor = input(msg).strip()
        if valor or not obligatorio:
            return valor
        print("  (no puede quedar vacío)")


def paso_1_datos_usuario() -> None:
    print("\n" + "=" * 64)
    print("  PASO 1/3 — Tus datos")
    print("=" * 64)
    if config_usuario.existe():
        actual = config_usuario.cargar() or {}
        print(f"Ya hay una configuración guardada: "
              f"{actual.get('nombre', '?')} <{actual.get('email', '?')}>")
        if _pedir("¿Volver a cargarla? (s/n): ", obligatorio=False).lower() != "s":
            return
    nombre = _pedir("Nombre y apellido: ")
    email = _pedir("Email corporativo (@pecomenergia.com.ar): ")
    config_usuario.guardar(nombre, email)
    print("✓ Guardado en config_usuario.json")


def paso_2_red() -> None:
    print("\n" + "=" * 64)
    print("  PASO 2/3 — Red")
    print("=" * 64)
    print(red_utils.resumen_texto())
    avisos = red_utils.avisos_preflight()
    if avisos:
        for a in avisos:
            print(a)
    else:
        print("Se detectan todas las redes conocidas -- listo para seguir.")
    _pedir("\nPresioná Enter para continuar...", obligatorio=False)


def paso_3_whatsupgold() -> None:
    print("\n" + "=" * 64)
    print("  PASO 3/3 — Login de WhatsUp Gold")
    print("=" * 64)
    print("Se va a abrir una ventana de Edge. Si pide login (SSO/Netskope")
    print("y/o usuario propio de WhatsUp Gold), completalo a mano esta vez")
    print("-- de ahí en adelante la sesión queda guardada y no se vuelve a")
    print("pedir (perfil_wug/).")
    resp = _pedir(
        "Presioná Enter para abrir la ventana (o 's' para saltear este paso): ",
        obligatorio=False,
    )
    if resp.lower() == "s":
        print("Salteado -- se va a pedir la próxima vez que corra el reporte.")
        return
    import check_whatsupgold as wug
    try:
        wug.check_whatsupgold(enviar_mail=False, headless=False)
    except Exception as e:
        print(f"(No se pudo confirmar el resultado automáticamente: "
              f"{type(e).__name__}: {e}. Si la ventana de Edge quedó "
              f"logueada, la sesión igual se guardó.)")


def main() -> None:
    print("Asistente de configuración inicial — Reporte Diario IT (Pecom Energía)")
    paso_1_datos_usuario()
    paso_2_red()
    paso_3_whatsupgold()
    print("\n" + "=" * 64)
    print("  Listo. De acá en más corré:")
    print("    python dashboards\\dashboard_reporte_diario.py")
    print("  (o Checklist-Portable.ps1)")
    print("=" * 64)


if __name__ == "__main__":
    main()
