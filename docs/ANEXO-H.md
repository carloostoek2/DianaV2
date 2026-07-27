## H6: Plantillas deterministas — saludo constante + "¿eres una IA?"

### H6.1 Por qué NO van en `ForbiddenKeywordsMiddleware`

Ese middleware corre en la capa de Telegram, antes de que exista un `Turn`/`IncomingTurn` formal, y su único camino de salida es "escalar en silencio, sin respuesta al VIP" (`handle_deterministic_escalation`). Ni el saludo ni "¿eres una IA?" quieren eso — quieren **una respuesta real, que sigue pasando por la cola de aprobación de la dueña** (modo supervisado no tiene excepciones, ni siquiera para texto 100% fijo — Anexo F.4). Así que el lugar correcto es dentro de `CognitiveDirector.handle_turn`, como un primer chequeo antes de invocar al Analista, no en el middleware.

### H6.2 Nuevo componente puro: `cognitive/template_gate.py`

Mismo espíritu que `Planner`/`RepetitionGuard` — determinista, sin I/O, sin LLM:

```python
@dataclass(frozen=True)
class TemplateRule:
    id: str
    trigger_patterns: list[str]   # keywords/frases, mismo estilo que match_forbidden_keywords
    max_words: int | None         # None = sin límite; usado para "saludo puro" vs mensaje mixto
    response_pool: list[str]      # 1 o más variantes
    reason: str                   # aparece en Decision.reason, visible en /traza y /turnos

class TemplateGate:
    def __init__(self, rules: list[TemplateRule], *, rng=random) -> None:
        self._rules = rules
        self._rng = rng

    def match(self, text: str) -> TemplateRule | None:
        words = text.strip().split()
        lower = text.lower()
        for rule in self._rules:
            if rule.max_words is not None and len(words) > rule.max_words:
                continue
            if any(_kw_hit(kw, lower) for kw in rule.trigger_patterns):
                return rule
        return None

    def render(self, rule: TemplateRule) -> str:
        return self._rng.choice(rule.response_pool)
```

`_kw_hit` reutiliza la misma lógica de `match_forbidden_keywords` (regex de palabra completa o frase) — no hace falta inventar un matcher nuevo.

### H6.3 Las dos reglas concretas

```python
saludo_constante = TemplateRule(
    id="saludo_constante",
    trigger_patterns=["hola", "holaa", "holis", "buenas", "buenos días",
                       "buenas tardes", "buenas noches", "hey", "qué tal"],
    max_words=4,   # evita falso positivo en "hola, tengo una duda sobre..."
    response_pool=["Holis 😁", "Holaa, qué tal?", "Hola amor, cómo vas?"],
    reason="plantilla_saludo",
)

deteccion_ia = TemplateRule(
    id="deteccion_ia",
    trigger_patterns=["eres una ia", "eres un bot", "eres ia",
                       "hablo con una ia", "hablo con un bot", "eres real"],
    max_words=None,
    response_pool=["jsjsj si y sólo vivo en tu mente 😏"],   # texto único, exacto
    reason="plantilla_deteccion_ia",
)
```

`max_words=4` en el saludo es el candado contra falsos positivos — sin él, "hola, quería preguntarte algo importante sobre el contenido" también dispararía la plantilla, que es justo lo que no quieres.

### H6.4 Integración en `CognitiveDirector.handle_turn`

```python
async def handle_turn(self, turn_context: IncomingTurn) -> Decision:
    turn = turn_context
    turn_id = turn.turn_id
    try:
        rule = self._template_gate.match(turn.text)
        if rule is not None:
            return await self._handle_template(turn, rule)
        return await self._run_pipeline(turn)
    except Exception:
        await self._status.transition(turn_id, TurnStatus.FAILED)
        raise

async def _handle_template(self, turn: IncomingTurn, rule: TemplateRule) -> Decision:
    text = self._template_gate.render(rule)
    decision = Decision(
        action="approve",
        reason=rule.reason,
        evaluation=None,          # no hubo Evaluador — no hay perfil que mostrar
        draft_text=text,
        mode_restriction_applied=None,
    )
    await self._store(turn.turn_id, "decision", decision)
    return decision
```

**Punto clave — no toqué `TurnOrchestrator`.** `Decision.action == "approve"` ya es el camino que existe hoy (`turn_orchestrator.py`, rama `if decision.action == "approve":`) — transiciona a `PENDING_APPROVAL` y llama a `admin_service.send_draft_for_approval` exactamente igual que un turno generado normal. La dueña ve el borrador en su cola con `reason: "plantilla_saludo"` o `"plantilla_deteccion_ia"` visible — eso ya cumple la función de "que se entere" que buscábamos con la idea original de escalar; no hace falta una segunda escalación en paralelo (y crear dos turnos por un mismo mensaje rompería la invariante del Turn Coordinator).

### H6.5 Qué se salta (y por qué es la ganancia real)

Con `rule` detectada: **Analista, Planificador, Retrievers, Constructor de Contexto, Generador y Evaluador nunca se ejecutan.** El turno pasa de ~11.5s (como en tu trace) a milisegundos, y de una llamada LLM cara (Analista) + otra (Generador) + otra (Evaluador) a cero llamadas LLM. Es la misma lógica de ahorro que ya aplicamos a la repetición 3x (H4) — cuando ya sabes la respuesta, no le pagues a un modelo por reinventarla.

### H6.6 Verificación adicional

1. "Hola" → `Decision.reason == "plantilla_saludo"`, `draft_text` es una de las 3 variantes, Analyst/Generator/Evaluator no se llaman (mock `assert_not_called`).
2. "Hola, tengo una pregunta sobre el contenido" (5+ palabras) → **no** dispara la plantilla, sigue el pipeline completo normal (valida el candado `max_words`).
3. "eres una ia?" → `draft_text == "jsjsj si y sólo vivo en tu mente 😏"` exacto, siempre (no hay pool que variar aquí).
4. El borrador de plantilla sigue pasando por `/traza` y por la cola de aprobación normal — la dueña puede corregir/aprobar igual que cualquier otro turno.
5. Limpieza de `config/persona_diana.yaml`: quitar el `(ver J.2 / examples)` de `reglas_estilo` (hallazgo de esta sesión).
