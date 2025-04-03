import json
import os
from typing import Any, List, Optional, Union

from pydantic import Field

from app.agent.react import ReActAgent
from app.exceptions import TokenLimitExceeded
from app.logger import logger
from app.prompt.toolcall import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import TOOL_CHOICE_TYPE, AgentState, Message, ToolCall, ToolChoice
from app.tool import CreateChatCompletion, Terminate, ToolCollection
from app.config import MAX_STEPS_TOOL_AGENT


TOOL_CALL_REQUIRED = "Tool calls required but none provided"


class ToolCallAgent(ReActAgent):
    """Base agent class for handling tool/function calls with enhanced abstraction"""

    name: str = "toolcall"
    description: str = "an agent that can execute tool calls."

    system_prompt: str = SYSTEM_PROMPT
    next_step_prompt: str = NEXT_STEP_PROMPT

    available_tools: ToolCollection = ToolCollection(
        CreateChatCompletion(), Terminate()
    )
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO  # type: ignore
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])

    tool_calls: List[ToolCall] = Field(default_factory=list)
    _current_base64_image: Optional[str] = None

    max_steps: int = MAX_STEPS_TOOL_AGENT
    max_observe: Optional[Union[int, bool]] = None

    async def think(self) -> bool:
        """Process current state and decide next actions using tools"""
        if self.next_step_prompt:
            user_msg = Message.user_message(self.next_step_prompt)
            self.messages += [user_msg]

            # Enviar solo actualización de estado
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("__special_status__: Analizando contexto actual...")

        try:
            # Limpiar mensajes para evitar references a tool_calls huérfanos
            self._clean_orphaned_tool_calls()

            # Get response with tool options
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("__special_status__: Consultando al modelo de lenguaje...")

            response = await self.llm.ask_tool(
                messages=self.messages,
                system_msgs=(
                    [Message.system_message(self.system_prompt)]
                    if self.system_prompt
                    else None
                ),
                tools=self.available_tools.to_params(),
                tool_choice=self.tool_choices,
            )

            # Actualizar el estado después de obtener respuesta del LLM
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("__special_status__: Evaluando respuesta del modelo...")
        except ValueError:
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("__special_status__: Error en la solicitud al LLM")
            raise
        except Exception as e:
            # Check if this is a RetryError containing TokenLimitExceeded
            if hasattr(e, "__cause__") and isinstance(e.__cause__, TokenLimitExceeded):
                token_limit_error = e.__cause__
                error_msg = f"Maximum token limit reached, cannot continue execution: {str(token_limit_error)}"
                logger.error(f"🚨 Token limit error (from RetryError): {token_limit_error}")

                if hasattr(self, 'send_progress_update'):
                    await self.send_progress_update("__special_status__: Límite de tokens alcanzado")

                self.memory.add_message(
                    Message.assistant_message(error_msg)
                )
                self.state = AgentState.FINISHED
                return False

            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("__special_status__: Error inesperado")

            raise

        self.tool_calls = tool_calls = (
            response.tool_calls if response and response.tool_calls else []
        )
        content = response.content if response and response.content else ""

        # Log response info
        logger.info(f"✨ {self.name}'s thoughts: {content}")
        logger.info(
            f"🛠️ {self.name} selected {len(tool_calls) if tool_calls else 0} tools to use"
        )

        # Enviar actualización de estado más específica según la respuesta
        if hasattr(self, 'send_progress_update'):
            if content and tool_calls:
                await self.send_progress_update("__special_status__: Procesando respuesta y herramientas...")
            elif content:
                await self.send_progress_update("__special_status__: Analizando respuesta textual...")
            elif tool_calls:
                await self.send_progress_update("__special_status__: Preparando herramientas seleccionadas...")

        if tool_calls:
            logger.info(
                f"🧰 Tools being prepared: {[call.function.name for call in tool_calls]}"
            )
            logger.info(f"🔧 Tool arguments: {tool_calls[0].function.arguments}")

            # Enviar actualización sobre las herramientas seleccionadas
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("__special_status__: Preparando herramientas...")

        try:
            if response is None:
                error_msg = "No response received from the LLM"
                if hasattr(self, 'send_progress_update'):
                    await self.send_progress_update("__special_status__: Sin respuesta del LLM")
                raise RuntimeError(error_msg)

            # Handle different tool_choices modes
            if self.tool_choices == ToolChoice.NONE:
                if tool_calls:
                    logger.warning(
                        f"🤔 Hmm, {self.name} tried to use tools when they weren't available!"
                    )
                    if hasattr(self, 'send_progress_update'):
                        await self.send_progress_update("__special_status__: Herramientas no disponibles")

                if content:
                    self.memory.add_message(Message.assistant_message(content))
                    return True
                return False

            # Create and add assistant message
            assistant_msg = (
                Message.from_tool_calls(content=content, tool_calls=self.tool_calls)
                if self.tool_calls
                else Message.assistant_message(content)
            )
            self.memory.add_message(assistant_msg)

            if self.tool_choices == ToolChoice.REQUIRED and not self.tool_calls:
                if hasattr(self, 'send_progress_update'):
                    await self.send_progress_update("__special_status__: Se requieren herramientas")
                return True  # Will be handled in act()

            # For 'auto' mode, continue with content if no commands but content exists
            if self.tool_choices == ToolChoice.AUTO and not self.tool_calls:
                if hasattr(self, 'send_progress_update') and content:
                    await self.send_progress_update("__special_status__: Generando respuesta directa")
                return bool(content)

            return bool(self.tool_calls)
        except Exception as e:
            error_msg = f"🚨 Oops! The {self.name}'s thinking process hit a snag: {e}"
            logger.error(error_msg)

            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("__special_status__: Error en proceso de pensamiento")

            self.memory.add_message(
                Message.assistant_message(
                    f"Error encountered while processing: {str(e)}"
                )
            )
            return False

    async def act(self) -> str:
        """Execute tool calls and handle their results"""
        if not self.tool_calls:
            if self.tool_choices == ToolChoice.REQUIRED:
                if hasattr(self, 'send_progress_update'):
                    await self.send_progress_update("__special_status__: Error: Faltan herramientas requeridas")
                raise ValueError(TOOL_CALL_REQUIRED)

            # Return last message content if no tool calls
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("__special_status__: Generando respuesta")
            return self.messages[-1].content or "No content or commands to execute"

        results = []
        total_tools = len(self.tool_calls)

        if hasattr(self, 'send_progress_update'):
            await self.send_progress_update("__special_status__: Iniciando ejecución de herramientas")

        for i, command in enumerate(self.tool_calls, 1):
            # Reset base64_image for each tool call
            self._current_base64_image = None

            if hasattr(self, 'send_progress_update'):
                if total_tools > 1:
                    await self.send_progress_update(f"__special_status__: Herramienta {i} de {total_tools}")

            result = await self.execute_tool(command)

            if self.max_observe:
                result = result[: self.max_observe]

            logger.info(
                f"🎯 Tool '{command.function.name}' completed its mission! Result: {result}"
            )

            # Add tool response to memory
            tool_msg = Message.tool_message(
                content=result,
                tool_call_id=command.id,
                name=command.function.name,
                base64_image=self._current_base64_image,
            )
            self.memory.add_message(tool_msg)
            results.append(result)

        if hasattr(self, 'send_progress_update'):
            await self.send_progress_update("__special_status__: Evaluando resultados finales")

        return "\n\n".join(results)

    async def execute_tool(self, command: ToolCall) -> str:
        """Execute a single tool call with robust error handling"""
        if not command or not command.function or not command.function.name:
            return "Error: Invalid command format"

        name = command.function.name
        if name not in self.available_tools.tool_map:
            return f"Error: Unknown tool '{name}'"

        try:
            # Enviar solo actualización de estado sobre la herramienta
            if hasattr(self, 'send_progress_update'):
                # Enviar actualizaciones de estado más específicas según la herramienta
                if name == "str_replace_editor":
                    await self.send_progress_update("__special_status__: Editando archivos...")
                elif name == "python_execute":
                    await self.send_progress_update("__special_status__: Ejecutando código Python...")
                elif name == "browser_use":
                    await self.send_progress_update("__special_status__: Navegando por la web...")
                elif name == "create_chat_completion":
                    await self.send_progress_update("__special_status__: Consultando al LLM para información adicional...")
                elif name == "terminate":
                    await self.send_progress_update("__special_status__: Finalizando tarea...")
                else:
                    await self.send_progress_update(f"__special_status__: Ejecutando herramienta: {name}...")

            # Parse arguments
            args = json.loads(command.function.arguments or "{}")

            # Solo enviar información específica sobre la operación al estado
            if hasattr(self, 'send_progress_update'):
                # Información específica según el tipo de herramienta y sus argumentos
                if name == "str_replace_editor" and "command" in args:
                    cmd = args.get("command", "")
                    if cmd == "create":
                        file_path = args.get("file_path", "")
                        file_name = os.path.basename(file_path) if file_path else "nuevo archivo"
                        await self.send_progress_update(f"__special_status__: Creando archivo: {file_name}...")
                    elif cmd == "edit":
                        file_path = args.get("file_path", "")
                        file_name = os.path.basename(file_path) if file_path else "archivo"
                        await self.send_progress_update(f"__special_status__: Modificando archivo: {file_name}...")
                    elif cmd == "view":
                        file_path = args.get("file_path", "")
                        file_name = os.path.basename(file_path) if file_path else "archivo"
                        await self.send_progress_update(f"__special_status__: Leyendo archivo: {file_name}...")
                elif name == "python_execute" and "code" in args:
                    code = args.get("code", "")
                    if "import " in code and "os" in code:
                        await self.send_progress_update("__special_status__: Realizando operaciones del sistema...")
                    elif "import " in code and any(lib in code for lib in ["matplotlib", "pyplot", "pandas"]):
                        await self.send_progress_update("__special_status__: Procesando datos o generando gráficos...")

            # Execute the tool
            logger.info(f"🔧 Activating tool: '{name}'...")
            result = await self.available_tools.execute(name=name, tool_input=args)

            # Enviar actualización de finalización
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("__special_status__: Analizando resultados...")

            # Verificar si la herramienta modificó archivos y actualizar el explorador
            # Las herramientas que modifican archivos suelen ser str_replace_editor, python_execute, etc.
            if name in ["str_replace_editor", "python_execute"] and hasattr(self, '_progress_callback'):
                # Enviar una señal para actualizar el árbol de archivos
                await self.send_progress_update("__refresh_file_tree__")

            # Handle special tools
            await self._handle_special_tool(name=name, result=result)

            # Check if result is a ToolResult with base64_image
            if hasattr(result, "base64_image") and result.base64_image:
                # Store the base64_image for later use in tool_message
                self._current_base64_image = result.base64_image

                # Format result for display
                observation = (
                    f"Observed output of cmd `{name}` executed:\n{str(result)}"
                    if result
                    else f"Cmd `{name}` completed with no output"
                )
                return observation

            # Format result for display (standard case)
            observation = (
                f"Observed output of cmd `{name}` executed:\n{str(result)}"
                if result
                else f"Cmd `{name}` completed with no output"
            )

            return observation
        except json.JSONDecodeError:
            error_msg = f"Error parsing arguments for {name}: Invalid JSON format"
            logger.error(
                f"📝 Oops! The arguments for '{name}' don't make sense - invalid JSON, arguments:{command.function.arguments}"
            )
            # Enviar actualización de error
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update(f"Error al analizar los argumentos para {name}")

            return f"Error: {error_msg}"
        except Exception as e:
            error_msg = f"⚠️ Tool '{name}' encountered a problem: {str(e)}"
            logger.exception(error_msg)

            # Enviar actualización de error
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update(f"Error al ejecutar {name}: {str(e)}")

            return f"Error: {error_msg}"

    async def _handle_special_tool(self, name: str, result: Any, **kwargs):
        """Handle special tool execution and state changes"""
        if not self._is_special_tool(name):
            return

        if self._should_finish_execution(name=name, result=result, **kwargs):
            # Set agent state to finished
            logger.info(f"🏁 Special tool '{name}' has completed the task!")
            self.state = AgentState.FINISHED

    @staticmethod
    def _should_finish_execution(**kwargs) -> bool:
        """Determine if tool execution should finish the agent"""
        return True

    def _is_special_tool(self, name: str) -> bool:
        """Check if tool name is in special tools list"""
        return name.lower() in [n.lower() for n in self.special_tool_names]

    def _clean_orphaned_tool_calls(self):
        """Limpia las referencias a tool_calls huérfanos para evitar errores de 'tool_call_id not found'"""
        logger.info(f"Limpiando posibles tool_calls huérfanos del historial de mensajes")

        # Identificar todos los tool_call_ids presentes en el historial
        tool_call_ids = set()
        assistant_tool_call_ids = {}

        # Primero, identificar todos los tool_call_ids usados por asistentes
        for i, msg in enumerate(self.messages):
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    if hasattr(tool_call, "id"):
                        assistant_tool_call_ids[tool_call.id] = i

        # Luego, identificar los tool_call_ids que tienen respuestas de herramientas
        for msg in self.messages:
            if hasattr(msg, "role") and msg.role == "tool" and hasattr(msg, "tool_call_id"):
                tool_call_ids.add(msg.tool_call_id)

        # Encontrar tool_calls huérfanos (sin respuesta de herramienta correspondiente)
        orphaned_tool_call_ids = set()
        for tool_id, msg_index in assistant_tool_call_ids.items():
            if tool_id not in tool_call_ids:
                orphaned_tool_call_ids.add((tool_id, msg_index))

        if orphaned_tool_call_ids:
            logger.warning(f"Encontrados {len(orphaned_tool_call_ids)} tool_calls huérfanos que serán limpiados")

            # Limpiar mensajes con tool_calls huérfanos
            clean_messages = []
            for i, msg in enumerate(self.messages):
                if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
                    # Verificar si este mensaje contiene tool_calls huérfanos
                    has_orphaned = any((tool_call.id, i) in orphaned_tool_call_ids for tool_call in msg.tool_calls if hasattr(tool_call, "id"))

                    if has_orphaned:
                        # Solo conservar el contenido de texto sin tool_calls
                        content = getattr(msg, "content", "") or ""
                        clean_messages.append(Message.assistant_message(content))
                        logger.info(f"Limpiado mensaje de asistente con tool_calls huérfanos en posición {i}")
                    else:
                        clean_messages.append(msg)
                else:
                    clean_messages.append(msg)

            # Reemplazar mensajes originales con los limpiados
            self.messages = clean_messages
        else:
            logger.info("No se encontraron tool_calls huérfanos en el historial")
