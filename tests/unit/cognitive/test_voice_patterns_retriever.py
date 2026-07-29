"""Unit tests for VoicePatternsRetriever (max 1, set intersection)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.retrievers.voice_patterns import VoicePatternsRetriever


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
        "needs_voice_patterns": True,
    }
    data.update(overrides)
    return Comprehension(**data)  # type: ignore[arg-type]


_MINI_PATTERNS = [
    {
        "id": "risa_jsjs",
        "tags": ["risa", "humor", "casual"],
        "patron": "jsjs / jshshs",
        "uso": "Cuando algo da risa.",
    },
    {
        "id": "saludo_holis",
        "tags": ["saludo", "apertura"],
        "patron": "Holis 😁",
        "uso": "Saludo casual.",
    },
    {
        "id": "apodo_amor",
        "tags": ["cariño", "cercania", "saludo"],
        "patron": "amor",
        "uso": "Para quien le importa.",
    },
]


@pytest.mark.asyncio
async def test_voice_patterns_match_first_by_list_order() -> None:
    retriever = VoicePatternsRetriever(_MINI_PATTERNS)
    result = await retriever.fetch(
        _turn(),
        _comp(emotion="positiva", intent="saludo", topics=["apertura"]),
    )
    assert result is not None
    # saludo_holis is first pattern that intersects saludo/apertura
    assert result["patron"] == "Holis 😁"
    assert set(result.keys()) == {"patron", "uso"}


@pytest.mark.asyncio
async def test_voice_patterns_max_one_never_returns_second_match() -> None:
    """Two patterns share tag 'saludo'; only first in list order is returned."""
    retriever = VoicePatternsRetriever(_MINI_PATTERNS)
    result = await retriever.fetch(
        _turn(),
        _comp(intent="saludo", topics=[], emotion="neutral"),
    )
    assert result is not None
    assert result["patron"] == "Holis 😁"
    assert result["patron"] != "amor"


@pytest.mark.asyncio
async def test_voice_patterns_match_by_emotion() -> None:
    retriever = VoicePatternsRetriever(
        [
            {
                "id": "humor",
                "tags": ["humor", "positiva"],
                "patron": "jsjs",
                "uso": "risa",
            }
        ]
    )
    result = await retriever.fetch(
        _turn(),
        _comp(emotion="positiva", intent="chat", topics=[]),
    )
    assert result is not None
    assert result["patron"] == "jsjs"


@pytest.mark.asyncio
async def test_voice_patterns_no_match_returns_none() -> None:
    retriever = VoicePatternsRetriever(_MINI_PATTERNS)
    result = await retriever.fetch(
        _turn(),
        _comp(emotion="ansiosa", intent="precio", topics=["pago"]),
    )
    assert result is None


@pytest.mark.asyncio
async def test_voice_patterns_empty_catalog_returns_none() -> None:
    retriever = VoicePatternsRetriever([])
    result = await retriever.fetch(_turn(), _comp(intent="saludo"))
    assert result is None



@pytest.mark.asyncio
async def test_production_catalog_emotion_cariñosa_recovers_pattern() -> None:
    """Issue 2: production tags intersect Emotion enum (cariñosa)."""
    from diana.cognitive.persona_catalog import load_persona_catalog

    catalog = load_persona_catalog()
    retriever = VoicePatternsRetriever(catalog["voice_patterns"])
    result = await retriever.fetch(
        _turn(),
        _comp(emotion="cariñosa", intent="chat", topics=[]),
    )
    assert result is not None
    assert "patron" in result and result["patron"]
    assert set(result.keys()) == {"patron", "uso"}


@pytest.mark.asyncio
async def test_production_catalog_emotion_positiva_recovers_pattern() -> None:
    from diana.cognitive.persona_catalog import load_persona_catalog

    catalog = load_persona_catalog()
    retriever = VoicePatternsRetriever(catalog["voice_patterns"])
    result = await retriever.fetch(
        _turn(),
        _comp(emotion="positiva", intent="chat", topics=[]),
    )
    assert result is not None
    assert result["patron"]



@pytest.mark.asyncio
async def test_voice_prefers_largest_intersection_over_first_hit() -> None:
    """Largest |signals ∩ tags| wins over earlier smaller matches."""
    patterns = [
        {
            "id": "early_positiva",
            "tags": ["positiva"],
            "patron": "jsjs",
            "uso": "early",
        },
        {
            "id": "saludo_holis",
            "tags": ["saludo", "apertura", "positiva"],
            "patron": "Holis 😁",
            "uso": "saludo",
        },
    ]
    retriever = VoicePatternsRetriever(patterns)
    result = await retriever.fetch(
        _turn(),
        _comp(emotion="positiva", intent="saludo", topics=["apertura"]),
    )
    assert result is not None
    assert result["patron"] == "Holis 😁"


@pytest.mark.asyncio
async def test_production_multi_signal_saludo_positiva_prefers_holis() -> None:
    """Production: emotion=positiva + saludo should beat early jsjs (score 1)."""
    from diana.cognitive.persona_catalog import load_persona_catalog

    catalog = load_persona_catalog()
    retriever = VoicePatternsRetriever(catalog["voice_patterns"])
    result = await retriever.fetch(
        _turn(),
        _comp(emotion="positiva", intent="saludo", topics=["apertura"]),
    )
    assert result is not None
    assert "Holis" in result["patron"]


@pytest.mark.asyncio
async def test_production_multi_signal_carinosa_extranar_reencuentro() -> None:
    """Production: cariñosa + extrañar → reencuentro (score 2 > apodo score 1)."""
    from diana.cognitive.persona_catalog import load_persona_catalog

    catalog = load_persona_catalog()
    retriever = VoicePatternsRetriever(catalog["voice_patterns"])
    result = await retriever.fetch(
        _turn(),
        _comp(emotion="cariñosa", intent="extrañar", topics=["extrañar"]),
    )
    assert result is not None
    assert "aquí estoy" in result["patron"] or "Cariño pero" in result["patron"]


@pytest.mark.asyncio
async def test_production_catalog_carinosa_vulnerable_disclosure_prefers_calm_tone() -> None:
    """Regression: production trace picked no voice_patterns for a warm-but-
    vulnerable disclosure (motivo de estudiar psicología, ligado a ansiedad
    propia). emotion=cariñosa alone ties 4 patterns (apodo_amor,
    tono_dificil_sin_drama, espontaneidad_poetica, reencuentro_carino) —
    tono_dificil_sin_drama must win once it also carries motivacion_personal,
    not apodo_amor (which was winning on catalog list order before the fix).
    """
    from diana.cognitive.persona_catalog import load_persona_catalog

    catalog = load_persona_catalog()
    retriever = VoicePatternsRetriever(catalog["voice_patterns"])
    result = await retriever.fetch(
        _turn("...pero por qué te decidiste estudiar psicología?"),
        _comp(
            emotion="cariñosa",
            intent="preguntar_motivo_estudios",
            topics=["estudios", "motivacion_personal", "psicologia"],
        ),
    )
    assert result is not None
    assert "sin dramatizar" in result["uso"] or "con calma" in result["uso"], (
        f"expected tono_dificil_sin_drama, got uso={result['uso']!r}"
    )
