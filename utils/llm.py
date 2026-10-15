"""utils/llm.py

Shared helpers for talking to the LLM.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable


def structured_output(llm: BaseChatModel, schema: type) -> Runnable[Any, Any]:
    """Return ``llm.with_structured_output(schema)`` hardened for Groq.

    Groq's default structured-output mode forces a tool call. Reasoning models
    such as ``openai/gpt-oss-120b`` sometimes answer with plain text instead, and
    Groq then rejects the whole request with ``tool_use_failed``. For Groq models
    we ask for a JSON-schema response first and fall back to forced tool calling
    if that fails. Any other chat model gets the plain default behaviour.
    """
    if type(llm).__name__ != "ChatGroq":
        return llm.with_structured_output(schema)

    primary = llm.with_structured_output(schema, method="json_schema")
    fallback = llm.with_structured_output(schema, method="function_calling")
    return primary.with_fallbacks([fallback])
