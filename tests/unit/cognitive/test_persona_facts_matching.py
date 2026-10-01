"""fix/persona-facts-matching: owner-panel "Datos personales" reach the LLM.

Covers: shared tema normalization (panel write + retriever read, legacy rows),
dynamic catalog temas in the Analyst prompt (per channel), atencion channel
guidance, multi-fact retrieval (configurable cap, score order), Evaluator
evidence, and the Analyst prompt typo fix.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.cognitive import analyst as analyst_mod
from diana.cognitive.context_builder import EVALUATOR_KNOWLEDGE_BLOCKS, ContextBuilder
from diana.cognitive.models import AnalystInput, Comprehension, IncomingTurn
from diana.cognitive.persona_catalog import (
    get_persona_atencion_catalog,
    get_persona_catalog,
)
from diana.cognitive.registry import build_default_registry
from diana.cognitive.retrievers.persona_facts import (
    DEFAULT_MAX_PERSONA_FACTS,
    PersonaFactsRetriever,
)
from diana.cognitive.tags import catalog_fact_topics, normalize_tag, normalize_tags
from diana.config.settings import Settings
from diana.cognitive.ports import InMemoryMessageHistory
from diana.telegram.handlers.persona_admin import _parse_fact, apply_persona_edit


def _turn(channel: str = "vip") -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=1, text="hola", channel_type=channel)  # type: ignore[arg-type]


def _comp(topics: list[str], intent: str = "otro", needs: bool = True) -> Comprehension:
    return Comprehension(
        intent=intent,
        topics=topics,
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
        needs_persona_facts=needs,
    )


class _Provider:
    def __init__(self, by_channel: dict) -> None:
        self.by_channel = by_channel
        self.requested: list[str] = []

    async def get_catalog(self, channel_type: str = "vip"):
        self.requested.append(channel_type)
        return self.by_channel.get(channel_type)


# --- 2. normalization ------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Motivación personal", "motivacion_personal"),
        ("  motivacion   PERSONAL  ", "motivacion_personal"),
        ("auto-cuidado", "auto_cuidado"),
        ("auto - cuidado", "auto_cuidado"),
        ("Atención", "atencion"),
        ("Ñoño", "nono"),
        ("motivacion_personal", "motivacion_personal"),
        ("__x__", "x"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_tag(raw, expected) -> None:
    assert normalize_tag(raw) == expected


def test_normalize_tags_dedupes_and_accepts_scalar() -> None:
    assert normalize_tags(["Familia", "familia", " ", "Duelo"]) == ["familia", "duelo"]
    assert normalize_tags("Vivienda") == ["vivienda"]
    assert normalize_tags(None) == []


def test_panel_parse_fact_stores_normalized_temas() -> None:
    item = _parse_fact("mot | Motivación personal, Estudios | Quise entenderme | nota")
    assert item["tema"] == ["motivacion_personal", "estudios"]
    assert item["nota_privada"] == "nota"


def test_panel_parse_fact_rejects_temas_that_normalize_to_empty() -> None:
    with pytest.raises(ValueError):
        _parse_fact("x | - , __ | hecho")


async def test_legacy_unnormalized_rows_still_match() -> None:
    """Rows saved before this fix (accents/spaces) match normalized topics."""
    legacy = [{"id": "m", "tema": ["Motivación personal"], "hecho": "Quise entenderme."}]
    r = PersonaFactsRetriever(legacy)
    out = await r.fetch(_turn(), _comp(["motivacion_personal"]))
    assert out == [{"hecho": "Quise entenderme.", "tema": "motivacion_personal"}]
    # And the reverse: the Analyst emitting an accented/spaced topic.
    out = await r.fetch(_turn(), _comp(["Motivación Personal"]))
    assert out is not None and out[0]["hecho"] == "Quise entenderme."


# --- 1. owner-added temas reachable via dynamic Analyst vocabulary ---------


def test_catalog_fact_topics_normalized_distinct_in_order() -> None:
    catalog = {
        "persona_facts": [
            {"tema": ["Mascota", "gatos"]},
            {"tema": "mascota"},
            {"tema": ["Viajes favoritos"]},
            "junk",
        ]
    }
    assert catalog_fact_topics(catalog) == ["mascota", "gatos", "viajes_favoritos"]
    assert catalog_fact_topics(None) == []
    assert catalog_fact_topics({"persona_facts": "bad"}) == []
    assert len(catalog_fact_topics({"persona_facts": [{"tema": [f"t{i}" for i in range(99)]}]}, limit=5)) == 5


def test_analyst_prompt_vip_without_catalog_is_unchanged_base() -> None:
    msgs = analyst_mod.Analyst(llm=None)._build_messages(  # type: ignore[arg-type]
        AnalystInput(turno_actual="hola", historial_reciente=[])
    )
    assert msgs[0]["content"] == analyst_mod._SYSTEM


def test_analyst_prompt_lists_active_catalog_temas() -> None:
    msgs = analyst_mod.Analyst(llm=None)._build_messages(  # type: ignore[arg-type]
        AnalystInput(
            turno_actual="¿tienes mascota?",
            historial_reciente=[],
            catalog_topics=["mascota", "viajes_favoritos"],
        )
    )
    system = msgs[0]["content"]
    assert system.startswith(analyst_mod._SYSTEM)
    assert "Active catalog temas (channel vip): mascota, viajes_favoritos" in system
    assert "ALSO valid topics" in system
    assert "biography" in system


def test_analyst_typo_fixed_topic_list_sentence_closed() -> None:
    assert "conexion, Set each" not in analyst_mod._SYSTEM
    assert "conexion — or from the active catalog temas" in analyst_mod._SYSTEM


async def test_owner_added_tema_end_to_end_reaches_generator_prompt() -> None:
    """Panel edit → live catalog → Analyst vocabulary → retriever → prompt."""
    static = get_persona_catalog()
    edited = apply_persona_edit(
        static, "fact", None, "gato | Mascota, Gatos | Tengo un gato llamado Michi | secreto"
    )
    assert "mascota" in catalog_fact_topics(edited)
    provider = _Provider({"vip": edited})
    registry = build_default_registry(
        InMemoryMessageHistory(),
        persona_facts=static["persona_facts"],
        persona_catalog_provider=provider,  # type: ignore[arg-type]
    )
    comp = _comp(["mascota"])
    facts = await registry.resolve("knowledge.persona_facts").fetch(_turn(), comp)
    assert facts == [{"hecho": "Tengo un gato llamado Michi", "tema": "mascota"}]
    built = ContextBuilder().build(
        _turn(), comp, {"knowledge.persona_facts": facts}, persona="P"
    )
    assert "Tengo un gato llamado Michi" in built.prompt_final
    assert "secreto" not in built.prompt_final


# --- 3. atencion channel -----------------------------------------------------


def test_analyst_prompt_atencion_guidance_and_temas() -> None:
    temas = catalog_fact_topics(get_persona_atencion_catalog())
    assert {"negocio", "atencion", "servicio", "entrega", "pago"} <= set(temas)
    msgs = analyst_mod.Analyst(llm=None)._build_messages(  # type: ignore[arg-type]
        AnalystInput(
            turno_actual="¿cómo pago?",
            historial_reciente=[],
            channel_type="atencion",
            catalog_topics=temas,
        )
    )
    system = msgs[0]["content"]
    assert "CHANNEL: atencion" in system
    assert "payment" in system and "business" in system
    assert "Active catalog temas (channel atencion)" in system
    assert "pago" in system


def test_analyst_prompt_atencion_guidance_without_catalog() -> None:
    msgs = analyst_mod.Analyst(llm=None)._build_messages(  # type: ignore[arg-type]
        AnalystInput(turno_actual="x", historial_reciente=[], channel_type="atencion")
    )
    assert "CHANNEL: atencion" in msgs[0]["content"]
    assert "Active catalog temas" not in msgs[0]["content"]


@pytest.mark.parametrize("tema", ["negocio", "atencion", "servicio", "entrega", "pago"])
async def test_atencion_catalog_temas_match(tema: str) -> None:
    provider = _Provider({"atencion": get_persona_atencion_catalog()})
    r = PersonaFactsRetriever([], persona_catalog_provider=provider)  # type: ignore[arg-type]
    out = await r.fetch(_turn("atencion"), _comp([tema]))
    assert out, f"atencion tema {tema!r} must match a fact"
    assert all(set(f) == {"hecho", "tema"} for f in out)
    assert provider.requested == ["atencion"]


# --- 4. multiple facts per turn -----------------------------------------------

_MULTI = [
    {"id": "a", "tema": ["familia"], "hecho": "A"},
    {"id": "b", "tema": ["familia", "duelo"], "hecho": "B"},
    {"id": "c", "tema": ["familia"], "hecho": "C"},
    {"id": "d", "tema": ["familia"], "hecho": "D"},
    {"id": "e", "tema": ["estudios"], "hecho": "E"},
]


async def test_multiple_facts_ordered_by_score_capped_default() -> None:
    assert DEFAULT_MAX_PERSONA_FACTS == 3
    r = PersonaFactsRetriever(_MULTI)
    out = await r.fetch(_turn(), _comp(["familia", "duelo"]))
    assert out is not None
    hechos = [f["hecho"] for f in out]
    assert hechos[0] == "B"  # familia + duelo (most specific) wins
    assert len(hechos) == 3  # capped
    assert hechos[1:] == ["A", "C"]  # ties keep catalog order
    assert "E" not in hechos  # no intersection → never included


async def test_max_facts_configurable() -> None:
    one = await PersonaFactsRetriever(_MULTI, max_facts=1).fetch(_turn(), _comp(["familia"]))
    assert one is not None and len(one) == 1
    many = await PersonaFactsRetriever(_MULTI, max_facts=10).fetch(_turn(), _comp(["familia"]))
    assert many is not None and [f["hecho"] for f in many] == ["A", "B", "C", "D"]
    with pytest.raises(ValueError):
        PersonaFactsRetriever(_MULTI, max_facts=0)


async def test_registry_propagates_persona_facts_max() -> None:
    registry = build_default_registry(
        InMemoryMessageHistory(), persona_facts=_MULTI, persona_facts_max=2
    )
    out = await registry.resolve("knowledge.persona_facts").fetch(_turn(), _comp(["familia"]))
    assert out is not None and len(out) == 2


def test_settings_persona_facts_max_default_and_bounds(monkeypatch) -> None:
    field = Settings.model_fields["persona_facts_max_per_turn"]
    assert field.default == 3
    metas = {type(m).__name__: m for m in field.metadata}
    assert getattr(metas.get("Ge"), "ge", None) == 1
    assert getattr(metas.get("Le"), "le", None) == 10


# --- 6. Evaluator evidence ------------------------------------------------------


def test_evaluator_receives_persona_facts_block() -> None:
    assert "knowledge.persona_facts" in EVALUATOR_KNOWLEDGE_BLOCKS
    rendered = ContextBuilder().render_knowledge_sections(
        {
            "knowledge.persona_facts": [{"hecho": "Tengo una hermana", "tema": "familia"}],
            "knowledge.history": [{"role": "vip", "text": "style-heavy"}],
        }
    )
    assert "Tengo una hermana" in rendered
    assert "style-heavy" not in rendered
