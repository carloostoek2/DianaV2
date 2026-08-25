"""RED contract: GrayZoneProposalService — system-generated RULE proposal.

Locked product decisions (AGENTS §4.5 + impact-analyzer/grayzone-general-context-proposal):
1. On consult_doctrine, an optional proposal (rule + reply + scope + confidence)
   is generated OUTSIDE the cognitive pipeline (application layer), using a
   restricted "general context" loan (global policies + gold examples + persona
   catalog). Nothing is written to memories/examples/profile/policies.
2. Fail-open: any error/timeout returns None; caller falls back to the current
   owner-writes-rule DM (never loses the query or the freeze).
3. The proposal is a SUGGESTION only: "Usar regla propuesta" adopts the RULE
   (not the message) through the existing rule→regen→approval path.
4. No threshold/gate is auto-calibrated (incidente de calibración).

These tests must fail on the pre-implementation codebase (Strict TDD).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from diana.application.gray_zone_proposal_service import (
    GrayZoneProposal,
    GrayZoneProposalService,
)


class _FakeLLM:
    """Minimal generate_structured stub returning a queued response."""

    def __init__(self, response: Any | None = None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.calls: list[list[dict]] = []

    async def generate_structured(self, messages: list[dict], schema: type, **kwargs: Any):
        self.calls.append(list(messages))
        if self._exc is not None:
            raise self._exc
        if self._response is None:
            raise RuntimeError("no response queued")
        if isinstance(self._response, schema):
            return self._response
        return schema.model_validate(self._response)


def _proposal(**overrides: Any) -> GrayZoneProposal:
    data = dict(
        proposed_rule="Ofrecer 10% si piden 3 o más unidades",
        proposed_reply="Sí, con 3 o más te hago 10% de descuento 😉",
        suggested_scope="vip",
        confidence=0.8,
    )
    data.update(overrides)
    return GrayZoneProposal(**data)


def _service(llm: Any = None, **kwargs: Any) -> GrayZoneProposalService:
    return GrayZoneProposalService(
        llm=llm if llm is not None else _FakeLLM(response=_proposal()),
        persona_facts=[{"tema": ["descuento"], "hecho": "ofrece descuentos por volumen"}],
        voice_patterns=[],
        **kwargs,
    )


# --- Shape ---------------------------------------------------------------


def test_gray_zone_proposal_model_shape() -> None:
    p = _proposal()
    assert p.proposed_rule
    assert p.proposed_reply
    assert p.suggested_scope in {"vip", "all"}
    assert 0.0 <= p.confidence <= 1.0


# --- Generation (happy path) ---------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_proposal_with_rule_and_reply() -> None:
    llm = _FakeLLM(response=_proposal())
    svc = _service(llm=llm)
    result = await svc.generate(
        question="¿Hay descuento por volumen?",
        draft="borrador original",
        channel_type="vip",
    )
    assert isinstance(result, GrayZoneProposal)
    assert result.proposed_rule
    assert result.proposed_reply
    # Prompt must include the original message as context (AGENTS §4.5).
    prompt_text = "\n".join(str(m) for m in llm.calls[0])
    assert "¿Hay descuento por volumen?" in prompt_text
    assert "borrador original" in prompt_text


@pytest.mark.asyncio
async def test_generate_never_writes_knowledge_banks() -> None:
    """The proposal path must make ZERO writes to knowledge stores.

    The service only reads (policies/gold/persona) and calls the LLM; no
    repository write method may be touched on this path (EA-05 mirror).
    """
    class _ReadOnlyRepo:
        def __init__(self) -> None:
            self.writes: list[str] = []

        async def list_active_for_vip(self, vip_id, limit: int = 5):
            return [{"rule": "regla global", "scope": "all", "trigger_description": "q"}]

        async def list_gold_global(self, limit: int = 3):
            return [{"turn_text": "t", "draft_text": "d", "corrected_text": "c"}]

        def __getattr__(self, name: str):
            # Any write-looking call must be recorded and fail the test.
            if name.startswith(("insert", "update", "delete", "promote", "save")):
                self.writes.append(name)
                return lambda *a, **k: (_ for _ in ()).throw(
                    AssertionError(f"write call {name} on proposal path")
                )
            raise AttributeError(name)

    repo = _ReadOnlyRepo()
    svc = GrayZoneProposalService(
        llm=_FakeLLM(response=_proposal()),
        policies_reader=repo,
        gold_reader=repo,
    )
    result = await svc.generate(
        question="¿Hay descuento?",
        draft="d",
        channel_type="vip",
    )
    assert result is not None
    assert repo.writes == []


@pytest.mark.asyncio
async def test_generate_fail_open_on_llm_error() -> None:
    """LLM error/timeout → None (never raises, never loses the query)."""
    svc = _service(llm=_FakeLLM(exc=ValueError("model exploded")))
    result = await svc.generate(
        question="¿Hay descuento?",
        draft="d",
        channel_type="vip",
    )
    assert result is None


@pytest.mark.asyncio
async def test_generate_fail_open_on_schema_mismatch() -> None:
    """Invalid/empty output → None (fail-open), not a crash."""
    svc = _service(llm=_FakeLLM(response={"proposed_rule": ""}))
    result = await svc.generate(
        question="¿Hay descuento?",
        draft="d",
        channel_type="vip",
    )
    assert result is None


@pytest.mark.asyncio
async def test_generate_includes_global_policies_and_gold_context() -> None:
    """The restricted general-context loan feeds the prompt (read-only)."""
    class _Repo:
        async def list_active_for_vip(self, vip_id, limit: int = 5):
            return [{"rule": "Nunca revelar precios sin consultar", "scope": "all"}]

        async def list_gold_global(self, limit: int = 3):
            return [{"turn_text": "¿precio?", "corrected_text": "te paso precio por DM"}]

    llm = _FakeLLM(response=_proposal())
    svc = GrayZoneProposalService(
        llm=llm,
        policies_reader=_Repo(),
        gold_reader=_Repo(),
    )
    await svc.generate(question="¿precio?", draft="d", channel_type="vip")
    prompt_text = "\n".join(str(m) for m in llm.calls[0])
    assert "Nunca revelar precios" in prompt_text
    assert "te paso precio por DM" in prompt_text


@pytest.mark.asyncio
async def test_generate_atencion_channel_uses_isolated_context() -> None:
    """Atención (no-VIP) proposal must never see VIP material (F4 isolation)."""
    class _Repo:
        async def list_active_for_vip(self, vip_id, limit: int = 5):
            assert vip_id is None  # atencion → globals only
            return [{"rule": "Regla general de atención", "scope": "all"}]

        async def list_gold_global(self, limit: int = 3):
            return []

    llm = _FakeLLM(response=_proposal())
    svc = GrayZoneProposalService(llm=llm, policies_reader=_Repo(), gold_reader=_Repo())
    result = await svc.generate(
        question="¿Cuánto cuesta?",
        draft="d",
        channel_type="atencion",
    )
    assert result is not None


# --- Usar regla propuesta semantics --------------------------------------


def test_proposal_is_rule_not_message() -> None:
    """The adopted value is the RULE, never the VIP-facing reply."""
    p = _proposal()
    assert p.proposed_rule != p.proposed_reply
    # The reply is a labeled reference; the rule is what persists (AGENTS §4.5).
    assert p.proposed_rule
