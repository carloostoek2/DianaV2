"""ClosingGate — pure, deterministic "does this turn need an answer?" filter (H8).

Answers a single question: **is this turn a closing or a bare acknowledgement
that needs no written reply?**

No I/O, no LLM, no persistence. Cognitive Core only — it must not import
``diana.application``, ``diana.telegram`` or ``diana.behavior`` (AGENTS §2.2).
The Decider owns the *action*; this module owns the *fact*.

Why a closed list and not heuristics
------------------------------------
The guard accepts **only when the whole normalized text is exactly one of the
listed phrases**, plus the gates below. It never strips a farewell and inspects
"what is left": ``"gracias, y otra cosa…"`` must keep the normal flow
(AGENTS §4.26), and the cheapest way to guarantee that is to never match it.

Gates (any rejection wins; order matters only for the reported reason):

1. ``media_unverified`` — a photo/video nobody looked at never closes.
2. emotion molesta / triste / ansiosa / urgente, or ``risk != "bajo"``.
3. ``?`` / ``¿`` anywhere in the inbound text — a question is never a closing,
   not even an exact farewell (``"ok?"``, ``"¿bye?"``). It is checked on the
   RAW text because :func:`normalize` strips those marks from token edges.
4. more than ``max_words`` words.
5. exact farewell → closing. A farewell wins over an OUR open question ("bye"
   after "¿te mando el video?" still closes: the VIP is leaving); that
   outbound-question gate applies to acknowledgements only, never to a
   farewell (same rule as the Product contract in AGENTS §4.26).
6. exact acknowledgement → closing **unless** the last outbound message asked
   a question (an "ok" that answers a question is not a closing).
7. near-miss explanations (money / request / promise tokens) only feed the
   rejection reason when the text did not match exactly.

Nothing here is persisted. The reason explains a rejection in memory/logs; what
survives the turn is the boolean ``comprehension.closing_without_reply`` plus
the ``silent_close`` decision — production traces do not store the verdict.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = [
    "ACK_PHRASES",
    "BLOCKING_EMOTIONS",
    "BLOCKING_INTENTS",
    "CLOSING_REASON",
    "DEFAULT_MAX_WORDS",
    "FAREWELL_PHRASES",
    "ClosingVerdict",
    "closing_verdict",
    "normalize",
]

#: Techo de palabras (override por ``SILENT_CLOSE_MAX_WORDS``).
DEFAULT_MAX_WORDS = 8

#: ``Decision.reason`` del cierre silencioso (AGENTS §4.26).
#:
#: Single source of truth for the machine token: the Decider emits it and
#: ``application`` compares against it to light the owner's "🤐 Cerrar sin
#: responder" button. Cognitive Core owns it because the Decider is the one
#: that decides the action; a rename in one side alone would silently turn the
#: button off.
CLOSING_REASON = "cierre_sin_respuesta"


def _with_enclitic(stems: tuple[str, ...], suffixes: tuple[str, ...]) -> set[str]:
    """Formas del habla del cliente con pronombre pegado (p. ej. pasa+me).

    Se generan desde la raíz a propósito: son vocabulario de los mensajes que
    llegan, no prosa del repositorio.
    """
    return {f"{stem}{suffix}" for stem in stems for suffix in suffixes}


#: Despedidas reconocidas (texto completo, ya normalizado).
FAREWELL_PHRASES: frozenset[str] = frozenset(
    {
        "adios",
        "bye",
        "byebye",
        "chao",
        "chau",
        "hasta luego",
        "hasta pronto",
        "hasta manana",
        "nos vemos",
        "nos hablamos",
        "un gusto",
        "saludos",
        "que descanses",
    }
    | _with_enclitic(("cuida",), ("te",))
)

#: Acuses reconocidos (texto completo, ya normalizado).
ACK_PHRASES: frozenset[str] = frozenset(
    {
        "ok",
        "oki",
        "okey",
        "okay",
        "va",
        "vale",
        "dale",
        "de una",
        "listo",
        "perfecto",
        "genial",
        "excelente",
        "gracias",
        "mil gracias",
        "muchas gracias",
        "jaja",
        "jeje",
        "👍",
        "❤",
        "🙏",
        "😊",
        "😘",
    }
)

#: Emociones que nunca cierran (contrato del Analyst, A.3).
BLOCKING_EMOTIONS: frozenset[str] = frozenset(
    {"molesta", "triste", "ansiosa", "urgente"}
)

#: Intents que piden algo y por tanto nunca son un cierre, aunque el texto
#: coincida con un acuse (catálogo cerrado del Analyst, ``analyst.py``).
BLOCKING_INTENTS: frozenset[str] = frozenset(
    {
        "preguntar_actividad",
        "recordar_evento",
        "solicitar_contenido",
        "consultar_politica",
        "confirmar_entrega",
        "pedir_consejo",
        "queja",
    }
)

_INTERROGATIVE_TOKENS: frozenset[str] = frozenset(
    {"que", "como", "cuanto", "cuando", "donde", "quien", "cual", "porque"}
)
_REQUEST_TOKENS: frozenset[str] = frozenset(
    {
        "manda",
        "mandas",
        "envia",
        "envias",
        "pasa",
        "pasas",
        "avisa",
        "avisas",
        "dime",
        "cuentame",
        "puedes",
        "podrias",
        "ayudame",
        "necesito",
        "quiero",
        "pides",
    }
    | _with_enclitic(("manda", "envia", "pasa", "avisa", "pide"), ("me", "lo", "la"))
)
_PROMISE_TOKENS: frozenset[str] = frozenset(
    {
        "manana",
        "luego",
        "despues",
        "ahorita",
        "lunes",
        "martes",
        "miercoles",
        "jueves",
        "viernes",
        "sabado",
        "domingo",
        "semanas",
    }
)
_MONEY_TOKENS: frozenset[str] = frozenset(
    {
        "pago",
        "pagar",
        "pague",
        "transferencia",
        "transferir",
        "deposito",
        "tarjeta",
        "precio",
        "banco",
        "cuenta",
        "cuanto",
        "dinero",
    }
)

_STRIP_CHARS = ".,;:!¡?¿\"'«»“”‘’()[]{}—–-…~`´"
#: Invisibles que ensucian la comparación (variation selectors, ZWJ).
_INVISIBLE = "️︎‍⃣"
_SKIN_TONES = range(0x1F3FB, 0x1F400)


def _strip_invisible(text: str) -> str:
    """Drop skin-tone modifiers, variation selectors and joiners."""
    kept = "".join(ch for ch in text if ord(ch) not in _SKIN_TONES)
    return "".join(ch for ch in kept if ch not in _INVISIBLE)


def _normalize_token(token: str) -> str:
    """Lowercase token with laughs folded and 3+ char runs collapsed.

    ``jajaja`` → ``jaja`` · ``jejeje`` → ``jeje`` · ``okkk`` → ``ok`` ·
    ``graciasss`` → ``gracias``.
    """
    if re.fullmatch(r"(?:ja){2,}", token):
        return "jaja"
    if re.fullmatch(r"(?:je){2,}", token):
        return "jeje"
    return re.sub(r"(.)\1{2,}", r"\1", token)


def normalize(text: str) -> str:
    """Normalize text for exact comparison against the closed lists.

    Lowercase, accents stripped, invisible marks removed, punctuation removed
    from token edges, whitespace collapsed. Emojis survive so ``👍`` matches.
    """
    if not text:
        return ""
    stripped = _strip_invisible(str(text))
    decomposed = unicodedata.normalize("NFKD", stripped)
    without_marks = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch)
    )
    tokens: list[str] = []
    for raw in without_marks.lower().split():
        token = raw.strip(_STRIP_CHARS)
        if token:
            tokens.append(_normalize_token(token))
    return " ".join(tokens)


@dataclass(frozen=True, slots=True)
class ClosingVerdict:
    """Result of the guard: would this turn close without a written reply?"""

    is_closing: bool
    reason: str
    kind: str | None = None  # "farewell" | "ack" when is_closing


def _last_line_asks(text: str | None) -> bool:
    """True when the last non-empty outbound line contains a question mark."""
    if not text:
        return False
    for line in reversed(str(text).splitlines()):
        line = line.strip()
        if line:
            return "?" in line or "¿" in line
    return False


def closing_verdict(
    text: str,
    *,
    intent: str = "",
    emotion: str = "neutral",
    risk: str = "bajo",
    media_unverified: bool = False,
    last_outbound_text: str | None = None,
    max_words: int = DEFAULT_MAX_WORDS,
) -> ClosingVerdict:
    """Decide whether ``text`` closes the turn without a written reply.

    Pure and side-effect free. Any doubt returns ``is_closing=False`` with a
    reason the trace can show — the normal pipeline is always the safe path.
    """
    if media_unverified:
        return ClosingVerdict(False, "media_unverified")
    if str(emotion or "").strip().lower() in BLOCKING_EMOTIONS:
        return ClosingVerdict(False, "emotion")
    if str(risk or "").strip().lower() != "bajo":
        return ClosingVerdict(False, "risk")
    # A question is doubt, and silence is worse than answering: never close on
    # a message that asks something, not even an exact farewell ("¿bye?").
    # Raw text on purpose — ``normalize`` strips ``?``/``¿`` from token edges.
    raw = str(text or "")
    if "?" in raw or "¿" in raw:
        return ClosingVerdict(False, "question")
    normalized = normalize(text)
    if not normalized:
        return ClosingVerdict(False, "empty")
    tokens = normalized.split()
    if len(tokens) > max(1, int(max_words)):
        return ClosingVerdict(False, "too_long")

    farewell = normalized in FAREWELL_PHRASES
    ack = normalized in ACK_PHRASES

    if (farewell or ack) and str(intent or "").strip().lower() in BLOCKING_INTENTS:
        return ClosingVerdict(False, "intent")

    # A farewell wins over an open question: the VIP is leaving.
    if farewell:
        return ClosingVerdict(True, "farewell", "farewell")

    if ack:
        if _last_line_asks(last_outbound_text):
            return ClosingVerdict(False, "open_question")
        return ClosingVerdict(True, "ack", "ack")

    return ClosingVerdict(False, _near_miss_reason(tokens))


def _near_miss_reason(tokens: list[str]) -> str:
    """Why a text that looked like a closing is not one (trace/explanation only).

    Ordered from the most actionable signal to the least: money and requests
    are what the owner most needs to see when a "gracias" did not close.
    """
    token_set = set(tokens)
    if token_set & _MONEY_TOKENS:
        return "money"
    if token_set & _REQUEST_TOKENS:
        return "request"
    if token_set & _PROMISE_TOKENS:
        return "promise"
    if token_set & _INTERROGATIVE_TOKENS:
        return "question"
    return "no_exact_match"
