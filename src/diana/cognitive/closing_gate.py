"""ClosingGate — pure, deterministic "does this turn need an answer?" filter (H8).

Answers a single question: **is this turn a closing or a bare acknowledgement
that needs no written reply?**

No I/O, no LLM, no persistence. Cognitive Core only — it must not import
``diana.application``, ``diana.telegram`` or ``diana.behavior`` (AGENTS §2.2).
The Decider owns the *action*; this module owns the *fact*.

Two paths, one set of doors
---------------------------
1. **Closed list** — every message of the burst, after stripping its vocatives
   ("hermosa", "mi amor", "Dianita") and an opening greeting ("hola"), must be
   EXACTLY one of the listed phrases. Nothing is ever invented from content:
   ``"gracias, y otra cosa…"`` keeps the normal flow because what remains after
   the strip is not a list phrase.
2. **``model_says_no_reply``** — the Analyst already read the turn and said it
   expects no written reply. It buys the cases no list reaches ("no te
   preocupes", "si ya mucho mejor gracias") and never skips a door below.

Doors (any rejection wins; order matters only for the reported reason):

1. ``media_unverified`` — a photo/video nobody looked at never closes.
2. emotion molesta / triste / ansiosa / urgente, or ``risk != "bajo"``.
3. ``?`` / ``¿`` anywhere in the inbound text — a question is never a closing,
   not even an exact farewell (``"ok?"``, ``"¿bye?"``). It is checked on the
   RAW text because :func:`normalize` strips those marks from token edges.
4. more than ``max_words`` words — closed-list path only: the cap exists
   because the list cannot read, and the Analyst (path 2) did read.
5. exact farewell → closing. A farewell wins over an OUR open question ("bye"
   after "¿te mando el video?" still closes: the VIP is leaving); that
   outbound-question gate applies to acknowledgements only, never to a
   farewell (same rule as the Product contract in AGENTS §4.26).
6. exact acknowledgement → closing **unless** the last outbound message asked
   a question (an "ok" that answers a question is not a closing).
7. path 2 adds two doors of its own: a greeting (``intent == "saludar"``)
   always deserves its answer, and a turn that mentions money always does.
8. near-miss explanations (money / request / promise tokens) only feed the
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
    "GREETING_PHRASES",
    "VOCATIVE_PHRASES",
    "ClosingVerdict",
    "closing_verdict",
    "normalize",
    "split_burst",
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


#: Despedidas reconocidas (texto completo, ya normalizado y sin vocativos).
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
        "que descanses bien",
        "descansa",
        # Despedidas de noche al uso en México (2026-11-01): "Pasa buena noche"
        # y "buenas noches" son el cierre más común del chat nocturno y no
        # estaban en la lista, así que Diana contestaba cada despedida.
        "buenas noches",
        "pasa buena noche",
        "pasa linda noche",
        "dulces suenos",
        # Despedidas del DÍA (2026-11-10): la lista tenía solo las de la noche,
        # así que "Pasa buen día" —el cierre más común de la mañana— no
        # cerraba nunca. Solo las formas con verbo: un "Buen día" suelto es un
        # saludo y espera respuesta, y ese lo decide el camino del Analyst.
        "pasa buen dia",
        "pasa buena tarde",
        "pasa un buen dia",
        "pasa buena semana",
        "que tengas buen dia",
        "que tengas lindo dia",
        "que tengas bonita semana",
        "que tengas buena noche",
        "que tengas buen fin",
        "feliz noche",
        "feliz dia",
    }
    | _with_enclitic(("cuida",), ("te",))
)

#: Acuses reconocidos (texto completo, ya normalizado y sin vocativos).
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
        # Acuses de conversación (2026-11-10): faltaban los que el cliente usa
        # para asentir sin pedir nada. Se dejan fuera a propósito los ambiguos
        # ("si", "no", "claro", "igual"), que solo cierran por el camino del
        # Analyst porque también pueden ser la respuesta a una pregunta.
        "que bueno",
        "que bien",
        "muy bien",
        "que rico",
        "de nada",
        "con gusto",
        "me alegra",
        "que gusto",
        "ok gracias",
    }
)

#: Vocativos: apodos con los que el cliente acompaña casi todas sus frases.
#: Se quitan ANTES de comparar contra la lista. "Pasa buena noche hermosa" es
#: la misma despedida que "Pasa buena noche"; hasta 2026-11-10 el adjetivo
#: bastaba para que no cerrara, y con estos clientes SIEMPRE viene el adjetivo.
VOCATIVE_PHRASES: frozenset[str] = frozenset(
    {
        "mi vida",
        "mi amor",
        "mi reina",
        "mi corazon",
        "mi cielo",
        "mi bella",
        "mi nina",
        "mi bella dianita",
        "mi hermosa dianita",
        "mi querida dianita",
        "mi dianita",
        "dianita hermosa",
        "hermosa dianita",
        "bella diana",
        "hermosa diana",
        "bella dama",
        "amor",
        "hermosa",
        "bella",
        "preciosa",
        "linda",
        "guapa",
        "corazon",
        "reina",
        "princesa",
        "cielo",
        "dianita",
        "diana",
        "bebe",
        "muneca",
        "munequita",
        "nena",
        "senorita",
    }
)

#: Saludos que pueden abrir el mensaje ("Hola amor, buenas noches"). Se quitan
#: solo del INICIO: un saludo suelto es un saludo, no un cierre, y si al
#: quitarlo no queda nada el turno vuelve al flujo normal.
GREETING_PHRASES: frozenset[str] = frozenset(
    {"hola", "holaa", "holis", "hello", "hey", "buenos dias", "buen dia", "buenas"}
)

#: Encabezado de ráfaga que arma el pipeline antes de llegar aquí.
_BURST_HEADER_RE = re.compile(
    r"\(\s*el vip envi[oó] [^)]*mensajes seguidos\s*\)", re.IGNORECASE
)
#: Prefijo "[N/M] " de cada mensaje dentro de la ráfaga.
_BURST_PREFIX_RE = re.compile(r"^\[\s*\d+\s*/\s*\d+\s*\]")

#: Relleno admisible alrededor de una frase de la lista: un vocativo o un
#: saludo, de frase más larga a más corta ("mi vida" antes que "mi").
_FILLER_PHRASES_LONGEST_FIRST: tuple[tuple[str, ...], ...] = tuple(
    sorted(
        (tuple(p.split()) for p in VOCATIVE_PHRASES | GREETING_PHRASES),
        key=len,
        reverse=True,
    )
)
#: Frases de la lista, de la más larga a la más corta, para que la más
#: específica gane cuando dos podrían encajar.
_LIST_PHRASES_LONGEST_FIRST: tuple[tuple[str, str], ...] = tuple(
    sorted(
        [(p, "farewell") for p in FAREWELL_PHRASES]
        + [(p, "ack") for p in ACK_PHRASES],
        key=lambda item: len(item[0].split()),
        reverse=True,
    )
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


def split_burst(text: str) -> list[str]:
    """Split the coalesced turn text into the individual messages it carries.

    The orchestrator merges an open burst into ONE text with a header
    ("(el VIP envió N mensajes seguidos)") and a "[N/M] " prefix per message.
    Bubbles can nest (a stored row may already carry an older burst), so the
    header and the prefix are stripped repeatedly.

    Why per message: the closing decision belongs to each message — "Me quedé
    esperando el video / Descansa" is NOT a closing, because the first line
    asks for something. Comparing the merged block against the closed list, as
    the first version did, made every burst impossible to close (more than half
    of the turns).
    """
    messages: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        while line:
            without_prefix = _BURST_PREFIX_RE.sub("", line, count=1).strip()
            without_header = _BURST_HEADER_RE.sub("", without_prefix, count=1).strip()
            if without_header == line:
                break
            line = without_header
        if line:
            messages.append(line)
    return messages


def _is_filler(tokens: list[str]) -> bool:
    """True when ``tokens`` is nothing but vocatives and greetings."""
    index = 0
    while index < len(tokens):
        for phrase in _FILLER_PHRASES_LONGEST_FIRST:
            size = len(phrase)
            if tuple(tokens[index : index + size]) == phrase:
                index += size
                break
        else:
            return False
    return True


def _match_list(normalized: str) -> ClosingVerdict | None:
    """Match a listed phrase with only vocatives/greetings around it.

    The phrase itself must appear CONTIGUOUS and complete, and every token
    outside it must be filler. That is what lets "Pasa buena noche hermosa"
    close (the farewell is intact, "hermosa" is just a vocative) while
    "no te preocupes linda" does not (there is no farewell to recognise: the
    vocative is stripped, never the message).
    """
    tokens = normalized.split()
    for phrase, kind in _LIST_PHRASES_LONGEST_FIRST:
        words = phrase.split()
        size = len(words)
        for start in range(len(tokens) - size + 1):
            if tokens[start : start + size] != words:
                continue
            if _is_filler(tokens[:start] + tokens[start + size :]):
                return ClosingVerdict(True, kind, kind)
    return None


def _message_verdict(
    message: str, *, intent: str, last_outbound_text: str | None, max_words: int
) -> ClosingVerdict:
    """Classify ONE message of the burst against the closed list."""
    normalized = normalize(message)
    if not normalized:
        return ClosingVerdict(False, "empty")
    tokens = normalized.split()
    if len(tokens) > max(1, int(max_words)):
        return ClosingVerdict(False, "too_long")
    match = _match_list(normalized)
    if match is None:
        return ClosingVerdict(False, _near_miss_reason(tokens))
    if str(intent or "").strip().lower() in BLOCKING_INTENTS:
        return ClosingVerdict(False, "intent")
    # A farewell wins over an open question: the VIP is leaving.
    if match.kind == "farewell":
        return match
    if _last_line_asks(last_outbound_text):
        return ClosingVerdict(False, "open_question")
    return match


def closing_verdict(
    text: str,
    *,
    intent: str = "",
    emotion: str = "neutral",
    risk: str = "bajo",
    media_unverified: bool = False,
    last_outbound_text: str | None = None,
    max_words: int = DEFAULT_MAX_WORDS,
    model_says_no_reply: bool = False,
) -> ClosingVerdict:
    """Decide whether ``text`` closes the turn without a written reply.

    Pure and side-effect free. Any doubt returns ``is_closing=False`` with a
    reason the trace can show — the normal pipeline is always the safe path.

    Two paths (AGENTS §4.26):

    * **closed list** — every message of the burst, with its vocatives and
      opening greeting stripped, is exactly a farewell or an acknowledgement;
    * **``model_says_no_reply``** — the Analyst judged that the turn expects no
      written reply. It never skips a door: questions, money, blocking intents,
      greetings, high risk, upset emotions and unseen media all still reject.
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

    messages = split_burst(text)
    if not messages:
        return ClosingVerdict(False, "empty")

    verdicts = [
        _message_verdict(
            message,
            intent=intent,
            last_outbound_text=last_outbound_text,
            max_words=max_words,
        )
        for message in messages
    ]
    # The burst closes only when EVERY message closes: one line that asks for
    # something keeps the whole turn in the normal flow.
    if all(verdict.is_closing for verdict in verdicts):
        kind = "farewell" if any(v.kind == "farewell" for v in verdicts) else "ack"
        return ClosingVerdict(True, kind, kind)

    first_open = next(v for v in verdicts if not v.is_closing)
    if model_says_no_reply:
        model_verdict = _model_verdict(
            raw, intent=intent, last_outbound_text=last_outbound_text
        )
        if model_verdict.is_closing:
            return model_verdict
        # The door that rejected the Analyst's suggestion is the one the trace
        # must show: "the list did not match" is true but useless when the real
        # reason was money, a greeting or an open question.
        return ClosingVerdict(False, model_verdict.reason)
    return ClosingVerdict(False, first_open.reason)


def _model_verdict(
    raw: str, *, intent: str, last_outbound_text: str | None
) -> ClosingVerdict:
    """Second path: the Analyst says the turn expects no written reply.

    Same safety doors as the list path, minus the word cap (the Analyst read
    the whole burst; the cap only exists because the list cannot read), plus
    two of its own: a greeting always deserves its answer, and a turn that
    mentions money always deserves one too.
    """
    normalized = normalize(raw)
    if not normalized:
        return ClosingVerdict(False, "empty")
    label = str(intent or "").strip().lower()
    if label == "saludar":
        return ClosingVerdict(False, "greeting")
    if label in BLOCKING_INTENTS:
        return ClosingVerdict(False, "intent")
    if set(normalized.split()) & _MONEY_TOKENS:
        return ClosingVerdict(False, "money")
    if _last_line_asks(last_outbound_text):
        return ClosingVerdict(False, "open_question")
    return ClosingVerdict(True, "model", "model")


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
