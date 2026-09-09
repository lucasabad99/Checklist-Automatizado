# Checklist-Portable.ps1
# ------------------------
# Lanzador portable del Reporte Diario IT (Pecom Energía).
#
# A propósito NO tiene ninguna ruta fija (nada de "C:\MisRepositorios\...").
# Usa $PSScriptRoot -- la carpeta donde vive ESTE archivo -- así funciona
# sin importar dónde se haya clonado/descomprimido el repo en la PC de
# quien lo corre (la tuya, la de un compañero, da igual).
#
# Primera vez en una PC: si no existe config_usuario.json, dashboard_reporte_diario.py
# arranca solo el asistente setup_inicial.py (nombre/email + diagnóstico de
# red + login de WhatsUp Gold) antes de levantar el panel. Ver README.md,
# sección 1.6.
#
# Requisitos (una sola vez por PC, ver scripts-powershell\instalar_dependencias.bat
# y la sección 6 del README): Python 3.10+, Microsoft Edge, Outlook y 3CX
# instalados, y las dependencias de Python ya instaladas.

Set-Location (Join-Path $PSScriptRoot "dashboards")
python .\dashboard_reporte_diario.py
