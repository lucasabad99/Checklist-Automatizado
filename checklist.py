"""
checklist.py — Checklist automatizado Pecom Energía
Ejecuta las 7 verificaciones en secuencia, muestra el resultado
en consola y envía un reporte HTML por Outlook al finalizar.

Uso:
    python checklist.py

Ver README.md para dependencias y configuración previa.
"""

import sys
from datetime import datetime
from pathlib import Path


# ═════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN — editá esta sección
# ═════════════════════════════════════════════════════════════════════════════

MAIL_DESTINATARIO = "lucasabad80@gmail.com"   # ← cambiá por el mail del gerente
MAIL_CC           = ""                         # ← CC opcional (ej: "jefe@pecom.com.ar")
NOMBRE_REMITENTE  = "Lucas Abad"
CARGO_REMITENTE   = "IT & Innovación"

# ═════════════════════════════════════════════════════════════════════════════
#  REGISTRO CENTRAL DE RESULTADOS
# ═════════════════════════════════════════════════════════════════════════════

_resultados = []   # {nombre, ok, detalle, items}

MESES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def _reg(nombre: str, ok: bool, detalle: str = "", items: list = None):
    _resultados.append({"nombre": nombre, "ok": ok, "detalle": detalle, "items": items or []})
    icono  = "✓" if ok else "✗"
    estado = "OK" if ok else "FALLO"
    det    = f"  — {detalle}" if detalle else ""
    print(f"\n  {icono} [{estado}]  {nombre}{det}")


def _separador(num: int, total: int, titulo: str):
    print("\n" + "═" * 72)
    print(f"  PASO {num}/{total} — {titulo}")
    print("═" * 72)


# ═════════════════════════════════════════════════════════════════════════════
#  PASO 1 — HTTP Status
# ═════════════════════════════════════════════════════════════════════════════

def paso_http_status():
    _separador(1, 7, "Verificación de sitios web")
    try:
        from check_http_status import correr_verificacion, generar_resumen, guardar_log
        items      = correr_verificacion()
        resumen    = generar_resumen(items)
        guardar_log(resumen, items)
        errores    = [r for r in items if r["estado"] == "ERROR"]
        ok_n       = len(items) - len(errores)
        _reg("Sitios Web Corporativos", len(errores) == 0,
             f"{ok_n}/{len(items)} sitios responden correctamente", items=items)
    except Exception as e:
        _reg("Sitios Web Corporativos", False, f"{type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  PASO 2 — Certificados SSL
# ═════════════════════════════════════════════════════════════════════════════

def paso_certificados():
    _separador(2, 7, "Verificación de certificados SSL")
    try:
        from check_certificados import check_certificado, imprimir_resultado, URLS

        print(f"\nVerificando {len(URLS)} certificados...\n")
        print("─" * 110)

        items    = []
        vencidos = []
        alertas  = []
        errores  = []

        for url in URLS:
            r = check_certificado(url)
            imprimir_resultado(r)
            items.append(r)
            if not r["ok"]:
                errores.append(r["host"])
            elif r.get("vencido"):
                vencidos.append(r["host"])
            elif r.get("alerta"):
                alertas.append(r["host"])

        print("─" * 110)

        if vencidos:
            _reg("Certificados SSL", False, f"VENCIDOS: {', '.join(vencidos)}", items=items)
        elif errores:
            _reg("Certificados SSL", False, f"Sin acceso: {', '.join(errores)}", items=items)
        elif alertas:
            _reg("Certificados SSL", True,
                 f"Por vencer pronto: {', '.join(alertas)}", items=items)
        else:
            _reg("Certificados SSL", True, f"{len(URLS)} certificados válidos", items=items)
    except Exception as e:
        _reg("Certificados SSL", False, f"{type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  PASO 3 — Humand SSO
# ═════════════════════════════════════════════════════════════════════════════

def paso_humand_sso():
    _separador(3, 7, "Acceso SSO a Humand")
    print("\n  NOTA: Al finalizar, presioná Enter en la terminal para continuar.\n")
    try:
        from check_humandSSO import check_sso
        ok = check_sso()
        _reg("Acceso SSO — Humand", ok, "Screenshot guardado en ./evidencias/")
    except SystemExit as e:
        _reg("Acceso SSO — Humand", e.code == 0)
    except Exception as e:
        _reg("Acceso SSO — Humand", False, f"{type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  PASO 4 — 3CX Llamadas
# ═════════════════════════════════════════════════════════════════════════════

def paso_3cx():
    _separador(4, 7, "Verificación de llamadas salientes (3CX Phone)")
    try:
        from check_Llamadas3cx import check_3cx
        ok = check_3cx()
        _reg("Telefonía IP — 3CX", ok, "Screenshot guardado en ./evidencias/")
    except Exception as e:
        _reg("Telefonía IP — 3CX", False, f"{type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  PASO 5 — Citrix RDP
# ═════════════════════════════════════════════════════════════════════════════

def paso_citrix_rdp():
    _separador(5, 7, "Acceso Citrix / Remote Desktop Connection")
    try:
        from check_citrix import check_citrix_rdp
        ok = check_citrix_rdp()
        _reg("Citrix / Remote Desktop", ok, "Screenshots guardados en ./evidencias/")
    except SystemExit as e:
        _reg("Citrix / Remote Desktop", e.code == 0)
    except Exception as e:
        _reg("Citrix / Remote Desktop", False, f"{type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  PASO 6 — SAP Login
# ═════════════════════════════════════════════════════════════════════════════

def paso_sap():
    _separador(6, 7, "Login SAP ECC Producción")
    try:
        from sap_login_check import check_sap_login
        resultado = check_sap_login()
        _reg("SAP ECC Producción", resultado == "OK")
    except SystemExit as e:
        _reg("SAP ECC Producción", e.code == 0, "Proceso terminó con sys.exit")
    except Exception as e:
        _reg("SAP ECC Producción", False, f"{type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  PASO 7 — Email Helpdesk
# ═════════════════════════════════════════════════════════════════════════════

def paso_email_helpdesk():
    _separador(7, 7, "Envío de mail de prueba vía Outlook (ticket helpdesk)")
    try:
        from enviar_mail_outlook import enviar
        enviar()
        _reg("Email Helpdesk (Outlook)", True, "Mail enviado a tickets@pecomenergia.com.ar")
    except Exception as e:
        _reg("Email Helpdesk (Outlook)", False, f"{type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  RESUMEN EN CONSOLA
# ═════════════════════════════════════════════════════════════════════════════

def imprimir_resumen_consola() -> bool:
    ahora  = datetime.now()
    ok_n   = sum(1 for r in _resultados if r["ok"])
    fail_n = len(_resultados) - ok_n
    borde  = "═" * 70

    print("\n\n")
    print("╔" + borde + "╗")
    print("║" + "  RESUMEN FINAL — CHECKLIST AUTOMATIZADO PECOM ENERGÍA".center(70) + "║")
    print("╠" + borde + "╣")
    print(f"║  Fecha: {ahora.strftime('%d/%m/%Y')}   Hora: {ahora.strftime('%H:%M:%S')}{'':34}║")
    print("╠" + borde + "╣")

    for r in _resultados:
        icono  = "✓" if r["ok"] else "✗"
        estado = "OK   " if r["ok"] else "FALLO"
        det    = ("  " + r["detalle"][:32]) if r["detalle"] else ""
        linea  = f"  {icono} [{estado}]  {r['nombre']:<28}{det}"
        print(f"║{linea:<70}║")

    print("╠" + borde + "╣")
    global_txt = "TODO OK ✓" if fail_n == 0 else f"{fail_n} verificación(es) con fallo ✗"
    print(f"║  {ok_n} OK  |  {fail_n} con fallo   →   {global_txt}{'':>{70 - 38 - len(global_txt)}}║")
    print("╚" + borde + "╝\n")

    Path("logs_http").mkdir(exist_ok=True)
    ts   = ahora.strftime("%Y%m%d_%H%M%S")
    path = Path("logs_http") / f"checklist_resumen_{ts}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"CHECKLIST AUTOMATIZADO — PECOM ENERGÍA\n")
        f.write(f"Fecha: {ahora.strftime('%d/%m/%Y')}   Hora: {ahora.strftime('%H:%M:%S')}\n")
        f.write("=" * 72 + "\n\n")
        for r in _resultados:
            det = f"  ({r['detalle']})" if r["detalle"] else ""
            f.write(f"  {'✓' if r['ok'] else '✗'} [{'OK' if r['ok'] else 'FALLO':<5}]  {r['nombre']}{det}\n")
        f.write(f"\nTotal: {ok_n} OK  |  {fail_n} con fallo\n")
        f.write("=" * 72 + "\n")
    print(f"  Reporte de texto guardado en: {path}")
    return fail_n == 0


# ═════════════════════════════════════════════════════════════════════════════
#  GENERADOR DE EMAIL HTML
# ═════════════════════════════════════════════════════════════════════════════

def _badge_ok() -> str:
    return ('<span style="display:inline-block;background-color:#1a7340;color:#ffffff;'
            'font-weight:bold;font-size:12px;padding:2px 10px;">OK</span>')


def _badge_fallo(texto: str = "FALLO") -> str:
    return (f'<span style="display:inline-block;background-color:#C62828;color:#ffffff;'
            f'font-weight:bold;font-size:12px;padding:2px 10px;">{texto}</span>')


def _badge_alerta() -> str:
    return ('<span style="display:inline-block;background-color:#E65100;color:#ffffff;'
            'font-weight:bold;font-size:12px;padding:2px 10px;">ALERTA</span>')


def _seccion_header(titulo: str, ok: bool) -> str:
    indicador = "✓" if ok else "✗"
    color_ind = "#1a7340" if ok else "#C62828"
    return f"""
    <tr>
      <td colspan="2" style="padding:20px 0 6px 0;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="border-left:4px solid {color_ind};padding:4px 0 4px 10px;">
              <strong style="font-size:14px;color:#1B3F6B;text-decoration:underline;">{titulo}</strong>
            </td>
            <td align="right" style="font-size:18px;color:{color_ind};font-weight:bold;">{indicador}</td>
          </tr>
        </table>
      </td>
    </tr>
    <tr><td colspan="2" style="padding:0;"><hr style="border:none;border-top:1px solid #e8eaf0;margin:0;"></td></tr>
    """


def _html_sitios_web(items: list) -> str:
    if not items:
        return ""
    html = '<tr><td colspan="2" style="padding:6px 0 0 0;"><table width="100%" cellpadding="0" cellspacing="0" border="0">'
    for i in items:
        ok_item = i.get("estado") == "OK"
        lat     = f'<span style="color:#888;font-size:11px;"> ({i["latencia"]} ms)</span>' if i.get("latencia") else ""
        badge   = _badge_ok() if ok_item else _badge_fallo()
        det     = f'<br><span style="color:#C62828;font-size:11px;padding-left:16px;">↳ {i["detalle"]}</span>' if not ok_item and i.get("detalle") else ""
        bg      = "#ffffff" if ok_item else "#fff5f5"
        html += f"""
        <tr style="background-color:{bg};">
          <td style="padding:5px 8px;border-bottom:1px solid #f0f0f0;font-size:13px;">
            <span style="color:#333;">{i['nombre']}</span>{lat}{det}
          </td>
          <td align="right" style="padding:5px 8px;border-bottom:1px solid #f0f0f0;white-space:nowrap;">{badge}</td>
        </tr>"""
    html += "</table></td></tr>"
    return html


def _html_certificados(items: list) -> str:
    if not items:
        return ""
    html = '<tr><td colspan="2" style="padding:6px 0 0 0;"><table width="100%" cellpadding="0" cellspacing="0" border="0">'
    for i in items:
        if not i.get("ok"):
            badge = _badge_fallo("ERROR")
            det   = i.get("error", "Error desconocido")
            html += f"""
            <tr style="background-color:#fff5f5;">
              <td style="padding:5px 8px;border-bottom:1px solid #f0f0f0;font-size:13px;">
                <strong>{i.get('host','?')}</strong>
                <span style="color:#C62828;font-size:11px;"> — {det}</span>
              </td>
              <td align="right" style="padding:5px 8px;border-bottom:1px solid #f0f0f0;">{badge}</td>
            </tr>"""
            continue

        if i.get("vencido"):
            badge = _badge_fallo("VENCIDO")
            bg    = "#fff5f5"
        elif i.get("alerta"):
            badge = _badge_alerta()
            bg    = "#fff8f0"
        else:
            badge = _badge_ok()
            bg    = "#ffffff"

        dias = i.get("dias_restantes", "?")
        vence = i.get("vence", "?")
        html += f"""
        <tr style="background-color:{bg};">
          <td style="padding:5px 8px;border-bottom:1px solid #f0f0f0;font-size:13px;">
            <strong>{i.get('host','?')}</strong>
            <span style="color:#555;"> — Expiración de Certificado: <strong>{vence}</strong>
            ({dias} días)</span>
          </td>
          <td align="right" style="padding:5px 8px;border-bottom:1px solid #f0f0f0;white-space:nowrap;">{badge}</td>
        </tr>"""
    html += "</table></td></tr>"
    return html


def _html_paso_simple(r: dict) -> str:
    badge   = _badge_ok() if r["ok"] else _badge_fallo()
    detalle = r.get("detalle", "")
    bg      = "#ffffff" if r["ok"] else "#fff5f5"
    det_html = f'<br><span style="color:#555;font-size:12px;">{detalle}</span>' if detalle else ""
    return f"""
    <tr>
      <td colspan="2" style="padding:8px 0 0 0;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr style="background-color:{bg};">
            <td style="padding:8px 10px;font-size:13px;border:1px solid #e8eaf0;">
              {r['nombre']}{det_html}
            </td>
            <td align="right" style="padding:8px 10px;border:1px solid #e8eaf0;border-left:none;white-space:nowrap;">{badge}</td>
          </tr>
        </table>
      </td>
    </tr>"""


def generar_html_email() -> str:
    ahora    = datetime.now()
    ok_n     = sum(1 for r in _resultados if r["ok"])
    fail_n   = len(_resultados) - ok_n
    fecha_es = f"{ahora.day} de {MESES[ahora.month]} de {ahora.year}"

    banner_bg  = "#1a7340" if fail_n == 0 else "#C62828"
    banner_txt = "TODAS LAS VERIFICACIONES: OK ✓" if fail_n == 0 else f"{fail_n} verificación(es) con FALLO ✗"

    # ── Tabla de resumen ejecutivo ───────────────────────────────────────────
    filas_resumen = ""
    for r in _resultados:
        bg    = "#f5faf7" if r["ok"] else "#fff5f5"
        badge = _badge_ok() if r["ok"] else _badge_fallo()
        det   = f'<span style="color:#666;font-size:11px;"> — {r["detalle"]}</span>' if r["detalle"] else ""
        filas_resumen += f"""
        <tr style="background-color:{bg};">
          <td style="padding:7px 12px;border-bottom:1px solid #e8eaf0;font-size:13px;">
            <strong>{r['nombre']}</strong>{det}
          </td>
          <td align="right" style="padding:7px 12px;border-bottom:1px solid #e8eaf0;white-space:nowrap;">{badge}</td>
        </tr>"""

    # ── Detalle por sección ──────────────────────────────────────────────────
    detalle_secciones = ""
    for r in _resultados:
        detalle_secciones += _seccion_header(r["nombre"], r["ok"])
        if r["nombre"] == "Sitios Web Corporativos" and r.get("items"):
            detalle_secciones += _html_sitios_web(r["items"])
        elif r["nombre"] == "Certificados SSL" and r.get("items"):
            detalle_secciones += _html_certificados(r["items"])
        else:
            detalle_secciones += _html_paso_simple(r)
        detalle_secciones += '<tr><td colspan="2" style="padding:4px 0;"></td></tr>'

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background-color:#edf0f5;font-family:Calibri,Arial,sans-serif;font-size:14px;color:#222;">

<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#edf0f5">
<tr><td align="center" style="padding:30px 10px;">

  <!-- Contenedor -->
  <table width="660" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#ffffff;border:1px solid #d0d5de;max-width:660px;">

    <!-- ── HEADER ── -->
    <tr>
      <td bgcolor="#1B3F6B" style="background-color:#1B3F6B;padding:28px 36px;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td>
              <p style="margin:0;padding:0;font-size:24px;font-weight:bold;color:#ffffff;
                         letter-spacing:2px;font-family:Calibri,Arial,sans-serif;">PECOM</p>
              <p style="margin:2px 0 0 0;padding:0;font-size:11px;color:#7aafd4;letter-spacing:1px;">
                ENERGÍA</p>
              <p style="margin:10px 0 0 0;padding:0;font-size:13px;color:#a8c8e8;">
                Checklist Automatizado de Sistemas IT</p>
            </td>
            <td align="right" valign="top">
              <p style="margin:0;padding:0;font-size:20px;font-weight:bold;color:#ffffff;">
                {ahora.strftime('%d/%m/%Y')}</p>
              <p style="margin:4px 0 0 0;padding:0;font-size:12px;color:#7aafd4;">
                {ahora.strftime('%H:%M:%S')} hs</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- ── BANNER RESULTADO GLOBAL ── -->
    <tr>
      <td bgcolor="{banner_bg}" style="background-color:{banner_bg};padding:16px 36px;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td>
              <p style="margin:0;padding:0;font-size:16px;font-weight:bold;color:#ffffff;">
                {banner_txt}</p>
              <p style="margin:4px 0 0 0;padding:0;font-size:12px;color:rgba(255,255,255,0.85);">
                {ok_n} de {len(_resultados)} verificaciones completadas con éxito</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- ── CUERPO ── -->
    <tr>
      <td style="padding:32px 36px;">

        <p style="margin:0 0 6px 0;font-size:15px;">Estimados, buenos días.</p>
        <p style="margin:0 0 28px 0;color:#444;">
          A continuación el reporte automatizado del Checklist de Sistemas IT
          correspondiente al <strong>{fecha_es}</strong>.
        </p>

        <!-- Tabla resumen ejecutivo -->
        <p style="margin:0 0 8px 0;">
          <strong style="font-size:13px;color:#1B3F6B;text-transform:uppercase;
                          letter-spacing:1px;">Resumen</strong>
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="border:1px solid #d0d5de;margin-bottom:36px;">
          <tr bgcolor="#edf1f7">
            <td style="background-color:#edf1f7;padding:8px 12px;
                        border-bottom:2px solid #1B3F6B;">
              <strong style="font-size:12px;color:#1B3F6B;">SISTEMA / VERIFICACIÓN</strong>
            </td>
            <td align="right" style="background-color:#edf1f7;padding:8px 12px;
                                      border-bottom:2px solid #1B3F6B;">
              <strong style="font-size:12px;color:#1B3F6B;">ESTADO</strong>
            </td>
          </tr>
          {filas_resumen}
        </table>

        <!-- Detalle por sección -->
        <p style="margin:0 0 16px 0;">
          <strong style="font-size:13px;color:#1B3F6B;text-transform:uppercase;
                          letter-spacing:1px;">Detalle por sistema</strong>
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          {detalle_secciones}
        </table>

        <!-- Firma -->
        <table cellpadding="0" cellspacing="0" border="0"
               style="margin-top:36px;border-top:2px solid #edf0f5;padding-top:20px;width:100%;">
          <tr>
            <td>
              <p style="margin:0 0 2px 0;font-size:13px;color:#555;">Saludos,</p>
              <p style="margin:0 0 2px 0;font-size:15px;font-weight:bold;color:#222;">
                {NOMBRE_REMITENTE}</p>
              <p style="margin:0 0 6px 0;font-size:12px;color:#666;">{CARGO_REMITENTE}</p>
              <p style="margin:0;font-size:16px;font-weight:bold;color:#1B3F6B;letter-spacing:2px;">
                PECOM</p>
            </td>
          </tr>
        </table>

      </td>
    </tr>

    <!-- ── FOOTER ── -->
    <tr>
      <td bgcolor="#edf0f5" style="background-color:#edf0f5;padding:14px 36px;
                                    border-top:1px solid #d0d5de;">
        <p style="margin:0;font-size:11px;color:#888;">
          Reporte generado automáticamente — {ahora.strftime('%d/%m/%Y %H:%M:%S')}
          &nbsp;·&nbsp; Checklist Automatizado Pecom IT
        </p>
      </td>
    </tr>

  </table>

</td></tr>
</table>
</body>
</html>"""
    return html


# ═════════════════════════════════════════════════════════════════════════════
#  ENVÍO DE EMAIL VÍA OUTLOOK
# ═════════════════════════════════════════════════════════════════════════════

def enviar_reporte_email():
    ahora = datetime.now()
    print("\n" + "═" * 72)
    print("  Enviando reporte HTML por Outlook...")
    print("═" * 72)
    try:
        import win32com.client
        html_body = generar_html_email()
        outlook   = win32com.client.Dispatch("Outlook.Application")
        mail      = outlook.CreateItem(0)
        mail.To   = MAIL_DESTINATARIO
        if MAIL_CC:
            mail.CC = MAIL_CC
        mail.Subject  = f"Checklist Automatizado Pecom — {ahora.strftime('%d/%m/%Y')}"
        mail.HTMLBody = html_body
        mail.Send()
        print(f"\n  ✓ Reporte enviado a: {MAIL_DESTINATARIO}")
    except Exception as e:
        print(f"\n  ✗ Error al enviar el email: {type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    inicio = datetime.now()

    print("\n")
    print("╔" + "═" * 70 + "╗")
    print("║" + "  CHECKLIST AUTOMATIZADO — PECOM ENERGÍA".center(70) + "║")
    print(f"║  Inicio: {inicio.strftime('%d/%m/%Y  %H:%M:%S')}{'':47}║")
    print("╚" + "═" * 70 + "╝")

    paso_http_status()
    paso_certificados()
    paso_humand_sso()
    paso_3cx()
    paso_citrix_rdp()
    paso_sap()
    paso_email_helpdesk()

    todo_ok = imprimir_resumen_consola()
    enviar_reporte_email()

    fin      = datetime.now()
    duracion = int((fin - inicio).total_seconds())
    print(f"\n  Duración total: {duracion // 60}m {duracion % 60}s\n")

    sys.exit(0 if todo_ok else 1)