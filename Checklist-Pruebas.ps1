# Checklist-Pruebas.ps1
# ----------------------
# Lanzador del STACK DE PRUEBAS del Reporte Diario IT (ver sección 9 del README).
#
# Corre dashboard_reporte_diario_PRUEBAS.py (puerto 5011), en paralelo y sin
# pisar al panel del día a día (puerto 5010, que arranca con Checklist-Portable.ps1).
#
# Sirve para probar lo "escalable":
#   - La primera vez en una PC, si no existe config_usuario.json, arranca solo
#     el asistente setup_inicial.py: pide nombre + email corporativo, revisa
#     en qué red estás (cortesía / corporativa), y abre WhatsUp Gold para el
#     login manual único.
#   - En el panel muestra un aviso si falta alguna red antes de correr.
#   - El mail sale de la cuenta de Outlook que coincida con ese email.
#
# NO toca ni las URLs, ni el número de 3CX, ni los destinatarios -- eso sigue
# siendo lo mismo para todos.
#
# Sin rutas fijas: usa $PSScriptRoot, funciona desde cualquier carpeta.

Set-Location (Join-Path $PSScriptRoot "dashboards")
python .\dashboard_reporte_diario_PRUEBAS.py
