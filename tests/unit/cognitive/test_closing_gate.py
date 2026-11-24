"""ClosingGate: el candado que decide si un turno se contesta o se cierra solo.

Contrato (AGENTS §4.26): solo cierra cuando el texto COMPLETO es exactamente una
despedida o un acuse de la lista; cualquier duda vuelve al flujo normal. Estas
pruebas fijan los casos que el producto exige: "gracias, y otra cosa" sigue el
flujo normal, un "ok" que contesta una pregunta no es cierre, y una foto sin
revisar nunca cierra.
"""

from __future__ import annotations

import pytest

from diana.cognitive.closing_gate import (
    ACK_PHRASES,
    FAREWELL_PHRASES,
    ClosingVerdict,
    closing_verdict,
    normalize,
)


def _close(text: str, **kwargs) -> ClosingVerdict:
    return closing_verdict(text, **kwargs)


# ---------------------------------------------------------------------------
# Despedidas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["adiós", "Adiós!", "bye", "Bye!!", "chao", "hasta luego", "hasta mañana", "nos vemos", "cuídate", "CUÍDATE"],
)
def test_exact_farewell_closes_the_turn(text: str) -> None:
    verdict = _close(text)
    assert verdict.is_closing is True
    assert verdict.kind == "farewell"


def test_farewell_wins_over_an_open_question() -> None:
    """Si el VIP se despide, una pregunta nuestra no lo obliga a escribir.

    La puerta del mensaje saliente con ``?`` es del ACUSE, no de la despedida.
    """
    verdict = _close("bye", last_outbound_text="¿Te mando el video?")
    assert verdict.is_closing is True


@pytest.mark.parametrize("text", ["ok?", "¿ok?", "bye?", "¿bye?", "va?", "¿va?"])
def test_a_question_never_closes(text: str) -> None:
    """Una pregunta no se cierra, ni siquiera cuando el texto es una despedida.

    ``normalize`` borra ``?``/``¿`` de los bordes del token: sin la puerta
    sobre el texto crudo, "ok?" quedaría como un acuse exacto y Diana callaría
    justo en el caso en el que el VIP está preguntando algo.
    """
    verdict = _close(text)
    assert verdict.is_closing is False
    assert verdict.reason == "question"


def test_farewell_with_promise_keeps_normal_flow() -> None:
    """"Hasta mañana" cierra; prometer algo no."""
    assert _close("hasta mañana").is_closing is True
    assert _close("mañana te transfiero").is_closing is False


@pytest.mark.parametrize(
    "text",
    [
        "buenas noches",
        "Pasa buena noche",
        "PASA BUENA NOCHE!!",
        "pasa linda noche",
        "descansa",
        "que descanses bien",
        "dulces sueños",
    ],
)
def test_night_farewells_close_the_turn(text: str) -> None:
    """Despedidas nocturnas (2026-11-01).

    Caso real: el VIP escribió "Pasa buena noche", el candado no la reconocía,
    "pasa" leía como verbo de pedido y Diana contestó una despedida.
    """
    verdict = _close(text)
    assert verdict.is_closing is True
    assert verdict.kind == "farewell"


def test_night_farewell_mixed_with_other_business_stays_normal() -> None:
    """"Pasa buena noche, mañana hablamos" no es solo una despedida."""
    assert _close("Pasa buena noche, mañana hablamos").is_closing is False


# ---------------------------------------------------------------------------
# Acuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["ok", "OK!", "oki", "okay", "va", "vale", "dale", "de una", "listo", "perfecto", "gracias", "mil gracias", "muchas gracias", "graciasss", "jajaja", "jeje", "👍", "❤️", "🙏"],
)
def test_exact_ack_closes_the_turn(text: str) -> None:
    verdict = _close(text)
    assert verdict.is_closing is True
    assert verdict.kind == "ack"


def test_ack_that_answers_a_question_is_not_a_closing() -> None:
    """Un "ok" que contesta no es un cierre: la pregunta queda abierta."""
    verdict = _close("ok", last_outbound_text="¿Te mando el video?")
    assert verdict.is_closing is False
    assert verdict.reason == "open_question"


def test_open_question_check_reads_the_last_line_only() -> None:
    verdict = _close("ok", last_outbound_text="Hola amor\n¿te mando el video?")
    assert verdict.is_closing is False


@pytest.mark.parametrize(
    "text",
    [
        "gracias, y otra cosa…",
        "gracias, ¿me pasas el video?",
        "ok, pero mañana hablamos del pago",
        # "buenas noches" salió de esta lista el 2026-11-01: es despedida
        # nocturna (ver test_night_farewells_close_the_turn). Un saludo de
        # llegada sigue el flujo normal.
        "buenas tardes",
        "hola",
        "sí",
        "si",
        "no",
        "🥰",
    ],
)
def test_everything_else_keeps_the_normal_flow(text: str) -> None:
    assert _close(text).is_closing is False


# ---------------------------------------------------------------------------
# Puertas de seguridad
# ---------------------------------------------------------------------------


def test_unreviewed_media_never_closes() -> None:
    verdict = _close("gracias", media_unverified=True)
    assert verdict.is_closing is False
    assert verdict.reason == "media_unverified"


@pytest.mark.parametrize("emotion", ["molesta", "triste", "ansiosa", "urgente"])
def test_negative_emotion_never_closes(emotion: str) -> None:
    verdict = _close("bye", emotion=emotion)
    assert verdict.is_closing is False
    assert verdict.reason == "emotion"


@pytest.mark.parametrize("risk", ["medio", "alto"])
def test_non_low_risk_never_closes(risk: str) -> None:
    verdict = _close("bye", risk=risk)
    assert verdict.is_closing is False
    assert verdict.reason == "risk"


def test_request_intent_never_closes() -> None:
    verdict = _close("gracias", intent="solicitar_contenido")
    assert verdict.is_closing is False
    assert verdict.reason == "intent"


def test_long_text_never_closes() -> None:
    verdict = _close("ok muchas gracias por todo lo que hiciste hoy hermosa")
    assert verdict.is_closing is False
    assert verdict.reason == "too_long"


def test_word_ceiling_is_configurable() -> None:
    text = "nos vemos"
    assert _close(text, max_words=1).is_closing is False
    assert _close(text, max_words=8).is_closing is True


def test_empty_text_never_closes() -> None:
    assert _close("").is_closing is False
    assert _close("   ").is_closing is False


# ---------------------------------------------------------------------------
# Ráfaga y trazas
# ---------------------------------------------------------------------------


def test_burst_closes_when_every_message_is_a_closing() -> None:
    """Una ráfaga de cierres es un cierre: los dos mensajes se miran por separado.

    Hasta 2026-11-10 se comparaba el bloque entero contra la lista, así que una
    ráfaga no podía cerrar nunca (más de la mitad de los turnos).
    """
    assert _close("ok\nbye").is_closing is True


@pytest.mark.parametrize(
    "burst",
    [
        "Me quedé esperando el video\nDescansa",
        "(el VIP envió 2 mensajes seguidos)\n[1/2] Me quedé esperando el video\n[2/2] Descansa",
        "(el VIP envió 2 mensajes seguidos)\n[1/2] gracias\n[2/2] y otra cosa, mándame el enlace",
    ],
)
def test_burst_with_any_open_message_keeps_the_normal_flow(burst: str) -> None:
    """Si UN mensaje de la ráfaga pide algo, el turno se contesta.

    El contrato de producto no cambió: "gracias, y otra cosa…" sigue yendo al
    flujo normal, aunque llegue partido en dos burbujas.
    """
    assert _close(burst).is_closing is False


def test_nested_burst_headers_are_flattened() -> None:
    """Una fila guardada puede traer ráfagas anidadas: se aplanan todas."""
    nested = (
        "(el VIP envió 2 mensajes seguidos)\n"
        "[1/2] (el VIP envió 2 mensajes seguidos)\n"
        "[1/2] ok\n[2/2] gracias\n"
        "[2/2] listo"
    )
    assert _close(nested).is_closing is True


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("te paso el pago mañana", "money"),
        ("pásame el enlace", "request"),
        ("mañana te escribo", "promise"),
        ("qué dices", "question"),
        ("hasta lueguito", "no_exact_match"),
    ],
)
def test_near_misses_report_a_traceable_reason(text: str, reason: str) -> None:
    verdict = _close(text)
    assert verdict.is_closing is False
    assert verdict.reason == reason


def test_lists_are_disjoint() -> None:
    assert FAREWELL_PHRASES.isdisjoint(ACK_PHRASES)


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Bye!! ", "bye"),
        ("ADIÓS", "adios"),
        ("jajajaja", "jaja"),
        ("graciasss", "gracias"),
        ("❤️", "❤"),
        ("de   una", "de una"),
    ],
)
def test_normalize_folds_accents_case_and_punctuation(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_accented_farewell_normalizes_into_the_closed_list() -> None:
    """La forma con acento cae en la lista cerrada (sin escribirla aquí)."""
    assert normalize("¡Cuídate!") in FAREWELL_PHRASES


def test_the_reason_is_the_token_the_decider_emits() -> None:
    """Un solo dueño del token: el que enciende el botón es el que emite el Decisor."""
    from diana.application.draft_variants import CLOSING_REASON as app_token
    from diana.cognitive.closing_gate import CLOSING_REASON

    assert app_token == CLOSING_REASON


def test_the_decider_emits_the_shared_reason() -> None:
    """Si alguien renombra el token en un lado, esta prueba cae (no el botón)."""
    from diana.cognitive.closing_gate import CLOSING_REASON
    from diana.cognitive.models import Comprehension, Decision

    decider = _closing_decider()
    decision = decider.decide(
        _evaluation(),
        Comprehension(
            intent="saludar",
            topics=["x"],
            emotion="neutral",
            urgency="baja",
            risk="bajo",
            needs_memory=False,
            needs_policy=False,
            needs_schedule=False,
            needs_examples=False,
            needs_history=False,
            needs_context=False,
            closing_without_reply=True,
        ),
        mode="supervised",
    )
    assert isinstance(decision, Decision)
    assert decision.action == "silent_close"
    assert decision.reason == CLOSING_REASON


def _closing_decider():
    from diana.cognitive.decider import Decider

    return Decider(feature_silent_close_enabled=True)


def _evaluation():
    from diana.cognitive.models import EvaluationProfile

    return EvaluationProfile(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.95,
        coverage=0.9,
        empathy=0.9,
    )


# ---------------------------------------------------------------------------
# Vocativos y saludos (2026-11-10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Pasa buena noche hermosa",
        "Pasa buen día",
        "Pasa buen dia Dianita hermosa",
        "Que tengas buen día",
        "Que tengas bonita semana",
        "Hola amor.. buenas noches",
        "Gracias mi vida",
        "Gracias amor..",
        "Que bueno",
        "Muy bien",
        "De nada",
    ],
)
def test_vocatives_and_greetings_no_longer_block_the_closing(text: str) -> None:
    """Caso real (Hugo, 2026-11-10): el cliente agrega apodos a TODO.

    Sin quitar el vocativo o el saludo inicial, la lista exacta nunca coincidía
    y el bot contestaba cada despedida y cada acuse.
    """
    assert _close(text).is_closing is True


@pytest.mark.parametrize(
    "text",
    [
        "Hola bella",
        "Hola hermosa, ¿cómo estás?",
        "Buen día",
        "Buenas tardes",
    ],
)
def test_a_greeting_is_not_a_closing(text: str) -> None:
    """Un saludo espera su saludo de vuelta: que se quede sin respuesta es peor."""
    assert _close(text).is_closing is False


def test_stripping_never_invents_a_closing_from_content() -> None:
    """Quitar vocativos no convierte una frase cualquiera en despedida."""
    assert _close("no te preocupes linda").is_closing is False
    assert _close("me gustas mucho mi amor").is_closing is False
    assert _close("gracias por escucharme, lo aprecio mucho").is_closing is False


# ---------------------------------------------------------------------------
# Camino del Analyst (`suggested_no_reply`, 2026-11-10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "no te preocupes",
        "si ya mucho mejor gracias",
        "pues por hoy cenaré y descansaré un poco",
    ],
)
def test_analyst_signal_closes_what_no_list_reaches(text: str) -> None:
    verdict = _close(text, model_says_no_reply=True)
    assert verdict.is_closing is True
    assert verdict.kind == "model"


def test_analyst_signal_is_off_by_default() -> None:
    assert _close("no te preocupes").is_closing is False


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"media_unverified": True}, "media_unverified"),
        ({"emotion": "molesta"}, "emotion"),
        ({"risk": "alto"}, "risk"),
        ({"intent": "saludar"}, "greeting"),
        ({"intent": "solicitar_contenido"}, "intent"),
        ({"last_outbound_text": "¿Te mando el video?"}, "open_question"),
    ],
)
def test_analyst_signal_never_skips_a_door(kwargs: dict, reason: str) -> None:
    """La lectura del modelo amplía cobertura, nunca salta una puerta."""
    verdict = _close("no te preocupes", model_says_no_reply=True, **kwargs)
    assert verdict.is_closing is False
    assert verdict.reason == reason


@pytest.mark.parametrize(
    "text",
    [
        "no te preocupes por el pago",
        "ya te hice la transferencia",
        "¿me mandas el video?",
    ],
)
def test_analyst_signal_keeps_money_and_questions_in_the_flow(text: str) -> None:
    verdict = _close(text, model_says_no_reply=True)
    assert verdict.is_closing is False
