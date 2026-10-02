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
  only (owner panel + ``PersonaAdminService.save_persona``). Keeping it off
  the read path means a future blocklist change can never invalidate an
  already-active catalog (which would make the provider drop the WHOLE
  catalog). At runtime :func:`match_operacion` skips aliases that fail the
  policy instead (defense-in-depth).

Matching is deterministic: whole-word n-gram over :func:`tokenize_words`
(punctuation/accents/case stripped). No LLM involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from diana.cognitive.tags import normalize_tag, tokenize_words

OPERACION_KEY = "operacion"
OPERACION_ID_MAX_BYTES = 24
OPERACION_ALIAS_MIN_CHARS = 4
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


def alias_tokens(alias: Any) -> tuple[str, ...]:
    return tuple(tokenize_words(alias))


def fact_temas(catalog: dict[str, Any]) -> set[str]:
    """Normalized persona_facts temas (collision universe for aliases)."""
    out: set[str] = set()
    for fact in catalog.get("persona_facts") or []:
        if not isinstance(fact, dict):
            continue
        tema = fact.get("tema")
        for t in tema if isinstance(tema, list) else [tema]:
            n = normalize_tag(t)
            if n:
                out.add(n)
    return out


def alias_problem(alias: Any, temas: set[str]) -> str | None:
    """Return a Spanish reason when ``alias`` violates the alias policy, else None."""
    tokens = alias_tokens(alias)
    if not tokens:
        return "el alias está vacío o solo tiene puntuación"
    joined = " ".join(tokens)
    if len(joined.replace(" ", "")) < OPERACION_ALIAS_MIN_CHARS:
        return f"el alias «{alias}» es muy corto (mínimo {OPERACION_ALIAS_MIN_CHARS} caracteres)"
    content = [t for t in tokens if t not in _STOPWORDS]
    # Single common word (optionally with articles: "bot", "el bot") → reject.
    # Multi-word phrases of common words ("canal vip") are specific enough as
    # a whole-word n-gram and are allowed.
    if not content or (len(content) == 1 and content[0] in OPERACION_ALIAS_BLOCKLIST):
        return f"el alias «{alias}» es una palabra demasiado común"
    if "_".join(tokens) in temas or (len(tokens) == 1 and tokens[0] in temas):
        return f"el alias «{alias}» choca con un tema de Datos personales"
    return None


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


def validate_operacion_semantics(data: dict[str, Any]) -> None:
    """Alias policy for the WRITE path. Raises ``ValueError`` (Spanish reason)."""
    items = validate_operacion_structure(data)
    if not items:
        return
    temas = fact_temas(data)
    for item in items:
        for alias in item["alias"]:
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

    Items are ranked by the longest matching alias (more specific first),
    ties in catalog order; capped at ``limit``. Aliases that violate the
    alias policy are skipped (never trusted from storage blindly).
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
    ranked: list[tuple[int, int, OperacionHit]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        hecho = str(item.get("hecho") or "").strip()
        aliases = item.get("alias")
        if not hecho or not isinstance(aliases, list):
            continue
        best: tuple[int, str] | None = None
        for alias in aliases:
            if alias_problem(alias, temas) is not None:
                continue
            gram = alias_tokens(alias)
            if _contains_ngram(tokens, gram) and (best is None or len(gram) > best[0]):
                best = (len(gram), str(alias))
        if best is not None:
            ranked.append((-best[0], idx, OperacionHit(str(item.get("id")), best[1], hecho)))
    ranked.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in ranked[:limit]]


def _contains_ngram(tokens: list[str], gram: tuple[str, ...]) -> bool:
    n = len(gram)
    if n == 0 or n > len(tokens):
        return False
    return any(tuple(tokens[i : i + n]) == gram for i in range(len(tokens) - n + 1))


__all__ = [
    "DEFAULT_MAX_OPERACION_FACTS",
    "OPERACION_ALIAS_BLOCKLIST",
    "OPERACION_ALIAS_MIN_CHARS",
    "OPERACION_ID_MAX_BYTES",
    "OPERACION_KEY",
    "OperacionHit",
    "alias_problem",
    "fact_temas",
    "match_operacion",
    "validate_operacion_semantics",
    "validate_operacion_structure",
]
