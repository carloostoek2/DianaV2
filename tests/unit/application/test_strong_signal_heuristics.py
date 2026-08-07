"""Strong-signal heuristics — pure module, own vocabulary DISJOINT from j4_triggers."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from diana.application.strong_signal_heuristics import (
    _STRONG_SIGNAL_TERMS,
    match,
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


@pytest.mark.parametrize(
    "text",
    [
        # Introspección / apertura personal.
        "me siento raro últimamente",
        "no sé qué hacer con mi vida",
        "necesito hablar de algo",
        # Confianza / vínculo.
        "te tengo confianza",
        "quiero confiar en alguien",
        # Proyecto de vida / identidad.
        "estoy pensando en cambiar de vida",
        "mi relación con mi familia",
        "estoy pensando en mi futuro",
        "a veces siento que no puedo",
        # S4: accent-less Mexican chat must match the accented terms.
        "no se que hacer con mi vida",
        "quien soy yo realmente",
        "me siento triste, no se que hacer",
    ],
)
def test_strong_signal_matches(text: str) -> None:
    assert match(text) is True, text


@pytest.mark.parametrize(
    "text",
    [
        "cuánto cuesta",
        "precio",
        "agendar una cita",
        "nos vemos",
        "hola",
        "gracias por la atención",
        "quiero pagar el plan",
        "mi tarjeta",
        "",
        None,
    ],
)
def test_strong_signal_does_not_match(text: str | None) -> None:
    assert match(text) is False, text


def test_payment_terms_never_match_payment_language() -> None:
    """Disjunction guarantee: payment/commitment keywords (j4) are absent."""
    payment_like = [
        "cuánto cuesta el plan",
        "quiero comprar",
        "cómo pago",
        "compromiso con el pago",
    ]
    for text in payment_like:
        assert match(text) is False, text


@pytest.mark.parametrize(
    "text",
    [
        "no se que hacer",  # accent-less "no sé qué hacer"
        "no se que hacer con mi vida",
        "quien soy",  # accent-less "quién soy"
        "no se qué hacer",  # accented original still matches
    ],
)
def test_match_is_accent_insensitive_s4(text: str) -> None:
    """S4: NFKD folding makes accent-less Mexican chat match accented terms."""
    assert match(text) is True, text


def test_terms_are_strings_and_non_empty() -> None:
    assert _STRONG_SIGNAL_TERMS
    assert all(isinstance(t, str) and t.strip() for t in _STRONG_SIGNAL_TERMS)


def test_import_purity_no_llm_no_infra() -> None:
    """The module never imports llm/ or infrastructure/ (import-purity gate)."""
    import diana.application.strong_signal_heuristics as mod

    path = Path(mod.__file__)
    imported = _imported_modules(path)
    assert "aiogram" not in imported
    assert "infrastructure" not in imported
    assert "llm" not in imported
    assert imported <= {"re", "logging", "unicodedata", "__future__"}
