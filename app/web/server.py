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
            "action": truncate_text(self.current_action, 50)
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
                "content": truncate_text("OpenManus ya está procesando una solicitud. Por favor, espera a que termine.", 500),
                "sender": "assistant",
                "timestamp": datetime.now().isoformat()
            })
            return

        # Mostrar mensaje inicial para feedback inmediato
        await self.broadcast({
            "type": "chat",
            "content": truncate_text("Entendido, procesando tu solicitud...", 500),
            "sender": "assistant",
            "timestamp": timestamp
        })

        # Cambiar el estado a "thinking"
        await self.update_status("thinking", truncate_text(f"Analizando: {content}", 150))

        try:
            # Marcar que Manus está ejecutándose
            self.manus_running = True

            # Crear una nueva instancia de Manus para cada solicitud
            agent = Manus()

            # Configurar el callback para enviar actualizaciones de progreso
            async def progress_callback(message):
                # Verificar si es una señal especial para actualizar el árbol de archivos
                if message == "__refresh_file_tree__":
                    # Actualizar y enviar el árbol de archivos en tiempo real
                    await self.send_file_tree()
                    return

                # Enviar mensaje al chat solo si es una notificación importante sobre archivos
                should_send_to_chat = any([
                    "Cambios realizados:" in message,
                    "Error al procesar la solicitud:" in message,
                    "Tarea completada exitosamente" in message,
                    message == "Entendido, procesando tu solicitud..."
                ])

                # Actualizar el estado en base al contenido del mensaje
                if "__special_status__:" in message:
                    # Formato especial para actualizar directamente el estado
                    status_msg = message.split("__special_status__:")[1].strip()

                    # Decidir entre estado "thinking" o "working" según el mensaje
                    status_type = "thinking" if any([
                        "Analizando" in status_msg,
                        "Consultando" in status_msg,
                        "Evaluando" in status_msg,
                        "Reflexionando" in status_msg,
                        "Desarrollando" in status_msg
                    ]) else "working"

                    await self.update_status(status_type, truncate_text(status_msg, 150))
                elif "OpenManus está pensando" in message:
                    await self.update_status("thinking", truncate_text("Analizando el problema...", 150))
                elif "Consultando al LLM" in message:
                    await self.update_status("thinking", truncate_text("Generando solución...", 150))
                elif "Usando herramienta:" in message:
                    herramienta = message.replace("Usando herramienta:", "").strip()
                    await self.update_status("working", truncate_text(f"Usando {herramienta}...", 150))
                elif "Ejecutando " in message and "..." in message:
                    accion = message.replace("Ejecutando ", "").replace("...", "").strip()
                    await self.update_status("working", truncate_text(f"Ejecutando {accion}", 150))
                elif "Completada la ejecución de" in message:
                    await self.update_status("working", truncate_text("Procesando resultados...", 150))
                elif "Error" in message or "error" in message:
                    await self.update_status("error", truncate_text(message[:150], 150))
                elif "Ejecutando paso" in message:
                    step_info = message.replace("Ejecutando paso", "").strip()
                    await self.update_status("working", truncate_text(f"Paso {step_info}", 150))
                elif "Pensamiento:" in message:
                    await self.update_status("thinking", truncate_text("Analizando solución...", 150))

                # Para mensajes importantes, enviarlos como chat
                if should_send_to_chat:
                    await self.broadcast({
                        "type": "chat",
                        "content": truncate_text(message, 500),
                        "sender": "assistant",
                        "timestamp": datetime.now().isoformat()
                    })

            # Establecer el callback en el agente
            agent.set_progress_callback(progress_callback)

            # Registrar el tiempo de inicio para detectar archivos nuevos
            start_time = datetime.now().timestamp()

            # Tomar una instantánea del árbol de archivos antes
            workspace_path = os.path.join(os.getcwd(), "workspace")
            files_before = {}
            files_before_set = set()

            if os.path.exists(workspace_path):
                for root, dirs, files in os.walk(workspace_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        files_before[file_path] = {
                            "path": file_path,
                            "mtime": os.path.getmtime(file_path),
                            "size": os.path.getsize(file_path),
                            "name": file
                        }
                        files_before_set.add(file_path)

            # Ejecutar Manus directamente con el prompt del usuario
            logger.info(f"Ejecutando OpenManus con prompt: {content}")
            await agent.run(content)

            # Obtener archivos creados durante la ejecución
            files_after = {}
            files_after_set = set()

            if os.path.exists(workspace_path):
                for root, dirs, files in os.walk(workspace_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        files_after[file_path] = {
                            "path": file_path,
                            "mtime": os.path.getmtime(file_path),
                            "size": os.path.getsize(file_path),
                            "name": file
                        }
                        files_after_set.add(file_path)

            # Detectar cambios en los archivos
            newly_created_files = []
            modified_files = []
            renamed_files = []

            # Archivos nuevos (no existían antes)
            new_files = files_after_set - files_before_set
            for file_path in new_files:
                # Verificar si podría ser un archivo renombrado
                is_rename = False
                for old_path in files_before_set - files_after_set:
                    if (files_before[old_path]["size"] == files_after[file_path]["size"] or
                        files_before[old_path]["name"] == files_after[file_path]["name"]):
                        # Es probable que sea un archivo renombrado
                        renamed_files.append({
                            "old_path": old_path,
                            "new_path": file_path
                        })
                        is_rename = True
                        break

                if not is_rename:
                    newly_created_files.append(file_path)

            # Archivos modificados (existían antes pero han cambiado)
            for file_path in files_before_set.intersection(files_after_set):
                if files_after[file_path]["mtime"] > start_time:
                    modified_files.append(file_path)

            # Enviar actualizaciones sobre archivos modificados
            if newly_created_files or modified_files or renamed_files:
                # Preparar resumen de cambios en archivos
                changes_summary = []

                if newly_created_files:
                    if len(newly_created_files) <= 3:
                        created_files_paths = [os.path.relpath(p, workspace_path) for p in newly_created_files]
                        changes_summary.append(f"Creados: {', '.join(created_files_paths)}")
                    else:
                        changes_summary.append(f"Creados: {len(newly_created_files)} archivos")

                if modified_files:
                    if len(modified_files) <= 3:
                        modified_files_paths = [os.path.relpath(p, workspace_path) for p in modified_files]
                        changes_summary.append(f"Modificados: {', '.join(modified_files_paths)}")
                    else:
                        changes_summary.append(f"Modificados: {len(modified_files)} archivos")

                if renamed_files:
                    if len(renamed_files) <= 3:
                        renamed_paths = [f"{os.path.relpath(r['old_path'], workspace_path)} → {os.path.relpath(r['new_path'], workspace_path)}" for r in renamed_files]
                        changes_summary.append(f"Renombrados: {', '.join(renamed_paths)}")
                    else:
                        changes_summary.append(f"Renombrados: {len(renamed_files)} archivos")

                # Enviar un único mensaje con todos los cambios
                await self.broadcast({
                    "type": "chat",
                    "content": truncate_text(f"Cambios realizados: {'. '.join(changes_summary)}", 500),
                    "sender": "assistant",
                    "timestamp": datetime.now().isoformat()
                })

                # Actualizar el estado
                await self.update_status("working", truncate_text("Archivos actualizados", 150))

            # Notificar que la solicitud se completó
            await self.broadcast({
                "type": "chat",
                "content": truncate_text("Tarea completada exitosamente.", 500),
                "sender": "assistant",
                "timestamp": datetime.now().isoformat()
            })

            # Actualizar el árbol de archivos
            await self.send_file_tree()

            # Determinar qué archivo debemos mostrar
            file_to_show = None
            file_action = None

            # Prioridad: Renombrado > Modificado > Creado
            if renamed_files:
                file_to_show = renamed_files[0]["new_path"]
                file_action = "renombrado"
            elif modified_files:
                file_to_show = modified_files[0]
                file_action = "modificado"
            elif newly_created_files:
                file_to_show = newly_created_files[0]
                file_action = "creado"

            # Si se encontró un archivo para mostrar
            if file_to_show:
                # Enviar notificación para seleccionar el archivo
                await self.send_select_file_notification(file_to_show)

                # Enviar el contenido del archivo
                file_content = get_file_content(file_to_show)
                await self.send_file_content(file_to_show, file_content)

                # Actualizar el estado para mostrar qué archivo se seleccionó
                await self.update_status("idle", truncate_text(f"Archivo {file_action}: {os.path.basename(file_to_show)}", 150))

        except Exception as e:
            logger.error(f"Error al procesar el prompt: {e}")
            error_msg = str(e)

            # Simplificar el mensaje de error para el usuario
            if len(error_msg) > 100:
                error_msg = error_msg[:100] + "..."

            # Enviar mensaje de error al chat
            await self.broadcast({
                "type": "chat",
                "content": truncate_text(f"Error: {error_msg}", 500),
                "sender": "assistant",
                "timestamp": datetime.now().isoformat()
            })

            # Actualizar el estado para mostrar que hubo un error
            await self.update_status("error", truncate_text(f"Error: {error_msg}", 150))
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

def truncate_text(text, max_length=500):
    """Acorta el texto si excede la longitud máxima."""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

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
