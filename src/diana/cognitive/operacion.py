"""Persona "operación" — internal business-dynamics facts with alias triggers.

Payload contract (OPTIONAL top-level key of the persona catalog, per channel)::

    "operacion": [{"id": str, "hecho": str, "alias": [str, ...],
                   "nota_privada"?: str}]

Missing key ≡ empty list, so legacy payloads/versions keep validating.

Two validation layers on purpose:

* :func:`validate_operacion_structure` — shape only (types, ids, non-empty).
  Called from ``validate_persona_catalog`` on BOTH write and read paths.
* :func:`validate_operacion_semantics` — alias policy (min length, common-word
  blocklist, collision with ``persona_facts`` temas). Called on the WRITE path
  only (owner panel + ``PersonaAdminService.save_persona``), and only for the
  aliases that are new in that save (``previous=``): an alias already stored
  never blocks a save. Keeping it off the read path means a future blocklist
  change can never invalidate an already-active catalog (which would make the
  provider drop the WHOLE catalog). At runtime :func:`match_operacion` skips
  aliases that fail the policy instead (defense-in-depth) and
  :func:`alias_issues` lists them so the owner panel can warn.

Matching is deterministic: whole-word n-gram over :func:`tokenize_words`
(punctuation/accents/case stripped) of the alias CORE (:func:`alias_core`:
leading/trailing function words are optional, "El Diván" fires on "diván").
No LLM involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from diana.cognitive.tags import catalog_fact_topics, tokenize_words

OPERACION_KEY = "operacion"
OPERACION_ID_MAX_BYTES = 24
OPERACION_ALIAS_MIN_CHARS = 4
# A single capitalized word of exactly 3 letters is a proper name ("Ana",
# "Max") and is allowed; 1-2 letters never are.
OPERACION_ALIAS_PROPER_MIN_CHARS = 3
DEFAULT_MAX_OPERACION_FACTS = 2

# Common words that must never be an alias on their own: they appear in
# ordinary chat and would inject internal context on almost every turn.
OPERACION_ALIAS_BLOCKLIST: frozenset[str] = frozenset(
    {
        # generic channel / platform words
        "canal", "canales", "grupo", "grupos", "chat", "chats", "bot", "bots",
        "admin", "admins", "administrador", "administradora", "vip", "vips",
        "telegram", "whatsapp", "mensaje", "mensajes", "link", "links",
        "enlace", "enlaces", "cuenta", "perfil", "sistema", "soporte",
        "ayuda", "servicio", "info", "informacion", "contenido", "foto",
        "fotos", "video", "videos", "pago", "pagos", "precio", "precios",
        "suscripcion", "membresia", "privado", "publico", "diana",
        # greetings / chat fillers
        "hola", "holi", "holis", "buenas", "buenos", "dias", "tardes",
        "noches", "gracias", "porfa", "favor", "amor", "bebe", "cielo",
        "nena", "guapa", "linda", "bonita", "jaja", "jajaja", "jeje",
        "okey", "vale", "bueno", "claro", "tambien", "nada", "todo",
        "algo", "aqui", "alla", "ahora", "hoy", "manana", "ayer",
        "como", "cuando", "donde", "quien", "porque", "pero", "esto",
        "esta", "este", "eres", "estas", "tienes", "quiero", "puedo",
    }
)
# Ordinary 3-letter words that are also plausible names. Matching is
# case-insensitive (clients type in lowercase), so a capitalized alias "Sol",
# "Mar" or "Leo" would fire on "hace sol", "el mar", "leo un libro": rejected
# even with a capital initial.
OPERACION_ALIAS_SHORT_BLOCKLIST: frozenset[str] = frozenset(
    {
        "sol", "mar", "luz", "paz", "leo", "oro", "rey", "fin", "ver", "dar",
        "ser", "voy", "vas", "van", "muy", "mas", "hay", "uno", "dos", "fue",
        "era", "vez", "mes", "dia", "ola", "asi", "ahi", "aun", "tal", "tan",
        "eso", "esa", "ese", "mal", "pan", "sal", "rio", "red", "web", "app",
        "sms", "ojo", "pie", "ley", "gol",
    }
)
# Function words: ignored when deciding whether an alias is "one common word"
# ("el bot", "mi canal" are rejected like "bot" / "canal").
_STOPWORDS: frozenset[str] = frozenset(
    {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
        "al", "a", "en", "y", "o", "u", "que", "mi", "mis", "tu", "tus",
        "su", "sus", "es", "son", "por", "para", "con", "sin", "lo", "le",
        "se", "me", "te", "nos", "ya", "si", "no",
    }
)


@dataclass(frozen=True)
class OperacionHit:
    """One deterministic match: which item, through which alias."""

    id: str
    alias: str
    hecho: str


@dataclass(frozen=True)
class AliasIssue:
    """A stored alias the runtime ignores because it fails the alias policy."""

    id: str
    alias: str
    reason: str


def alias_tokens(alias: Any) -> tuple[str, ...]:
    return tuple(tokenize_words(alias))


def alias_core(alias: Any) -> tuple[str, ...]:
    """Alias tokens without LEADING/TRAILING function words (``_STOPWORDS``).

    ``"El Diván"`` → ``("divan",)``; ``"el canal de ventas"`` →
    ``("canal", "de", "ventas")`` (inner function words are kept). An alias
    made only of function words → ``()``. Pure; the stored alias is never
    rewritten (its capitalization matters for proper names).
    """
    tokens = list(alias_tokens(alias))
    while tokens and tokens[0] in _STOPWORDS:
        tokens.pop(0)
    while tokens and tokens[-1] in _STOPWORDS:
        tokens.pop()
    return tuple(tokens)


def fact_temas(catalog: dict[str, Any] | None) -> set[str]:
    """Normalized persona_facts temas (collision universe for aliases).

    Same normalization as the Analyst vocabulary (item 1): uncapped
    :func:`catalog_fact_topics`.
    """
    return set(catalog_fact_topics(catalog, limit=None))


def _starts_capitalized(alias: Any, token: str) -> bool:
    """True when the word of ``alias`` that tokenizes to ``token`` starts uppercase."""
    for word in str(alias).split():
        if tokenize_words(word) == [token]:
            letters = [ch for ch in word if ch.isalpha()]
            return bool(letters) and letters[0].isupper()
    return False


def alias_problem(alias: Any, temas: set[str]) -> str | None:
    """Return a Spanish reason when ``alias`` violates the alias policy, else None.

    Evaluated on :func:`alias_core` (what the matcher actually looks for):
    length (4+ letters, or a capitalized 3-letter proper name), common words
    and collision with a Datos personales tema.
    """
    if not alias_tokens(alias):
        return "el alias está vacío o solo tiene puntuación"
    core = alias_core(alias)
    # Only function words ("el", "de la") → as common as it gets.
    if not core:
        return f"el alias «{alias}» es una palabra demasiado común"
    single = core[0] if len(core) == 1 else None
    chars = sum(len(t) for t in core)
    proper_name = (
        single is not None
        and chars == OPERACION_ALIAS_PROPER_MIN_CHARS
        and _starts_capitalized(alias, single)
    )
    if chars < OPERACION_ALIAS_MIN_CHARS and not proper_name:
        return (
            f"el alias «{alias}» es muy corto (mínimo {OPERACION_ALIAS_MIN_CHARS} "
            f"letras, o {OPERACION_ALIAS_PROPER_MIN_CHARS} si es un nombre propio "
            "con mayúscula, como «Ana»)"
        )
    content = [t for t in core if t not in _STOPWORDS]
    # Single common word (with or without articles: "bot", "el bot") → reject.
    # Multi-word phrases of common words ("canal vip") are specific enough as
    # a whole-word n-gram and are allowed.
    if (len(content) == 1 and content[0] in OPERACION_ALIAS_BLOCKLIST) or (
        single is not None and single in OPERACION_ALIAS_SHORT_BLOCKLIST
    ):
        return f"el alias «{alias}» es una palabra demasiado común"
    if "_".join(core) in temas:
        return f"el alias «{alias}» choca con un tema de Datos personales"
    return None


def alias_issues(catalog: dict[str, Any] | None) -> list[AliasIssue]:
    """Stored aliases that :func:`match_operacion` ignores, with the reason.

    Pure and read-only: never raises, tolerates malformed shapes. The caller
    passes the catalog of ONE channel (isolation is the caller's job, like the
    retriever). Used by the owner panel to warn (it never blocks anything).
    """
    if not isinstance(catalog, dict):
        return []
    items = catalog.get(OPERACION_KEY)
    if not isinstance(items, list):
        return []
    temas = fact_temas(catalog)
    out: list[AliasIssue] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("alias"), list):
            continue
        for alias in item["alias"]:
            problem = alias_problem(alias, temas)
            if problem is not None:
                out.append(AliasIssue(str(item.get("id")), str(alias), problem))
    return out


def _stored_aliases(catalog: dict[str, Any] | None) -> dict[str, frozenset[str]]:
    """``{item id: aliases exactly as stored}`` of a previous catalog version."""
    if not isinstance(catalog, dict):
        return {}
    items = catalog.get(OPERACION_KEY)
    if not isinstance(items, list):
        return {}
    out: dict[str, frozenset[str]] = {}
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("alias"), list):
            out[str(item.get("id"))] = frozenset(
                a for a in item["alias"] if isinstance(a, str)
            )
    return out


def validate_operacion_structure(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Shape validation for the optional ``operacion`` key (read + write paths).

    Missing key → ``[]`` (the payload is NOT mutated). Raises ``ValueError``.
    """
    items = data.get(OPERACION_KEY)
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError("operacion must be a list")  # noqa: TRY004 — catalog contract is ValueError
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each operacion item must be an object")  # noqa: TRY004
        for req in ("id", "hecho", "alias"):
            if req not in item:
                raise ValueError(f"operacion item missing {req}")
        item_id = item["id"]
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError("operacion.id must be a non-empty string")
        if len(item_id.encode("utf-8")) > OPERACION_ID_MAX_BYTES:
            raise ValueError("operacion.id exceeds 24 bytes")
        if item_id in seen:
            raise ValueError(f"operacion has duplicate id: {item_id!r}")
        seen.add(item_id)
        if not isinstance(item["hecho"], str) or not item["hecho"].strip():
            raise ValueError("operacion.hecho must be a non-empty string")
        alias = item["alias"]
        if not isinstance(alias, list) or not alias:
            raise ValueError("operacion.alias must be a non-empty list")
        if not all(isinstance(a, str) and a.strip() for a in alias):
            raise ValueError("operacion.alias entries must be non-empty strings")
    return items


def validate_operacion_semantics(
    data: dict[str, Any], *, previous: dict[str, Any] | None = None
) -> None:
    """Alias policy for the WRITE path. Raises ``ValueError`` (Spanish reason).

    ``previous`` is the catalog this save replaces (active version of the SAME
    channel). When given, only aliases that are new in this save are checked
    (new item, or an alias added/changed in an edited item): an alias already
    stored under the same item id is kept as-is even if the policy got
    stricter. The runtime ignores it and the panel warns (:func:`alias_issues`),
    so a legacy alias never blocks saving another section. ``None`` → every
    alias is checked.
    """
    items = validate_operacion_structure(data)
    if not items:
        return
    temas = fact_temas(data)
    stored = _stored_aliases(previous)
    for item in items:
        known = stored.get(item["id"], frozenset())
        for alias in item["alias"]:
            if alias in known:
                continue
            problem = alias_problem(alias, temas)
            if problem is not None:
                raise ValueError(f"operación «{item['id']}»: {problem}")


def match_operacion(
    catalog: dict[str, Any] | None,
    text: str,
    *,
    limit: int = DEFAULT_MAX_OPERACION_FACTS,
) -> list[OperacionHit]:
    """Deterministic whole-word n-gram alias match over ``text``.

    Each alias matches through its :func:`alias_core`. Items are ranked by
    their most specific matching alias: more core letters first, then more
    core words, then catalog order; capped at ``limit``. Aliases that violate
    the alias policy are skipped (never trusted from storage blindly).
    """
    if not isinstance(catalog, dict) or limit < 1:
        return []
    items = catalog.get(OPERACION_KEY)
    if not isinstance(items, list) or not items:
        return []
    tokens = tokenize_words(text)
    if not tokens:
        return []
    temas = fact_temas(catalog)
    ranked: list[tuple[int, int, int, OperacionHit]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        hecho = str(item.get("hecho") or "").strip()
        aliases = item.get("alias")
        if not hecho or not isinstance(aliases, list):
            continue
        best: tuple[int, int, str] | None = None
        for alias in aliases:
            if alias_problem(alias, temas) is not None:
                continue
            core = alias_core(alias)
            if not _contains_ngram(tokens, core):
                continue
            score = (sum(len(t) for t in core), len(core))
            if best is None or score > best[:2]:
                best = (score[0], score[1], str(alias))
        if best is not None:
            hit = OperacionHit(str(item.get("id")), best[2], hecho)
            ranked.append((-best[0], -best[1], idx, hit))
    ranked.sort(key=lambda r: (r[0], r[1], r[2]))
    return [r[3] for r in ranked[:limit]]


def _contains_ngram(tokens: list[str], gram: tuple[str, ...]) -> bool:
    n = len(gram)
    if n == 0 or n > len(tokens):
        return False
    return any(tuple(tokens[i : i + n]) == gram for i in range(len(tokens) - n + 1))


__all__ = [
    "DEFAULT_MAX_OPERACION_FACTS",
    "OPERACION_ALIAS_BLOCKLIST",
    "OPERACION_ALIAS_MIN_CHARS",
    "OPERACION_ALIAS_PROPER_MIN_CHARS",
    "OPERACION_ALIAS_SHORT_BLOCKLIST",
    "OPERACION_ID_MAX_BYTES",
    "OPERACION_KEY",
    "AliasIssue",
    "OperacionHit",
    "alias_core",
    "alias_issues",
    "alias_problem",
    "fact_temas",
    "match_operacion",
    "validate_operacion_semantics",
    "validate_operacion_structure",
]
