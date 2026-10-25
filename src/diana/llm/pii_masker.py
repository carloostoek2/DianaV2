"""PII masking at the LLM trust boundary (pure functions, no I/O).

Every outbound LLM call crosses a trust boundary: message text leaves the
system and is processed by an external provider. This module replaces
personal identifiers (emails, phone numbers, payment cards, @handles, URLs)
with collision-safe placeholders before the payload is sent, and can restore
the originals on the provider reply when the model echoed a placeholder
verbatim (the reply goes back to the same VIP, so restoring is safe).

Design rules:
- Pure: no network, no Telegram, no persistence, no settings.
- Collision-safe: a placeholder is never a substring of the input text and
  is never reused for two different values.
- Order matters: URLs before emails (a URL may embed an email-like segment),
  phones before cards (a card-shaped digit run must not be half-consumed as
  a phone; cards are Luhn-validated), handles last (emails are already
  replaced, so their "@" never re-matches).
- Names are intentionally NOT masked: personalization depends on them and
  regexes cannot distinguish a first name from ordinary capitalized words.
  The agreement with the provider (docs/ACUERDO-PROVEEDOR-LLM.md) is the
  legal layer that covers the remaining exposure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_URL_RE = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+")
# Separators allowed between digit groups: ASCII space, hyphen, dot, hard
# space (U+00A0), tab and newline. Cards pasted from tables/pages often carry
# a hard space or dots, and a card broken across lines keeps its separator.
# ``\s`` already covers space, hard space, tab and newline; the dot and the
# hyphen are explicit.
_PHONE_SEP = r"[\s.\-]"
# Card lengths accepted (13–19 digits). Text and image/video vision share
# this single detection: one source of truth for what a card looks like.
_CARD_MIN_DIGITS = 13
_CARD_MAX_DIGITS = 19
# Longest card prefix retried inside one contiguous run longer than a card
# (a card glued to its CVV: ``4111111111111111123``).
_CARD_PREFIX_RETRY_MAX = 16
_CARD_SEP = r"[  \t\n.\-]"
# 13–19 digits with optional separators, then Luhn-validated below. The
# separator only sits BETWEEN digits: a trailing separator would make the
# engine backtrack over it, which both slowed long texts and merged two cards
# pasted back to back. This shape is linear for any input length.
_CARD_RE = re.compile(
    r"(?<!\d)\d(?:" + _CARD_SEP + r"?\d)"
    + r"{" + f"{_CARD_MIN_DIGITS - 1},{_CARD_MAX_DIGITS - 1}" + r"}(?!\d)"
)
# Mexico-centric phone shapes; the lookbehinds and trailing guard reject a
# match that starts inside a longer digit run, so a 16-digit card is never
# half-consumed as a phone.
_PHONE_MX_RE = re.compile(
    r"(?<!\d)(?<!\d" + _PHONE_SEP + r")"
    r"(?:\+?52" + _PHONE_SEP + r"?)?"
    r"(?:1" + _PHONE_SEP + r"?)?"
    r"\(?\d{2,4}\)?"
    + _PHONE_SEP + r"?\d{3,4}"
    + _PHONE_SEP + r"?\d{3,4}"
    r"(?!" + _PHONE_SEP + r"?\d)"
)
# International numbers that carry a "+" prefix.
_PHONE_INTL_RE = re.compile(
    r"(?<![\w+])\+\d{1,3}(?:" + _PHONE_SEP + r"?\d{2,4}){2,5}"
    r"(?!" + _PHONE_SEP + r"?\d)"
)
_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_])@[A-Za-z0-9_]{3,32}(?![A-Za-z0-9_])")
# Maximal digit runs inside a card-shaped match (group boundaries).
_DIGIT_RUN_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class MaskResult:
    """Output of :func:`mask_pii`."""

    masked: str
    mapping: dict[str, str] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)


def luhn_valid(digits: str) -> bool:
    """Luhn checksum guard against false positives on long digit runs."""
    if not digits or not digits.isdigit():
        return False
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _split_valid_card(value: str) -> tuple[str, str] | None:
    """Split a card-shaped match into (Luhn-valid card, remainder).

    A real message often carries the card plus its expiry or CVV
    (``4111 1111 1111 1111 12/27``). The regex matches the whole digit run and
    Luhn then fails on the extra groups, so ``re.sub`` would leave the card in
    clear: it cannot retry a shorter run at the same position. This helper
    drops whole groups from the right, at their boundaries, until the kept
    digits pass Luhn. The dropped part (expiry/CVV) stays visible, which is the
    agreed scope for this contract; the card itself is always masked.

    A card glued to a CVV without any separator (``4111111111111111123``) is a
    single group; for those runs the prefix is retried at character boundaries
    (L6). Only runs LONGER than a maximal card are retried, so a plain 16-digit
    order number is still never masked.

    Returns ``None`` when no prefix is a valid card, so a non-card digit run is
    never masked.
    """
    groups = list(_DIGIT_RUN_RE.finditer(value))
    for keep in range(len(groups), 0, -1):
        digits = "".join(group.group(0) for group in groups[:keep])
        if not _CARD_MIN_DIGITS <= len(digits) <= _CARD_MAX_DIGITS:
            continue
        if luhn_valid(digits):
            end = groups[keep - 1].end()
            return value[:end], value[end:]
    return _split_contiguous_card(value, groups)


def _split_contiguous_card(
    value: str, groups: list[re.Match[str]]
) -> tuple[str, str] | None:
    """Retry card prefixes inside one contiguous run longer than a card (L6).

    ``4111 1111 1111 1111 123`` is split by the group pass above; the glued
    form ``4111111111111111123`` has a single group, so the full run fails
    Luhn and the card would travel. Prefixes of 16…13 digits are retried here.
    """
    if len(groups) != 1:
        return None
    run = groups[0].group(0)
    if len(run) <= _CARD_PREFIX_RETRY_MAX:
        return None
    for length in range(_CARD_PREFIX_RETRY_MAX, _CARD_MIN_DIGITS - 1, -1):
        if luhn_valid(run[:length]):
            end = groups[0].start() + length
            return value[:end], value[end:]
    return None


def contains_valid_card(text: str) -> bool:
    """True when ``text`` carries at least one Luhn-valid card number.

    Single detection shared by the text masker and the image/video privacy
    filter: same separators (space, hyphen, dot, NBSP, tab, newline), same
    Luhn-on-prefix rule (13–19 digits), same grouped and glued forms.
    """
    if not text:
        return False
    return any(
        _split_valid_card(match.group(0)) is not None
        for match in _CARD_RE.finditer(text)
    )


def _fresh_token(
    label: str, text: str, used: set[str], next_index: dict[str, int]
) -> str:
    """Placeholder that is neither present in ``text`` nor already used.

    ``next_index`` remembers where the last placeholder for this label stopped,
    so the search is O(1) in the number of matches instead of rescanning
    ``[label]``, ``[label-1]`` … from zero on every card (that quadratic loop
    was what made a 25 KB card-spam text take seconds).
    """
    index = next_index.get(label, 0)
    while True:
        token = f"[{label}]" if index == 0 else f"[{label}-{index}]"
        index += 1
        if token not in used and token not in text:
            next_index[label] = index
            return token


def mask_pii(text: str) -> MaskResult:
    """Replace personal identifiers with placeholders.

    Returns the masked text plus a mapping placeholder → original value and
    per-entity counters. A text without matches is returned untouched with an
    empty mapping.
    """
    if not text:
        return MaskResult(masked=text)

    masked = text
    mapping: dict[str, str] = {}
    used: set[str] = set()
    stats: dict[str, int] = {}
    next_index: dict[str, int] = {}

    def _replace(pattern: re.Pattern[str], label: str) -> None:
        nonlocal masked
        count = 0

        def _sub(match: re.Match[str]) -> str:
            nonlocal count
            value = match.group(0)
            remainder = ""
            if label == "tarjeta":
                split = _split_valid_card(value)
                if split is None:
                    # Luhn-invalid: never mask a run that is not a card.
                    return value
                value, remainder = split
            token = _fresh_token(label, masked, used, next_index)
            used.add(token)
            mapping[token] = value
            count += 1
            return token + remainder

        masked = pattern.sub(_sub, masked)
        if count:
            stats[label] = count

    _replace(_URL_RE, "enlace")
    _replace(_EMAIL_RE, "correo")
    _replace(_PHONE_INTL_RE, "telefono")
    _replace(_PHONE_MX_RE, "telefono")
    _replace(_CARD_RE, "tarjeta")
    _replace(_HANDLE_RE, "usuario")
    return MaskResult(masked=masked, mapping=mapping, stats=stats)


def unmask_pii(text: str, mapping: dict[str, str]) -> str:
    """Restore placeholders introduced by :func:`mask_pii`.

    Only tokens present in ``mapping`` are replaced, so this can never inject
    data that was not masked in the first place. Longest tokens first so a
    generic placeholder never partially replaces a numbered one.
    """
    if not text or not mapping:
        return text
    for token in sorted(mapping, key=len, reverse=True):
        text = text.replace(token, mapping[token])
    return text
