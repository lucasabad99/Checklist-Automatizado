# Checklist Automatizado — Pecom Energía

Este repositorio tiene **dos herramientas relacionadas**:

1. **Reporte Diario** (`check_reporte_diario.py` + `dashboard_reporte_diario.py` + `tablero.py`) — **el producto actual**, el que ya se le mostró a Santiago (gerente) y quedó operativo. Corre 4 verificaciones (WhatsUp Gold, Email Helpdesk, URLs Corporativas, Llamadas 3CX), arma un mail HTML consolidado, y tiene un tablero de TV para la oficina.
2. **Checklist completo** (`checklist.py` + `dashboard.py`) — el checklist original de 8 pasos (agrega Citrix, SAP, Portales SSO y Humand). Sigue funcionando, pero es un flujo más largo y no es el que se usa día a día.

Si solo te interesa el uso diario, andá directo a la **sección 3**.

---

## Índice

1. [Condiciones para correr esto — LEER PRIMERO](#1-condiciones-para-correr-esto--leer-primero)
2. [Mapa del repositorio](#2-mapa-del-repositorio)
3. [Reporte Diario — uso del día a día](#3-reporte-diario--uso-del-día-a-día)
4. [Qué está hardcodeado y dónde tocarlo](#4-qué-está-hardcodeado-y-dónde-tocarlo)
5. [Qué es una verificación real vs. qué es "informativo"](#5-qué-es-una-verificación-real-vs-qué-es-informativo)
6. [Instalación desde cero](#6-instalación-desde-cero-para-un-compañero--otra-pc)
7. [Problemas comunes](#7-problemas-comunes)
8. [Checklist completo (8 pasos) — referencia](#8-checklist-completo-8-pasos--referencia)

---

## 1. Condiciones para correr esto — LEER PRIMERO

### 1.1 Red

**Hoy hace falta estar conectado a la Wifi "de cortesía" de la oficina + VPN, los dos al mismo tiempo.**

- Esto es porque **WhatsUp Gold** (`monitoreo.pecomenergia.com.ar`) está detrás de Netskope, y por ahora es la única combinación de red con la que deja pasar sin pedir permisos extra.
- Se probó con otras redes internas y **no funcionó** (bloqueo de permisos) — queda pendiente hablar con IT/infra para ver si se puede habilitar en la red corporativa normal, así no depende de la red de cortesía.
- El resto de los checks (Email Helpdesk, URLs Corporativas, Llamadas 3CX) no tienen esta restricción particular — dependen de la red corporativa / VPN normal, no de la red de cortesía específicamente.

> Si cambiás de red (como pasó al pasar a la red corporativa), la IP de tu PC cambia y hay que actualizarla en `EJECUTOR_URL` de `tablero.py` si estás usando el tablero desde otra PC. Se ve con `ipconfig`.

### 1.2 Apps que tienen que estar abiertas y logueadas

| App | Para qué se usa | Requisito |
|---|---|---|
| **Outlook** (escritorio) | Enviar el mail de Email Helpdesk y el reporte consolidado | Tiene que estar instalado y logueado — se controla vía COM (`win32com`), no SMTP. No hace falta tenerlo abierto en primer plano, pero sí logueado en la sesión de Windows. |
| **3CX Phone** (escritorio) | Originar la llamada de prueba | Tiene que estar **abierto y logueado**. El script lo detecta por el título de la ventana. |
| **Microsoft Edge** | Motor de automatización (Playwright, canal `msedge`) | No hace falta abrirlo a mano — Playwright lo controla directamente. Sí hace falta que Edge esté instalado (viene con Windows). |

### 1.3 Sesiones "guardadas" (perfiles de Edge persistentes)

Varios checks reutilizan una carpeta de perfil de Edge para no tener que loguearse cada vez. **La primera vez que se usa cada perfil, se abre una ventana de Edge y hay que loguearse manualmente** (usuario + password + MFA si corresponde); las corridas siguientes reutilizan esa sesión guardada mientras no expire.

| Carpeta | La usa | Sistema |
|---|---|---|
| `perfil_wug/` | `check_whatsupgold.py` | WhatsUp Gold (SSO + Netskope) |
| `edge_profile/` (o `EDGE_PROFILE_DIR` en `.env`) | `check_urls_corporativas.py` | Sesión general para las URLs corporativas |
| `edge_profile_check/` | `check_humandSSO.py` (checklist completo) | Humand |
| `edge_profile_citrix/` | `check_citrix_portal.py` (checklist completo) | Portal Citrix |
| `edge_profile_sso_portales/` | `check_sso_portales.py` (checklist completo) | Facilities + Compras |

Estas carpetas **no se suben a git** (están en `.gitignore`) porque contienen cookies de sesión — son específicas de cada PC/usuario.

### 1.4 Con qué cuenta corre todo esto

**No hay una cuenta de servicio separada.** Todo corre con la sesión de Windows / Outlook / 3CX / Edge de la persona que ejecuta el script en ese momento — es la cuenta personal, no una cuenta genérica de IT. Esto es importante si otra persona va a correrlo: necesita **sus propias** sesiones logueadas (Outlook propio, 3CX propio, perfiles de Edge propios con su propio login en WhatsUp Gold/URLs corporativas), no puede simplemente copiar las carpetas de perfil de otra persona y esperar que funcione igual (además de que probablemente quede identificado con la sesión de quien logueó originalmente).

### 1.5 Archivo `.env` (credenciales)

Usado principalmente por los checks del **checklist completo** (Citrix, Facilities, SSO Compras). Opcionalmente, el Reporte Diario también lo usa para automatizar el login propio de WhatsUp Gold (`WUG_USER` / `WUG_PASS` — ver [sección 4](#4-qué-está-hardcodeado-y-dónde-tocarlo)). No está en git. Ver [sección 6](#6-instalación-desde-cero-para-un-compañero--otra-pc) para el formato.

---

## 2. Mapa del repositorio

```
REPORTE DIARIO (producto actual)
├── check_reporte_diario.py        ← Lógica: corre los 4 checks, arma el HTML del mail
├── dashboard_reporte_diario.py    ← Panel web: correr → revisar → enviar (manual)
├── tablero.py                     ← Vista de TV/pantalla, solo lectura, auto-refresh
├── check_whatsupgold.py           ← Check 1: WhatsUp Gold (Down Monitors, Disk, Memory)
├── enviar_mail_outlook.py         ← Check 2: mail de prueba a tickets@pecomenergia.com.ar
├── check_urls_corporativas.py     ← Check 3: ~30 URLs corporativas + certificados SSL
└── check_Llamadas3cx.py           ← Check 4: llamada saliente de prueba por 3CX

CHECKLIST COMPLETO (8 pasos, uso menos frecuente)
├── checklist.py                   ← Orquestador de los 8 pasos
├── dashboard.py                   ← Panel web del checklist completo
├── check_certificados.py          ← Certificados SSL (5 sitios)
├── check_citrix_portal.py         ← Citrix / Remote Desktop
├── sap_login_check.py             ← Login SAP ECC
├── check_sso_portales.py          ← Portales Facilities + Compras
├── check_humandSSO.py             ← SSO Humand
└── (reusa check_Llamadas3cx.py, check_whatsupgold.py, enviar_mail_outlook.py)

DATOS GENERADOS (no se suben a git)
├── evidencias_whatsupgold/        ← Screenshots de los widgets de WUG
├── evidencias_urls/                ← Evidencias de URLs Corporativas
├── logs_http/                      ← Resúmenes de texto del checklist completo
├── estado_actual.json              ← Último estado del checklist completo (dashboard.py)
├── perfil_wug/, edge_profile*/     ← Perfiles de Edge con sesiones guardadas
└── .env                            ← Credenciales (Citrix, SSO) — no versionado
```

---

## 3. Reporte Diario — uso del día a día

### 3.1 Generar y enviar el reporte

1. Correr `iniciar_panel_reporte.bat` (o `python dashboard_reporte_diario.py`) y abrir **http://127.0.0.1:5010**.
2. Apretar **"Generar Reporte Diario"**. Corre en vivo: WhatsUp Gold → Email Helpdesk → URLs Corporativas → Llamadas 3CX. Esto **manda un mail real** a `tickets@pecomenergia.com.ar` y **origina una llamada real** por 3CX — es el comportamiento normal, no un simulacro.
3. Cuando termina, apretar **"Ver reporte"** para revisar el HTML completo (con las capturas de WhatsUp Gold) antes de mandarlo a nadie más.
4. Si está todo bien, **"Enviar por email"** — muestra el Para/CC exactos antes de confirmar, y recién ahí lo manda a Santiago + copias configuradas.

El envío es **manual a propósito**: nunca se manda solo, para poder frenar si algo salió mal en la corrida.

### 3.2 Programador automático (`programador_reporte.py`)

Corre solo, de fondo, dentro del mismo proceso de `dashboard_reporte_diario.py` (no hace falta arrancarlo aparte). Dos ciclos independientes:

- **Cada 20 min** (`REFRESH_RAPIDO_SEGUNDOS`): re-chequea URLs Corporativas — sin ventana, sin efectos secundarios. WhatsUp Gold **no** entra en este ciclo por defecto (`WUG_AUTO_REFRESH = False`) porque en modo headless Netskope bloquea la sesión y devuelve todo vacío — solo se puede refrescar sin ventana visible, y en tu PC de trabajo no queremos que se abra un navegador cada 20 min. En una máquina dedicada (ver `docs/tablero_en_servidor_interno.pdf`) sí conviene poner `WUG_AUTO_REFRESH = True`.
- **1 vez por día**, desde `HORA_DIARIA` (default `"08:00"`): corre Email Helpdesk + Llamadas 3CX — estos SÍ tienen efectos reales (mail real, llamada real), por eso no se repiten cada 20 min.

El estado queda guardado en `estado_reporte_diario.json` (no se sube a git) — un reinicio del proceso no pierde lo que ya corrió hoy. Nunca choca con el botón manual: hay un lock compartido, así que si uno está corriendo, el otro espera.

### 3.3 Tablero de TV

1. Correr `iniciar_tablero.bat` (o `python tablero.py`) en la PC/pantalla que va a mostrar el tablero.
2. Antes, editar `EJECUTOR_URL` en `tablero.py` con la IP de la PC donde corre `dashboard_reporte_diario.py` (se imprime en consola al arrancarlo).
3. Abrir **http://127.0.0.1:5050** en esa pantalla, pantalla completa (F11).

El tablero en sí **no ejecuta nada** — solo lee `/estado.json` cada 30 segundos y lo muestra. Los datos que muestra vienen tanto del botón manual como del programador automático (cada tarjeta indica su propia hora real de actualización).

---

## 4. Qué está hardcodeado y dónde tocarlo

| Qué | Dónde | Valor actual |
|---|---|---|
| Destinatario principal del reporte | `dashboard_reporte_diario.py` → `DESTINATARIO_PRINCIPAL` | `lucas.abad@pecomenergia.com` (mail de prueba — reemplazar por el de Santiago) |
| Copias (CC) | `dashboard_reporte_diario.py` → `MAIL_CC` | `["javier.manno@pecomenergia.com.ar"]` (lista de prueba) |
| Mail que recibe el ticket de prueba | `enviar_mail_outlook.py` → `DESTINATARIO` | `tickets@pecomenergia.com.ar` |
| Número al que llama 3CX | `check_Llamadas3cx.py` → `NUMERO_DESTINO` | `91555838452` |
| URLs corporativas verificadas | `check_urls_corporativas.py` → `URLS_CORPORATIVAS` | ~30 sitios (lista completa en el archivo) |
| Umbral "PARCIAL" de URLs | `check_reporte_diario.py` → `UMBRAL_PARCIAL_URLS` | 3 fallas o menos = PARCIAL, más = FALLA |
| Dashboards de WhatsUp Gold | `check_whatsupgold.py` → `DASHBOARDS` | `monitoreo.pecomenergia.com.ar`, viewId 859 (Down Monitors) y 863 (Disk + Memory) |
| Umbral crítico de disco | `check_whatsupgold.py` → `DISK_UMBRAL_PCT` | 90% |
| Umbral crítico de memoria | `check_whatsupgold.py` → `MEMORY_UMBRAL_PCT` | 90% |
| Cantidad para pasar de "alerta" a "crítico" en WUG | `check_reporte_diario.py` → `WUG_UMBRAL_CRITICO_CANTIDAD` | 3 items |
| Certificados SSL verificados (checklist completo) | `check_certificados.py` → `URLS` | 5 sitios |
| Días de alerta antes de vencimiento de cert | `check_certificados.py` → `DIAS_ALERTA` | 30 días |
| Puerto del panel / tablero | `dashboard_reporte_diario.py` / `tablero.py` → `PUERTO` / `PUERTO_LOCAL` | 5010 / 5050 |
| A qué servidor apunta el tablero | `tablero.py` → `EJECUTOR_URL` | Placeholder — hay que ponerlo a mano |
| Cada cuánto se refresca la vista del tablero | `tablero.py` → `REFRESH_SEGUNDOS` | 30 segundos |
| Cada cuánto corre el ciclo rápido (URLs, y WUG si está activado) | `programador_reporte.py` → `REFRESH_RAPIDO_SEGUNDOS` | 20 minutos |
| Hora de la corrida diaria (Email Helpdesk + 3CX) | `programador_reporte.py` → `HORA_DIARIA` | `"08:00"` |
| Si WhatsUp Gold entra al ciclo rápido de 20 min | `programador_reporte.py` → `WUG_AUTO_REFRESH` | `False` (headless no funciona por Netskope — ver sección 3.2) |
| Login propio de WhatsUp Gold (opcional, automatiza lo que hoy se tipea a mano) | `.env` → `WUG_USER` / `WUG_PASS` | Sin configurar = sigue pidiendo login manual |

Todos estos son variables sueltas al principio de cada archivo, comentadas — no hace falta tocar el resto del código para cambiarlas.

---

## 5. Qué es una verificación real vs. qué es "informativo"

El reporte consolidado (mail y tablero) tiene **6 secciones**, pero solo **4 tienen un chequeo automatizado real** detrás:

| Sección | ¿Chequeo real? |
|---|---|
| WhatsUp Gold | ✅ Sí — navega y captura los dashboards en vivo |
| Email Helpdesk | ✅ Sí — manda un mail real y confirma el envío |
| URLs Corporativas | ✅ Sí — pega contra cada URL y revisa el certificado |
| Llamadas 3CX | ✅ Sí — origina una llamada real |
| Accesos Remotos y Chequeo HES | ⚠️ No — texto fijo, siempre se muestra OK (VPN Forti, Citrix, e-mails HES) |
| Otros Sistemas | ⚠️ No — texto fijo, siempre se muestra OK (Cobranzas.com, Portal Office, Teams) |

En el tablero, las dos secciones sin chequeo real están marcadas como **"Informativo · sin chequeo automatizado"** (no dicen "Manual") para no confundirlas con las que sí se verifican de verdad.

---

## 6. Instalación desde cero (para un compañero / otra PC)

### 6.1 Requisitos

- Windows con Python 3.10+ (`python --version`)
- Microsoft Edge instalado (viene con Windows)
- Outlook de escritorio, logueado con una cuenta de Pecom
- 3CX Phone instalado

### 6.2 Dependencias

```
pip install flask playwright cryptography python-dotenv pywin32 Pillow requests pyautogui pygetwindow psutil
playwright install msedge
```

### 6.3 Credenciales (`.env`)

Necesario para el **checklist completo** (Citrix, Facilities, SSO Compras). Opcional para el Reporte Diario: solo si querés automatizar el login propio de WhatsUp Gold (`WUG_USER`/`WUG_PASS`) — sin eso, sigue pidiendo login manual la primera vez, como siempre. Crear un archivo `.env` en la carpeta del proyecto:

```
CITRIX_URL=https://citrix.pecomenergia.com.ar
CITRIX_USER=ARGENTINA\tu_usuario
CITRIX_PASS=tu_password

FACILITIES_USER=TU_USUARIO
FACILITIES_PASS=tu_password_facilities

SSO_USER=nombre.apellido@pecomenergia.com.ar
SSO_PASS=tu_password_microsoft

WUG_USER=tu_usuario_whatsupgold
WUG_PASS=tu_password_whatsupgold
```

### 6.4 Primera corrida (con ventanas visibles)

La primera vez, corré `python dashboard_reporte_diario.py` y apretá "Generar Reporte Diario" **con la pantalla a la vista**: si WhatsUp Gold o URLs Corporativas todavía no tienen sesión guardada, va a abrir una ventana de Edge pidiendo login. Con `WUG_USER`/`WUG_PASS` configurados en `.env`, WhatsUp Gold completa el login solo; si no, hay que loguearse a mano esa vez (las corridas siguientes ya no piden nada mientras la sesión no expire).

### 6.5 Conectividad

Confirmá que estás en la misma condición de red descrita en la [sección 1.1](#11-red) — hoy, red de cortesía + VPN — antes de asumir que algo "no anda": puede ser solo un tema de red, no del script.

---

## 7. Problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `UnicodeEncodeError` al correr el reporte | La consola no soporta caracteres como `→` o `✓` (típico si se redirige la salida a un archivo) | Ya resuelto: `dashboard.py` y `dashboard_reporte_diario.py` fuerzan UTF-8 al arrancar. Si aparece en otro script, avisar para aplicar el mismo fix. |
| El tablero dice "Sin conexión — mostrando últimos datos" | `EJECUTOR_URL` en `tablero.py` apunta a una IP vieja, o cambiaste de red | Revisar la IP actual con `ipconfig` y actualizar `EJECUTOR_URL` |
| El tablero dice "Sin datos todavía" | Todavía no se corrió "Generar Reporte Diario" en esta sesión del panel | Correrlo una vez desde `dashboard_reporte_diario.py` |
| WhatsUp Gold pide login en la ventana de Edge | Sesión de `perfil_wug/` vencida o primera vez | Loguearse a mano en esa ventana; queda guardado para la próxima |
| Alguien más no puede conectarse al tablero desde su PC | Firewall de Windows bloqueando el puerto entrante (5050 o 5010) | Permitir la conexión en el Firewall de Windows la primera vez que lo pida, o habilitarlo a mano |
| El mail no sale / tira error de Outlook | Outlook no está logueado, o no está instalado `pywin32` | Verificar que Outlook esté abierto y logueado; `pip install pywin32` |

---

## 8. Checklist completo (8 pasos) — referencia

Este es el flujo original, más largo, con pasos que no están en el Reporte Diario (Citrix, SAP, Portales SSO, Humand).

| Paso | Sistema | Descripción |
|------|---------|-------------|
| 1 | **Certificados SSL** | Controla que los certificados no estén vencidos ni por vencer |
| 2 | **3CX Phone** | Realiza una llamada saliente de prueba y verifica que salga |
| 3 | **Citrix / RDP** | Accede al portal Citrix de Pecom y abre un escritorio remoto |
| 4 | **SAP ECC** | Inicia sesión en SAP ECC Producción y verifica el login |
| 5 | **Portales Internos** | Verifica el acceso SSO a Facilities y Compras |
| 6 | **Humand SSO** | Verifica el acceso Single Sign-On al portal Humand usando Edge |
| 7 | **Email Helpdesk** | Envía un mail de prueba a `tickets@pecomenergia.com.ar` vía Outlook |
| 8 | **WhatsUp Gold** | Captura los widgets de monitoreo (Down Monitors, Disk, Memory) |

### Cómo ejecutar

```
python checklist.py
```

o con panel web:

```
python dashboard.py
```
→ abrir `http://127.0.0.1:5000`

> **Durante el paso de Humand** se abre el navegador. Cuando el script lo indique, presioná **Enter** en la terminal para continuar.

### Credenciales SAP (`sap_login_check.py`)

Editar directamente en el archivo:

```python
SAP_USER     = "TU_USUARIO"
SAP_PASSWORD = "TuPassword"
SAP_CLIENT   = "300"
```

### Destinatario del reporte (`checklist.py`)

```python
MAIL_DESTINATARIO = "destinatario@pecomenergia.com.ar"
MAIL_CC           = ""          # CC opcional
NOMBRE_REMITENTE  = "Lucas Emir Abad Cancinos"
CARGO_REMITENTE   = "IT & Innovación"
```

### Scripts individuales

| Script | Comando |
|--------|---------|
| Certificados SSL | `python check_certificados.py` |
| Llamadas 3CX | `python check_Llamadas3cx.py` |
| Citrix / RDP | `python check_citrix_portal.py` |
| SAP Login | `python sap_login_check.py` |
| Portales Internos (Facilities + Compras) | `python check_sso_portales.py` |
| Humand SSO | `python check_humandSSO.py` |
| Email de prueba | `python enviar_mail_outlook.py` |
| WhatsUp Gold | `python check_whatsupgold.py` |
| Reporte Diario (todo en uno, sin panel) | `python check_reporte_diario.py` |

### Códigos de salida

| Código | Significado |
|--------|-------------|
| `0` | Todas las verificaciones pasaron correctamente |
| `1` | Una o más verificaciones fallaron |
