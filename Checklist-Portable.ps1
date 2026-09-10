# Checklist-Portable.ps1
# ------------------------
# Lanzador del Reporte Diario IT (Pecom Energía) -- EL DEL DÍA A DÍA.
#
# Corre dashboard_reporte_diario.py (puerto 5010), que quedó exactamente
# como estaba y funciona OK. Para probar la parte "escalable" (asistente de
# primera vez, diagnóstico de red, etc.) NO uses este archivo: usá
# Checklist-Pruebas.ps1. Ver sección 9 del README.
#
# A propósito NO tiene ninguna ruta fija (nada de "C:\MisRepositorios\...").
# Usa $PSScriptRoot -- la carpeta donde vive ESTE archivo -- así funciona
# sin importar dónde se haya clonado/descomprimido el repo.
#
# Requisitos (una sola vez por PC, ver scripts-powershell\instalar_dependencias.bat
# y la sección 6 del README): Python 3.10+, Microsoft Edge, Outlook y 3CX
# instalados, y las dependencias de Python ya instaladas.

Set-Location (Join-Path $PSScriptRoot "dashboards")
python .\dashboard_reporte_diario.py
