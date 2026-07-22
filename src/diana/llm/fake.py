"""Scriptable FakeLLM for unit tests (no network)."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import Any

from pydantic import BaseModel


class FakeLLM:
    """Queue/map-driven LLM double that records every call for assertions.

    Cognitive components receive this via constructor DI as an ``LLMProvider``.
    """

    name: str = "fake"

    def __init__(
        self,
        *,
        text_responses: list[str] | None = None,
        structured_responses: list[BaseModel | dict[str, Any]] | None = None,
    ) -> None:
        self._text: deque[str] = deque(text_responses or [])
        self._structured: deque[BaseModel | dict[str, Any]] = deque(
            structured_responses or []
        )
        # (method_name, kwargs) for TAC-01 assertions
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def generate(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        self.calls.append(
            (
                "generate",
                {
                    "messages": deepcopy(list(messages)),
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        )
        if not self._text:
            raise RuntimeError("FakeLLM text response queue is empty")
        return self._text.popleft()

    async def generate_structured(
        self,
        messages: list[dict],
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        self.calls.append(
            (
                "generate_structured",
                {
                    "messages": deepcopy(list(messages)),
                    "schema": schema,
                    **kwargs,
                },
            )
        )
        if not self._structured:
            raise RuntimeError("FakeLLM structured response queue is empty")
        item = self._structured.popleft()
        if isinstance(item, BaseModel):
            if not isinstance(item, schema):
                raise TypeError(
                    f"FakeLLM structured item type {type(item).__name__} "
                    f"does not match schema {schema.__name__}"
                )
            return item
        return schema.model_validate(item)

    def enqueue_text(self, text: str) -> None:
        self._text.append(text)

    def enqueue_structured(self, value: BaseModel | dict[str, Any]) -> None:
        self._structured.append(value)
