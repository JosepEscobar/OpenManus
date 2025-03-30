from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional
import asyncio

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
        """Execute the agent's main loop asynchronously.

        Args:
            request: Optional initial user request to process.

        Returns:
            A string summarizing the execution results.

        Raises:
            RuntimeError: If the agent is not in IDLE state at start.
        """
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        if request:
            self.update_memory("user", request)
            # Solo enviar actualización de estado, no mensaje al chat
            await self.send_progress_update("__special_status__: Inicializando análisis de solicitud...")

        results: List[str] = []
        async with self.state_context(AgentState.RUNNING):
            # Solo enviar actualización de estado, no mensaje al chat
            await self.send_progress_update("__special_status__: Planificando respuesta...")

            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):
                self.current_step += 1
                step_message = f"Ejecutando paso {self.current_step}/{self.max_steps}"
                logger.info(step_message)
                # Enviar este mensaje como una actualización de estado
                await self.send_progress_update(f"__special_status__: Ejecutando paso {self.current_step}/{self.max_steps}")

                if self.current_step == 1:
                    await self.send_progress_update("__special_status__: Comenzando procesamiento...")

                # Ejecutar el paso
                step_result = await self.step()

                # Registrar el resultado pero no enviar como mensaje de chat
                if step_result:
                    logger.info(f"Resultado del paso {self.current_step}: {step_result[:100]}..." if len(step_result) > 100 else step_result)

                    # Actualizar estado basado en el número de paso
                    if self.current_step == 1:
                        await self.send_progress_update("__special_status__: Buscando solución óptima...")
                    elif self.current_step % 5 == 0:  # cada 5 pasos
                        await self.send_progress_update("__special_status__: Avanzando en la resolución...")

                # Check for stuck state
                if self.is_stuck():
                    logger.warning("OpenManus está atascado en un bucle. Intentando nuevas estrategias...")
                    await self.send_progress_update("__special_status__: Cambiando enfoque para resolver el problema...")
                    self.handle_stuck_state()

                results.append(f"Step {self.current_step}: {step_result}")

            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.IDLE
                logger.info(f"Terminado: Se alcanzó el número máximo de pasos ({self.max_steps})")
                await self.send_progress_update("__special_status__: Completado por límite de pasos")
                results.append(f"Terminated: Reached max steps ({self.max_steps})")
            else:
                logger.info("OpenManus ha completado la tarea")
                await self.send_progress_update("__special_status__: Finalizando ejecución")

        await SANDBOX_CLIENT.cleanup()
        await self.send_progress_update("__special_status__: Proceso completado")

        return "\n".join(results) if results else "No steps executed"

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
