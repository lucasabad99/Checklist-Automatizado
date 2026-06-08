# Checklist Automatizado — Pecom Energía

Script de verificación automática del estado de los sistemas críticos de IT.
Ejecuta 7 pruebas en secuencia, saca evidencias (screenshots) de cada una
y genera un reporte final con el resultado global.

---
FUNCIONA CON VPN
## ¿Qué verifica?

| Paso | Sistema | Descripción |
|------|---------|-------------|
| 1 | **Sitios Web** | Verifica que los portales corporativos respondan correctamente (HTTP 200/301) |
| 2 | **Certificados SSL** | Controla que los certificados no estén vencidos ni por vencer |
| 3 | **Humand SSO** | Verifica el acceso Single Sign-On al portal Humand usando Edge |
| 4 | **3CX Phone** | Realiza una llamada saliente de prueba y verifica que salga |
| 5 | **Citrix / RDP** | Accede al portal Citrix de Pecom y abre un escritorio remoto |
| 6 | **SAP ECC** | Inicia sesión en SAP ECC Producción y verifica el login |
| 7 | **Email Helpdesk** | Envía un mail de prueba a `tickets@pecomenergia.com.ar` vía Outlook |

---

## Requisitos previos

### Python 3.10+

Verificar con:
```
python --version
```

### Dependencias

Instalar todo con:
```
pip install playwright cryptography requests python-dotenv pyautogui pygetwindow pillow pywin32 psutil
```

Instalar el navegador Edge para Playwright (solo la primera vez):
```
playwright install msedge
```

---

## Configuración

### 1. Archivo `.env` (credenciales Citrix)

Crear un archivo `.env` en la misma carpeta con:

```
CITRIX_URL=https://citrix.pecomenergia.com.ar
CITRIX_USER=ARGENTINA\tu_usuario
CITRIX_PASS=tu_password
```

### 2. Credenciales SAP (`sap_login_check.py`)

Editar las siguientes líneas del archivo con las credenciales correctas:

```python
SAP_USER     = "TU_USUARIO"
SAP_PASSWORD = "TuPassword"
SAP_CLIENT   = "300"
```

### 3. Sesión Humand SSO (`check_humandSSO.py`)

La **primera vez** que se ejecute el paso de Humand, se abrirá Edge y habrá que
iniciar sesión manualmente (incluyendo MFA si corresponde). El perfil queda guardado
en `./edge_profile_check/` y las ejecuciones siguientes entran automáticamente.

### 4. 3CX Phone

El cliente **3CX Phone** debe estar **abierto y logueado** antes de correr el
checklist. El script lo detecta por el nombre de la ventana.

---

## Cómo ejecutar

```
python checklist.py
```

El script corre los 7 pasos en secuencia. Al finalizar muestra un resumen en
pantalla y guarda un reporte en `./logs_http/`.

> **Durante los pasos 3 y 5** (Humand y Citrix) se abrirá el navegador.
> Cuando el script indique, presioná **Enter** en la terminal para continuar
> al siguiente paso.

---

## Salida y evidencias

### Pantalla — Resumen final

```
╔══════════════════════════════════════════════════════════════════════╗
║          RESUMEN FINAL — CHECKLIST AUTOMATIZADO PECOM ENERGÍA        ║
╠══════════════════════════════════════════════════════════════════════╣
║  Fecha: 26/05/2026   Hora: 09:15:42                                  ║
╠══════════════════════════════════════════════════════════════════════╣
║  ✓ [OK   ]  HTTP Status           7/7 sitios responden               ║
║  ✓ [OK   ]  Certificados SSL      5 certificados válidos              ║
║  ✓ [OK   ]  Humand SSO            Screenshot guardado en ./evidencias ║
║  ✓ [OK   ]  3CX Llamadas          Screenshot guardado en ./evidencias ║
║  ✓ [OK   ]  Citrix RDP            Screenshots guardados en ./evidencias║
║  ✓ [OK   ]  SAP Login                                                 ║
║  ✓ [OK   ]  Email Outlook         Mail enviado a tickets@pecom...     ║
╠══════════════════════════════════════════════════════════════════════╣
║  7 OK  |  0 con fallo   →   TODO OK ✓                                ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Archivos generados

| Carpeta | Archivo | Contenido |
|---------|---------|-----------|
| `./logs_http/` | `checklist_resumen_YYYYMMDD_HHmmss.txt` | Reporte completo de la corrida |
| `./logs_http/` | `checklist_YYYYMMDD.log` | Bitácora acumulativa del día |
| `./logs_http/` | `resumen_YYYYMMDD.txt` | Resumen de estado HTTP |
| `./evidencias/` | `Humand_YYYYMMDD_HHmmss.png` | Screenshot Humand SSO |
| `./evidencias/` | `3CX_YYYYMMDD_HHmmss.png` | Screenshot llamada 3CX |
| `./evidencias/` | `Citrix-RDP_1_portal_*.png` | Screenshot portal Citrix |
| `./evidencias/` | `Citrix-RDP_2_rdp_dialog_*.png` | Screenshot diálogo RDP |
| `./evidencias/` | `Citrix-RDP_4_desktop_*.png` | Screenshot escritorio remoto |

---

## Scripts individuales

Cada verificación también se puede correr por separado:

| Script | Comando |
|--------|---------|
| Estado de sitios web | `python check_http_status.py` |
| Certificados SSL | `python check_certificados.py` |
| Humand SSO | `python check_humandSSO.py` |
| Llamadas 3CX | `python check_Llamadas3cx.py` |
| Citrix / RDP | `python check_citrix.py` |
| SAP Login | `python sap_login_check.py` |
| Email de prueba | `python enviar_mail_outlook.py` |

---

## Códigos de salida

| Código | Significado |
|--------|-------------|
| `0` | Todas las verificaciones pasaron correctamente |
| `1` | Una o más verificaciones fallaron |

---

## Estructura del proyecto

```
.
├── checklist.py              ← Script principal (ejecutar este)
├── check_http_status.py      ← Paso 1: Estado HTTP
├── check_certificados.py     ← Paso 2: Certificados SSL
├── check_humandSSO.py        ← Paso 3: Humand SSO
├── check_Llamadas3cx.py      ← Paso 4: 3CX Phone
├── check_citrix.py           ← Paso 5: Citrix RDP
├── sap_login_check.py        ← Paso 6: SAP ECC
├── enviar_mail_outlook.py    ← Paso 7: Email Outlook
├── .env                      ← Credenciales Citrix (no subir a git)
├── evidencias/               ← Screenshots de cada verificación
├── logs_http/                ← Reportes y bitácoras
├── edge_profile_check/       ← Perfil Edge para Humand SSO
└── edge_profile_citrix/      ← Perfil Edge para Citrix
```
