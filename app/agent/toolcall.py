import json
from typing import Any, List, Optional, Union

from pydantic import Field

from app.agent.react import ReActAgent
from app.exceptions import TokenLimitExceeded
from app.logger import logger
from app.prompt.toolcall import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import TOOL_CHOICE_TYPE, AgentState, Message, ToolCall, ToolChoice
from app.tool import CreateChatCompletion, Terminate, ToolCollection


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

    max_steps: int = 30
    max_observe: Optional[Union[int, bool]] = None

    async def think(self) -> bool:
        """Process current state and decide next actions using tools"""
        if self.next_step_prompt:
            user_msg = Message.user_message(self.next_step_prompt)
            self.messages += [user_msg]

            # Enviar actualización de que el agente está pensando
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("OpenManus está pensando...")

        try:
            # Get response with tool options
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("Consultando al LLM para decidir el siguiente paso...")

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
        except ValueError:
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("Error: Valor inválido en la solicitud al LLM")
            raise
        except Exception as e:
            # Check if this is a RetryError containing TokenLimitExceeded
            if hasattr(e, "__cause__") and isinstance(e.__cause__, TokenLimitExceeded):
                token_limit_error = e.__cause__
                error_msg = f"Maximum token limit reached, cannot continue execution: {str(token_limit_error)}"
                logger.error(f"🚨 Token limit error (from RetryError): {token_limit_error}")

                if hasattr(self, 'send_progress_update'):
                    await self.send_progress_update(f"Error: Se alcanzó el límite de tokens: {str(token_limit_error)}")

                self.memory.add_message(
                    Message.assistant_message(error_msg)
                )
                self.state = AgentState.FINISHED
                return False

            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update(f"Error inesperado: {str(e)}")

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

        # Enviar actualizaciones sobre lo que piensa el agente
        if hasattr(self, 'send_progress_update') and content:
            # Resumir el contenido si es muy largo
            thought_summary = content[:200] + "..." if len(content) > 200 else content
            await self.send_progress_update(f"Pensamiento: {thought_summary}")

        if tool_calls:
            logger.info(
                f"🧰 Tools being prepared: {[call.function.name for call in tool_calls]}"
            )
            logger.info(f"🔧 Tool arguments: {tool_calls[0].function.arguments}")

            # Enviar actualización sobre las herramientas seleccionadas
            if hasattr(self, 'send_progress_update'):
                tools_selected = ", ".join([call.function.name for call in tool_calls])
                await self.send_progress_update(f"Herramientas seleccionadas: {tools_selected}")

        try:
            if response is None:
                error_msg = "No response received from the LLM"
                if hasattr(self, 'send_progress_update'):
                    await self.send_progress_update(f"Error: {error_msg}")
                raise RuntimeError(error_msg)

            # Handle different tool_choices modes
            if self.tool_choices == ToolChoice.NONE:
                if tool_calls:
                    logger.warning(
                        f"🤔 Hmm, {self.name} tried to use tools when they weren't available!"
                    )
                    if hasattr(self, 'send_progress_update'):
                        await self.send_progress_update("Advertencia: El agente intentó usar herramientas que no están disponibles")

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
                    await self.send_progress_update("No se seleccionaron herramientas, pero se requiere el uso de herramientas")
                return True  # Will be handled in act()

            # For 'auto' mode, continue with content if no commands but content exists
            if self.tool_choices == ToolChoice.AUTO and not self.tool_calls:
                if hasattr(self, 'send_progress_update') and content:
                    await self.send_progress_update("No se seleccionaron herramientas, procediendo con la respuesta directa")
                return bool(content)

            return bool(self.tool_calls)
        except Exception as e:
            error_msg = f"🚨 Oops! The {self.name}'s thinking process hit a snag: {e}"
            logger.error(error_msg)

            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update(f"Error durante el proceso de pensamiento: {str(e)}")

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
                    await self.send_progress_update("Error: Se requieren llamadas a herramientas pero no se proporcionaron")
                raise ValueError(TOOL_CALL_REQUIRED)

            # Return last message content if no tool calls
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update("No hay herramientas que ejecutar, continuando con la respuesta directa")
            return self.messages[-1].content or "No content or commands to execute"

        results = []
        total_tools = len(self.tool_calls)

        if hasattr(self, 'send_progress_update'):
            await self.send_progress_update(f"Ejecutando {total_tools} herramienta(s)...")

        for i, command in enumerate(self.tool_calls, 1):
            # Reset base64_image for each tool call
            self._current_base64_image = None

            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update(f"Ejecutando herramienta {i}/{total_tools}: {command.function.name}")

            result = await self.execute_tool(command)

            if self.max_observe:
                result = result[: self.max_observe]

            logger.info(
                f"🎯 Tool '{command.function.name}' completed its mission! Result: {result}"
            )

            if hasattr(self, 'send_progress_update'):
                result_summary = f"Resultado de {command.function.name}: " + (result[:150] + "..." if len(result) > 150 else result)
                await self.send_progress_update(result_summary)

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
            await self.send_progress_update("Todas las herramientas han completado la ejecución")

        return "\n\n".join(results)

    async def execute_tool(self, command: ToolCall) -> str:
        """Execute a single tool call with robust error handling"""
        if not command or not command.function or not command.function.name:
            return "Error: Invalid command format"

        name = command.function.name
        if name not in self.available_tools.tool_map:
            return f"Error: Unknown tool '{name}'"

        try:
            # Enviar actualización de progreso sobre la herramienta que se va a usar
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update(f"Usando herramienta: {name}")

            # Parse arguments
            args = json.loads(command.function.arguments or "{}")

            # Registrar los argumentos para herramientas importantes
            if hasattr(self, 'send_progress_update'):
                arg_summary = ", ".join([f"{k}={v}" for k, v in args.items() if isinstance(v, (str, int, float, bool))])
                if arg_summary:
                    await self.send_progress_update(f"Parámetros: {arg_summary[:150]}..." if len(arg_summary) > 150 else f"Parámetros: {arg_summary}")

            # Execute the tool
            logger.info(f"🔧 Activating tool: '{name}'...")

            # Enviar actualización de inicio de ejecución
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update(f"Ejecutando {name}...")

            result = await self.available_tools.execute(name=name, tool_input=args)

            # Enviar actualización de finalización
            if hasattr(self, 'send_progress_update'):
                await self.send_progress_update(f"Completada la ejecución de {name}")

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
