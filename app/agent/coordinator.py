"""
Coordinator Agent for OpenManus
==============================

This module provides a Coordinator agent that:
1. Creates a Context.md file with project understanding
2. Creates a TODO.md file with a breakdown of subtasks
3. Invokes Manus for each subtask individually with context
4. Marks tasks as complete when finished
5. Manages the execution flow to optimize token usage and avoid rate limits
"""

import os
import re
import time
import asyncio
from typing import List, Dict, Optional, Tuple

from pydantic import Field

from app.agent.base import BaseAgent
from app.logger import logger
from app.schema import AgentState, Message
from app.agent.manus import Manus
from app.llm import LLM
from app.config import MAX_STEPS_COORDINATOR


class CoordinatorAgent(BaseAgent):
    """
    Coordinator agent that breaks down complex tasks into manageable subtasks.

    This agent creates and maintains a TODO.md file, invokes Manus for each subtask,
    and tracks progress to ensure all tasks are completed systematically.
    """

    name: str = "Coordinator"
    description: str = "An agent that coordinates the execution of complex tasks by creating and managing a TODO.md file"

    system_prompt: str = """
    You are the OpenManus Coordinator, responsible for:
    1. Understanding the project requirements and creating a Context.md file
    2. Breaking down complex tasks into small, manageable subtasks
    3. Creating a clear TODO.md file with these subtasks
    4. Executing these subtasks one by one by calling the Manus agent with proper context
    5. Tracking progress and ensuring all tasks are completed systematically

    Your main goal is to optimize the execution process by reducing token usage and avoiding rate limits.
    """

    next_step_prompt: str = """
    Please consider the current state and decide the next action:
    - If we need to create Context.md, do so to provide overall project understanding
    - If we need to create or update the TODO.md file, do so
    - If we need to execute the next task in the TODO list, identify it clearly
    - If all tasks are complete, summarize the results

    Remember to maintain a clear record of progress and be systematic in your approach.
    """

    todo_file_path: str = Field(default="workspace/TODO.md")
    context_file_path: str = Field(default="workspace/Context.md")
    current_task_index: int = Field(default=0)
    tasks: List[Dict[str, str]] = Field(default_factory=list)
    manus_agent: Manus = Field(default_factory=Manus)
    original_request: str = Field(default="")
    summary: List[str] = Field(default_factory=list)
    context_content: str = Field(default="")

    # Use the configured maximum steps value
    max_steps: int = MAX_STEPS_COORDINATOR

    async def create_context_file(self, request: str) -> str:
        """Generate a Context.md file with project understanding."""
        logger.info(f"[COORDINATOR] Iniciando creación de Context.md para la solicitud: {request[:50]}...")
        self.original_request = request
        start_time = time.time()

        # Prompt the LLM to create a context document
        context_prompt = f"""
        Analiza la siguiente solicitud y crea un archivo Context.md claro que ayudará a guiar la implementación.
        Este documento de contexto se compartirá con cada ejecutor de tarea para proporcionar comprensión general del proyecto.

        REQUEST: {request}

        Formatea tu respuesta como un documento Markdown con las siguientes secciones:

        # Project Context

        ## Project Overview
        [Descripción de alto nivel de lo que estamos construyendo]

        ## Key Requirements
        [Lista de los requisitos más importantes]

        ## Technical Stack
        [Tecnologías, frameworks y servicios a utilizar]

        ## Architecture Overview
        [Breve descripción de la arquitectura del sistema]

        ## Implementation Approach
        [Cómo abordaremos la implementación]

        ## Task Execution Guidelines
        [Directrices para ejecutar las tareas correctamente]
        - Cada agente SOLO debe implementar su tarea específica asignada
        - El contexto del proyecto es SOLO para comprensión, NO para implementación
        - No se debe intentar implementar otras partes del sistema
        - Si una tarea depende de componentes que no existen, el agente debe SOLO informar la dependencia
        - Cada tarea debe implementarse de forma aislada, como una pequeña pieza del rompecabezas

        ## Task Granularity Guidelines
        [Directrices sobre el tamaño y la granularidad ideal de las tareas]
        - Cada tarea debe ser lo más pequeña posible, idealmente completable en 5-10 minutos
        - Las tareas deben centrarse en una sola acción o componente
        - Las tareas grandes deben dividirse en múltiples tareas más pequeñas
        - Ejemplos de buena granularidad: "Crear un único archivo", "Implementar una única función", "Configurar un único componente"

        ## ⚠️ RESTRICCIONES IMPORTANTES ⚠️
        - LOS AGENTES NO DEBEN INTENTAR IMPLEMENTAR TODO EL PROYECTO
        - CADA AGENTE SOLO DEBE IMPLEMENTAR SU TAREA ESPECÍFICA
        - NO SE DEBEN CREAR COMPONENTES FUERA DEL ALCANCE DE LA TAREA ASIGNADA
        - SI FALTAN DEPENDENCIAS, SOLO INFORMAR - NO CREARLAS
        - CADA TAREA ES UNA PEQUEÑA PIEZA DEL ROMPECABEZAS, NO EL ROMPECABEZAS COMPLETO

        DIRECTRICES IMPORTANTES:
        1. Sé exhaustivo pero conciso - esto se referenciará a lo largo del proyecto
        2. Enfócate en proporcionar una comprensión clara de lo que estamos construyendo
        3. Incluye cualquier decisión técnica o restricción mencionada en la solicitud
        4. Este contexto debe ayudar a los ejecutores de tareas a entender cómo su tarea específica encaja en el panorama general
        5. Incluye consejos claros sobre la importancia de la granularidad fina en las tareas
        6. ENFATIZA que cada ejecutor SOLO debe implementar su tarea específica
        """

        logger.info(f"[COORDINATOR] Solicitando al LLM crear el documento de contexto del proyecto...")
        if self._progress_callback:
            await self._progress_callback(f"__special_status__: Analizando solicitud y creando contexto del proyecto...")

        # Crear un mensaje de usuario en formato adecuado para el LLM
        user_message = {"role": "user", "content": context_prompt}
        messages = [user_message]

        logger.info(f"[COORDINATOR] Enviando petición al LLM para crear Context.md")
        response = await self.llm.ask(messages)

        # Guardar el contenido de contexto
        self.context_content = response if response else "# Project Context\n\nNo context available."

        logger.info(f"[COORDINATOR] Respuesta del LLM recibida después de {time.time() - start_time:.2f} segundos")

        # Write to the Context.md file
        os.makedirs(os.path.dirname(self.context_file_path), exist_ok=True)
        with open(self.context_file_path, 'w') as f:
            f.write(self.context_content)

        logger.info(f"[COORDINATOR] Archivo Context.md creado en {self.context_file_path}")

        if self._progress_callback:
            await self._progress_callback(f"Documento de contexto del proyecto creado")
            await self._progress_callback(f"__refresh_file_tree__")

        return f"Created Context.md with project understanding"

    async def create_todo_file(self, request: str) -> str:
        """Generate a TODO.md file with a breakdown of tasks."""
        logger.info(f"[COORDINATOR] Iniciando creación de TODO.md para la solicitud: {request[:50]}...")

        # Ensure we have context first
        if not self.context_content:
            await self.create_context_file(request)

        start_time = time.time()

        # Prompt the LLM to create a task breakdown
        todo_prompt = f"""
        Divide la siguiente solicitud en tareas EXTREMADAMENTE PEQUEÑAS Y ESPECÍFICAS para una implementación paso a paso.
        Usa el contexto del proyecto para informar tu desglose.

        REQUEST: {request}

        PROJECT CONTEXT:
        {self.context_content[:2000]}... [Context continues]

        Formatea tu respuesta como una lista TODO de Markdown SIMPLE donde cada tarea es una acción MUY ESPECÍFICA Y PEQUEÑA:

        # Task Breakdown

        ## Tasks
        - [ ] Task 1: Implementar una única función pequeña
        - [ ] Task 2: Crear un único archivo específico
        - [ ] Task 3: Configurar un único componente o característica
        ...y así sucesivamente

        DIRECTRICES IMPORTANTES:
        1. Divide la solicitud en muchas tareas EXTREMADAMENTE PEQUEÑAS Y GRANULARES
        2. Cada tarea debe ser completable en 3 horas MÁXIMO por un desarrollador junior
        3. Las tareas deben ser secuenciales y construirse unas sobre otras
        4. Cada tarea debe ser MUY específica, enfocada en UNA SOLA ACCIÓN
        5. Una tarea NO DEBE INCLUIR múltiples acciones o componentes
        6. EVITA tareas como "Implementar backend" o "Crear frontend" - son demasiado grandes
        7. En su lugar, usa tareas como "Crear archivo models/user.py con esquema básico" o "Implementar función de login en auth.py"
        8. CREA SOLO UNA LISTA PLANA, SIN SPRINTS, SECCIONES O AGRUPACIONES
        9. UTILIZA ÚNICAMENTE el formato "- [ ] Task X: Breve descripción específica" para cada tarea
        10. NO incluyas encabezados, secciones o explicaciones entre tareas
        11. Solo proporciona una lista de tareas numerada simple
        12. Asegúrate de que cada tarea sea lo más PEQUEÑA Y ESPECÍFICA POSIBLE
        13. DIVIDE cualquier tarea grande en múltiples tareas más pequeñas
        """

        logger.info(f"[COORDINATOR] Solicitando al LLM desglosar la tarea en subtareas extremadamente pequeñas...")
        if self._progress_callback:
            await self._progress_callback(f"__special_status__: Analizando solicitud y creando plan de tareas granulares...")

        # Crear un mensaje de usuario en formato adecuado para el LLM
        user_message = {"role": "user", "content": todo_prompt}
        messages = [user_message]

        logger.info(f"[COORDINATOR] Enviando petición al LLM con formato adecuado")
        response = await self.llm.ask(messages)

        # Ya no necesitamos verificar response.content porque ahora response es directamente el string
        todo_content = response if response else "# Task Breakdown\n\n## Tasks\n- [ ] Task 1: Complete the requested task"

        # Asegurarse de que solo tenga tareas simples
        logger.info(f"[COORDINATOR] Procesando respuesta para asegurar formato correcto de tareas")

        # Extraer solo las líneas de tareas y mantener sólo el formato deseado
        task_lines = []
        task_pattern = r'- \[([ x])\] .*'

        lines = todo_content.split('\n')
        in_tasks_section = False

        for line in lines:
            # Si encontramos un encabezado de tareas, marcar que estamos en la sección
            if '# Task Breakdown' in line or '## Tasks' in line:
                in_tasks_section = True
                task_lines.append(line)
            # Si es una línea de tarea válida y estamos en la sección de tareas, agregar
            elif re.match(task_pattern, line) and in_tasks_section:
                task_lines.append(line)
            # Si estamos en la sección de tareas, incluir líneas en blanco
            elif line.strip() == "" and in_tasks_section:
                task_lines.append(line)
            # Si encontramos otro encabezado después de la sección de tareas, terminar
            elif line.startswith('#') and in_tasks_section:
                break

        # Si no encontramos tareas, crear una estructura básica
        if len(task_lines) <= 2:  # Solo encabezados, sin tareas reales
            task_lines = ["# Task Breakdown", "", "## Tasks", "- [ ] Task 1: Complete the requested task"]

        # Reconstruir el contenido con solo las tareas
        todo_content = '\n'.join(task_lines)

        logger.info(f"[COORDINATOR] Respuesta del LLM recibida y procesada después de {time.time() - start_time:.2f} segundos")

        # Write to the TODO.md file
        os.makedirs(os.path.dirname(self.todo_file_path), exist_ok=True)
        with open(self.todo_file_path, 'w') as f:
            f.write(todo_content)

        logger.info(f"[COORDINATOR] Archivo TODO.md creado en {self.todo_file_path}")

        # Parse the tasks from the TODO content
        self.parse_tasks(todo_content)

        task_descriptions = "\n".join([f"  - Tarea {t['number']}: {t['description'][:50]}..." for t in self.tasks])
        logger.info(f"[COORDINATOR] Se identificaron {len(self.tasks)} tareas:\n{task_descriptions}")

        if self._progress_callback:
            await self._progress_callback(f"Plan de tareas creado con {len(self.tasks)} pasos a ejecutar")
            await self._progress_callback(f"__refresh_file_tree__")

        return f"Created TODO.md with {len(self.tasks)} tasks"

    def parse_tasks(self, todo_content: str) -> None:
        """Parse tasks from the TODO.md content."""
        logger.info(f"[COORDINATOR] Analizando contenido del TODO para extraer tareas")

        # Regular expression to match tasks in the format: - [ ] Task description or - [x] Task description
        task_pattern = r'- \[([ x])\] (.*)'
        matches = re.finditer(task_pattern, todo_content)

        # Preservar las tareas y su estado de completado actuales
        previous_tasks = {task["original"]: task for task in self.tasks} if self.tasks else {}

        tasks_found = []
        for match in matches:
            is_complete = match.group(1) == 'x'
            description = match.group(2).strip()

            # Extract task number and description if format is "Task X: Description"
            task_num_match = re.match(r'(?:Task\s+)?(\d+)[:.]?\s*(.*)', description)
            if task_num_match:
                task_num = int(task_num_match.group(1))
                clean_description = task_num_match.group(2).strip()
            else:
                task_num = len(tasks_found) + 1
                clean_description = description

            # Crear la entrada de la tarea con datos detectados del archivo
            task_data = {
                "number": task_num,
                "description": clean_description,
                "completed": is_complete,  # Estado desde el archivo
                "original": description
            }

            # Si la tarea ya existe y está marcada como completada, mantener ese estado
            if description in previous_tasks and previous_tasks[description]["completed"]:
                task_data["completed"] = True
                logger.debug(f"[COORDINATOR] Preservando estado completado para tarea existente: {task_num}")

            tasks_found.append(task_data)
            logger.debug(f"[COORDINATOR] Encontrada tarea {task_num}: {clean_description[:50]}... (Completada: {task_data['completed']})")

        # Actualizar la lista de tareas
        self.tasks = tasks_found

        # Sort tasks by number
        self.tasks.sort(key=lambda x: x["number"])

        # Log tasks status
        completed = sum(1 for t in self.tasks if t["completed"])
        logger.info(f"[COORDINATOR] Tareas identificadas: {len(self.tasks)} total, {completed} completadas")
        task_status_log = "\n".join([f"  - Tarea {t['number']}: {t['description'][:30]}... (Completada: {t['completed']})" for t in self.tasks])
        logger.info(f"[COORDINATOR] Lista de tareas:\n{task_status_log}")

        # Si hay tareas completadas pero no están marcadas en el archivo, actualizar el archivo
        if completed > 0:
            logger.info(f"[COORDINATOR] Actualizando archivo TODO.md para reflejar {completed} tareas completadas")
            self.update_todo_file()

    def update_todo_file(self) -> None:
        """Update the TODO.md file with current task status."""
        logger.info(f"[COORDINATOR] Actualizando estado de tareas en TODO.md")

        if not os.path.exists(self.todo_file_path):
            logger.warning(f"[COORDINATOR] Archivo TODO.md no encontrado en {self.todo_file_path}")
            return

        try:
            # Leer todo el contenido del archivo
            with open(self.todo_file_path, 'r') as f:
                lines = f.readlines()

            # Crear un diccionario que mapee descripciones originales a estado de completado
            task_completion_map = {task['original']: task['completed'] for task in self.tasks}

            # Comparar cada línea y actualizarla si es necesario
            updated_lines = []
            updates_made = 0

            for line in lines:
                # Ver si la línea corresponde a una tarea
                task_match = re.match(r'- \[([ x])\] (.*)', line.strip())

                if task_match:
                    # Extraer partes de la tarea
                    current_status = task_match.group(1)
                    task_description = task_match.group(2)

                    # Verificar si tenemos información sobre esta tarea
                    if task_description in task_completion_map:
                        # Determinar el nuevo estado basado en nuestro mapa
                        new_status = 'x' if task_completion_map[task_description] else ' '

                        # Sólo actualizar si el estado ha cambiado
                        if current_status != new_status:
                            updated_line = f"- [{new_status}] {task_description}\n"
                            updated_lines.append(updated_line)
                            updates_made += 1
                            logger.info(f"[COORDINATOR] Actualizada tarea: '{task_description[:30]}...' a {'completada' if new_status == 'x' else 'pendiente'}")
                        else:
                            updated_lines.append(line)
                    else:
                        # Mantener la línea como está si no tenemos información
                        updated_lines.append(line)
                else:
                    # Mantener líneas que no son tareas
                    updated_lines.append(line)

            # Escribir el contenido actualizado al archivo
            if updates_made > 0:
                logger.info(f"[COORDINATOR] Escribiendo {updates_made} actualizaciones al archivo TODO.md")
                with open(self.todo_file_path, 'w') as f:
                    f.writelines(updated_lines)
            else:
                logger.warning(f"[COORDINATOR] No se realizaron cambios en el archivo TODO.md.")
                # Registrar el estado actual para depuración
                task_status = ", ".join([f"Task {i+1}: {t['completed']}" for i, t in enumerate(self.tasks)])
                logger.debug(f"[COORDINATOR] Estado actual de tareas: {task_status}")

                # Registrar las primeras líneas del archivo para depuración
                first_lines = "".join(lines[:10]) if len(lines) > 10 else "".join(lines)
                logger.debug(f"[COORDINATOR] Primeras líneas de TODO.md:\n{first_lines}")

        except Exception as e:
            logger.error(f"[COORDINATOR] Error al actualizar TODO.md: {str(e)}")
            import traceback
            logger.error(f"[COORDINATOR] Traceback: {traceback.format_exc()}")

    def get_next_task(self) -> Optional[Dict[str, str]]:
        """Get the next incomplete task from the task list."""
        logger.info(f"[COORDINATOR] Buscando la siguiente tarea pendiente...")

        for task in self.tasks:
            if not task["completed"]:
                logger.info(f"[COORDINATOR] Próxima tarea a ejecutar: Tarea {task['number']} - {task['description'][:50]}...")
                return task

        logger.info(f"[COORDINATOR] No se encontraron más tareas pendientes, todas completadas")
        return None

    async def execute_task_with_manus(self, task: Dict[str, str]) -> str:
        """Execute a single task using the Manus agent."""
        task_num = task['number']
        task_description = task['description']
        task_original = task['original']

        logger.info(f"[COORDINATOR] ======= INICIANDO EJECUCIÓN DE TAREA {task_num} =======")
        logger.info(f"[COORDINATOR] Tarea {task_num}: {task_description}")

        # Actualizar el estado para indicar que se está iniciando una nueva tarea
        if self._progress_callback:
            await self._progress_callback(f"__special_status__: Iniciando tarea {task_num} de {len(self.tasks)}")
            await self._progress_callback(f"Iniciando tarea {task_num}: {task_description}")

        start_time = time.time()

        # Load context content if not already loaded
        if not self.context_content and os.path.exists(self.context_file_path):
            with open(self.context_file_path, 'r') as f:
                self.context_content = f.read()

        # Create a task prompt that includes context
        task_prompt = f"""
        # ASIGNACIÓN DE TAREA ESPECÍFICA

        ## Contexto del Proyecto
        {self.context_content[:1000]}... [Ver Context.md para contexto completo]

        ## ADVERTENCIA IMPORTANTE ⚠️
        EL CONTEXTO ANTERIOR ES SÓLO INFORMATIVO. NO INTENTES IMPLEMENTAR TODO EL PROYECTO.
        NO DEBES CREAR NADA QUE NO ESTÉ EXPLÍCITAMENTE SOLICITADO EN TU TAREA ESPECÍFICA.

        ## Tu Tarea Específica
        Estás trabajando en la Tarea {task_num} de {len(self.tasks)}:
        "{task_description}"

        ## RESTRICCIONES CRÍTICAS ⚠️
        1. IMPLEMENTA ÚNICA Y EXCLUSIVAMENTE LA TAREA DESCRITA ARRIBA
        2. NO CREES ARCHIVOS, FUNCIONES O COMPONENTES QUE NO ESTÉN DIRECTAMENTE RELACIONADOS CON ESTA TAREA
        3. NO INTENTES AVANZAR HACIA OTRAS TAREAS, AUNQUE TENGAS EL CONTEXTO DEL PROYECTO COMPLETO
        4. NO DEBES IMPLEMENTAR OTRAS PARTES DEL PROYECTO, INCLUSO SI CREES QUE SON NECESARIAS
        5. CÉNTRATE EXCLUSIVAMENTE EN LA TAREA ASIGNADA Y NADA MÁS

        ## Instrucciones de Tarea
        Esta es SOLO UNA PEQUEÑA PARTE de un proyecto más grande descrito en el contexto anterior.

        Tu trabajo es ejecutar ÚNICAMENTE esta tarea específica y muy focalizada.
        NO intentes completar ninguna otra tarea.
        NO implementes funcionalidades adicionales que no estén explícitamente solicitadas.

        Céntrate exclusivamente en implementar EXACTAMENTE lo que requiere esta tarea pequeña y concreta.

        ## Solicitud Original
        {self.original_request}

        ## Directrices Importantes
        1. SOLO implementa la tarea específica y pequeña asignada a ti
        2. La tarea debe ser completable en 5-10 minutos máximo
        3. Considera cómo esta pequeña tarea encaja en el contexto general del proyecto
        4. Informa claramente de tus resultados cuando termines
        5. Si creas archivos, asegúrate de que sigan las convenciones del proyecto
        6. NO implementes otras tareas o funcionalidades adicionales
        7. Concéntrate SOLO en completar esta única tarea pequeña y específica
        8. IGNORA cualquier dependencia que creas necesaria pero no exista - esa será otra tarea
        9. SI NO PUEDES COMPLETAR LA TAREA SIN OTRAS PARTES DEL SISTEMA, SOLO INFORMA DE ELLO Y NO INTENTES CREAR ESAS PARTES
        """

        # Preparación para ejecución
        if self._progress_callback:
            await self._progress_callback(f"__special_status__: Analizando tarea {task_num}: {task_description[:50]}...")

        # Limpiar el estado del agente Manus antes de cada tarea
        self.manus_agent = Manus()
        if hasattr(self, '_progress_callback') and self._progress_callback:
            self.manus_agent.set_progress_callback(self._progress_callback)

        # Notificar inicio de ejecución
        if self._progress_callback:
            await self._progress_callback(f"__special_status__: Ejecutando tarea {task_num}: {task_description[:50]}...")
            await self._progress_callback(f"Ejecutando tarea {task_num}: {task_description}")

        # Execute the task with Manus
        logger.info(f"[COORDINATOR] Invocando al agente Manus para ejecutar la tarea {task_num}")
        # Grabamos marcas de tiempo para asegurar que la tarea no se atasque
        execution_start = time.time()

        try:
            # Ejecución de la tarea con timeout de seguridad (10 minutos máximo por tarea)
            result = await asyncio.wait_for(
                self.manus_agent.run(task_prompt),
                timeout=600
            )
            execution_time = time.time() - execution_start
            logger.info(f"[COORDINATOR] Tarea {task_num} completada en {execution_time:.2f} segundos")

            # Notificar finalización exitosa
            if self._progress_callback:
                await self._progress_callback(f"__special_status__: Finalizando tarea {task_num}")
                await self._progress_callback(f"Tarea {task_num} completada en {execution_time:.2f} segundos")
        except asyncio.TimeoutError:
            logger.error(f"[COORDINATOR] ¡Timeout! La tarea {task_num} excedió el tiempo máximo de ejecución (10 minutos)")
            result = f"Error: La tarea {task_num} no pudo completarse dentro del tiempo límite (10 minutos)"

            # Notificar error por timeout
            if self._progress_callback:
                await self._progress_callback(f"__special_status__: Error: Timeout en tarea {task_num}")
                await self._progress_callback(f"Error: La tarea {task_num} excedió el tiempo máximo permitido")
        except Exception as e:
            logger.error(f"[COORDINATOR] Error al ejecutar la tarea {task_num}: {str(e)}")
            result = f"Error al ejecutar la tarea {task_num}: {str(e)}"

            # Notificar error general
            if self._progress_callback:
                await self._progress_callback(f"__special_status__: Error en tarea {task_num}")
                await self._progress_callback(f"Error al ejecutar la tarea {task_num}: {str(e)[:100]}...")

        # Asegurar un periodo de enfriamiento entre tareas (3 segundos)
        await asyncio.sleep(3)

        # Marcar la tarea como completada directamente
        task["completed"] = True
        logger.info(f"[COORDINATOR] Marcando tarea {task_num} como completada en la lista interna")

        # Actualizar el archivo TODO
        logger.info(f"[COORDINATOR] Intentando actualizar TODO.md para marcar tarea {task_num} como completada")

        # Actualizar el archivo TODO.md con el nuevo estado
        # Primero guardamos una copia del estado original para verificación
        todo_content_before = ""
        if os.path.exists(self.todo_file_path):
            with open(self.todo_file_path, 'r') as f:
                todo_content_before = f.read()

        # Varios intentos para asegurar que la tarea se marque correctamente
        update_successful = False
        max_retries = 3

        for attempt in range(max_retries):
            logger.info(f"[COORDINATOR] Intento {attempt+1}/{max_retries} de actualizar TODO.md")

            # Actualizar el archivo TODO.md
            self.update_todo_file()

            # Verificar si la actualización fue exitosa
            if os.path.exists(self.todo_file_path):
                with open(self.todo_file_path, 'r') as f:
                    todo_content_after = f.read()

                # Comprobar si el estado de la tarea ha cambiado
                task_marked_completed = f"- [x] {task_original}" in todo_content_after
                if task_marked_completed:
                    logger.info(f"[COORDINATOR] Verificado: Tarea {task_num} marcada como completada en TODO.md")
                    update_successful = True
                    break
                else:
                    logger.warning(f"[COORDINATOR] Tarea {task_num} no aparece como completada después del intento {attempt+1}")

            # Esperar antes del siguiente intento
            await asyncio.sleep(1)

        # Si todos los intentos anteriores fallaron, hacer una actualización manual directa
        if not update_successful:
            logger.warning(f"[COORDINATOR] Los intentos automáticos fallaron. Realizando actualización manual directa.")

            try:
                # Leer las líneas del archivo
                lines = todo_content_before.splitlines()
                updated_lines = []
                task_found = False

                # Buscar y actualizar la línea específica de la tarea
                for line in lines:
                    if task_original in line and "- [ ]" in line:
                        updated_line = line.replace("- [ ]", "- [x]")
                        updated_lines.append(updated_line)
                        task_found = True
                        logger.info(f"[COORDINATOR] Actualización manual: Encontrada y actualizada tarea {task_num}")
                    else:
                        updated_lines.append(line)

                # Si se encontró la tarea, escribir el archivo actualizado
                if task_found:
                    with open(self.todo_file_path, 'w') as f:
                        f.write("\n".join(updated_lines))
                    logger.info(f"[COORDINATOR] Actualización manual exitosa para tarea {task_num}")
                    update_successful = True
                else:
                    logger.error(f"[COORDINATOR] Error crítico: No se encontró la tarea {task_num} en el archivo TODO.md")

                    # Verificar si la tarea ya estaba marcada como completada
                    for line in lines:
                        if task_original in line and "- [x]" in line:
                            logger.info(f"[COORDINATOR] ¡Tarea {task_num} ya estaba marcada como completada!")
                            update_successful = True
                            break
            except Exception as e:
                logger.error(f"[COORDINATOR] Error en actualización manual: {str(e)}")

        # Si aún así no se pudo actualizar, registrar error detallado
        if not update_successful:
            logger.error(f"[COORDINATOR] Error crítico: No se pudo actualizar la tarea {task_num} en TODO.md después de múltiples intentos")
            logger.error(f"[COORDINATOR] Texto de tarea: '{task_original}'")
            logger.error(f"[COORDINATOR] Contenido parcial de TODO.md: {todo_content_before[:500]}...")

            # Notificar el problema
            if self._progress_callback:
                await self._progress_callback(f"__special_status__: Advertencia: No se pudo actualizar TODO.md")
                await self._progress_callback(f"Advertencia: No se pudo actualizar el estado de la tarea {task_num} en TODO.md")

        # Add to summary
        summary = f"Task {task_num} completed: {task_description}"
        self.summary.append(summary)
        logger.info(f"[COORDINATOR] Resumen actualizado: {len(self.summary)}/{len(self.tasks)} tareas completadas")
        logger.info(f"[COORDINATOR] ======= FIN DE EJECUCIÓN DE TAREA {task_num} =======")

        # Actualizar barra de estado con tarea finalizada
        if self._progress_callback:
            await self._progress_callback(f"__special_status__: Tarea {task_num} finalizada")
            await self._progress_callback(f"__refresh_file_tree__")
            completed_tasks = sum(1 for t in self.tasks if t["completed"])
            await self._progress_callback(f"__special_status__: Progreso: {completed_tasks}/{len(self.tasks)} tareas completadas")

        # Asegurar un periodo de enfriamiento después de cada tarea (5 segundos)
        await asyncio.sleep(5)

        return result

    async def step(self) -> str:
        """Execute a single step in the coordination process."""
        logger.info(f"[COORDINATOR] Ejecutando paso de coordinación #{self.current_step}")

        # First check if Context.md exists
        if not os.path.exists(self.context_file_path) and self.context_content == "":
            logger.info(f"[COORDINATOR] No hay contexto definido, creando archivo Context.md...")

            # Actualizar estado para indicar que se está creando el contexto
            if self._progress_callback:
                await self._progress_callback(f"__special_status__: Analizando solicitud y creando contexto del proyecto")

            # Get the user's request from memory
            user_messages = [msg for msg in self.memory.messages if msg.role == "user"]
            if not user_messages:
                logger.warning(f"[COORDINATOR] No se encontraron mensajes del usuario en memoria")
                if self._progress_callback:
                    await self._progress_callback(f"__special_status__: Error: No se encontró la solicitud del usuario")
                return "No user request found in memory."

            request = user_messages[-1].content
            logger.info(f"[COORDINATOR] Solicitud del usuario encontrada: {request[:50]}...")
            result = await self.create_context_file(request)
            return result

        # If we haven't parsed tasks yet, check if TODO.md exists
        if not self.tasks and os.path.exists(self.todo_file_path):
            logger.info(f"[COORDINATOR] Encontrado archivo TODO.md existente, cargando tareas...")

            # Actualizar estado para indicar que se están cargando tareas
            if self._progress_callback:
                await self._progress_callback(f"__special_status__: Cargando tareas existentes")

            with open(self.todo_file_path, 'r') as f:
                todo_content = f.read()
            self.parse_tasks(todo_content)

            # Asegurar que el archivo refleja el estado actual después de cargar tareas
            logger.info(f"[COORDINATOR] Asegurando que TODO.md refleja el estado actual después de cargar tareas")
            self.update_todo_file()

            # Mostrar estado de progreso
            completed_tasks = sum(1 for t in self.tasks if t["completed"])
            if self._progress_callback:
                await self._progress_callback(f"__special_status__: Progreso: {completed_tasks}/{len(self.tasks)} tareas")
                await self._progress_callback(f"__refresh_file_tree__")
                await self._progress_callback(f"Cargadas {len(self.tasks)} tareas, {completed_tasks} completadas")

        # If we still don't have tasks, we need to create the TODO file
        if not self.tasks:
            logger.info(f"[COORDINATOR] No hay tareas definidas, creando archivo TODO.md...")

            # Actualizar estado para indicar que se están creando tareas
            if self._progress_callback:
                await self._progress_callback(f"__special_status__: Planificando tareas")

            # Get the user's request from memory
            user_messages = [msg for msg in self.memory.messages if msg.role == "user"]
            if not user_messages:
                logger.warning(f"[COORDINATOR] No se encontraron mensajes del usuario en memoria")
                if self._progress_callback:
                    await self._progress_callback(f"__special_status__: Error: No se encontró la solicitud del usuario")
                return "No user request found in memory."

            request = user_messages[-1].content
            logger.info(f"[COORDINATOR] Solicitud del usuario encontrada: {request[:50]}...")
            result = await self.create_todo_file(request)
            return result

        # Get the next task to execute
        next_task = self.get_next_task()

        # If all tasks are completed, we're done
        if not next_task:
            logger.info(f"[COORDINATOR] Todas las tareas completadas, finalizando ejecución")
            self.state = AgentState.FINISHED

            # Actualizar estado para indicar finalización
            if self._progress_callback:
                await self._progress_callback(f"__special_status__: Completado: Todas las tareas finalizadas")

            # Create a final summary
            logger.info(f"[COORDINATOR] Generando resumen final de ejecución")
            summary_text = "# Task Execution Summary\n\n"
            for i, summary_item in enumerate(self.summary, 1):
                summary_text += f"{i}. {summary_item}\n"

            # Add the summary to the TODO.md file
            logger.info(f"[COORDINATOR] Añadiendo resumen de ejecución al archivo TODO.md")
            with open(self.todo_file_path, 'a') as f:
                f.write("\n\n## Execution Summary\n")
                f.write(summary_text)

            if self._progress_callback:
                await self._progress_callback(f"Todas las tareas han sido completadas")
                await self._progress_callback(f"__refresh_file_tree__")
                # Actualizar estado final
                await self._progress_callback(f"__special_status__: ¡Completado!")

            return f"All tasks completed. Results saved to {self.todo_file_path}"

        # Execute the next task
        logger.info(f"[COORDINATOR] Ejecutando la siguiente tarea: Tarea {next_task['number']}")

        # Actualizar estado para indicar inicio de nueva tarea
        if self._progress_callback:
            current_idx = self.tasks.index(next_task) + 1
            completed = sum(1 for t in self.tasks if t["completed"])
            remaining = len(self.tasks) - completed
            await self._progress_callback(f"__special_status__: Preparando tarea {next_task['number']} (Progreso: {completed}/{len(self.tasks)})")

        result = await self.execute_task_with_manus(next_task)

        # Asegurar que el archivo TODO.md está actualizado después de ejecutar la tarea
        if os.path.exists(self.todo_file_path):
            logger.info(f"[COORDINATOR] Verificando una última vez que TODO.md está actualizado correctamente")

            # Primero comprobar si la tarea aparece como completada
            with open(self.todo_file_path, 'r') as f:
                content = f.read()
                task_marker = f"- [x] {next_task['original']}"

                if task_marker not in content:
                    logger.warning(f"[COORDINATOR] Tarea {next_task['number']} no aparece como completada, forzando actualización")
                    self.update_todo_file()

            # Registrar estado actual de las tareas después de la actualización
            completed = sum(1 for t in self.tasks if t["completed"])
            total = len(self.tasks)
            logger.info(f"[COORDINATOR] Estado actual: {completed}/{total} tareas completadas")

            if self._progress_callback:
                await self._progress_callback(f"__refresh_file_tree__")
                await self._progress_callback(f"__special_status__: {completed}/{total} tareas completadas")

        # Informar que la tarea ha sido completada y mostrar resultado
        completion_message = f"Completed task {next_task['number']}: {next_task['description']}"
        if self._progress_callback:
            await self._progress_callback(completion_message)

        return f"{completion_message}\nResult: {result}"

    async def run(self, request: Optional[str] = None) -> str:
        """Run the coordinator agent with a given request."""
        logger.info(f"[COORDINATOR] Iniciando coordinador con solicitud: {request[:50] if request else 'None'}...")

        # Set up the progress callback for the Manus agent
        if hasattr(self, '_progress_callback') and self._progress_callback:
            logger.info(f"[COORDINATOR] Configurando callback de progreso para el agente Manus")
            self.manus_agent.set_progress_callback(self._progress_callback)

        # Clean up any existing tasks
        self.tasks = []
        self.current_task_index = 0
        self.summary = []
        self.context_content = ""

        logger.info(f"[COORDINATOR] Estado reiniciado, comenzando ejecución")

        # Run the base implementation
        start_time = time.time()
        result = await super().run(request)
        total_time = time.time() - start_time

        logger.info(f"[COORDINATOR] Ejecución completada en {total_time:.2f} segundos")
        logger.info(f"[COORDINATOR] Resultado: {result[:100]}...")

        return result
