"""Unit tests for PersonaFactsRetriever (set intersection, no embeddings)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.retrievers.persona_facts import PersonaFactsRetriever


def _turn(text: str = "hola") -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=1, text=text)


def _comp(**overrides: object) -> Comprehension:
    data: dict = {
        "intent": "chat",
        "topics": [],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        "needs_memory": False,
        "needs_policy": False,
        "needs_schedule": False,
        "needs_examples": False,
        "needs_history": False,
        "needs_context": False,
        "needs_persona_facts": True,
    }
    data.update(overrides)
    return Comprehension(**data)  # type: ignore[arg-type]


_MINI_FACTS = [
    {
        "id": "familia_hermana",
        "tema": ["familia"],
        "hecho": "Tengo una hermana, Laura.",
        "nota_privada": "NO mencionar gastritis.",
    },
    {
        "id": "familia_duelo",
        "tema": ["familia", "duelo"],
        "hecho": "Perdí a mi mamá el año pasado.",
    },
    {
        "id": "estudios",
        "tema": ["estudios"],
        "hecho": "Termino psicología.",
    },
]


@pytest.mark.asyncio
async def test_persona_facts_match_by_topic() -> None:
    retriever = PersonaFactsRetriever(_MINI_FACTS)
    result = await retriever.fetch(_turn(), _comp(topics=["familia"]))
    assert result is not None
    assert result["hecho"] == "Tengo una hermana, Laura."
    assert result["tema"] == "familia"
    assert set(result.keys()) == {"hecho", "tema"}


@pytest.mark.asyncio
async def test_persona_facts_match_by_intent_only() -> None:
    retriever = PersonaFactsRetriever(_MINI_FACTS)
    result = await retriever.fetch(
        _turn(),
        _comp(intent="duelo", topics=[]),
    )
    assert result is not None
    assert "mamá" in result["hecho"] or "mama" in result["hecho"].lower()
    assert result["tema"] in ("familia", "duelo")


@pytest.mark.asyncio
async def test_persona_facts_no_match_returns_none() -> None:
    retriever = PersonaFactsRetriever(_MINI_FACTS)
    result = await retriever.fetch(
        _turn(),
        _comp(intent="saludo", topics=["clima"]),
    )
    assert result is None


@pytest.mark.asyncio
async def test_persona_facts_never_emits_nota_privada() -> None:
    retriever = PersonaFactsRetriever(_MINI_FACTS)
    result = await retriever.fetch(_turn(), _comp(topics=["familia"]))
    assert result is not None
    assert "nota_privada" not in result
    assert set(result.keys()) == {"hecho", "tema"}


@pytest.mark.asyncio
async def test_persona_facts_empty_catalog_returns_none() -> None:
    retriever = PersonaFactsRetriever([])
    result = await retriever.fetch(_turn(), _comp(topics=["familia"]))
    assert result is None



@pytest.mark.asyncio
async def test_persona_facts_prefers_largest_intersection() -> None:
    """When topics overlap multiple facts, prefer largest |intersection| (ties: list order)."""
    retriever = PersonaFactsRetriever(_MINI_FACTS)
    result = await retriever.fetch(
        _turn(),
        _comp(topics=["familia", "duelo"], intent="chat"),
    )
    assert result is not None
    assert "mamá" in result["hecho"] or "mama" in result["hecho"].lower()
    # familia_duelo intersects {familia, duelo} = 2; hermana only {familia} = 1
    assert result["hecho"] == "Perdí a mi mamá el año pasado."


@pytest.mark.asyncio
async def test_persona_facts_match_is_case_insensitive() -> None:
    retriever = PersonaFactsRetriever(_MINI_FACTS)
    result = await retriever.fetch(
        _turn(),
        _comp(topics=["Familia"], intent="chat"),
    )
    assert result is not None
    assert "Laura" in result["hecho"]



@pytest.mark.asyncio
async def test_production_catalog_familia_gold() -> None:
    """Issue 8: production catalog gold — familia topic returns hermana fact."""
    from diana.cognitive.persona_catalog import load_persona_catalog

    catalog = load_persona_catalog()
    retriever = PersonaFactsRetriever(catalog["persona_facts"])
    result = await retriever.fetch(
        _turn(),
        _comp(topics=["familia"], intent="chat"),
    )
    assert result is not None
    assert "Laura" in result["hecho"]
    assert "nota_privada" not in result


@pytest.mark.asyncio
async def test_production_catalog_motivacion_beats_generic_estudios_tag() -> None:
    """Regression: production trace picked estudios_psicologia (trayectoria/status)
    instead of motivacion_psicologia (the actual "why did you choose this" fact)
    for "qué te llevó a estudiar psicología?" — both facts share the generic
    "estudios" tag, which used to tie plain intersection-count scoring. Tag-
    specificity weighting must make the fact with the unique tag win.
    """
    from diana.cognitive.persona_catalog import load_persona_catalog

    catalog = load_persona_catalog()
    retriever = PersonaFactsRetriever(catalog["persona_facts"])
    result = await retriever.fetch(
        _turn("Oye y qué te llevo a estudiar psicología?"),
        _comp(
            intent="preguntar_motivacion_estudios",
            topics=["trayectoria", "estudios", "motivacion_personal"],
        ),
    )
    assert result is not None
    assert "ansiedad" in result["hecho"].lower() or "entender" in result["hecho"].lower(), (
        "expected the motivacion_psicologia fact (the 'why'), got: "
        f"{result['hecho']!r}"
    )


@pytest.mark.asyncio
async def test_weighted_score_prefers_specific_tag_over_shared_tag() -> None:
    """Unit-level version of the regression, isolated from the real catalog."""
    facts = [
        {"id": "a_shared_plus_common", "tema": ["comun", "raro_a"], "hecho": "A"},
        {"id": "b_shared_plus_rare", "tema": ["comun", "raro_b"], "hecho": "B"},
        {"id": "c_only_common", "tema": ["comun"], "hecho": "C"},
    ]
    retriever = PersonaFactsRetriever(facts)
    # "comun" appears in all 3 facts (weight 1/3 each); "raro_b" appears only
    # in fact B (weight 1). Topics hit both "comun" and "raro_b" -> B should
    # win over A (which only hits "comun") even though plain count would tie
    # A and B at 1-each-intersection-with-"comun"-only... here it's simpler:
    # B's weighted score (1/3 + 1) > A's weighted score (1/3 only, no raro_a hit).
    result = await retriever.fetch(_turn(), _comp(topics=["comun", "raro_b"]))
    assert result is not None
    assert result["hecho"] == "B"


class _FakeProvider:
    """Minimal PersonaCatalogProvider double with a mutable catalog."""

    def __init__(self, catalog) -> None:
        self.catalog = catalog

    async def get_catalog(self, channel_type: str = "vip"):
        return self.catalog


@pytest.mark.asyncio
async def test_hot_swap_persona_facts_via_provider() -> None:
    from diana.cognitive.retrievers.persona_facts import PersonaFactsRetriever

    v1 = {"persona_facts": [{"id": "a", "tema": ["familia"], "hecho": "hecho v1"}]}
    v2 = {"persona_facts": [{"id": "b", "tema": ["familia"], "hecho": "hecho v2"}]}
    provider = _FakeProvider(dict(v1))
    retriever = PersonaFactsRetriever(persona_catalog_provider=provider)  # type: ignore[arg-type]

    result = await retriever.fetch(_turn(), _comp(topics=["familia"]))
    assert result is not None and result["hecho"] == "hecho v1"

    # New catalog object (simulates invalidate + new DB payload) → hot swap.
    provider.catalog = dict(v2)
    result = await retriever.fetch(_turn(), _comp(topics=["familia"]))
    assert result is not None and result["hecho"] == "hecho v2"


@pytest.mark.asyncio
async def test_provider_none_falls_back_to_constructor_state() -> None:
    from diana.cognitive.retrievers.persona_facts import PersonaFactsRetriever

    provider = _FakeProvider(None)
    retriever = PersonaFactsRetriever(
        _MINI_FACTS,
        persona_catalog_provider=provider,  # type: ignore[arg-type]
    )
    result = await retriever.fetch(_turn(), _comp(topics=["familia"]))
    assert result is not None and "Laura" in result["hecho"]



@pytest.mark.asyncio
async def test_identity_stable_no_rebuild() -> None:
    """Same catalog object across fetches must NOT rebuild retriever state."""
    from diana.cognitive.retrievers.persona_facts import PersonaFactsRetriever

    catalog = {"persona_facts": [{"id": "a", "tema": ["familia"], "hecho": "hecho"}]}
    provider = _FakeProvider(catalog)
    retriever = PersonaFactsRetriever(persona_catalog_provider=provider)  # type: ignore[arg-type]

    await retriever.fetch(_turn(), _comp(topics=["familia"]))
    first_tag_freq = retriever._tag_freq
    await retriever.fetch(_turn(), _comp(topics=["familia"]))
    # Same catalog object -> same internal state object (no rebuild).
    assert retriever._tag_freq is first_tag_freq


@pytest.mark.asyncio
async def test_missing_slice_keeps_last_good_state() -> None:
    """A live catalog omitting the key must not wipe the retriever state."""
    from diana.cognitive.retrievers.persona_facts import PersonaFactsRetriever

    v1 = {"persona_facts": [{"id": "a", "tema": ["familia"], "hecho": "hecho v1"}]}
    provider = _FakeProvider(dict(v1))
    retriever = PersonaFactsRetriever(persona_catalog_provider=provider)  # type: ignore[arg-type]
    await retriever.fetch(_turn(), _comp(topics=["familia"]))

    provider.catalog = {"other_key": []}  # key missing -> None slice
    result = await retriever.fetch(_turn(), _comp(topics=["familia"]))
    assert result is not None and result["hecho"] == "hecho v1"
