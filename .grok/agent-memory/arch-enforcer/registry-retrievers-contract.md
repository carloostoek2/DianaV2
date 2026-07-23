# Arch Audit: registry-retrievers-contract

**Date:** 2026-07-23  
**Auditor:** arch-enforcer  
**Plan:** `.planning/quick/registry-retrievers-contract/PLAN.md`  
**Summary:** `.planning/quick/registry-retrievers-contract/SUMMARY.md`  
**Contract:** `docs/contratos_restantes.md` Anexo H (H.1–H.4)  
**Verdict:** PASS WITH NOTES  
**Critical violations:** 0

## Scope audited

Production:
- `src/diana/cognitive/registry.py` — resolve map; `UNIMPLEMENTED_CAPABILITIES`; `PLANNER_CAPABILITY_UNIVERSE`; boot resolve loop
- `src/diana/cognitive/retrievers/history.py` — bare `{autor,texto,timestamp}` list; empty `[]`; drop bot/unknown; local role map
- `src/diana/cognitive/retrievers/context.py` — English H.3 keys only; formulas L4; injectable `clock`
- `src/diana/cognitive/retrievers/schedule.py` — half-register `fuente=no_implementado`; fetch → None
- `src/diana/cognitive/ports.py` — `Retriever` Protocol docstring (bare resultado ↔ conceptual H.2 envelope)
- Stubs: `memory.py`, `policy.py`, `examples.py`, `profile.py` (unchanged seats, still None)
- `src/diana/cognitive/director.py` — retrieve loop **unchanged** (bare `retrieved[cap] = await fetch(...)`)
- `src/diana/cognitive/context_builder.py` — `_is_null_like` **untouched**; empty history `[]` still omitted (D.5)

Cross-checks:
- AGENTS.md §3 Capability Registry + Retrievers; §3.2 no cross-retriever; §5.5 anti-contam; §6.1 retriever rules
- Import purity: cognitive ↛ telegram / behavior / learning / aiogram / infrastructure / application
- Layer direction: Registry → Retrievers → ports only; no Behavior / Learning / Telegram
- Commits: `5cc909a`, `f49bfb3`, `163dc5a`

## Evidence

| Check | Result |
|-------|--------|
| H.1 Registry single question (name → Retriever) | **PASS** — static `_by_name` map; `resolve` / `register` only |
| H.1 unknown capability | **PASS** — `KeyError("unknown capability: …")`; not mid-turn for planned caps |
| H.1 planner universe boot fail-fast | **PASS** — `build_default_registry` loops `PLANNER_CAPABILITY_UNIVERSE` + `resolve` |
| H.2 bare resultado (L1 locked) | **PASS** — no Spanish envelope DTO; Protocol documents conceptual `{capacidad, resultado, fuente}` |
| H.2 fetch signature | **PASS** — `fetch(turn, comprehension)` kept; `chat_id` via `IncomingTurn` (L9) |
| H.3 History shape | **PASS** — bare `list[{autor, texto, timestamp}]`; **no** `{mensajes:}` wrapper (D.5 safe) |
| H.3 History empty | **PASS** — `[]` never `None` (locked by test) |
| H.3 History role map | **PASS** — local `_ROLE_TO_AUTOR` copy; `owner`→`dueña`; bot/assistant/unknown dropped |
| H.3 Context keys | **PASS** — exactly `waiting_for_reply_since` + `is_first_message_of_day`; always object |
| H.3 Context formulas | **PASS** — end→start waiting; vip today count ≤ 1; empty → waiting None / first True |
| H.3 Memory/Policy/Examples stubs | **PASS** — registered real classes → always `None` |
| H.3 Schedule half-register (L5) | **PASS** — resolve OK; `fuente=="no_implementado"`; fetch None; not KeyError when planned |
| H.3 Profile F2 seat (L7) | **PASS** — still registered STUB → None; outside planner universe |
| H.4 no cross-retriever imports | **PASS** — peer modules have no `diana.cognitive.retrievers.*` imports; AST gate |
| H.4 read-only | **PASS** — history/context only `get_recent`; AST forbids commit/flush/delete/session.add/sqlalchemy |
| Anti-contamination examples↔memory | **PASS** — examples AST gate; history chat-scoped via port |
| Director loop unchanged | **PASS** — still `retrieved[cap] = await retriever.fetch(...)`; no unwrap |
| D.5 empty history omit | **PASS** — bare `[]` remains null-like; Context always non-empty dict when planned (A3 intentional) |
| Cognitive purity | **PASS** — no telegram/behavior/learning/infra/aiogram imports in package |
| Scope vs PLAN | **PASS** — production edits in registry + retrievers + ports docstring; tests blast only; no alembic / composition signature / planner / director production / telegram / behavior / learning |
| No H.2 envelope in knowledge map | **PASS** — director isolation asserts bare shapes |
| No Decision / Anexos A–G / I re-open | **PASS** |

## Findings

### Critical (must fix before advance)

_None._

### Medium

_None that block advance._

### Observations

1. **Literal H.3 “Schedule no registrado” vs half-register** — Prose says the registry “ni siquiera tiene una entrada”, then requires recognized-but-unimplemented with `fuente=no_implementado`. Runtime correctly follows locked L5 (still registered + fuente + None). Product interpretation is coherent with Anexo C (planner still requests schedule) and TAC-02 seven seats.
2. **H.2 envelope is docstring-only** — Intentional L1 to avoid Director unwrap and ContextBuilder breakage. Trace `retrieved` stores bare resultado; `fuente` is not persisted in the knowledge map (only class attribute on ScheduleRetriever). Acceptable for F1; full envelope in traces would be a future item.
3. **Dual `get_recent` (History + Context)** — Both hit the history port independently. Shared snapshot / R7 explicitly out of scope; not a layer violation.
4. **Role map duplication** — `_ROLE_TO_AUTOR` copied in HistoryRetriever (and Director keeps its own for Analyst history). Correct: retrievers must not import Director. Drift risk is test-locked for history mapping.
5. **Boot fail-fast scope** — Only `PLANNER_CAPABILITY_UNIVERSE` is asserted at `build_default_registry`; true-unknown names still KeyError at first resolve. Composition already builds the default registry at startup, so planned caps cannot surprise mid-turn.
6. **Context always emitted when planned** — Non-null-like dict with both keys → ContextBuilder always includes `knowledge.context` section. Intentional H.3 “object always” (A3); differs from empty history omission.
7. **Residuals (documented, out of scope)** — `MVP_COMPONENT_DESIGN.md` §5.7 schedule wording (R10 documentador); dirty-tree alembic `002_turns_error` (L10).

## Compliance Checklist

- [x] Capas respetadas (Registry/Retrievers in Cognitive; no telegram/behavior/learning)
- [x] Scope del PLAN respetado (no Director production, no alembic, no Anexos A–G/I, no envelope DTO)
- [x] Registry responde solo name → Retriever (H.1)
- [x] Cada Retriever responde solo “qué sabemos sobre X?” (H.2)
- [x] Bare resultado en knowledge map; no envelope runtime (L1)
- [x] History bare list / empty `[]` never None; bots dropped (L2/L3)
- [x] Context English H.3 keys only; always object (L4)
- [x] Schedule half-registered + fuente + None (L5)
- [x] Stubs Memory/Policy/Examples registered → None (L6); Profile F2 seat (L7)
- [x] No cross-retriever imports; read-only (L8/H.4)
- [x] Anti-contaminación: chat-scoped history; examples sin memories
- [x] D.5 null-like: empty history still omitted; no `{mensajes:[]}` wrapper
- [x] Director 100% determinista; retrieve loop unchanged
- [x] Tests lock H.1–H.4 shapes + isolation + AST gates
- [x] Logging: no new critical paths requiring structured logs in this item

## Handoff

**Verdict: PASS WITH NOTES** (0 critical) → advance to **test-guardian** for `registry-retrievers-contract`.

Next agent: **test-guardian**  
Focus: primary cluster (registry, retrievers, director isolation, context_builder fixtures, planner still requests schedule, import purity) + H.4 AST gates + full `tests/unit` regression; mock policy FakeLLM/InMemory only.
