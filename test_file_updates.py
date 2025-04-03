import asyncio
import os
import sys
import random
import string
import time

# Agregar el directorio actual al path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.agent.manus import Manus

async def test_file_updates():
    """Prueba la funcionalidad de actualizaciones en tiempo real del árbol de archivos."""

    # Crear el directorio workspace si no existe
    workspace_path = os.path.join(os.getcwd(), "workspace")
    os.makedirs(workspace_path, exist_ok=True)

    # Generar un ID aleatorio para los archivos
    random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

    # Callback para mostrar mensajes de progreso
    async def progress_callback(message):
        print(f"[PROGRESO]: {message}")

    # Crear una instancia de Manus y configurar el callback
    agent = Manus()
    agent.set_progress_callback(progress_callback)

    # Crear un prompt que creará múltiples archivos
    prompt = f"""
    Sigue estos pasos exactamente:
    1. Crea un archivo llamado 'test_file1_{random_id}.txt' con el contenido 'Primer archivo de prueba'
    2. Espera 1 segundo
    3. Crea un archivo llamado 'test_file2_{random_id}.txt' con el contenido 'Segundo archivo de prueba'
    4. Espera 1 segundo
    5. Crea un directorio llamado 'test_dir_{random_id}'
    6. Crea un archivo dentro de ese directorio llamado 'test_subfile_{random_id}.txt'
    7. Termina
    """

    print("=== Iniciando prueba de actualizaciones en tiempo real ===")
    print(f"Prompt:\n{prompt}")

    # Ejecutar Manus
    result = await agent.run(prompt)

    print("\n=== Prueba completada ===")
    print(f"Resultado: {result}")

    # Verificar que se hayan creado los archivos
    file1 = os.path.join(workspace_path, f"test_file1_{random_id}.txt")
    file2 = os.path.join(workspace_path, f"test_file2_{random_id}.txt")
    dir_path = os.path.join(workspace_path, f"test_dir_{random_id}")
    subfile = os.path.join(dir_path, f"test_subfile_{random_id}.txt")

    files_created = []
    if os.path.exists(file1):
        files_created.append(file1)
    if os.path.exists(file2):
        files_created.append(file2)
    if os.path.exists(dir_path) and os.path.isdir(dir_path):
        files_created.append(dir_path)
    if os.path.exists(subfile):
        files_created.append(subfile)

    print(f"\nArchivos creados ({len(files_created)}/{4}):")
    for file_path in files_created:
        if os.path.isdir(file_path):
            print(f"- Directorio: {os.path.basename(file_path)}")
        else:
            with open(file_path, 'r') as f:
                content = f.read()
            print(f"- Archivo: {os.path.basename(file_path)}, Contenido: {content}")

    if len(files_created) == 4:
        print("\nTEST EXITOSO: Todos los archivos fueron creados correctamente")
    else:
        print(f"\nTEST FALLIDO: Solo se crearon {len(files_created)} de 4 archivos esperados")

if __name__ == "__main__":
    asyncio.run(test_file_updates())
