"""
Script para probar el agente coordinador (CoordinatorAgent) de forma independiente.
Este script permite ejecutar el agente coordinador directamente desde la línea de comandos.
"""

import asyncio
import os
import time
from datetime import datetime

from app.agent.coordinator import CoordinatorAgent
from app.logger import logger

async def print_progress(message: str):
    """Función de callback para mostrar el progreso del agente coordinador."""
    # Mostrar mensajes de estado especiales con formato
    if "__special_status__:" in message:
        status_msg = message.split("__special_status__:")[1].strip()
        print(f"[ESTADO] {status_msg}")
    # Actualizar árbol de archivos si es necesario
    elif message == "__refresh_file_tree__":
        print("[SISTEMA] Actualizando árbol de archivos...")
    # Mostrar otros mensajes normalmente
    else:
        print(f"[INFO] {message}")

async def run_coordinator():
    """Ejecuta el agente coordinador con una solicitud del usuario."""
    # Crear directorio workspace si no existe
    os.makedirs("workspace", exist_ok=True)

    # Crear agente coordinador
    agent = CoordinatorAgent()
    agent.set_progress_callback(print_progress)

    try:
        # Obtener prompt del usuario
        prompt = input("Ingresa tu solicitud para OpenManus: ")

        if not prompt.strip():
            logger.warning("Prompt vacío proporcionado.")
            return

        print("\n==== Iniciando ejecución del Coordinador ====")
        print(f"Fecha/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Solicitud: {prompt}")
        print("==============================================\n")

        # Registrar tiempo de inicio
        start_time = time.time()

        # Ejecutar el agente coordinador
        result = await agent.run(prompt)

        # Calcular tiempo de ejecución
        elapsed_time = time.time() - start_time

        print("\n==== Ejecución completada ====")
        print(f"Tiempo total: {elapsed_time:.2f} segundos")
        print(f"Resultado: {result}")
        print("==============================\n")

        # Mostrar ruta al archivo TODO.md
        todo_path = agent.todo_file_path
        if os.path.exists(todo_path):
            print(f"El archivo TODO.md se ha creado en: {todo_path}")
            print("Contenido del TODO.md:")
            with open(todo_path, "r") as f:
                print("\n" + f.read())

    except KeyboardInterrupt:
        print("\nOperación cancelada por el usuario.")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        print(f"\nSe produjo un error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(run_coordinator())
