"""hardener/persona-reglas ítem 1: Políticas y Patrones de voz llegan al modelo.

Mismo patrón que test_persona_facts_matching.py (commit 6507796):
normalización en ambos lados del cruce, guardado canónico en el panel,
vocabulario por canal para el Analyst y efecto en zona gris.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.retrievers.policy import PolicyRetriever
from diana.cognitive.retrievers.voice_patterns import VoicePatternsRetriever
from diana.cognitive.tags import (
    catalog_fact_topics,
    catalog_pattern_tags,
    catalog_policy_topics,
    fair_share_limits,
    normalize_tag,
)
from diana.telegram.handlers.persona_admin import (
    _parse_pattern,
    _parse_policy,
    apply_persona_edit,
)


def _turn(channel: str = "vip") -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=1, text="hola", channel_type=channel)  # type: ignore[arg-type]


def _comp(
    topics: list[str],
    *,
    intent: str = "otro",
    emotion: str = "neutral",
    needs_policy: bool = False,
    needs_voice: bool = False,
) -> Comprehension:
    return Comprehension(
        intent=intent,
        topics=topics,
        emotion=emotion,  # type: ignore[arg-type]
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=needs_policy,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
        needs_voice_patterns=needs_voice,
    )


class _Provider:
    def __init__(self, by_channel: dict) -> None:
        self.by_channel = by_channel
        self.requested: list[str] = []

    async def get_catalog(self, channel_type: str = "vip"):
        self.requested.append(channel_type)
        return self.by_channel.get(channel_type)


# --- 1. normalización: idempotencia (llave de cruce para ítems 3 y 5) -------


@pytest.mark.parametrize(
    "raw",
    ["Precios especiales", "cariño", "extrañar", "precios/pagos", "Tema-pesado", "tono "],
)
def test_normalize_tag_is_idempotent(raw) -> None:
    once = normalize_tag(raw)
    assert normalize_tag(once) == once


# --- 2. panel: guardado canónico ------------------------------------------


def test_panel_parse_policy_stores_normalized_temas() -> None:
    item = _parse_policy("precios_esp | Precios especiales, Costos | No doy descuentos")
    assert item == {
        "id": "precios_esp",
        "tema": ["precios_especiales", "costos"],
        "regla": "No doy descuentos",
    }


def test_panel_parse_pattern_stores_normalized_tags() -> None:
    item = _parse_pattern("dificil | Tema pesado, Cariño | ay amor | Temas difíciles")
    assert item == {
        "id": "dificil",
        "tags": ["tema_pesado", "carino"],
        "patron": "ay amor",
        "uso": "Temas difíciles",
    }


@pytest.mark.parametrize(
    "text",
    ["p | - , __ | regla", "p | ‐ | regla"],
)
def test_panel_parse_policy_rejects_temas_that_normalize_to_empty(text) -> None:
    with pytest.raises(ValueError):
        _parse_policy(text)


def test_panel_parse_pattern_rejects_tags_that_normalize_to_empty() -> None:
    with pytest.raises(ValueError):
        _parse_pattern("p | - , __ | patron | uso")


def test_apply_persona_edit_policy_and_pattern_canonical() -> None:
    base = {"policies": [], "voice_patterns": []}
    out = apply_persona_edit(base, "policy", None, "p1 | Precios especiales | Regla")
    assert out["policies"][-1]["tema"] == ["precios_especiales"]
    out = apply_persona_edit(out, "pattern", None, "v1 | Tema pesado | patron | uso")
    assert out["voice_patterns"][-1]["tags"] == ["tema_pesado"]


# --- 3. lectura: legacy sin normalizar coincide (ambos lados) ---------------


async def test_policy_legacy_raw_tema_matches_normalized_topic() -> None:
    legacy = [{"id": "pe", "tema": ["Precios especiales"], "regla": "No hay descuentos."}]
    r = PolicyRetriever(static_policies=legacy)
    out = await r.fetch(_turn(), _comp(["precios_especiales"], needs_policy=True))
    assert out == ["Trigger: pe | Rule: No hay descuentos."]
    # Y al revés: el Analyst emite el tema con acento/espacios.
    out = await r.fetch(_turn(), _comp(["Precios Especiales"], needs_policy=True))
    assert out == ["Trigger: pe | Rule: No hay descuentos."]


async def test_policy_scalar_tema_and_intent_signal_normalized() -> None:
    r = PolicyRetriever(static_policies=[{"id": "x", "tema": "Pedir Consejo", "regla": "R"}])
    out = await r.fetch(_turn(), _comp([], intent="pedir_consejo"))
    assert out == ["Trigger: x | Rule: R"]


async def test_policy_no_match_still_returns_empty_list() -> None:
    r = PolicyRetriever(static_policies=[{"id": "x", "tema": ["precios"], "regla": "R"}])
    assert await r.fetch(_turn(), _comp(["", "  "], intent="")) == []


_VOICE = [
    {"id": "dificil", "tags": ["Tema pesado"], "patron": "ay amor", "uso": "U1"},
    {"id": "apodo", "tags": ["cariño"], "patron": "amor", "uso": "U2"},
]


async def test_voice_legacy_raw_tag_matches_normalized_topic() -> None:
    r = VoicePatternsRetriever(_VOICE)
    out = await r.fetch(_turn(), _comp(["tema_pesado"], needs_voice=True))
    assert out == {"patron": "ay amor", "uso": "U1"}


async def test_voice_accented_tag_matches_both_raw_and_normalized_signals() -> None:
    r = VoicePatternsRetriever(_VOICE)
    # topic normalizado que ahora ofrece el addendum
    assert await r.fetch(_turn(), _comp(["carino"])) == {"patron": "amor", "uso": "U2"}
    # topic crudo de la lista fija de _SYSTEM
    assert await r.fetch(_turn(), _comp(["cariño"])) == {"patron": "amor", "uso": "U2"}


async def test_voice_static_carinosa_tag_matches_emotion_enum() -> None:
    """R2: emoción ``cariñosa`` (enum crudo) ↔ tag ``cariñosa`` normalizado en ambos lados."""
    patterns = [{"id": "a", "tags": ["cariñosa"], "patron": "P", "uso": "U"}]
    r = VoicePatternsRetriever(patterns)
    assert await r.fetch(_turn(), _comp([], emotion="cariñosa")) == {"patron": "P", "uso": "U"}


async def test_voice_string_tags_do_not_crash() -> None:
    """R8: ``tags`` como string ya no cuenta caracteres ni divide entre cero."""
    r = VoicePatternsRetriever([{"id": "r", "tags": "risa", "patron": "jsjs", "uso": "U"}])
    assert await r.fetch(_turn(), _comp(["risa"])) == {"patron": "jsjs", "uso": "U"}


# --- 4. helpers de vocabulario: puros, sin tope por defecto, por tipo -------


def test_catalog_policy_topics_normalized_distinct_in_order() -> None:
    catalog = {
        "policies": [
            {"tema": ["Precios especiales", "costos"]},
            {"tema": "costos"},
            {"tema": ["Citas"]},
            "junk",
            {"regla": "sin tema"},
        ],
        "voice_patterns": [{"tags": ["risa"]}],
        "persona_facts": [{"tema": ["familia"]}],
    }
    assert catalog_policy_topics(catalog) == ["precios_especiales", "costos", "citas"]
    assert catalog_policy_topics(None) == []
    assert catalog_policy_topics({"policies": "bad"}) == []
    assert catalog_policy_topics({}) == []


def test_catalog_pattern_tags_normalized_distinct_in_order() -> None:
    catalog = {
        "voice_patterns": [
            {"tags": ["Tema pesado", "cariño"]},
            {"tags": "risa"},
            {"tags": ["cariño", "extrañar"]},
            42,
        ],
        "policies": [{"tema": ["precios"]}],
    }
    assert catalog_pattern_tags(catalog) == ["tema_pesado", "carino", "risa", "extranar"]
    assert catalog_pattern_tags(None) == []
    assert catalog_pattern_tags({"voice_patterns": {"x": 1}}) == []


def test_vocabulary_helpers_have_no_default_cap_but_accept_limit() -> None:
    many_pol = {"policies": [{"tema": [f"t{i}" for i in range(99)]}]}
    many_voz = {"voice_patterns": [{"tags": [f"g{i}" for i in range(99)]}]}
    assert len(catalog_policy_topics(many_pol)) == 99
    assert len(catalog_pattern_tags(many_voz)) == 99
    assert len(catalog_policy_topics(many_pol, limit=5)) == 5
    assert len(catalog_pattern_tags(many_voz, limit=5)) == 5
    # catalog_fact_topics conserva su firma/tope compatibles (limit=60).
    many_facts = {"persona_facts": [{"tema": [f"f{i}" for i in range(99)]}]}
    assert len(catalog_fact_topics(many_facts)) == 60
    assert len(catalog_fact_topics(many_facts, limit=None)) == 99


def test_vocabulary_helpers_are_separated_by_section() -> None:
    catalog = {
        "persona_facts": [{"tema": ["familia"]}],
        "policies": [{"tema": ["precios"]}],
        "voice_patterns": [{"tags": ["risa"]}],
    }
    assert catalog_fact_topics(catalog) == ["familia"]
    assert catalog_policy_topics(catalog) == ["precios"]
    assert catalog_pattern_tags(catalog) == ["risa"]


# --- 5. presupuesto justo por tipo (puro; reutilizable por ítems 3 y 5) -----


@pytest.mark.parametrize(
    ("sizes", "budget", "expected"),
    [
        # Todo cabe → nada se recorta (estáticos VIP 14/9/28 y atención 7/14/12).
        ([14, 9, 28], 60, [14, 9, 28]),
        ([7, 14, 12], 60, [7, 14, 12]),
        ([20, 20, 20], 60, [20, 20, 20]),
        # 60+ Datos: Políticas y Voz conservan su parte.
        ([70, 8, 28], 60, [26, 8, 26]),
        ([70, 8, 8], 60, [44, 8, 8]),
        ([100, 100, 100], 60, [20, 20, 20]),
        # Un solo tipo presente → todo el presupuesto.
        ([100, 0, 0], 60, [60, 0, 0]),
        ([0, 100, 0], 60, [0, 60, 0]),
        ([0, 0, 100], 60, [0, 0, 60]),
        # Sobrante indivisible → +1 a los primeros activos en orden de entrada.
        ([100, 7, 100], 60, [27, 7, 26]),
        ([100, 100, 100], 62, [21, 21, 20]),
        ([5, 5, 5], 2, [1, 1, 0]),
        # Ausentes / vacíos / presupuesto 0.
        ([0, 0, 0], 60, [0, 0, 0]),
        ([], 60, []),
        ([10, 10, 10], 0, [0, 0, 0]),
    ],
)
def test_fair_share_limits_cases(sizes, budget, expected) -> None:
    assert fair_share_limits(sizes, budget) == expected


def test_fair_share_limits_rejects_negative_budget() -> None:
    with pytest.raises(ValueError):
        fair_share_limits([1, 2, 3], -1)


def test_fair_share_limits_invariants_and_determinism() -> None:
    budget = 60
    for a in range(0, 75, 7):
        for b in range(0, 75, 11):
            for c in range(0, 75, 13):
                sizes = [a, b, c]
                limits = fair_share_limits(sizes, budget)
                assert limits == fair_share_limits(list(sizes), budget)  # determinista
                assert all(0 <= lim <= s for lim, s in zip(limits, sizes))
                assert sum(limits) == min(budget, sum(sizes))
                present = [s for s in sizes if s > 0]
                if present:
                    floor = budget // len(present)
                    for lim, s in zip(limits, sizes):
                        if s > 0:
                            assert lim >= min(s, floor), (sizes, limits)
