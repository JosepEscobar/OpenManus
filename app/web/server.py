import asyncio
import json
import logging
import os
import re
from typing import Dict, List, Optional, Set, Union

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.logger import logger

# Modelos para los mensajes
class Message(BaseModel):
    type: str
    content: Optional[str] = None
    timestamp: Optional[str] = None
    sender: Optional[str] = None
    path: Optional[str] = None
    tree: Optional[List[dict]] = None
    files: Optional[List[str]] = None
    status: Optional[str] = None
    action: Optional[str] = None

class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.file_tree: List[dict] = []
        self.active_files: Set[str] = set()
        self.status: str = "idle"
        self.current_action: str = ""

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Cliente conectado. Total de conexiones: {len(self.active_connections)}")
        # Enviar el estado inicial
        await self.send_status(websocket)
        await self.send_file_tree(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_text(json.dumps(message))

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        await websocket.send_text(json.dumps(message))

    async def send_file_tree(self, websocket: Optional[WebSocket] = None):
        # Actualizar el árbol de archivos antes de enviarlo
        workspace_path = os.path.join(os.getcwd(), "workspace")
        if os.path.exists(workspace_path):
            self.file_tree = scan_directory(workspace_path)

        message = {
            "type": "fileTree",
            "tree": self.file_tree
        }
        if websocket:
            await self.send_personal_message(message, websocket)
        else:
            await self.broadcast(message)

    async def send_file_content(self, path: str, content: str, websocket: Optional[WebSocket] = None):
        message = {
            "type": "fileContent",
            "path": path,
            "content": content
        }
        if websocket:
            await self.send_personal_message(message, websocket)
        else:
            await self.broadcast(message)

    async def send_status(self, websocket: Optional[WebSocket] = None):
        message = {
            "type": "status",
            "status": self.status,
            "action": self.current_action
        }
        if websocket:
            await self.send_personal_message(message, websocket)
        else:
            await self.broadcast(message)

    async def update_status(self, status: str, action: str):
        self.status = status
        self.current_action = action
        await self.send_status()

    def set_file_tree(self, tree: List[dict]):
        self.file_tree = tree

    def set_active_files(self, files: List[str]):
        self.active_files = set(files)

    async def send_active_files(self):
        message = {
            "type": "activeFiles",
            "files": list(self.active_files)
        }
        await self.broadcast(message)

    async def send_select_file_notification(self, path: str):
        """Envía una notificación para seleccionar un archivo en el explorador."""
        message = {
            "type": "selectFile",
            "path": path
        }
        await self.broadcast(message)

    async def process_chat_message(self, content: str, timestamp: str, websocket: WebSocket):
        """Procesa un mensaje de chat y ejecuta comandos simples."""
        # Mostrar el eco del mensaje para feedback inmediato
        await self.broadcast({
            "type": "chat",
            "content": f"Echo: {content}",
            "sender": "assistant",
            "timestamp": timestamp
        })

        # Cambiar el estado a "thinking"
        await self.update_status("thinking", f"Procesando: {content}")

        try:
            # Procesar comandos básicos
            if "crea un archivo" in content.lower() or "crear un archivo" in content.lower():
                file_path = await self.create_file(content, timestamp)
                if file_path:
                    # Enviar notificación para seleccionar el archivo
                    await self.send_select_file_notification(file_path)
                    # Enviar el contenido del archivo
                    content = get_file_content(file_path)
                    await self.send_file_content(file_path, content)
            elif "crea un directorio" in content.lower() or "crear un directorio" in content.lower():
                await self.create_directory(content, timestamp)
            else:
                await self.broadcast({
                    "type": "chat",
                    "content": "Lo siento, solo puedo procesar comandos básicos como crear archivos o directorios por ahora.",
                    "sender": "assistant",
                    "timestamp": timestamp
                })
        except Exception as e:
            logger.error(f"Error al procesar el prompt: {e}")
            await self.broadcast({
                "type": "chat",
                "content": f"Error al procesar la solicitud: {str(e)}",
                "sender": "assistant",
                "timestamp": timestamp
            })
        finally:
            # Cambiar el estado a "idle" al finalizar
            await self.update_status("idle", "Esperando instrucciones")

    async def create_file(self, content: str, timestamp: str):
        """Crea un archivo en el workspace basado en el mensaje."""
        # Extraer nombre del archivo
        file_match = re.search(r'llama[a-z]{0,2} (\w+\.\w+)', content.lower())
        if not file_match:
            file_match = re.search(r'archivo (?:llamado )?(\w+\.\w+)', content.lower())

        if not file_match:
            await self.broadcast({
                "type": "chat",
                "content": "No pude detectar el nombre del archivo. Por favor, especifica el nombre claramente, por ejemplo: 'Crea un archivo llamado ejemplo.txt'.",
                "sender": "assistant",
                "timestamp": timestamp
            })
            return None

        filename = file_match.group(1)

        # Extraer contenido
        content_match = re.search(r'contenido [\'"](.+?)[\'"]', content, re.DOTALL)
        file_content = content_match.group(1) if content_match else "# Archivo creado por OpenManus\n\nEste es un archivo de ejemplo."

        # Crear el archivo en el workspace
        workspace_path = os.path.join(os.getcwd(), "workspace")
        file_path = os.path.join(workspace_path, filename)

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(file_content)

            await self.broadcast({
                "type": "chat",
                "content": f"Archivo '{filename}' creado exitosamente.",
                "sender": "assistant",
                "timestamp": timestamp
            })

            # Actualizar el árbol de archivos
            await self.send_file_tree()

            return file_path

        except Exception as e:
            logger.error(f"Error al crear el archivo {filename}: {e}")
            await self.broadcast({
                "type": "chat",
                "content": f"Error al crear el archivo: {str(e)}",
                "sender": "assistant",
                "timestamp": timestamp
            })
            return None

    async def create_directory(self, content: str, timestamp: str):
        """Crea un directorio en el workspace basado en el mensaje."""
        # Extraer nombre del directorio
        dir_match = re.search(r'directorio (?:llamado )?(\w+)', content.lower())

        if not dir_match:
            await self.broadcast({
                "type": "chat",
                "content": "No pude detectar el nombre del directorio. Por favor, especifica el nombre claramente, por ejemplo: 'Crea un directorio llamado ejemplos'.",
                "sender": "assistant",
                "timestamp": timestamp
            })
            return

        dirname = dir_match.group(1)

        # Crear el directorio en el workspace
        workspace_path = os.path.join(os.getcwd(), "workspace")
        dir_path = os.path.join(workspace_path, dirname)

        try:
            os.makedirs(dir_path, exist_ok=True)

            await self.broadcast({
                "type": "chat",
                "content": f"Directorio '{dirname}' creado exitosamente.",
                "sender": "assistant",
                "timestamp": timestamp
            })

            # Actualizar el árbol de archivos
            await self.send_file_tree()

        except Exception as e:
            logger.error(f"Error al crear el directorio {dirname}: {e}")
            await self.broadcast({
                "type": "chat",
                "content": f"Error al crear el directorio: {str(e)}",
                "sender": "assistant",
                "timestamp": timestamp
            })

def scan_directory(path: str) -> List[dict]:
    """Escanea un directorio y devuelve una estructura de árbol de archivos."""
    result = []

    try:
        for item in os.listdir(path):
            item_path = os.path.join(path, item)

            # Ignorar archivos y directorios ocultos
            if item.startswith('.'):
                continue

            if os.path.isdir(item_path):
                result.append({
                    "name": item,
                    "path": item_path,
                    "type": "directory",
                    "children": scan_directory(item_path)
                })
            else:
                result.append({
                    "name": item,
                    "path": item_path,
                    "type": "file"
                })
    except Exception as e:
        logger.error(f"Error al escanear directorio {path}: {e}")

    return result

def get_file_content(path: str) -> str:
    """Lee el contenido de un archivo."""
    try:
        with open(path, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        logger.error(f"Error al leer el archivo {path}: {e}")
        return f"Error al leer el archivo: {str(e)}"

def create_app():
    app = FastAPI(title="OpenManus Web Server")
    manager = WebSocketManager()

    # Configurar CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # En producción, esto debería limitarse a orígenes conocidos
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup_event():
        # Inicializar el árbol de archivos
        workspace_path = os.path.join(os.getcwd(), "workspace")
        if os.path.exists(workspace_path):
            file_tree = scan_directory(workspace_path)
            manager.set_file_tree(file_tree)

        # Inicializar archivos activos (por ejemplo, archivos abiertos)
        manager.set_active_files([])

        # Inicializar estado
        await manager.update_status("idle", "Esperando instrucciones")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    message_data = json.loads(data)
                    message_type = message_data.get("type", "")

                    if message_type == "getFileContent":
                        file_path = message_data.get("path", "")
                        if file_path and os.path.exists(file_path):
                            content = get_file_content(file_path)
                            await manager.send_file_content(file_path, content, websocket)
                        else:
                            await manager.send_personal_message({
                                "type": "error",
                                "message": f"Archivo no encontrado: {file_path}"
                            }, websocket)

                    elif message_type == "refreshFileTree":
                        await manager.send_file_tree()

                    elif message_type == "chat":
                        content = message_data.get("content", "")
                        timestamp = message_data.get("timestamp", "")

                        # Procesar el mensaje con comandos básicos
                        asyncio.create_task(manager.process_chat_message(content, timestamp, websocket))

                except json.JSONDecodeError:
                    await manager.send_personal_message({
                        "type": "error",
                        "message": "Formato de mensaje inválido"
                    }, websocket)

        except WebSocketDisconnect:
            manager.disconnect(websocket)

    # Servir archivos estáticos de la aplicación web
    app.mount("/", StaticFiles(directory="openmanus-web/dist", html=True), name="static")

    return app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.web.server:create_app()", host="0.0.0.0", port=8001, reload=True)
