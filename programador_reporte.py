"""
programador_reporte.py — Programador automático del Reporte Diario (Pecom Energía)

Corre en segundo plano dentro del mismo proceso de dashboard_reporte_diario.py
(así comparte memoria con check_reporte_diario y no hace falta sincronizar
nada entre procesos). Dos ciclos independientes:

  1. Cada REFRESH_RAPIDO_SEGUNDOS (default 20 min): re-chequea WhatsUp Gold +
     URLs Corporativas. Ninguno de los dos tiene efectos secundarios reales
     (no mandan mail, no llaman a nadie) — son seguros para correr solos,
     desatendidos, todo el día.

  2. Una vez por día, a partir de HORA_DIARIA: corre Email Helpdesk +
     Llamadas 3CX. Estos SÍ tienen efectos reales (mandan un ticket de
     verdad a tickets@pecomenergia.com.ar y originan una llamada real por
     3CX) — por eso NO se re-ejecutan cada 20 min, solo una vez al día.

Si un chequeo automático falla (error de red, sesión vencida, etc.), el
programador NO pisa el último dato bueno conocido con un "FALLA" — mejor
mostrar en el tablero un dato viejo con su hora, que un estado falso por un
problema pasajero.

2026-08-25 — confirmado en producción: WhatsUp Gold en modo headless NO
funciona (Netskope bloquea la sesión sin ventana visible; los 3 widgets
vuelven "N/D"). Por eso WUG quedó AFUERA del ciclo rápido (WUG_AUTO_REFRESH
= False): no tiene sentido "caer" a headless=False cada 20 min, porque eso
abriría una ventana de Edge visible cada 20 minutos — igual de disruptivo
que lo que se quería evitar. WhatsUp Gold sigue actualizándose con el botón
manual del panel y en la corrida diaria (con ventana visible, una sola vez
al día). Si en el futuro se resuelve el tema de Netskope en headless, poner
WUG_AUTO_REFRESH = True para volver a sumarlo al ciclo rápido.
"""

import time
import threading
from datetime import datetime, date

import check_reporte_diario as rep
import check_whatsupgold as wug_mod
import check_urls_corporativas as urls_mod
import enviar_mail_outlook as mail_tickets_mod
import check_Llamadas3cx as tcx_mod

# ═════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN — editá esta sección
# ═════════════════════════════════════════════════════════════════════════════

REFRESH_RAPIDO_SEGUNDOS = 20 * 60   # WhatsUp Gold + URLs Corporativas

# Hora del día (formato "HH:MM", 24hs) a partir de la cual corre la
# verificación diaria (Email Helpdesk + 3CX). Se dispara la primera vez que
# el ciclo pasa por esa hora y no corrió todavía hoy — no hace falta que
# coincida exacto al minuto.
HORA_DIARIA = "08:00"

# Ver nota arriba. False = WUG no se toca en el ciclo rápido (ni headless
# —no funciona— ni visible —sería una ventana cada 20 min—).
WUG_AUTO_REFRESH = False
URLS_AUTO_HEADLESS = True

# ═════════════════════════════════════════════════════════════════════════════


def _refrescar_rapido() -> None:
    """WhatsUp Gold (si WUG_AUTO_REFRESH) + URLs Corporativas. Sin efectos
    secundarios reales en ninguno de los dos."""
    evidencias_wug = None   # None = "no tocar el campo existente"
    if WUG_AUTO_REFRESH:
        try:
            wug_mod.check_whatsupgold(enviar_mail=False, headless=True)
            ultima_wug = wug_mod.obtener_ultima_corrida()
            capturadas = ultima_wug.get("evidencias") or {}
            if capturadas:
                evidencias_wug = capturadas
            else:
                print("[PROGRAMADOR] WhatsUp Gold no capturó nada esta vez "
                      "(¿sesión vencida en modo headless?) — se mantiene el dato anterior.")
        except Exception as e:
            print(f"[PROGRAMADOR] Error refrescando WhatsUp Gold: {type(e).__name__}: {e}")

    resultados_urls = None
    try:
        _, urls_capturadas = urls_mod.verificar_urls_corporativas(
            headless=URLS_AUTO_HEADLESS, enviar_mail=False
        )
        if urls_capturadas:
            resultados_urls = urls_capturadas
    except Exception as e:
        print(f"[PROGRAMADOR] Error refrescando URLs Corporativas: {type(e).__name__}: {e}")

    if evidencias_wug is not None or resultados_urls is not None:
        rep.actualizar_parcial(evidencias_wug=evidencias_wug, resultados_urls=resultados_urls)
        print(f"[PROGRAMADOR] Refresco rápido (WUG + URLs) — {datetime.now().strftime('%H:%M:%S')}")
    else:
        print(f"[PROGRAMADOR] Refresco rápido sin novedades para guardar — "
              f"{datetime.now().strftime('%H:%M:%S')}")


def _correr_diario() -> None:
    """Email Helpdesk + Llamadas 3CX. Manda un mail real y origina una llamada real."""
    print(f"[PROGRAMADOR] >>> Verificación diaria (Email + 3CX) — {datetime.now().strftime('%H:%M:%S')}")

    ok_email, info_email = False, {
        "destinatario": "-", "asunto": "-", "timestamp": datetime.now(),
        "error": "Error desconocido",
    }
    try:
        ok_email, info_email = mail_tickets_mod.enviar_mail_tickets()
    except Exception as e:
        print(f"[PROGRAMADOR] Error en Email Helpdesk: {type(e).__name__}: {e}")
        info_email["error"] = f"{type(e).__name__}: {e}"

    ok_3cx = False
    try:
        ok_3cx, _ = tcx_mod.check_3cx()
    except Exception as e:
        print(f"[PROGRAMADOR] Error en 3CX: {type(e).__name__}: {e}")

    rep.actualizar_parcial(ok_email=ok_email, info_email=info_email, ok_3cx=ok_3cx)
    print(f"[PROGRAMADOR] Verificación diaria completa — "
          f"Email: {'OK' if ok_email else 'FALLA'}  3CX: {'OK' if ok_3cx else 'FALLA'}")


def _debe_correr_diaria_ahora() -> bool:
    """True si ya pasó HORA_DIARIA y todavía no corrió la diaria hoy.
    Se fija en el timestamp persistido de info_email (no en una variable en
    memoria) para no repetir la corrida si el proceso se reinicia el mismo día."""
    datos = rep.obtener_ultima_corrida_reporte()
    info_email = datos.get("info_email") or {}
    ts_email = info_email.get("timestamp")
    if ts_email and ts_email.date() == date.today():
        return False

    hh, mm = (int(x) for x in HORA_DIARIA.split(":"))
    ahora = datetime.now()
    return (ahora.hour, ahora.minute) >= (hh, mm)


def _loop() -> None:
    import pythoncom
    # Todo el ciclo corre en este único hilo de fondo — Outlook/COM necesita
    # CoInitialize() una vez por hilo antes de usarse.
    pythoncom.CoInitialize()
    try:
        while True:
            try:
                _refrescar_rapido()
                if _debe_correr_diaria_ahora():
                    _correr_diario()
            except Exception as e:
                print(f"[PROGRAMADOR] Error inesperado en el ciclo: {type(e).__name__}: {e}")
            time.sleep(REFRESH_RAPIDO_SEGUNDOS)
    finally:
        pythoncom.CoUninitialize()


def iniciar() -> None:
    """Arranca el programador en un hilo de fondo daemon. Llamar una sola
    vez al arrancar dashboard_reporte_diario.py."""
    threading.Thread(target=_loop, daemon=True).start()
    ciclo_rapido = "WhatsUp Gold + URLs" if WUG_AUTO_REFRESH else "URLs Corporativas (WhatsUp Gold desactivado, ver nota arriba)"
    print(f"[PROGRAMADOR] Iniciado — {ciclo_rapido} cada "
          f"{REFRESH_RAPIDO_SEGUNDOS // 60} min · Email + 3CX una vez por día "
          f"desde las {HORA_DIARIA} hs.")
