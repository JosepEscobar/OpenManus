"""
Script de prueba para comunicarse con el servidor WebSocket de OpenManus.
"""
import asyncio
import json
import time
from datetime import datetime
import websockets

async def test_websocket():
    # Conectar al WebSocket
    uri = "ws://localhost:8001/ws"
    async with websockets.connect(uri) as websocket:
        print("Conectado al servidor WebSocket")

        # Recibir mensajes iniciales
        status_msg = await websocket.recv()
        print(f"Estado recibido: {status_msg}")

        tree_msg = await websocket.recv()
        print(f"Árbol de archivos recibido: {json.loads(tree_msg)['type']}")

        # Enviar un mensaje de prueba
        message = {
            "type": "chat",
            "content": "Crea un archivo llamado test_file.md con el contenido 'Esto es una prueba desde WebSocket'",
            "sender": "user",
            "timestamp": datetime.now().isoformat()
        }

        print(f"Enviando mensaje: {message['content']}")
        await websocket.send(json.dumps(message))

        # Esperar y recibir respuestas
        try:
            for _ in range(10):  # Esperar hasta 10 mensajes o 30 segundos
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                print(f"Respuesta recibida: {response}")

                # Si recibimos un mensaje de completado, salir del bucle
                if "Solicitud completada exitosamente" in response:
                    break

        except asyncio.TimeoutError:
            print("Tiempo de espera agotado")

        print("Prueba completada")

if __name__ == "__main__":
    asyncio.run(test_websocket())
