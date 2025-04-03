import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Set, Union
import time

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.logger import logger
from app.agent.manus import Manus
from app.agent.coordinator import CoordinatorAgent

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
        # Contador de mensajes para seguimiento
        self.message_counter = 0
        # Último momento de actividad para cada conexión
        self.last_activity: Dict[WebSocket, float] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Registrar el momento de conexión
        self.last_activity[websocket] = time.time()
        logger.info(f"Cliente conectado. Total de conexiones: {len(self.active_connections)}")

        # Enviar el estado inicial
        await self.send_status(websocket)
        await self.send_file_tree(websocket)

        # Iniciar tarea de mantenimiento de conexión para este websocket
        asyncio.create_task(self._keep_alive(websocket))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        # Limpiar los datos de seguimiento
        if websocket in self.last_activity:
            del self.last_activity[websocket]
        logger.info(f"Cliente desconectado. Conexiones restantes: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Envía un mensaje a todos los clientes conectados con reintentos si es necesario."""
        self.message_counter += 1
        message_id = self.message_counter

        # Registrar intento de broadcast
        logger.debug(f"[WS:BROADCAST:{message_id}] Enviando mensaje tipo {message.get('type')} a {len(self.active_connections)} clientes")

        # Lista para seguir conexiones con errores
        failed_connections = []

        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
                # Actualizar timestamp de última actividad
                self.last_activity[connection] = time.time()
            except Exception as e:
                logger.error(f"[WS:BROADCAST:{message_id}] Error al enviar mensaje a cliente: {str(e)}")
                failed_connections.append(connection)

        # Limpiar conexiones fallidas
        for failed in failed_connections:
            logger.warning(f"[WS:BROADCAST:{message_id}] Desconectando cliente con error de comunicación")
            try:
                self.disconnect(failed)
            except:
                pass

        # Registrar resultado del broadcast
        if failed_connections:
            logger.warning(f"[WS:BROADCAST:{message_id}] Mensaje enviado a {len(self.active_connections) - len(failed_connections)}/{len(self.active_connections)} clientes")
        else:
            logger.debug(f"[WS:BROADCAST:{message_id}] Mensaje enviado exitosamente a todos los clientes")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Envía un mensaje a un cliente específico con manejo de errores."""
        self.message_counter += 1
        message_id = self.message_counter

        try:
            await websocket.send_text(json.dumps(message))
            # Actualizar timestamp de última actividad
            self.last_activity[websocket] = time.time()
            logger.debug(f"[WS:PERSONAL:{message_id}] Mensaje enviado exitosamente al cliente")
            return True
        except Exception as e:
            logger.error(f"[WS:PERSONAL:{message_id}] Error al enviar mensaje personal: {str(e)}")
            # Intentar desconectar el websocket con error
            try:
                self.disconnect(websocket)
            except:
                pass
            return False

    async def _keep_alive(self, websocket: WebSocket):
        """Mantiene activa la conexión websocket enviando pings periódicos."""
        try:
            while websocket in self.active_connections:
                await asyncio.sleep(30)  # Enviar ping cada 30 segundos

                # Verificar si la conexión sigue activa
                if websocket not in self.active_connections:
                    break

                # Enviar ping
                try:
                    ping_message = {"type": "ping", "timestamp": datetime.now().isoformat()}
                    await websocket.send_text(json.dumps(ping_message))
                    self.last_activity[websocket] = time.time()
                    logger.debug(f"[WS:PING] Enviado ping a cliente")
                except Exception as e:
                    logger.warning(f"[WS:PING] Error al enviar ping, desconectando: {str(e)}")
                    # Si falla el ping, desconectar
                    if websocket in self.active_connections:
                        self.disconnect(websocket)
                    break
        except asyncio.CancelledError:
            logger.debug("[WS:PING] Tarea de keep-alive cancelada")
        except Exception as e:
            logger.error(f"[WS:PING] Error en tarea keep-alive: {str(e)}")

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
            "action": truncate_text(self.current_action, 100)
        }
        if websocket:
            await self.send_personal_message(message, websocket)
        else:
            await self.broadcast(message)

    async def update_status(self, status: str, action: str):
        """Actualiza el estado del sistema y lo envía a todos los clientes conectados."""
        logger.info(f"Actualizando estado a: {status} - {action}")
        self.status = status
        self.current_action = action

        # Asegurar que el mensaje sea enviado inmediatamente
        message = {
            "type": "status",
            "status": self.status,
            "action": truncate_text(self.current_action, 100)
        }

        try:
            await self.broadcast(message)
            # Agregar verificación de envío exitoso
            logger.info(f"Estado actualizado exitosamente: {status} - {truncate_text(action, 50)}")
        except Exception as e:
            logger.error(f"Error al enviar actualización de estado: {e}")
            # Intentar nuevamente después de un breve retraso
            try:
                await asyncio.sleep(0.5)
                await self.broadcast(message)
                logger.info(f"Reintento exitoso de actualización de estado: {status}")
            except Exception as e2:
                logger.error(f"Error en segundo intento de actualización de estado: {e2}")

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
        Procesa un mensaje de chat usando OpenManus para generar una respuesta.
        Ahora utiliza el CoordinatorAgent para gestionar tareas grandes dividiéndolas
        en subtareas más pequeñas y gestionando mejor los límites de tasa.
        """
        if self.manus_running:
            await self.broadcast({
                "type": "chat",
                "content": "OpenManus ya está procesando una solicitud. Por favor espera.",
                "sender": "system",
                "timestamp": datetime.now().isoformat()
            })
            return

        try:
            # Marcar que el proceso está ejecutándose
            self.manus_running = True

            # Iniciar con estado de pensamiento claro en la interfaz
            await self.update_status("thinking", "Iniciando análisis de la solicitud...")

            # Verificar la actualización correcta del estado con un temporizador periódico
            status_check_task = asyncio.create_task(self._periodic_status_check())

            # Crear una nueva instancia del CoordinatorAgent para cada solicitud
            agent = CoordinatorAgent()
            logger.info("Iniciando CoordinatorAgent para manejar la tarea de forma optimizada")

            # Configurar el callback para enviar actualizaciones de progreso
            async def progress_callback(message):
                # Log detallado para seguimiento de todos los mensajes
                logger.debug(f"[CALLBACK] Mensaje recibido: {message[:100]}...")

                # Verificar si es una señal especial para actualizar el árbol de archivos
                if message == "__refresh_file_tree__":
                    # Actualizar y enviar el árbol de archivos en tiempo real
                    logger.info(f"[CALLBACK] Actualizando árbol de archivos")
                    await self.send_file_tree()
                    return

                # Señal especial para actualizar la barra de estado
                if "__special_status__:" in message:
                    # Extraer el mensaje de estado real
                    status_message = message.split("__special_status__:")[1].strip()
                    logger.info(f"[CALLBACK] Recibido mensaje de estado especial: {status_message}")

                    # Determinar el tipo de estado basado en el contenido
                    status_type = "working"  # Estado predeterminado

                    # Verificar mensajes de error
                    if any(keyword in status_message.lower() for keyword in
                          ["error", "timeout", "falló", "no se pudo", "error:"]):
                        status_type = "error"
                        logger.info(f"[CALLBACK] Detectado estado de ERROR: {status_message}")

                    # Verificar mensajes de completado
                    elif any(keyword in status_message.lower() for keyword in
                          ["completado", "finalizada", "completadas", "¡completado!", "todas las tareas finalizadas"]):
                        status_type = "done"
                        logger.info(f"[CALLBACK] Detectado estado de COMPLETADO: {status_message}")

                    # Verificar mensajes de progreso
                    elif "progreso:" in status_message.lower():
                        # Extraer información de progreso para decidir el estado
                        status_type = "working"
                        logger.info(f"[CALLBACK] Detectado indicador de PROGRESO: {status_message}")

                    # Verificar mensajes de trabajo en progreso
                    elif any(keyword in status_message.lower() for keyword in
                          ["ejecutando", "iniciando", "tarea", "preparando"]):
                        status_type = "working"
                        logger.info(f"[CALLBACK] Detectado estado de TRABAJO: {status_message}")

                    # Verificar mensajes de pensamiento/análisis
                    elif any(keyword in status_message.lower() for keyword in
                          ["analizando", "planificando", "evaluando", "pensando", "consultando"]):
                        status_type = "thinking"
                        logger.info(f"[CALLBACK] Detectado estado de PENSAMIENTO: {status_message}")

                    # Actualizar el estado en la interfaz
                    logger.info(f"[CALLBACK] Actualizando estado UI a {status_type}: {status_message}")
                    await self.update_status(status_type, status_message)

                    # Verificar que el estado se haya actualizado correctamente
                    if self.status != status_type:
                        logger.warning(f"[CALLBACK] ¡Alerta! Estado no actualizado correctamente. Esperado: {status_type}, Actual: {self.status}")
                        # Forzar actualización nuevamente
                        await asyncio.sleep(0.2)
                        await self.update_status(status_type, status_message)

                    return

                # Enviar mensaje al chat solo si es una notificación importante
                should_send_to_chat = any([
                    "Cambios realizados:" in message,
                    "Error al procesar la solicitud:" in message,
                    "Error al ejecutar la tarea" in message,
                    "Tarea completada" in message,
                    message.startswith("Tarea ") and "completada" in message,
                    "Completed task" in message and ":" in message,
                    "Task Execution Summary" in message,
                    "Created TODO.md with" in message,
                    "All tasks completed" in message,
                    message.startswith("Ejecutando tarea") and ":" in message,
                    message.startswith("Iniciando tarea") and ":" in message,
                    "Plan de tareas creado con" in message,
                    "Cargadas" in message and "tareas" in message
                ])

                if should_send_to_chat:
                    logger.info(f"[CALLBACK] Enviando mensaje importante al chat: {message[:100]}...")
                    await self.broadcast({
                        "type": "chat",
                        "content": truncate_text(message, 500),
                        "sender": "assistant",
                        "timestamp": datetime.now().isoformat()
                    })

                    # También actualizamos el estado basado en el contenido del mensaje
                    # para mantener informado al usuario en la barra de estado
                    if "Error" in message:
                        logger.info(f"[CALLBACK] Actualizando estado por contenido: ERROR")
                        await self.update_status("error", truncate_text(message, 100))
                    elif "Tarea completada" in message or "Completed task" in message:
                        logger.info(f"[CALLBACK] Actualizando estado por contenido: PROGRESO")
                        await self.update_status("working", f"Progresando: {truncate_text(message, 80)}")
                    elif "Ejecutando tarea" in message or "Iniciando tarea" in message:
                        logger.info(f"[CALLBACK] Actualizando estado por contenido: TRABAJO")
                        await self.update_status("working", truncate_text(message, 100))
                    elif "Created TODO.md" in message or "Plan de tareas creado" in message:
                        logger.info(f"[CALLBACK] Actualizando estado por contenido: PLANIFICACIÓN")
                        await self.update_status("thinking", "Planificación completada, comenzando ejecución...")
                    elif "All tasks completed" in message:
                        logger.info(f"[CALLBACK] Actualizando estado por contenido: COMPLETADO")
                        await self.update_status("done", "Todas las tareas completadas")
                else:
                    # Para mensajes no importantes, actualizar el estado más sutilmente
                    # sin enviar al chat, para mantener la UI actualizada
                    status_updates = {
                        "analyzing": ("thinking", "Analizando información..."),
                        "creating": ("working", "Creando componentes..."),
                        "updating": ("working", "Actualizando archivos..."),
                        "checking": ("working", "Verificando resultados..."),
                        "fixing": ("working", "Arreglando problemas..."),
                        "running": ("working", "Ejecutando código..."),
                        "testing": ("working", "Probando funcionalidad...")
                    }

                    # Detectar palabras clave para actualización sutil de estado
                    for keyword, (status, description) in status_updates.items():
                        if keyword.lower() in message.lower() and self.status != status:
                            logger.info(f"[CALLBACK] Actualización sutil de estado: {status} - {description}")
                            await self.update_status(status, description)
                            break

            # Establecer el callback en el agente
            agent.set_progress_callback(progress_callback)

            # Actualizar estado antes de comenzar
            await self.update_status("thinking", "Analizando solicitud y preparando plan...")

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

            # Ejecutar utilizando el CoordinatorAgent con actualización de estado
            logger.info(f"Ejecutando CoordinatorAgent con prompt: {content}")
            await self.update_status("thinking", "Procesando solicitud...")

            # Ejecutar el agente con manejo explícito de estados
            try:
                result = await agent.run(content)
                logger.info(f"Resultado de CoordinatorAgent: {result[:100]}")
            except Exception as e:
                logger.error(f"Error durante la ejecución del agente: {str(e)}")
                await self.update_status("error", f"Error en la ejecución: {str(e)[:100]}")
                raise

            # Actualizar estado para indicar que está procesando los resultados
            await self.update_status("working", "Finalizando y procesando resultados...")

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
                changes_message = "Cambios realizados:\n"

                if newly_created_files:
                    changes_message += "\nArchivos creados:\n"
                    for file_path in newly_created_files:
                        rel_path = os.path.relpath(file_path, workspace_path)
                        changes_message += f"- {rel_path}\n"

                if modified_files:
                    changes_message += "\nArchivos modificados:\n"
                    for file_path in modified_files:
                        rel_path = os.path.relpath(file_path, workspace_path)
                        changes_message += f"- {rel_path}\n"

                if renamed_files:
                    changes_message += "\nArchivos renombrados:\n"
                    for rename_info in renamed_files:
                        old_rel = os.path.relpath(rename_info["old_path"], workspace_path)
                        new_rel = os.path.relpath(rename_info["new_path"], workspace_path)
                        changes_message += f"- {old_rel} → {new_rel}\n"

                # Enviar resumen de cambios
                await self.broadcast({
                    "type": "chat",
                    "content": changes_message,
                    "sender": "system",
                    "timestamp": datetime.now().isoformat()
                })

                # Resaltar el primer archivo creado o modificado para su revisión
                if newly_created_files:
                    first_file = newly_created_files[0]
                    await self.send_select_file_notification(first_file)
                    # Actualizar estado con el archivo creado
                    await self.update_status("done", f"Archivo creado: {os.path.basename(first_file)}")
                elif modified_files:
                    first_file = modified_files[0]
                    await self.send_select_file_notification(first_file)
                    # Actualizar estado con el archivo modificado
                    await self.update_status("done", f"Archivo modificado: {os.path.basename(first_file)}")

            # Enviar mensaje final
            await self.broadcast({
                "type": "chat",
                "content": "✅ Tarea completada. Revisa los archivos generados o modificados.",
                "sender": "system",
                "timestamp": datetime.now().isoformat()
            })

            # Actualizar estado final DEFINITIVAMENTE a completado
            await self.update_status("done", "¡Tarea completada con éxito!")

            # Cancelar el temporizador de verificación de estado
            if 'status_check_task' in locals() and not status_check_task.done():
                status_check_task.cancel()

            # Actualizar árbol de archivos una última vez
            await self.send_file_tree()

        except Exception as e:
            error_message = f"Error al procesar la solicitud: {str(e)}"
            logger.error(error_message)

            # Registrar el traceback completo para depuración
            import traceback
            logger.error(traceback.format_exc())

            # Enviar mensaje de error al cliente
            await self.broadcast({
                "type": "chat",
                "content": error_message,
                "sender": "system",
                "timestamp": datetime.now().isoformat()
            })

            # Actualizar estado de error DEFINITIVAMENTE
            await self.update_status("error", f"Error: {str(e)[:100]}")

            # Cancelar el temporizador de verificación de estado si existe
            if 'status_check_task' in locals() and not status_check_task.done():
                status_check_task.cancel()
        finally:
            # Asegurar que el estado refleje el fin del proceso
            if self.status != "error" and self.status != "done":
                await self.update_status("done", "Proceso finalizado")

            # Marcar que el proceso ha terminado para permitir nuevas solicitudes
            self.manus_running = False

    async def _periodic_status_check(self):
        """Verifica periódicamente que el estado se esté mostrando correctamente."""
        try:
            while True:
                # Enviar estado actual cada 10 segundos para asegurar actualización
                await asyncio.sleep(10)
                logger.info(f"Verificación periódica de estado: {self.status} - {truncate_text(self.current_action, 50)}")

                # Reenviar el estado actual a todos los clientes
                message = {
                    "type": "status",
                    "status": self.status,
                    "action": truncate_text(self.current_action, 100)
                }
                await self.broadcast(message)
        except asyncio.CancelledError:
            logger.info("Verificación periódica de estado cancelada")
        except Exception as e:
            logger.error(f"Error en verificación periódica de estado: {e}")

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
                try:
                    # Usar timeout para detectar desconexiones silenciosas
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=60  # 60 segundos de timeout
                    )

                    # Actualizar timestamp de actividad
                    manager.last_activity[websocket] = time.time()

                    try:
                        message_data = json.loads(data)
                        message_type = message_data.get("type", "")

                        # Responder a pings del cliente
                        if message_type == "ping":
                            await manager.send_personal_message({
                                "type": "pong",
                                "timestamp": datetime.now().isoformat()
                            }, websocket)
                            continue

                        # Resto del código para manejar mensajes...
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

                except asyncio.TimeoutError:
                    # Verificar si el cliente sigue conectado
                    current_time = time.time()
                    last_time = manager.last_activity.get(websocket, 0)

                    if current_time - last_time > 120:  # 2 minutos sin actividad
                        logger.warning(f"[WS] Cliente sin actividad por más de 2 minutos, desconectando")
                        break

                    # Enviar ping para mantener la conexión
                    try:
                        await manager.send_personal_message({
                            "type": "ping",
                            "timestamp": datetime.now().isoformat()
                        }, websocket)
                    except:
                        # Si falla el ping, salir del bucle
                        logger.warning(f"[WS] No se pudo enviar ping, desconectando cliente")
                        break

        except WebSocketDisconnect:
            logger.info(f"[WS] Cliente desconectado normalmente")
            manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"[WS] Error en conexión websocket: {str(e)}")
            # Asegurar desconexión limpia
            if websocket in manager.active_connections:
                manager.disconnect(websocket)

    # Servir archivos estáticos de la aplicación web
    app.mount("/", StaticFiles(directory="openmanus-web/dist", html=True), name="static")

    return app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.web.server:create_app()", host="0.0.0.0", port=8001, reload=True)
