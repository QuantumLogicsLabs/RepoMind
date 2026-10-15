from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """State persisted for a single session."""

    session_id: str
    history: InMemoryChatMessageHistory = field(default_factory=InMemoryChatMessageHistory)
    completed_steps: list[str] = field(default_factory=list)
    last_plan: list[str] = field(default_factory=list)


def _estimate_message_tokens(message: BaseMessage) -> int:
    """Fast heuristic to estimate tokens in a message (approx 4 chars per token)."""
    content = str(message.content) if message.content else ""
    return len(content) // 4


class MemoryManager:
    """Manages per-session conversation + lightweight task memory with smart token trimming.

    Thread-safe: a lock guards session creation/lookup so concurrent
    batch jobs (different session_ids running in parallel threads) cannot
    race on the underlying dict.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str) -> SessionState:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionState(session_id=session_id)
            return self._sessions[session_id]

    def get_history(self, session_id: str) -> InMemoryChatMessageHistory:
        return self.get_or_create(session_id).history

    def append_user_message(self, session_id: str, content: str) -> None:
        self.get_history(session_id).add_message(HumanMessage(content=content))

    def append_ai_message(self, session_id: str, content: str) -> None:
        self.get_history(session_id).add_message(AIMessage(content=content))

    def set_plan(self, session_id: str, plan_steps: list[str]) -> None:
        state = self.get_or_create(session_id)
        state.last_plan = list(plan_steps)

    def mark_step_completed(self, session_id: str, step: str) -> None:
        state = self.get_or_create(session_id)
        if step not in state.completed_steps:
            state.completed_steps.append(step)

    def get_progress(self, session_id: str) -> dict:
        state = self.get_or_create(session_id)
        total = len(state.last_plan)

        return {
            "completed": len(state.completed_steps),
            "total": total,
            "steps": state.completed_steps,
            "remaining": max(total - len(state.completed_steps), 0),
        }

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

    def get_context_messages(
        self,
        session_id: str,
        max_messages: int | None = 12,
        max_tokens: int = 4000,
    ) -> list[BaseMessage]:
        """Returns recent messages within BOTH a message count limit and a token budget.

        Always prioritizes keeping the most recent messages.
        """
        messages = self.get_history(session_id).messages
        if not messages:
            return []

        # 1. Apply simple message count cutoff first
        if max_messages is not None and len(messages) > max_messages:
            messages = messages[-max_messages:]

        # 2. Apply smart token budget trimming
        retained_messages: list[BaseMessage] = []
        current_tokens = 0

        # Traverse from newest to oldest
        for msg in reversed(messages):
            msg_tokens = _estimate_message_tokens(msg)

            # Always keep at least the very last message, even if it's large
            if not retained_messages or (current_tokens + msg_tokens <= max_tokens):
                retained_messages.append(msg)
                current_tokens += msg_tokens
            else:
                logger.info(
                    f"Memory Trim: Token budget reached ({current_tokens}/{max_tokens}). "
                    f"Dropped {len(messages) - len(retained_messages)} older messages."
                )
                break

        # Reverse back to chronological order (oldest to newest)
        return list(reversed(retained_messages))
