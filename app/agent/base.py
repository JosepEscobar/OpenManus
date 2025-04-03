from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional
import asyncio
import time

from pydantic import BaseModel, Field, model_validator

from app.llm import LLM
from app.logger import logger
from app.sandbox.client import SANDBOX_CLIENT
from app.schema import ROLE_TYPE, AgentState, Memory, Message


class BaseAgent(BaseModel, ABC):
    """Abstract base class for managing agent state and execution.

    Provides foundational functionality for state transitions, memory management,
    and a step-based execution loop. Subclasses must implement the `step` method.
    """

    # Core attributes
    name: str = Field(..., description="Unique name of the agent")
    description: Optional[str] = Field(None, description="Optional agent description")

    # Prompts
    system_prompt: Optional[str] = Field(
        None, description="System-level instruction prompt"
    )
    next_step_prompt: Optional[str] = Field(
        None, description="Prompt for determining next action"
    )

    # Dependencies
    llm: LLM = Field(default_factory=LLM, description="Language model instance")
    memory: Memory = Field(default_factory=Memory, description="Agent's memory store")
    state: AgentState = Field(
        default=AgentState.IDLE, description="Current agent state"
    )

    # Execution control
    max_steps: int = Field(default=10, description="Maximum steps before termination")
    current_step: int = Field(default=0, description="Current step in execution")

    duplicate_threshold: int = 2

    # Progress update callbacks
    _progress_callback = None

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"  # Allow extra fields for flexibility in subclasses

    @model_validator(mode="after")
    def initialize_agent(self) -> "BaseAgent":
        """Initialize agent with default settings if not provided."""
        if self.llm is None or not isinstance(self.llm, LLM):
            self.llm = LLM(config_name=self.name.lower())
        if not isinstance(self.memory, Memory):
            self.memory = Memory()
        return self

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """Context manager for safe agent state transitions.

        Args:
            new_state: The state to transition to during the context.

        Yields:
            None: Allows execution within the new state.

        Raises:
            ValueError: If the new_state is invalid.
        """
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")

        previous_state = self.state
        self.state = new_state
        try:
            yield
        except Exception as e:
            self.state = AgentState.ERROR  # Transition to ERROR on failure
            raise e
        finally:
            self.state = previous_state  # Revert to previous state

    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        base64_image: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Add a message to the agent's memory.

        Args:
            role: The role of the message sender (user, system, assistant, tool).
            content: The message content.
            base64_image: Optional base64 encoded image.
            **kwargs: Additional arguments (e.g., tool_call_id for tool messages).

        Raises:
            ValueError: If the role is unsupported.
        """
        message_map = {
            "user": Message.user_message,
            "system": Message.system_message,
            "assistant": Message.assistant_message,
            "tool": lambda content, **kw: Message.tool_message(content, **kw),
        }

        if role not in message_map:
            raise ValueError(f"Unsupported message role: {role}")

        # Create message with appropriate parameters based on role
        kwargs = {"base64_image": base64_image, **(kwargs if role == "tool" else {})}
        self.memory.add_message(message_map[role](content, **kwargs))

    def set_progress_callback(self, callback):
        """Set the callback function to be called on progress updates."""
        self._progress_callback = callback


    async def send_progress_update(self, content: str):
        """Send a progress update message to the client."""
        if self._progress_callback:
            await self._progress_callback(content)
        else:
            # Si no hay callback, solo registra en el log
            logger.info(f"Progress update: {content}")

    async def run(self, request: Optional[str] = None) -> str:
        """
        Run the agent with an optional request string.

        Args:
            request: Optional string to initialize the agent with

        Returns:
            String result of agent execution

        Raises:
            Exception: If agent fails to make progress
        """
        if self.state != AgentState.IDLE and self.state != AgentState.FINISHED:
            logger.warning(
                f"Agent {self.name} already running (state: {self.state}). Resetting."
            )

        # Reset agent state
        self.state = AgentState.IDLE
        self.current_step = 0

        # Clear memory before running if request is provided
        if request:
            self.memory.clear()
            if request:
                self.memory.add_message(Message.user_message(request))

        # Limpiar cualquier referencia inconsistente a tool_calls en el historial
        self._clean_tool_call_references()

        # Run the agent in a loop until finished or max steps reached
        async with self.state_context(AgentState.RUNNING):
            try:
                while (
                    self.state == AgentState.RUNNING
                    and self.current_step < self.max_steps
                ):
                    self.current_step += 1
                    logger.info(
                        f"Executing step {self.current_step}/{self.max_steps}"
                    )

                    if self._progress_callback:
                        await self._progress_callback(
                            f"Ejecutando paso {self.current_step}/{self.max_steps}"
                        )

                    start_step = time.time()

                    try:
                        step_result = await self.step()
                    except Exception as e:
                        logger.error(f"Error in step execution: {e}")
                        if hasattr(e, "__cause__") and isinstance(
                            e.__cause__, TokenLimitExceeded
                        ):
                            # Stop execution if we hit token limits
                            self.state = AgentState.FINISHED
                            return f"Error: Token limit exceeded: {e.__cause__}"
                        raise

                    logger.info(
                        f"Step {self.current_step} complete in {time.time() - start_step:.2f}s. Result: {step_result[:100]}..."
                        if len(step_result) > 100
                        else step_result
                    )

                    # Check if we're stuck in a loop
                    if self.is_stuck():
                        if self._progress_callback:
                            await self._progress_callback(
                                "Agente atascado en un bucle. Intentando recuperar..."
                            )
                        self.handle_stuck_state()

                if self.current_step >= self.max_steps and self.state != AgentState.FINISHED:
                    logger.warning(
                        f"Agent {self.name} reached max steps ({self.max_steps}) without finishing."
                    )
                    if self._progress_callback:
                        await self._progress_callback(
                            f"Máximo de pasos alcanzado ({self.max_steps}). Finalizando."
                        )
                    final_result = (
                        f"Agent {self.name} reached maximum steps ({self.max_steps}) without finishing."
                    )
                else:
                    final_result = f"Agent {self.name} completed execution in {self.current_step} steps."

                return final_result
            except Exception as e:
                logger.error(f"Error in agent execution: {e}")
                self.state = AgentState.ERROR
                raise

    def _clean_tool_call_references(self) -> None:
        """Limpia las referencias inconsistentes a tool_calls en el historial del agente

        Este método es útil para evitar errores como 'tool_call_id not found in tool_calls of previous message'
        que ocurren cuando hay una desincronización entre los mensajes del asistente y las respuestas de herramientas.
        """
        if not self.memory or not self.memory.messages:
            return

        logger.info(f"[BASE_AGENT] Limpiando posibles referencias inconsistentes a tool_calls")

        # Recopilar todos los tool_call_ids de mensajes del asistente
        assistant_tool_calls = {}  # {message_index: [tool_call_ids]}
        tool_responses = {}  # {tool_call_id: message_index}
        orphan_tool_messages = []  # Índices de mensajes de herramientas huérfanos

        # Identificar tool_calls y respuestas
        for i, msg in enumerate(self.memory.messages):
            # Mensajes del asistente con tool_calls
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
                assistant_tool_calls[i] = []
                for tool_call in msg.tool_calls:
                    if hasattr(tool_call, "id") and tool_call.id:
                        assistant_tool_calls[i].append(tool_call.id)
                logger.debug(f"[BASE_AGENT] Mensaje {i} (asistente) tiene tool_calls: {assistant_tool_calls[i]}")

            # Mensajes de herramientas
            if hasattr(msg, "role") and msg.role == "tool" and hasattr(msg, "tool_call_id") and msg.tool_call_id:
                tool_responses[msg.tool_call_id] = i
                logger.debug(f"[BASE_AGENT] Mensaje {i} (herramienta) responde a tool_call_id: {msg.tool_call_id}")

        # Identificar respuestas de herramientas huérfanas (sin tool_call correspondiente)
        valid_tool_call_ids = []
        for msgs in assistant_tool_calls.values():
            valid_tool_call_ids.extend(msgs)

        for tool_call_id, msg_idx in tool_responses.items():
            if tool_call_id not in valid_tool_call_ids:
                orphan_tool_messages.append(msg_idx)
                logger.warning(f"[BASE_AGENT] Detectado mensaje de herramienta huérfano en posición {msg_idx} con tool_call_id: {tool_call_id}")

        # Identificar mensajes del asistente con tool_calls sin respuestas
        for msg_idx, call_ids in assistant_tool_calls.items():
            for call_id in call_ids:
                if call_id not in tool_responses:
                    logger.warning(f"[BASE_AGENT] Tool call sin respuesta detectado en mensaje {msg_idx}, tool_call_id: {call_id}")
                    # No eliminamos estos mensajes, pero es útil saberlo para diagnóstico

        # Eliminar mensajes de herramientas huérfanos o corregir el historial
        if orphan_tool_messages:
            logger.warning(f"[BASE_AGENT] Se eliminarán {len(orphan_tool_messages)} mensajes de herramientas huérfanos")

            # Crear una nueva lista de mensajes filtrados
            filtered_messages = []
            for i, msg in enumerate(self.memory.messages):
                if i not in orphan_tool_messages:
                    filtered_messages.append(msg)
                else:
                    logger.info(f"[BASE_AGENT] Eliminando mensaje huérfano: {msg.role} con tool_call_id: {getattr(msg, 'tool_call_id', 'N/A')}")

            # Actualizar la memoria con los mensajes filtrados
            self.memory.messages = filtered_messages
            logger.info(f"[BASE_AGENT] Historial limpiado: {len(self.memory.messages)} mensajes después de limpieza")

            # Verificación final
            tool_messages_after = sum(1 for msg in self.memory.messages if hasattr(msg, "role") and msg.role == "tool")
            logger.info(f"[BASE_AGENT] Mensajes de herramientas después de limpieza: {tool_messages_after}")
        else:
            logger.info(f"[BASE_AGENT] No se encontraron referencias inconsistentes a tool_calls")

    @abstractmethod
    async def step(self) -> str:
        """Execute a single step in the agent's workflow.

        Must be implemented by subclasses to define specific behavior.
        """

    def handle_stuck_state(self):
        """Handle stuck state by adding a prompt to change strategy"""
        stuck_prompt = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."
        self.next_step_prompt = f"{stuck_prompt}\n{self.next_step_prompt}"
        logger.warning(f"Agent detected stuck state. Added prompt: {stuck_prompt}")

    def is_stuck(self) -> bool:
        """Check if the agent is stuck in a loop by detecting duplicate content"""
        if len(self.memory.messages) < 2:
            return False

        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False

        # Count identical content occurrences
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )

        return duplicate_count >= self.duplicate_threshold

    @property
    def messages(self) -> List[Message]:
        """Retrieve a list of messages from the agent's memory."""
        return self.memory.messages

    @messages.setter
    def messages(self, value: List[Message]):
        """Set the list of messages in the agent's memory."""
        self.memory.messages = value
