"""Unit tests for ContextBuilder prompt assembly (Anexo D)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.exceptions import ContextExceedsLimitError
from diana.cognitive.models import BuiltContext, Comprehension, IncomingTurn


def _turn(text: str = "VIP says hi") -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=1, text=text)


def _comprehension() -> Comprehension:
    return Comprehension(
        intent="greet",
        topics=["hello"],
        emotion="positiva",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=True,
        needs_context=True,
    )


def _section_headings(prompt: str) -> list[str]:
    return [line for line in prompt.splitlines() if line.startswith("## ")]


def test_always_includes_persona_and_current_message() -> None:
    builder = ContextBuilder()
    built = builder.build(
        _turn("current message body"),
        _comprehension(),
        knowledge={},
        persona="You are Diana, warm and professional.",
    )
    assert isinstance(built, BuiltContext)
    assert "You are Diana, warm and professional." in built.prompt_final
    assert "current message body" in built.prompt_final


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
    built = builder.build(
        _turn("hello"),
        _comprehension(),
        knowledge=knowledge,
        persona="Persona block",
    )
    for cap in knowledge:
        assert cap not in built.prompt_final
    assert "Persona block" in built.prompt_final
    assert "hello" in built.prompt_final


def test_non_null_knowledge_sections_included() -> None:
    builder = ContextBuilder()
    knowledge = {
        "knowledge.history": [{"autor": "vip", "texto": "prior", "timestamp": ""}],
        "knowledge.context": {
            "waiting_for_reply_since": "t1",
            "is_first_message_of_day": True,
        },
        "knowledge.memory": None,
    }
    built = builder.build(
        _turn("now"),
        _comprehension(),
        knowledge=knowledge,
        persona="Voice",
    )
    assert "## Knowledge: knowledge.history" in built.prompt_final
    assert "prior" in built.prompt_final
    assert '"waiting_for_reply_since": "t1"' in built.prompt_final
    assert "## Knowledge: knowledge.context" in built.prompt_final
    assert "## Knowledge: knowledge.memory" not in built.prompt_final


def test_comprehension_summary_present() -> None:
    builder = ContextBuilder()
    c = _comprehension()
    built = builder.build(_turn("x"), c, knowledge={}, persona="P")
    assert "intent: greet" in built.prompt_final
    assert f"intent: {c.intent}" in built.prompt_final


def test_empty_list_and_dict_knowledge_omitted() -> None:
    builder = ContextBuilder()
    knowledge = {
        "knowledge.history": [],
        "knowledge.context": {},
        "knowledge.memory": None,
    }
    built = builder.build(
        _turn("hello"),
        _comprehension(),
        knowledge=knowledge,
        persona="Persona",
    )
    assert "knowledge.history" not in built.prompt_final
    assert "knowledge.context" not in built.prompt_final
    assert "knowledge.memory" not in built.prompt_final


def test_list_included_blocks_matches_prompt_sections() -> None:
    builder = ContextBuilder()
    knowledge = {
        "knowledge.history": [{"autor": "vip", "texto": "prior", "timestamp": ""}],
        "knowledge.context": {
            "waiting_for_reply_since": None,
            "is_first_message_of_day": True,
        },
        "knowledge.memory": None,
        "knowledge.policy": [],
        "knowledge.examples": {},
        "knowledge.schedule": "   ",
        "knowledge.profile": "has value",
    }
    built = builder.build(
        _turn("now"),
        _comprehension(),
        knowledge=knowledge,
        persona="Voice",
    )
    blocks = builder.list_included_blocks(knowledge)
    headings = [
        line.removeprefix("## Knowledge: ").strip()
        for line in built.prompt_final.splitlines()
        if line.startswith("## Knowledge: ")
    ]
    assert blocks == headings
    assert built.included_blocks == headings
    assert blocks == [
        "knowledge.history",
        "knowledge.context",
        "knowledge.profile",
    ]
    # profile last among non-null knowledge blocks (D.4 fixed order)
    assert blocks[-1] == "knowledge.profile"


def test_list_included_blocks_empty_when_all_null_like() -> None:
    builder = ContextBuilder()
    knowledge = {
        "knowledge.history": None,
        "knowledge.context": [],
        "knowledge.memory": {},
        "knowledge.policy": "",
        "knowledge.examples": "  \t  ",
    }
    assert builder.list_included_blocks(knowledge) == []


def test_build_returns_built_context_prompt_and_blocks() -> None:
    builder = ContextBuilder()
    knowledge = {
        "knowledge.history": [{"role": "vip", "text": "prior"}],
        "knowledge.context": None,
        "knowledge.memory": "mem body",
    }
    built = builder.build(
        _turn("now"),
        _comprehension(),
        knowledge=knowledge,
        persona="Voice",
    )
    assert isinstance(built, BuiltContext)
    assert isinstance(built.prompt_final, str)
    assert isinstance(built.included_blocks, list)
    headings = [
        line.removeprefix("## Knowledge: ").strip()
        for line in built.prompt_final.splitlines()
        if line.startswith("## Knowledge: ")
    ]
    assert built.included_blocks == headings
    assert built.included_blocks == ["knowledge.history", "knowledge.memory"]


def test_d4_current_turn_is_last_section() -> None:
    builder = ContextBuilder()
    knowledge = {
        "knowledge.history": [{"autor": "vip", "texto": "prior", "timestamp": ""}],
        "knowledge.context": {
            "waiting_for_reply_since": None,
            "is_first_message_of_day": False,
        },
    }
    built = builder.build(
        _turn("CURRENT-BODY-XYZ"),
        _comprehension(),
        knowledge=knowledge,
        persona="Persona text",
    )
    headings = _section_headings(built.prompt_final)
    # Full D.4 order: Persona → knowledge (fixed) → Comprehension → Current last
    assert headings == [
        "## Persona",
        "## Knowledge: knowledge.history",
        "## Knowledge: knowledge.context",
        "## Comprehension",
        "## Current VIP message",
    ]
    assert built.prompt_final.rstrip().endswith("CURRENT-BODY-XYZ")


def test_build_preserves_turn_text_trailing_whitespace() -> None:
    """Current VIP message is last: must not strip trailing spaces from turn.text."""
    builder = ContextBuilder()
    vip_body = "hello VIP  \t  "
    built = builder.build(
        _turn(vip_body),
        _comprehension(),
        knowledge={},
        persona="Persona",
    )
    # Body after heading must match turn.text exactly (before final prompt newline)
    marker = "## Current VIP message\n"
    assert marker in built.prompt_final
    after = built.prompt_final.split(marker, 1)[1]
    # Final assembly may add a single trailing newline after the body
    assert after == vip_body + "\n" or after == vip_body
    assert vip_body in built.prompt_final
    # Trailing spaces on the VIP line must survive (pre-fix .strip() ate them)
    body_line = after.rstrip("\n")
    assert body_line == vip_body
    assert body_line.endswith("  \t  ")


def test_d4_knowledge_emitted_in_fixed_order_regardless_of_dict_insertion() -> None:
    builder = ContextBuilder()
    # Reverse / shuffled insertion order relative to D.4 emission tuple
    knowledge = {
        "knowledge.profile": "profile body",
        "knowledge.persona_facts": {"hecho": "f", "tema": "familia"},
        "knowledge.voice_patterns": {"patron": "jsjs", "uso": "risa"},
        "knowledge.schedule": "schedule body",
        "knowledge.examples": ["ex1"],
        "knowledge.policy": {"rule": "no spam"},
        "knowledge.memory": "mem",
        "knowledge.context": {"n": 1},
        "knowledge.history": [{"role": "vip", "text": "h"}],
        "knowledge.unknown_cap": "must be ignored",
    }
    built = builder.build(
        _turn("now"),
        _comprehension(),
        knowledge=knowledge,
        persona="P",
    )
    headings = [
        line.removeprefix("## Knowledge: ").strip()
        for line in built.prompt_final.splitlines()
        if line.startswith("## Knowledge: ")
    ]
    assert headings == [
        "knowledge.history",
        "knowledge.context",
        "knowledge.persona_facts",
        "knowledge.voice_patterns",
        "knowledge.memory",
        "knowledge.policy",
        "knowledge.examples",
        "knowledge.schedule",
        "knowledge.profile",
    ]
    assert "knowledge.unknown_cap" not in built.prompt_final
    assert built.included_blocks == headings


def test_contexto_excede_limite_raises_typed_error_no_truncate() -> None:
    builder = ContextBuilder(max_prompt_chars=50)
    knowledge = {
        "knowledge.history": [{"role": "vip", "text": "X" * 200}],
    }
    with pytest.raises(ContextExceedsLimitError) as exc_info:
        builder.build(
            _turn("now"),
            _comprehension(),
            knowledge=knowledge,
            persona="Persona",
        )
    exc = exc_info.value
    assert str(exc) == "contexto_excede_limite"
    assert exc.reason == "contexto_excede_limite"
    # No truncated partial return — exception only


def test_style_rules_optional_under_persona() -> None:
    builder = ContextBuilder()
    built_with = builder.build(
        _turn("now"),
        _comprehension(),
        knowledge={"knowledge.history": [{"t": 1}]},
        persona="Base persona",
        style_rules=["Be concise", "No emojis"],
    )
    headings = _section_headings(built_with.prompt_final)
    persona_idx = headings.index("## Persona")
    first_knowledge_idx = next(
        i for i, h in enumerate(headings) if h.startswith("## Knowledge:")
    )
    assert persona_idx < first_knowledge_idx
    assert "Be concise" in built_with.prompt_final
    assert "No emojis" in built_with.prompt_final
    # Style lines appear before first knowledge section
    assert built_with.prompt_final.index("Be concise") < built_with.prompt_final.index(
        "## Knowledge:"
    )

    built_empty = builder.build(
        _turn("now"),
        _comprehension(),
        knowledge={},
        persona="Base persona",
        style_rules=[],
    )
    assert "Be concise" not in built_empty.prompt_final

    built_default = builder.build(
        _turn("now"),
        _comprehension(),
        knowledge={},
        persona="Base persona",
    )
    assert "Be concise" not in built_default.prompt_final


def test_included_blocks_exclude_comprehension_and_persona() -> None:
    builder = ContextBuilder()
    built = builder.build(
        _turn("now"),
        _comprehension(),
        knowledge={"knowledge.history": [{"role": "vip", "text": "h"}]},
        persona="Persona label text",
    )
    for block in built.included_blocks:
        assert block.startswith("knowledge.")
        assert "Comprehension" not in block
        assert "Persona" not in block
    assert "Comprehension" not in built.included_blocks
    assert "Persona" not in built.included_blocks



def test_persona_voice_emitted_between_context_and_memory() -> None:
    """H2: persona_facts and voice_patterns sit between context and memory."""
    builder = ContextBuilder()
    knowledge = {
        "knowledge.memory": "mem",
        "knowledge.persona_facts": {"hecho": "Hermana", "tema": "familia"},
        "knowledge.voice_patterns": {"patron": "jsjs", "uso": "risa"},
        "knowledge.context": {"n": 1},
        "knowledge.history": [{"role": "vip", "text": "h"}],
    }
    built = builder.build(
        _turn("now"),
        _comprehension(),
        knowledge=knowledge,
        persona="P",
    )
    headings = [
        line.removeprefix("## Knowledge: ").strip()
        for line in built.prompt_final.splitlines()
        if line.startswith("## Knowledge: ")
    ]
    assert headings == [
        "knowledge.history",
        "knowledge.context",
        "knowledge.persona_facts",
        "knowledge.voice_patterns",
        "knowledge.memory",
    ]
