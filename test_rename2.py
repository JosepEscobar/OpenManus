"""
Script de prueba para solicitar a OpenManus renombrar un archivo adicional.
"""
import asyncio
import json
import time
from datetime import datetime
import websockets

async def test_rename():
    # Conectar al WebSocket
    uri = "ws://localhost:8001/ws"
    async with websockets.connect(uri) as websocket:
        print("Conectado al servidor WebSocket")

        # Recibir mensajes iniciales
        status_msg = await websocket.recv()
        print(f"Estado recibido: {status_msg}")

        tree_msg = await websocket.recv()
        print(f"Árbol de archivos recibido: {json.loads(tree_msg)['type']}")

        # Enviar un mensaje para renombrar un archivo
        message = {
            "type": "chat",
            "content": "Renombra el archivo otro_archivo.txt a archivo_editado.md y cambia su contenido a '# Archivo editado y renombrado\n\nEste archivo ha sido renombrado y editado exitosamente por OpenManus.'",
            "sender": "user",
            "timestamp": datetime.now().isoformat()
        }

        print(f"Enviando mensaje: {message['content']}")
        await websocket.send(json.dumps(message))

        # Esperar y recibir respuestas
        try:
            completed = False
            for _ in range(20):  # Esperar hasta 20 mensajes o 60 segundos
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                response_data = json.loads(response)
                print(f"Tipo de respuesta: {response_data.get('type', 'desconocido')}")

                if response_data.get('type') == 'chat':
                    print(f"Mensaje de chat: {response_data.get('content', '')}")

                    # Si recibimos un mensaje de completado o archivo renombrado, terminar
                    if "Solicitud completada exitosamente" in response_data.get('content', ''):
                        completed = True
                    elif "archivo renombrado" in response_data.get('content', ''):
                        print("¡Archivo renombrado con éxito!")

                if completed and response_data.get('type') == 'fileContent':
                    print(f"Contenido del archivo:\n{response_data.get('content', '')}")
                    break

        except asyncio.TimeoutError:
            print("Tiempo de espera agotado")

        print("Prueba completada")

if __name__ == "__main__":
    asyncio.run(test_rename())
