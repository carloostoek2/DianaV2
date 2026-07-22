"""Unit tests for ContextBuilder prompt assembly."""

from __future__ import annotations

from uuid import uuid4

from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.models import Comprehension, IncomingTurn


def _turn(text: str = "VIP says hi") -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=1, text=text)


def _comprehension() -> Comprehension:
    return Comprehension(
        intent="greet",
        topics=["hello"],
        emotion="friendly",
        urgency="baja",
        risk="bajo",
    )


def test_always_includes_persona_and_current_message() -> None:
    builder = ContextBuilder()
    prompt = builder.build(
        _turn("current message body"),
        _comprehension(),
        knowledge={},
        persona="You are Diana, warm and professional.",
    )
    assert "You are Diana, warm and professional." in prompt
    assert "current message body" in prompt


def test_null_knowledge_omits_stub_headings() -> None:
    builder = ContextBuilder()
    knowledge = {
        "knowledge.history": None,
        "knowledge.context": None,
        "knowledge.memory": None,
        "knowledge.policy": None,
        "knowledge.examples": None,
        "knowledge.schedule": None,
        "knowledge.profile": None,
    }
    prompt = builder.build(
        _turn("hello"),
        _comprehension(),
        knowledge=knowledge,
        persona="Persona block",
    )
    # No empty capability section headings for null values
    for cap in knowledge:
        assert cap not in prompt
    assert "Persona block" in prompt
    assert "hello" in prompt


def test_non_null_knowledge_sections_included() -> None:
    builder = ContextBuilder()
    knowledge = {
        "knowledge.history": [{"role": "vip", "text": "prior"}],
        "knowledge.context": {"message_count": 1, "last_role": "vip"},
        "knowledge.memory": None,
    }
    prompt = builder.build(
        _turn("now"),
        _comprehension(),
        knowledge=knowledge,
        persona="Voice",
    )
    assert "knowledge.history" in prompt or "history" in prompt.lower()
    assert "prior" in prompt
    assert "message_count" in prompt or "1" in prompt
    # null memory must not appear as a heading
    assert "knowledge.memory" not in prompt


def test_comprehension_summary_present() -> None:
    builder = ContextBuilder()
    c = _comprehension()
    prompt = builder.build(_turn("x"), c, knowledge={}, persona="P")
    assert c.intent in prompt or "greet" in prompt
