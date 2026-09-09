@echo off
title Reporte Diario - Instalacion
cd /d %~dp0

echo ============================================================
echo   Instalando dependencias de Python...
echo   (esto puede tardar unos minutos la primera vez)
echo ============================================================
echo.

python -m pip install --upgrade pip
python -m pip install flask playwright cryptography python-dotenv pywin32 Pillow requests pyautogui pygetwindow psutil

echo.
echo ============================================================
echo   Instalando el navegador Edge para Playwright...
echo ============================================================
echo.

python -m playwright install msedge

echo.
echo ============================================================
echo   Listo. Antes de la primera corrida real, confirma que
echo   tenes Outlook logueado y 3CX Phone abierto (ver README.md,
echo   seccion 1). Despues corre iniciar_panel_reporte.bat
echo ============================================================
pause
