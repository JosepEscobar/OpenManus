"""
Agentes inteligentes para OpenManus.

Un agente es una entidad autónoma que puede percibir su entorno,
tomar decisiones y ejecutar acciones para cumplir objetivos.
"""

from app.agent.base import BaseAgent
from app.agent.manus import Manus
from app.agent.browser import BrowserAgent
from app.agent.react import ReActAgent
from app.agent.toolcall import ToolCallAgent
from app.agent.coordinator import CoordinatorAgent

__all__ = [
    "BaseAgent",
    "Manus",
    "BrowserAgent",
    "ReActAgent",
    "ToolCallAgent",
    "CoordinatorAgent"
]
