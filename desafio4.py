import tkinter as tk
from tkinter import ttk, messagebox
import ipaddress
import json
import queue
import threading
import requests

requests.packages.urllib3.disable_warnings()

print("edgar harim")

ROUTER = "10.10.20.48"
USUARIO = "developer"
CONTRASENA = 'C1sco12345'
BASE_URL = f"https://{ROUTER}/restconf/data/ietf-interfaces:interfaces"
HEADERS = {
    "Accept": "application/yang-data+json",
    "Content-type": "application/yang-data+json",
}
AUTH = (USUARIO, CONTRASENA)
INTERFACES_PROTEGIDAS = {"Loopback0", "Loopback10", "Loopback109"}
respuestas = queue.Queue()
trabajando = False


def actualizar_estado(mensaje, exito=None):
    if exito is True:
        color, texto = "#28A745", "white"
    elif exito is False:
        color, texto = "#DC3545", "white"
    else:
        color, texto = "#D9D9D9", "black"
    barra_estado.config(text=mensaje, bg=color, fg=texto)


def escribir_resultado(texto):
    resultado.config(state="normal")
    resultado.delete("1.0", tk.END)
    resultado.insert(tk.END, texto)
    resultado.config(state="disabled")


def mostrar_error(mensaje):
    actualizar_estado(mensaje, False)
    escribir_resultado(mensaje)


def permitir_loopback(nombre):
    return nombre.startswith("Loopback") and nombre[8:].isdigit() and nombre not in INTERFACES_PROTEGIDAS


def enviar_operacion(tipo, url, datos=None, nombre=""):
    """Ejecuta el trabajo de red fuera del hilo de Tkinter."""
    def trabajo():
        try:
            kwargs = {
                "auth": AUTH, "headers": HEADERS,
                "verify": False, "timeout": 15,
            }
            if tipo == "PUT":
                kwargs["data"] = json.dumps(datos)
            respuesta = requests.request(tipo, url, **kwargs)
            respuestas.put((tipo, nombre, respuesta.status_code, respuesta.text))
        except requests.exceptions.RequestException as error:
            respuestas.put((tipo, nombre, None, str(error)))

    global trabajando
    if trabajando:
        return
    trabajando = True
    for boton in botones:
        boton.config(state="disabled")
    actualizar_estado("Procesando petición RESTCONF...", None)
    escribir_resultado("Consultando el router, por favor espera...")
    threading.Thread(target=trabajo, daemon=True).start()


def procesar_respuestas():
    """La interfaz solamente se modifica desde el hilo principal."""
    global trabajando
    try:
        while True:
            tipo, nombre, codigo, contenido = respuestas.get_nowait()
            trabajando = False
            for boton in botones:
                boton.config(state="normal")

            if codigo is None:
                mostrar_error(f"Error de conexión RESTCONF: {contenido}")
                messagebox.showerror("Error de conexión", contenido)
                continue

            if tipo == "GET" and codigo == 200:
                try:
                    datos = json.loads(contenido)
                    interfaces = datos.get("ietf-interfaces:interfaces", {}).get("interface", [])
                    interfaz = next((i for i in interfaces if i.get("name") == nombre), None)
                    if interfaz is None:
                        mostrar_error(f"Interfaz {nombre} no encontrada - HTTP 404 (búsqueda local)")
                        continue
                    ipv4 = interfaz.get("ietf-ip:ipv4", {})
                    direcciones = ipv4.get("address", [])
                    ip = direcciones[0].get("ip", "Sin asignar") if direcciones else "Sin asignar"
                    mascara = direcciones[0].get("netmask", "Sin asignar") if direcciones else "Sin asignar"
                    habilitada = interfaz.get("enabled", True)
                    estado = "Habilitada" if habilitada else "Deshabilitada"
                    escribir_resultado(
                        f"Interfaz: {nombre}\n"
                        f"Dirección IP: {ip}\n"
                        f"Máscara: {mascara}\n"
                        f"Estado administrativo: {estado}\n"
                        f"Código HTTP: {codigo}"
                    )
                    actualizar_estado("Operación exitosa - HTTP 200", True)
                    print("STATUS OK:", codigo)
                except (ValueError, TypeError, KeyError, IndexError) as error:
                    mostrar_error(f"Error al interpretar JSON: {error}")
            elif tipo == "PUT" and codigo in (200, 201, 204):
                actualizar_estado(f"Operación exitosa - HTTP {codigo}", True)
                escribir_resultado(f"Interfaz {nombre} creada o actualizada.\nCódigo HTTP: {codigo}")
                print("STATUS OK:", codigo)
                messagebox.showinfo("Operación exitosa", f"Interfaz {nombre} creada o actualizada.\nCódigo HTTP: {codigo}")
            elif tipo == "DELETE" and 200 <= codigo <= 299:
                actualizar_estado(f"Eliminación exitosa - HTTP {codigo}", True)
                escribir_resultado(f"Interfaz {nombre} eliminada.\nCódigo HTTP: {codigo}")
                print("STATUS OK:", codigo)
                messagebox.showinfo("Eliminación exitosa", f"Interfaz {nombre} eliminada.\nCódigo HTTP: {codigo}")
            else:
                mensaje = f"Error RESTCONF - HTTP {codigo}"
                actualizar_estado(mensaje, False)
                escribir_resultado(f"{mensaje}\n{contenido}")
                messagebox.showerror("Error RESTCONF", f"{mensaje}\n{contenido[:700]}")
    except queue.Empty:
        pass
    ventana.after(100, procesar_respuestas)


def consultar_interfaz():
    nombre = entrada_interfaz.get().strip()
    if not nombre:
        mostrar_error("Escribe el nombre de una interfaz.")
        return
    enviar_operacion("GET", BASE_URL, nombre=nombre)


def crear_interfaz():
    nombre = entrada_nombre.get().strip()
    ip = entrada_ip.get().strip()
    mascara = entrada_mascara.get().strip()
    descripcion = entrada_descripcion.get().strip()

    if not all((nombre, ip, mascara, descripcion)):
        mostrar_error("Completa todos los campos del formulario.")
        messagebox.showwarning("Datos incompletos", "Completa todos los campos.")
        return
    if not permitir_loopback(nombre):
        mostrar_error("Usa una Loopback de prueba, sin modificar las interfaces protegidas.")
        messagebox.showwarning("Interfaz no permitida", "Usa una interfaz Loopback de prueba; Loopback0, Loopback10 y Loopback109 están protegidas.")
        return
    try:
        ipaddress.IPv4Address(ip)
        ipaddress.IPv4Network(f"0.0.0.0/{mascara}")
    except ValueError:
        mostrar_error("Dirección IPv4 o máscara no válida.")
        messagebox.showwarning("Datos no válidos", "Revisa la dirección IPv4 y la máscara.")
        return

    yangConfig = {
        "ietf-interfaces:interface": {
            "name": nombre,
            "description": descripcion,
            "type": "iana-if-type:softwareLoopback",
            "enabled": True,
            "ietf-ip:ipv4": {"address": [{"ip": ip, "netmask": mascara}]},
            "ietf-ip:ipv6": {},
        }
    }
    enviar_operacion("PUT", f"{BASE_URL}/interface={nombre}", yangConfig, nombre)


def eliminar_interfaz():
    nombre = entrada_nombre.get().strip()
    if not nombre:
        mostrar_error("Escribe el nombre de la interfaz que deseas eliminar.")
        return
    if not permitir_loopback(nombre):
        mostrar_error("Solo se permite eliminar Loopbacks de prueba no protegidas.")
        messagebox.showwarning("Interfaz no permitida", "No puedes eliminar las interfaces protegidas del Sandbox.")
        return
    if not messagebox.askyesno("Confirmar eliminación", f"¿Estás seguro de eliminar la interfaz {nombre}?"):
        actualizar_estado("Eliminación cancelada por el usuario.", None)
        return
    enviar_operacion("DELETE", f"{BASE_URL}/interface={nombre}", nombre=nombre)


ventana = tk.Tk()
ventana.title("RESTCONF con Python y Tkinter")
ventana.geometry("850x750")
ventana.minsize(680, 630)

barra_estado = tk.Label(
    ventana, text="Estado: Esperando operación...", font=("Arial", 11),
    bg="#D9D9D9", fg="black", anchor="w", padx=15, pady=10,
)
barra_estado.pack(side=tk.BOTTOM, fill=tk.X)

titulo = tk.Label(ventana, text="Buscador de Interfaces RESTCONF", font=("Arial", 18, "bold"))
titulo.pack(pady=12)
tk.Label(ventana, text="edgar harim", font=("Arial", 12)).pack(pady=5)
tk.Label(ventana, text="Nombre de la interfaz:").pack(pady=5)
entrada_interfaz = tk.Entry(ventana, width=40)
entrada_interfaz.pack(pady=5)
boton_consultar = tk.Button(ventana, text="Consultar Interfaz", command=consultar_interfaz)
boton_consultar.pack(pady=12)

formulario = tk.LabelFrame(
    ventana, text="Configuración de Interfaces",
    font=("Arial", 12, "bold"), padx=15, pady=12,
)
formulario.pack(pady=8)

def campo(texto, fila):
    tk.Label(formulario, text=texto).grid(row=fila, column=0, padx=10, pady=5, sticky="e")
    entrada = tk.Entry(formulario, width=30)
    entrada.grid(row=fila, column=1, padx=10, pady=5)
    return entrada

entrada_nombre = campo("Nombre de Interfaz:", 0)
entrada_ip = campo("Dirección IP:", 1)
entrada_mascara = campo("Máscara:", 2)
entrada_descripcion = campo("Descripción:", 3)

boton_crear = tk.Button(formulario, text="Crear/Actualizar Interfaz", command=crear_interfaz)
boton_crear.grid(row=4, column=0, columnspan=2, pady=10)
boton_eliminar = tk.Button(formulario, text="Eliminar Interfaz", command=eliminar_interfaz)
boton_eliminar.grid(row=5, column=0, columnspan=2, pady=8)

resultado = tk.Text(ventana, width=85, height=7, wrap="word", state="disabled")
resultado.pack(pady=10, padx=16, fill=tk.BOTH, expand=True)

botones = (boton_consultar, boton_crear, boton_eliminar)
ventana.after(100, procesar_respuestas)
ventana.mainloop()
