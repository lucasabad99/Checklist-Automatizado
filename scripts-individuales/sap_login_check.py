"""
sap_login_check.py
------------------
Abre SAP Logon automáticamente, se loguea en ECC Producción
y verifica que el acceso funcione correctamente.

Requisitos:
  - Python 3.x
  - pywin32: pip install pywin32
  - psutil:  pip install psutil
  - SAP Scripting habilitado y SIN notificaciones:
      ✅ Activar scripting
      ☐ Notificar cuando un script se añade a un SAP GUI
      ☐ Notificar cuando un script abre una conexión
"""

import win32com.client
import subprocess
import time
import sys
import psutil

# ─────────────────────────────────────────
#  CONFIGURACIÓN — editá estos valores
# ─────────────────────────────────────────
SAP_LOGON_PATH      = r"C:\Program Files (x86)\SAP\FrontEnd\SAPgui\saplogon.exe"
SAP_CONNECTION_NAME = "ECC Producción"
SAP_USER            = "SVILAR"
SAP_PASSWORD        = "Elsa2026$$"
SAP_CLIENT          = "300"    # Mandante — ajustá si es distinto
SAP_LANGUAGE        = "ES"
# ─────────────────────────────────────────


def sap_logon_esta_abierto():
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and 'saplogon' in proc.info['name'].lower():
            return True
    return False


def check_sap_login():
    print("=" * 50)
    print("  SAP Login Check — ECC Producción")
    print("=" * 50)

    # 1. Abrir SAP Logon si no está corriendo
    print("\n[1/4] Verificando SAP Logon...")
    if sap_logon_esta_abierto():
        print("  ✓ SAP Logon ya estaba abierto")
    else:
        print("  → SAP Logon cerrado, abriendo...")
        try:
            subprocess.Popen([SAP_LOGON_PATH])
            print("  → Esperando que cargue SAP Logon (10 seg)...")
            time.sleep(10)
            print("  ✓ SAP Logon iniciado")
        except Exception as e:
            print(f"  ✗ No se pudo abrir SAP Logon: {e}")
            sys.exit(1)

    # 2. Conectar con la Scripting API
    print("\n[2/4] Conectando con SAP Scripting API...")
    application = None
    for intento in range(5):
        try:
            sap_gui_auto = win32com.client.GetObject("SAPGUI")
            application  = sap_gui_auto.GetScriptingEngine
            break
        except Exception:
            print(f"  → Intento {intento + 1}/5, esperando...")
            time.sleep(3)

    if application is None:
        print("  ✗ No se pudo conectar con la Scripting API.")
        sys.exit(1)
    print("  ✓ Scripting API conectada")

    # 3. Abrir conexión a ECC Producción
    print(f"\n[3/4] Abriendo '{SAP_CONNECTION_NAME}'...")
    try:
        connection = application.OpenConnection(SAP_CONNECTION_NAME, True)
        time.sleep(4)
    except Exception as e:
        print(f"  ✗ Error al abrir la conexión: {e}")
        sys.exit(1)
    print("  ✓ Conexión establecida")

    # 4. Login
    print("\n[4/4] Ingresando credenciales y verificando...")
    resultado = "ERROR"
    try:
        session = connection.Children(0)

        # Completar login si estamos en pantalla S000
        if session.Info.Transaction == "S000":
            session.findById("wnd[0]/usr/txtRSYST-MANDT").text = SAP_CLIENT
            session.findById("wnd[0]/usr/txtRSYST-BNAME").text = SAP_USER
            session.findById("wnd[0]/usr/pwdRSYST-BCODE").text = SAP_PASSWORD
            session.findById("wnd[0]/usr/txtRSYST-LANGU").text = SAP_LANGUAGE
            session.findById("wnd[0]").sendVKey(0)  # Enter

            # Esperar que SAP procese el login completamente
            print("  → Esperando respuesta del servidor...")
            time.sleep(20)

            # Cerrar popup de sesión múltiple si aparece
            try:
                session.findById("wnd[1]")
                print("  ⚠ Popup detectado (sesión múltiple), cerrando...")
                session.findById("wnd[1]/usr/btnSPOP-OPTION1").press()
                time.sleep(3)
            except:
                pass
        else:
            print("  ⚠ La sesión ya estaba activa.")

        # Verificar login comprobando si ya NO estamos en la pantalla S000.
        # Si el campo de mandante (txtRSYST-MANDT) ya no existe = login exitoso.
        for intento in range(5):
            try:
                user_logged = session.Info.User
                if user_logged:
                    print(f"  ✓ Login exitoso — Usuario: {user_logged}")
                    resultado = "OK"
                    break
            except:
                pass
            try:
                session.findById("wnd[0]/usr/txtRSYST-MANDT")
                # Campo existe → todavía en pantalla de login
                print(f"  → Intento {intento+1}/5 — aún en pantalla de login, esperando...")
                time.sleep(3)
            except Exception:
                # Campo NO existe → ya pasamos el login
                print(f"  ✓ Login confirmado — pantalla de login superada")
                resultado = "OK"
                break
        else:
            print(f"  ✗ No se pudo confirmar el login después de 5 intentos")
            resultado = "FAIL"

    except Exception as e:
        print(f"  ✗ Error durante el login: {e}")
        resultado = "ERROR"

    # Cerrar sesión limpiamente
    try:
        session.findById("wnd[0]").close()
        time.sleep(1)
        try:
            session.findById("wnd[1]/usr/btnSPOP-OPTION1").press()
        except:
            pass
    except:
        pass

    print("\n" + "=" * 50)
    print(f"  Resultado final: {resultado}")
    print("=" * 50)
    return resultado


if __name__ == "__main__":
    resultado = check_sap_login()
    sys.exit(0 if resultado == "OK" else 1)