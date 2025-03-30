"""
Script de prueba final para solicitar a OpenManus que use explícitamente el comando rename.
"""
import asyncio
import json
import time
import os
from datetime import datetime
import websockets

async def test_rename_specific():
    # Crear un archivo de prueba
    test_file_path = os.path.join(os.getcwd(), "workspace", "prueba_final.txt")
    with open(test_file_path, "w") as f:
        f.write("Este es un archivo de prueba final.\nVamos a renombrarlo explícitamente.")

    print(f"Archivo creado: {test_file_path}")

    # Conectar al WebSocket
    uri = "ws://localhost:8001/ws"
    async with websockets.connect(uri) as websocket:
        print("Conectado al servidor WebSocket")

        # Recibir mensajes iniciales
        status_msg = await websocket.recv()
        print(f"Estado recibido: {status_msg}")

        tree_msg = await websocket.recv()
        print(f"Árbol de archivos recibido: {json.loads(tree_msg)['type']}")

        # Enviar un mensaje para renombrar un archivo utilizando explícitamente el comando rename
        message = {
            "type": "chat",
            "content": "Usa el comando 'rename' para cambiar el nombre del archivo 'prueba_final.txt' a 'prueba_exitosa.md' y luego modifica su contenido para que diga '# Prueba exitosa\n\nEl archivo ha sido renombrado correctamente usando el comando rename.'",
            "sender": "user",
            "timestamp": datetime.now().isoformat()
        }

        print(f"Enviando mensaje: {message['content']}")
        await websocket.send(json.dumps(message))

        # Esperar y recibir respuestas
        try:
            completed = False
            file_renamed = False

            for _ in range(30):  # Aumentamos el número de intentos
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                response_data = json.loads(response)
                print(f"Tipo de respuesta: {response_data.get('type', 'desconocido')}")

                if response_data.get('type') == 'chat':
                    content = response_data.get('content', '')
                    print(f"Mensaje de chat: {content}")

                    # Detectar mensajes específicos
                    if "Solicitud completada exitosamente" in content:
                        completed = True
                        print("Solicitud completada")
                    elif "archivo renombrado" in content.lower():
                        file_renamed = True
                        print("¡Archivo renombrado con éxito!")

                # Si hemos completado la solicitud y recibimos el contenido del archivo, salimos
                if completed and response_data.get('type') == 'fileContent':
                    print(f"Contenido del archivo:\n{response_data.get('content', '')}")
                    break

            # Verificar resultados después del bucle
            print("\nResultados de la prueba:")
            old_file_exists = os.path.exists(test_file_path)
            new_file_path = os.path.join(os.getcwd(), "workspace", "prueba_exitosa.md")
            new_file_exists = os.path.exists(new_file_path)

            print(f"¿El archivo original sigue existiendo? {old_file_exists}")
            print(f"¿El archivo renombrado existe? {new_file_exists}")

            if new_file_exists:
                with open(new_file_path, "r") as f:
                    print(f"Contenido del archivo renombrado:\n{f.read()}")

            # La prueba es exitosa si el archivo original no existe y el nuevo sí
            if not old_file_exists and new_file_exists:
                print("\n¡PRUEBA EXITOSA! OpenManus renombró correctamente el archivo.")
            else:
                print("\nPRUEBA FALLIDA: OpenManus no renombró correctamente el archivo.")

        except asyncio.TimeoutError:
            print("Tiempo de espera agotado")

        print("\nPrueba completada")

if __name__ == "__main__":
    asyncio.run(test_rename_specific())
