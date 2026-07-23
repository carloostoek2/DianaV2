# SUMMARY — registry-retrievers-contract

## Objective

Align Capability Registry + Retrievers runtime to `docs/contratos_restantes.md` Anexo H (H.1–H.4).

## Tasks completed

| Task | Result | Commit |
|------|--------|--------|
| 1 History/Context H.3 shapes | GREEN 12 retriever tests | `5cc909a` fix(cognitive): align History/Context retrievers to Anexo H.3 shapes |
| 2 Schedule half-register + Registry H.1 | GREEN registry+retrievers | `f49bfb3` fix(cognitive): mark knowledge.schedule half-registered (Anexo H.3) |
| 3 Blast fixtures + H.4 gates | GREEN full unit | `163dc5a` test(cognitive): lock registry/retriever Anexo H blast fixtures |

## What changed

### Production
- **HistoryRetriever**: bare `list[{autor,texto,timestamp}]`; empty `[]` never `None`; drop bot/unknown; map `owner`→`dueña` (local role map).
- **ContextRetriever**: always dict with only `waiting_for_reply_since` + `is_first_message_of_day`; injectable `clock`; formulas from plan L4.
- **ScheduleRetriever**: `fuente="no_implementado"`; `fetch→None`; still registered.
- **CapabilityRegistry**: `UNIMPLEMENTED_CAPABILITIES`, `PLANNER_CAPABILITY_UNIVERSE`; boot resolve loop in `build_default_registry`.
- **ports.Retriever**: docstring documents bare resultado ↔ conceptual H.2 envelope.

### Tests
- H.3 history/context shape locks + empty-history never-None.
- Schedule half-register + planner universe + stub/profile seats.
- Director isolation + ContextBuilder fixtures updated to H.3 keys.
- H.4 AST gates: no cross-peer retriever imports; read-only (no commit/flush/delete/session.add).

## Deviations

None. No Director production edits. No alembic / dirty-tree touch. No `{mensajes:}` wrapper. No H.2 envelope DTO.

## Verifications

```text
pytest tests/unit/cognitive/test_registry.py test_retrievers.py test_director.py
      test_context_builder.py test_planner.py test_import_purity.py  → 81 passed
pytest tests/unit/application/test_turn_orchestrator.py
      tests/unit/infrastructure/test_sql_repo_shapes.py              → 26 passed
pytest tests/unit                                                              → 425 passed
```

## Success criteria

- [x] History empty `[]` never `None`; non-empty bare `{autor,texto,timestamp}` (bots excluded)
- [x] Context only English H.3 keys; always object
- [x] Memory/Policy/Examples stubs → `None`; Profile F2 seat remains
- [x] Schedule resolve OK + `fuente=="no_implementado"` + fetch None
- [x] No H.2 envelope in runtime knowledge map; Director loop unchanged
- [x] No cross-retriever imports; read-only preserved
- [x] ContextBuilder still omits empty history `[]` (D.5 intact)
- [x] Full `tests/unit` green
- [x] No alembic / no-touch list violated

## Residuals

- **title:** MVP_COMPONENT_DESIGN.md §5.7 still says schedule=STUB without half-register nuance
- **clase_sugerida:** out-of-scope
- **por_qué:** PLAN non-goal (documentador residual R10)
- **archivos:** `docs/MVP_COMPONENT_DESIGN.md`

- **title:** Dirty tree residual `turns.error` / alembic `002_turns_error.py` untouched
- **clase_sugerida:** out-of-scope
- **por_qué:** L10 no-touch; pre-existing dirty tree outside this item
- **archivos:** `alembic/versions/002_turns_error.py`, infra models/turns

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles
- [x] Convenciones del proyecto respetadas

## Handoff

Next: **arch-enforcer** for registry-retrievers-contract.

## Hardener review
- HARD_ID: 1dab3c8b · effort 4 · rounds 1 · open 0
