import asyncio
import logging
import os
import sys
import random
import string

# Configurar el logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Agregar el directorio actual al path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.web.server import create_app
from app.agent.manus import Manus

async def test_feedback():
    """Prueba la funcionalidad de feedback de OpenManus"""

    # Crear el directorio workspace si no existe
    workspace_path = os.path.join(os.getcwd(), "workspace")
    os.makedirs(workspace_path, exist_ok=True)

    # Crear un archivo simple en el workspace para probar modificaciones
    test_file_path = os.path.join(workspace_path, "test_file.txt")
    with open(test_file_path, "w") as f:
        f.write("Este es un archivo de prueba\n")

    print("=== Configurando el test de feedback de OpenManus ===")
    print(f"Archivo de prueba creado: {test_file_path}")

    # Definir un callback simple para mostrar el progreso
    async def progress_callback(message):
        print(f"[PROGRESO]: {message}")

    # Crear una instancia de Manus y configurar el callback
    agent = Manus()
    agent.set_progress_callback(progress_callback)

    # Generar un prompt simple para ejecutar
    random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    prompt = f"Crea un archivo llamado test_resultado_{random_id}.txt en el directorio workspace con el contenido 'Prueba exitosa'"

    print(f"\n=== Ejecutando OpenManus con el prompt: ===\n{prompt}\n")

    # Ejecutar OpenManus
    result = await agent.run(prompt)

    print("\n=== Ejecución completada ===")
    print(f"Resultado: {result}")

    # Verificar que se haya creado el archivo
    expected_file = os.path.join(workspace_path, f"test_resultado_{random_id}.txt")
    if os.path.exists(expected_file):
        with open(expected_file, "r") as f:
            content = f.read()
        print(f"\n=== Archivo creado: {expected_file} ===")
        print(f"Contenido: {content}")
        print("TEST EXITOSO: El archivo fue creado correctamente")
    else:
        print(f"TEST FALLIDO: No se encontró el archivo {expected_file}")

if __name__ == "__main__":
    asyncio.run(test_feedback())
