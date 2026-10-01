"""fix/persona-facts-matching: gray-zone proposal uses the live panel catalog,
respects the conversation channel and NEVER lends ``nota_privada``."""

from __future__ import annotations

import json
from typing import Any

from diana.application.gray_zone_proposal_service import (
    GrayZoneProposal,
    GrayZoneProposalService,
)


class _LLM:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def generate_structured(self, messages: list[dict], schema: type, **_: Any):
        self.calls.append(list(messages))
        return GrayZoneProposal(proposed_rule="regla", confidence=0.5)


class _Provider:
    def __init__(self, by_channel: dict | None = None, exc: Exception | None = None) -> None:
        self.by_channel = by_channel or {}
        self.exc = exc
        self.requested: list[str] = []

    async def get_catalog(self, channel_type: str = "vip"):
        self.requested.append(channel_type)
        if self.exc:
            raise self.exc
        return self.by_channel.get(channel_type)


_STATIC_VIP = [
    {"id": "s", "tema": ["familia"], "hecho": "static vip", "nota_privada": "PRIVADO-STATIC"},
]


def _loan(llm: _LLM) -> dict:
    payload = json.loads(llm.calls[-1][1]["content"])
    return payload["general_context_loan"]


async def test_uses_live_catalog_for_channel_and_strips_nota_privada() -> None:
    provider = _Provider(
        {
            "vip": {
                "persona_facts": [
                    {"id": "v", "tema": ["familia"], "hecho": "live vip", "nota_privada": "PRIVADO-LIVE"},
                ],
                "voice_patterns": [{"id": "p", "patron": "jaja", "nota_privada": "X"}],
            },
            "atencion": {
                "persona_facts": [{"id": "a", "tema": ["pago"], "hecho": "live atencion"}],
                "voice_patterns": [],
            },
        }
    )
    llm = _LLM()
    svc = GrayZoneProposalService(
        llm=llm, persona_facts=_STATIC_VIP, persona_catalog_provider=provider
    )

    await svc.generate(question="q", draft="d", channel_type="vip")
    loan = _loan(llm)
    raw = llm.calls[-1][1]["content"]
    assert loan["persona_facts"] == [{"tema": ["familia"], "hecho": "live vip"}]
    assert "PRIVADO" not in raw and "nota_privada" not in raw
    assert loan["voice_patterns"] == [{"id": "p", "patron": "jaja"}]

    await svc.generate(question="q", draft="d", channel_type="atencion")
    loan = _loan(llm)
    assert loan["persona_facts"] == [{"tema": ["pago"], "hecho": "live atencion"}]
    assert "live vip" not in llm.calls[-1][1]["content"]
    assert provider.requested == ["vip", "atencion"]


async def test_provider_failure_vip_falls_back_to_static_sanitized() -> None:
    llm = _LLM()
    svc = GrayZoneProposalService(
        llm=llm,
        persona_facts=_STATIC_VIP,
        persona_catalog_provider=_Provider(exc=RuntimeError("db down")),
    )
    out = await svc.generate(question="q", draft="d", channel_type="vip")
    assert out is not None  # fail-open preserved
    assert _loan(llm)["persona_facts"] == [{"tema": ["familia"], "hecho": "static vip"}]
    assert "PRIVADO-STATIC" not in llm.calls[-1][1]["content"]


async def test_atencion_never_borrows_static_vip_facts() -> None:
    llm = _LLM()
    svc = GrayZoneProposalService(
        llm=llm, persona_facts=_STATIC_VIP, persona_catalog_provider=_Provider({})
    )
    await svc.generate(question="q", draft="d", channel_type="atencion")
    assert _loan(llm)["persona_facts"] == []
    # No provider at all: atencion still gets nothing from the VIP static slice.
    llm2 = _LLM()
    svc2 = GrayZoneProposalService(llm=llm2, persona_facts=_STATIC_VIP)
    await svc2.generate(question="q", draft="d", channel_type="atencion")
    assert _loan(llm2)["persona_facts"] == []


async def test_no_provider_vip_uses_static_without_nota_privada() -> None:
    llm = _LLM()
    svc = GrayZoneProposalService(llm=llm, persona_facts=_STATIC_VIP)
    await svc.generate(question="q", draft="d", channel_type="vip")
    assert _loan(llm)["persona_facts"] == [{"tema": ["familia"], "hecho": "static vip"}]
    assert "nota_privada" not in llm.calls[-1][1]["content"]
