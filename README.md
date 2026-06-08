# Checklist Automatizado — Pecom Energía

Script de verificación automática del estado de los sistemas críticos de IT.
Ejecuta 7 pruebas en secuencia, saca evidencias (screenshots) de cada una,
genera un resumen en consola y envía un reporte HTML por Outlook al finalizar.

---
FUNCIONA CON VPN
## ¿Qué verifica?

| Paso | Sistema | Descripción |
|------|---------|-------------|
| 1 | **Certificados SSL** | Controla que los certificados no estén vencidos ni por vencer |
| 2 | **3CX Phone** | Realiza una llamada saliente de prueba y verifica que salga |
| 3 | **Citrix / RDP** | Accede al portal Citrix de Pecom y abre un escritorio remoto |
| 4 | **SAP ECC** | Inicia sesión en SAP ECC Producción y verifica el login |
| 5 | **Portales Internos** | Verifica el acceso SSO a Facilities y Compras |
| 6 | **Humand SSO** | Verifica el acceso Single Sign-On al portal Humand usando Edge |
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

### 1. Archivo `.env` (credenciales)

Crear un archivo `.env` en la misma carpeta con:

```
CITRIX_URL=https://citrix.pecomenergia.com.ar
CITRIX_USER=ARGENTINA\tu_usuario
CITRIX_PASS=tu_password

FACILITIES_USER=TU_USUARIO
FACILITIES_PASS=tu_password_facilities

SSO_USER=nombre.apellido@pecomenergia.com.ar
SSO_PASS=tu_password_microsoft
```

### 2. Credenciales SAP (`sap_login_check.py`)

Editar las siguientes líneas del archivo con las credenciales correctas:

```python
SAP_USER     = "TU_USUARIO"
SAP_PASSWORD = "TuPassword"
SAP_CLIENT   = "300"
```

### 3. Destinatario del reporte (`checklist.py`)

Al principio de `checklist.py` configurar los datos del email de reporte:

```python
MAIL_DESTINATARIO = "destinatario@pecomenergia.com.ar"
MAIL_CC           = ""          # CC opcional
NOMBRE_REMITENTE  = "Lucas Abad"
CARGO_REMITENTE   = "IT & Innovación"
```

### 4. Sesión Humand SSO (`check_humandSSO.py`)

La **primera vez** que se ejecute el paso de Humand, se abrirá Edge y habrá que
iniciar sesión manualmente (incluyendo MFA si corresponde). El perfil queda guardado
en `./edge_profile_check/` y las ejecuciones siguientes entran automáticamente.

### 5. Portales Internos (`check_sso_portales.py`)

- **Facilities** usa login directo con `FACILITIES_USER` y `FACILITIES_PASS`.
- **Compras** usa SSO Microsoft con `SSO_USER` y `SSO_PASS`.

Los perfiles de Edge se guardan en `./edge_profile_sso_portales/` por portal.

### 6. 3CX Phone

El cliente **3CX Phone** debe estar **abierto y logueado** antes de correr el
checklist. El script lo detecta por el nombre de la ventana.

---

## Cómo ejecutar

```
python checklist.py
```

El script corre los 7 pasos en secuencia. Al finalizar muestra un resumen en
pantalla, guarda un reporte en `./logs_http/` y envía un reporte HTML por Outlook.

> **Durante el paso 6** (Humand) se abrirá el navegador.
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
║  ✓ [OK   ]  Certificados SSL      5 certificados válidos              ║
║  ✓ [OK   ]  Telefonía IP — 3CX    Screenshot guardado en ./evidencias ║
║  ✓ [OK   ]  Citrix / Remote Desktop   Screenshots guardados           ║
║  ✓ [OK   ]  SAP ECC Producción                                        ║
║  ✓ [OK   ]  Portales Internos (Facilities + Compras)                  ║
║  ✓ [OK   ]  Acceso SSO — Humand   Screenshot guardado en ./evidencias ║
║  ✓ [OK   ]  Email Helpdesk (Outlook)  Mail enviado a tickets@pecom... ║
╠══════════════════════════════════════════════════════════════════════╣
║  7 OK  |  0 con fallo   →   TODO OK ✓                                ║
╚══════════════════════════════════════════════════════════════════════╝
```

Al terminar también se envía un email HTML a `MAIL_DESTINATARIO` con el resumen
completo y el detalle por sección, incluyendo estado de cada certificado SSL.

### Archivos generados

| Carpeta | Archivo | Contenido |
|---------|---------|-----------|
| `./logs_http/` | `checklist_resumen_YYYYMMDD_HHmmss.txt` | Reporte de texto de la corrida |
| `./evidencias/` | `Humand_YYYYMMDD_HHmmss.png` | Screenshot Humand SSO |
| `./evidencias/` | `3CX_YYYYMMDD_HHmmss.png` | Screenshot llamada 3CX |
| `./evidencias/` | `Citrix-RDP_1_portal_*.png` | Screenshot portal Citrix |
| `./evidencias/` | `Citrix-RDP_2_rdp_dialog_*.png` | Screenshot diálogo RDP |
| `./evidencias/` | `Citrix-RDP_4_desktop_*.png` | Screenshot escritorio remoto |
| `./evidencias_sso_portales/` | `SSO_Facilities_YYYYMMDD_HHmmss.png` | Screenshot portal Facilities |
| `./evidencias_sso_portales/` | `SSO_Compras_YYYYMMDD_HHmmss.png` | Screenshot portal Compras |

---

## Scripts individuales

Cada verificación también se puede correr por separado:

| Script | Comando |
|--------|---------|
| Certificados SSL | `python check_certificados.py` |
| Llamadas 3CX | `python check_Llamadas3cx.py` |
| Citrix / RDP | `python check_citrix.py` |
| SAP Login | `python sap_login_check.py` |
| Portales Internos (Facilities + Compras) | `python check_sso_portales.py` |
| Humand SSO | `python check_humandSSO.py` |
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
├── checklist.py                  ← Script principal (ejecutar este)
├── check_certificados.py         ← Paso 1: Certificados SSL
├── check_Llamadas3cx.py          ← Paso 2: 3CX Phone
├── check_citrix.py               ← Paso 3: Citrix RDP
├── sap_login_check.py            ← Paso 4: SAP ECC
├── check_sso_portales.py         ← Paso 5: Portales Internos (Facilities + Compras)
├── check_humandSSO.py            ← Paso 6: Humand SSO
├── enviar_mail_outlook.py        ← Paso 7: Email Helpdesk
├── .env                          ← Credenciales (no subir a git)
├── evidencias/                   ← Screenshots de Humand, 3CX, Citrix
├── evidencias_sso_portales/      ← Screenshots de Facilities y Compras
├── logs_http/                    ← Reportes de texto
├── edge_profile_check/           ← Perfil Edge para Humand SSO
├── edge_profile_citrix/          ← Perfil Edge para Citrix
└── edge_profile_sso_portales/    ← Perfiles Edge para Facilities y Compras
```
