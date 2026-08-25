@echo off
title Reporte Diario - Panel de Control
cd /d %~dp0

echo ============================================================
echo   Panel del Reporte Diario
echo   Se va a abrir en: http://127.0.0.1:5010
echo   (dejá esta ventana abierta mientras lo usás)
echo ============================================================
echo.

python dashboard_reporte_diario.py

echo.
echo ------------------------------------------------------------
echo El panel se detuvo. Si fue un error inesperado, revisa el
echo mensaje de arriba (README.md tiene la seccion "Problemas
echo comunes"). Si lo cerraste vos con Ctrl+C, todo bien.
echo ------------------------------------------------------------
pause
