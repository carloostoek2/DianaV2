"""Pure split helpers: length windows and conversational paragraphs."""

from __future__ import annotations

from diana.behavior.split import split_paragraphs, split_text


THREE_PARAS = (
    "Oye, estuve pensando en lo que me contaste ayer en la noche.\n\n"
    "La verdad tiene mucho sentido, no lo había visto de esa forma.\n\n"
    "Cuando puedas cuéntame cómo te fue hoy, me da curiosidad."
)


def test_split_paragraphs_blank_lines_three_bubbles() -> None:
    parts = split_paragraphs(THREE_PARAS)
    assert parts == [
        "Oye, estuve pensando en lo que me contaste ayer en la noche.",
        "La verdad tiene mucho sentido, no lo había visto de esa forma.",
        "Cuando puedas cuéntame cómo te fue hoy, me da curiosidad.",
    ]


def test_split_paragraphs_single_block_unchanged() -> None:
    text = "Solo un párrafo sin saltos de línea en el medio."
    assert split_paragraphs(text) == [text]


def test_split_paragraphs_short_single_newlines_stay_one() -> None:
    text = "Hola\nqué onda\ntodo bien"
    assert split_paragraphs(text) == [text]


def test_split_paragraphs_long_single_newlines_split() -> None:
    a = "Estuve pensando bastante en lo que me dijiste ayer por la noche."
    b = "La verdad tiene mucho sentido y no lo había visto de esa forma."
    c = "Cuando puedas cuéntame cómo te fue hoy porque me da curiosidad."
    assert len(a) >= 40 and len(b) >= 40 and len(c) >= 40
    parts = split_paragraphs(f"{a}\n{b}\n{c}")
    assert parts == [a, b, c]


def test_split_paragraphs_empty() -> None:
    assert split_paragraphs("") == []
    assert split_paragraphs("   \n\n  ") == []


def test_split_text_still_cuts_overlong_window() -> None:
    text = "Hello world. This is fine, really."
    parts = split_text(text, max_chars=20)
    assert len(parts) >= 2
    assert all(len(p) <= 20 for p in parts)
