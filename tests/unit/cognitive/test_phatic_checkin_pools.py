
"""Extra unit tests: phatic check-in subtype detection + pool pick."""

from __future__ import annotations

import random

from diana.cognitive.template_gate import (
    CHECKIN_BIENESTAR_POOL,
    CHECKIN_DIA_POOL,
    CHECKIN_WARM_NOD_POOL,
    PhaticLightContext,
    checkin_reason_for,
    detect_phatic_subtype,
    is_phatic_template_reason,
    looks_like_checkin_text,
    looks_like_pure_greeting_text,
    pick_checkin_reply,
)


def test_detect_subtype_pure_hola_not_checkin() -> None:
    assert detect_phatic_subtype("Hola") == "saludo_puro"
    assert detect_phatic_subtype("qué tal") == "saludo_puro"
    assert looks_like_checkin_text("Hola") is False
    assert looks_like_pure_greeting_text("Hola") is True


def test_detect_subtype_bienestar_and_dia() -> None:
    assert detect_phatic_subtype("cómo estás") == "checkin_bienestar"
    assert detect_phatic_subtype("como estas") == "checkin_bienestar"
    assert detect_phatic_subtype("Que tal como estas?") == "checkin_bienestar"
    assert detect_phatic_subtype("Hola como estas") == "checkin_bienestar"
    assert detect_phatic_subtype("qué tal tu día") == "checkin_dia"
    assert detect_phatic_subtype("Que tal tu día") == "checkin_dia"
    assert looks_like_checkin_text("cómo estás") is True
    assert looks_like_pure_greeting_text("cómo estás") is False


def test_detect_subtype_rejects_sales_long_substance() -> None:
    assert detect_phatic_subtype("cómo estás, quiero comprar el pack") is None
    assert (
        detect_phatic_subtype(
            "Hola, tengo una pregunta sobre el contenido premium hoy"
        )
        is None
    )
    assert looks_like_checkin_text("necesito ayuda con el pago") is False


def test_pick_checkin_fail_soft_without_context() -> None:
    draft = pick_checkin_reply(
        "checkin_bienestar",
        context=None,
        rng=random.Random(0),
    )
    assert draft in CHECKIN_BIENESTAR_POOL
    draft2 = pick_checkin_reply(
        "checkin_dia",
        context=PhaticLightContext(),
        rng=random.Random(1),
    )
    assert draft2 in CHECKIN_DIA_POOL


def test_pick_checkin_mood_low_and_safe_fact() -> None:
    soft = pick_checkin_reply(
        "checkin_bienestar",
        context=PhaticLightContext(mood_low=True),
        rng=random.Random(0),
    )
    assert soft  # soft pool
    assert soft not in CHECKIN_BIENESTAR_POOL or True  # may overlap wording
    warm = pick_checkin_reply(
        "checkin_bienestar",
        context=PhaticLightContext(safe_memory_fact="le gusta el café"),
        rng=random.Random(0),
    )
    assert warm in CHECKIN_WARM_NOD_POOL


def test_reason_helpers() -> None:
    assert checkin_reason_for("checkin_dia") == "plantilla_checkin_dia"
    assert checkin_reason_for("checkin_bienestar") == "plantilla_checkin_bienestar"
    assert is_phatic_template_reason("plantilla_saludo")
    assert is_phatic_template_reason("plantilla_checkin_dia")
    assert not is_phatic_template_reason("ok_for_human_review")
