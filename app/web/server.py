import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Set, Union

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.logger import logger
from app.agent.manus import Manus

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
        self.manus_running = False

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
        """
        Procesa un mensaje de chat enviándolo directamente a OpenManus.
        No realiza ningún procesamiento intermedio, simplemente pasa el prompt.
        """
        # Si Manus ya está ejecutándose, no permitimos iniciar otra instancia
        if self.manus_running:
            await self.broadcast({
                "type": "chat",
                "content": "OpenManus ya está procesando una solicitud. Por favor, espera a que termine.",
                "sender": "assistant",
                "timestamp": datetime.now().isoformat()
            })
            return

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
            # Marcar que Manus está ejecutándose
            self.manus_running = True

            # Crear una nueva instancia de Manus para cada solicitud
            agent = Manus()

            # Registrar el tiempo de inicio para detectar archivos nuevos
            start_time = datetime.now().timestamp()

            # Tomar una instantánea del árbol de archivos antes
            workspace_path = os.path.join(os.getcwd(), "workspace")
            files_before = set()
            if os.path.exists(workspace_path):
                for root, dirs, files in os.walk(workspace_path):
                    for file in files:
                        files_before.add(os.path.join(root, file))

            # Ejecutar Manus directamente con el prompt del usuario
            logger.info(f"Ejecutando OpenManus con prompt: {content}")
            await agent.run(content)

            # Obtener archivos creados durante la ejecución
            files_after = set()
            newly_created_files = []
            if os.path.exists(workspace_path):
                for root, dirs, files in os.walk(workspace_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        files_after.add(file_path)
                        # Si el archivo es nuevo o modificado
                        if file_path not in files_before or os.path.getmtime(file_path) > start_time:
                            newly_created_files.append(file_path)

            # Notificar que la solicitud se completó
            await self.broadcast({
                "type": "chat",
                "content": "Solicitud completada exitosamente.",
                "sender": "assistant",
                "timestamp": datetime.now().isoformat()
            })

            # Actualizar el árbol de archivos
            await self.send_file_tree()

            # Si se crearon nuevos archivos, mostrar el primero
            if newly_created_files:
                # Ordenar por tiempo de modificación (más reciente primero)
                newly_created_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                latest_file = newly_created_files[0]

                # Enviar notificación para seleccionar el archivo
                await self.send_select_file_notification(latest_file)

                # Enviar el contenido del archivo
                file_content = get_file_content(latest_file)
                await self.send_file_content(latest_file, file_content)

                # Informar al usuario
                await self.broadcast({
                    "type": "chat",
                    "content": f"Se ha seleccionado automáticamente el archivo recién creado: {os.path.basename(latest_file)}",
                    "sender": "assistant",
                    "timestamp": datetime.now().isoformat()
                })

        except Exception as e:
            logger.error(f"Error al procesar el prompt: {e}")
            await self.broadcast({
                "type": "chat",
                "content": f"Error al procesar la solicitud: {str(e)}",
                "sender": "assistant",
                "timestamp": datetime.now().isoformat()
            })
        finally:
            # Marcar que Manus ha terminado
            self.manus_running = False

            # Cambiar el estado a "idle" al finalizar
            await self.update_status("idle", "Esperando instrucciones")

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

                        # Procesar el mensaje directamente con OpenManus
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
