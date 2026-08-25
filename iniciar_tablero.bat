@echo off
title Reporte Diario - Tablero de TV
cd /d %~dp0

echo ============================================================
echo   Tablero de TV
echo   Se va a abrir en: http://127.0.0.1:5050
echo.
echo   IMPORTANTE: antes de usarlo, confirma que EJECUTOR_URL
echo   dentro de tablero.py apunta a la IP correcta de la PC
echo   donde corre el panel (iniciar_panel_reporte.bat).
echo   Ver README.md, seccion 3.2.
echo ============================================================
echo.

python tablero.py

echo.
echo ------------------------------------------------------------
echo El tablero se detuvo. Si fue un error inesperado, revisa el
echo mensaje de arriba (README.md tiene la seccion "Problemas
echo comunes"). Si lo cerraste vos con Ctrl+C, todo bien.
echo ------------------------------------------------------------
pause
