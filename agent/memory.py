from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


@dataclass
class SessionState:
    """State persisted for a single session."""

    session_id: str
    history: InMemoryChatMessageHistory = field(default_factory=InMemoryChatMessageHistory)
    completed_steps: List[str] = field(default_factory=list)
    last_plan: List[str] = field(default_factory=list)


class MemoryManager:
    """
    Manages per-session conversation + lightweight task memory.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}

    def get_or_create(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
        return self._sessions[session_id]

    def get_history(self, session_id: str) -> InMemoryChatMessageHistory:
        return self.get_or_create(session_id).history

    def append_user_message(self, session_id: str, content: str) -> None:
        self.get_history(session_id).add_message(HumanMessage(content=content))

    def append_ai_message(self, session_id: str, content: str) -> None:
        self.get_history(session_id).add_message(AIMessage(content=content))

    def set_plan(self, session_id: str, plan_steps: List[str]) -> None:
        state = self.get_or_create(session_id)
        state.last_plan = list(plan_steps)

    def mark_step_completed(self, session_id: str, step: str) -> None:
        state = self.get_or_create(session_id)
        state.completed_steps.append(step)

    def get_context_messages(self, session_id: str, max_messages: Optional[int] = 12) -> List[BaseMessage]:
        messages = self.get_history(session_id).messages
        if max_messages is None or len(messages) <= max_messages:
            return messages
        return messages[-max_messages:]