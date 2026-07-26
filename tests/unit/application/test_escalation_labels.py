"""Escalation tipo mapping and Spanish owner labels."""

from __future__ import annotations

import pytest

from diana.application.escalation_labels import (
    SYSTEM_ESCALATION_TIPOS,
    label_es_for_tipo,
    tipo_from_reason,
)


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("frustracion_directa", "frustracion_directa"),
        ("pregunta_repetida", "pregunta_repetida"),
        ("pago_precio", "pago_precio"),
        ("compromiso_real", "compromiso_real"),
        ("identidad_ia", "identidad_ia"),
        ("palabra_prohibida", "palabra_prohibida"),
        ("safety_below_threshold", "semantica"),
        ("ok_for_human_review", "semantica"),
        ("", "semantica"),
    ],
)
def test_tipo_from_reason(reason: str, expected: str) -> None:
    assert tipo_from_reason(reason) == expected


def test_system_tipos_complete() -> None:
    assert SYSTEM_ESCALATION_TIPOS == {
        "frustracion_directa",
        "pregunta_repetida",
        "pago_precio",
        "compromiso_real",
        "identidad_ia",
        "palabra_prohibida",
    }


def test_label_es_known_tipos() -> None:
    assert "Frustración" in label_es_for_tipo("frustracion_directa")
    assert "molesta" in label_es_for_tipo("frustracion_directa")
    assert label_es_for_tipo("pregunta_repetida") == "Pregunta repetida"
    assert label_es_for_tipo("unknown_xyz") == "unknown_xyz"
