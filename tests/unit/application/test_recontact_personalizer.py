"""Unit tests for RecontactPersonalizer (REE-02/COG-15 reduced pipeline)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.recontact_personalizer import RecontactPersonalizer


class FakeLLM:
    def __init__(self, text: str | None = None, *, fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls: list[list[dict]] = []

    async def generate(self, messages: list[dict], **kwargs):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("llm boom")
        return self.text or ""


class FakeMemories:
    def __init__(self, facts=None, *, fail=False) -> None:
        self._facts = facts or []
        self._fail = fail

    async def list_by_vip(self, vip_id, *, statuses=None, limit=200):
        if self._fail:
            raise RuntimeError("mem boom")
        return self._facts


class FakePolicies:
    def __init__(self, policies=None, *, fail=False) -> None:
        self._policies = policies or []
        self._fail = fail

    async def list_active_for_vip(self, vip_id, limit=5):
        if self._fail:
            raise RuntimeError("pol boom")
        return self._policies


class FakeProfiles:
    def __init__(self, profile=None, *, fail=False) -> None:
        self._profile = profile
        self._fail = fail

    async def get_by_vip(self, vip_id):
        if self._fail:
            raise RuntimeError("prof boom")
        return self._profile


def _fact(texto: str, category: str = "preferencias") -> dict:
    return {"category": category, "content": {"texto": texto}, "status": "auto"}


def _make(
    llm=None,
    memories=None,
    policies=None,
    profiles=None,
) -> RecontactPersonalizer:
    return RecontactPersonalizer(
        llm=llm or FakeLLM(text="¡Ana! ¿Cómo va todo?"),
        memories=memories or FakeMemories(),
        policies=policies or FakePolicies(),
        profiles=profiles or FakeProfiles(),
    )


@pytest.mark.asyncio
async def test_personalize_uses_template_and_context() -> None:
    vip_id = uuid4()
    llm = FakeLLM(text="¡Ana! Pensé en ti, ¿cómo va el viaje?")
    memories = FakeMemories(
        facts=[_fact("Le gusta viajar"), _fact("Tiene un perro")]
    )
    policies = FakePolicies([{"rule": "No ofrecer descuentos sin preguntar"}])
    profiles = FakeProfiles(
        SimpleNamespace(recent_trend={"estado": "entusiasmada con un viaje"})
    )
    pz = _make(llm=llm, memories=memories, policies=policies, profiles=profiles)

    result = await pz.personalize(
        vip_id=vip_id, template="Hola {nombre}", nombre="Ana"
    )

    assert result == "¡Ana! Pensé en ti, ¿cómo va el viaje?"
    user_msg = llm.calls[0][-1]["content"]
    assert "Hola {nombre}" in user_msg
    assert "Le gusta viajar" in user_msg
    assert "No ofrecer descuentos sin preguntar" in user_msg
    assert "entusiasmada con un viaje" in user_msg


@pytest.mark.asyncio
async def test_sensitive_facts_never_reach_the_prompt() -> None:
    vip_id = uuid4()
    llm = FakeLLM(text="mensaje")
    memories = FakeMemories(
        facts=[
            _fact("Le gusta el café", category="preferencias"),
            _fact("Mencionó problemas de salud", category="sensible"),
            _fact("Número de tarjeta", category="sensible"),
        ]
    )
    pz = _make(llm=llm, memories=memories)

    await pz.personalize(vip_id=vip_id, template="Hola", nombre="Ana")

    user_msg = llm.calls[0][-1]["content"]
    assert "Le gusta el café" in user_msg
    assert "problemas de salud" not in user_msg
    assert "Número de tarjeta" not in user_msg


@pytest.mark.asyncio
async def test_llm_error_falls_back_to_template() -> None:
    vip_id = uuid4()
    pz = _make(llm=FakeLLM(fail=True))

    result = await pz.personalize(
        vip_id=vip_id, template="Hola Ana", nombre="Ana"
    )
    assert result == "Hola Ana"


@pytest.mark.asyncio
async def test_empty_llm_output_falls_back_to_template() -> None:
    vip_id = uuid4()
    pz = _make(llm=FakeLLM(text="   "))

    result = await pz.personalize(
        vip_id=vip_id, template="Hola Ana", nombre="Ana"
    )
    assert result == "Hola Ana"


@pytest.mark.asyncio
async def test_retrieval_error_falls_back_to_template() -> None:
    vip_id = uuid4()
    pz = _make(memories=FakeMemories(fail=True))

    result = await pz.personalize(
        vip_id=vip_id, template="Hola Ana", nombre="Ana"
    )
    assert result == "Hola Ana"


@pytest.mark.asyncio
async def test_empty_context_skips_llm() -> None:
    vip_id = uuid4()
    llm = FakeLLM(text="no debería usarse")
    pz = _make(llm=llm, memories=FakeMemories(), policies=FakePolicies(), profiles=FakeProfiles(None))

    result = await pz.personalize(
        vip_id=vip_id, template="Hola Ana", nombre="Ana"
    )
    assert result == "Hola Ana"
    assert llm.calls == []
