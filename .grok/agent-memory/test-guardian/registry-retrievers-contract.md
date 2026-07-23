# Test-Guardian Report: registry-retrievers-contract

**Date:** 2026-07-23  
**Auditor:** test-guardian  
**Plan:** `.planning/quick/registry-retrievers-contract/PLAN.md`  
**Summary:** `.planning/quick/registry-retrievers-contract/SUMMARY.md`  
**Arch:** `.grok/agent-memory/arch-enforcer/registry-retrievers-contract.md` (PASS WITH NOTES, 0 critical)  
**Impact:** `.grok/agent-memory/impact-analyzer/registry-retrievers-contract.md`  
**Verdict:** suite protege adecuadamente

## Coverage Audit

### DoD map (Anexo H.1–H.4 + PLAN tasks 1–3)

| Contract / DoD item | Protected by | Status |
|---------------------|--------------|--------|
| H.1 resolve name→Retriever | `test_default_registry_resolves_all_seven_capabilities`, `test_register_and_resolve_custom` | OK |
| H.1 unknown → KeyError | `test_unknown_capability_raises_key_error` | OK |
| H.1 planner universe boot fail-fast | `test_build_default_registry_resolves_planner_universe` | OK |
| H.1 seven seats incl. profile F2 | `test_capabilities_lists_registered_names` + `test_profile_f2_seat_still_registered` | OK |
| H.2 bare resultado (no envelope DTO) | Director isolation asserts bare list/dict/`None` in `retrieved` | OK |
| H.3 History shape `{autor,texto,timestamp}` | `test_history_retriever_returns_chat_scoped_messages` | OK |
| H.3 History empty `[]` never None | `test_history_retriever_empty_chat_returns_empty_list_not_none` | OK |
| H.3 History owner→dueña; bots dropped | `test_history_retriever_maps_owner_to_duena` + chat-scoped (assistant dropped) | OK |
| H.3 History chat isolation + limit | `test_history_retriever_isolates_chat_ids`, `test_history_retriever_respects_limit` | OK |
| H.3 Context English keys only | `test_context_retriever_derives_partial_from_history` (keys set; no message_count) | OK |
| H.3 Context empty → waiting None / first True | `test_context_retriever_empty_history` | OK |
| H.3 Context formulas (L4) | `test_context_waiting_when_last_is_vip`, `test_context_not_waiting_when_last_is_owner`, `test_context_is_first_message_of_day_false_with_two_vip_today` | OK |
| H.3 Memory/Policy/Examples stubs → None | `test_stubs_return_none` + `test_memory_policy_examples_registered_stubs` | OK |
| H.3 Schedule half-register + fuente | `test_schedule_is_unimplemented_seat` | OK |
| H.3 Profile F2 seat | `test_profile_f2_seat_still_registered` | OK |
| H.4 no cross-retriever imports | `test_retrievers_have_no_cross_peer_imports_ast` | OK |
| H.4 read-only | `test_retrievers_are_read_only_ast` | OK |
| H.4 examples anti-contam AST | `test_examples_stub_has_no_memory_imports_ast` | OK |
| D.5 empty history still omitted | `test_empty_list_and_dict_knowledge_omitted` (CB fixtures H.3 keys) | OK |
| Director real registry isolation | `test_registry_isolation_history_uses_turn_chat_id` (history/context shapes + stubs/schedule None) | OK |
| Planner still requests schedule | `test_planner_single_true_flag_maps_to_single_cap[needs_schedule…]`, C.4 example set | OK |
| Cognitive import purity | `test_cognitive_package_has_no_forbidden_imports` | OK |

**PLAN-required test names:** all present in `test_registry.py` (8) + `test_retrievers.py` (14) + director isolation + CB fixtures + H.4 AST gates.

### Production alignment (static)

- `registry.py`: `UNIMPLEMENTED_CAPABILITIES`, `PLANNER_CAPABILITY_UNIVERSE`, boot resolve loop, seven seats.
- `history.py`: bare mapped list; empty `[]`; drop unmapped roles; local `_ROLE_TO_AUTOR`.
- `context.py`: only H.3 English keys; injectable `clock`; L4 formulas.
- `schedule.py`: `fuente="no_implementado"`; `fetch→None`.
- `ports.Retriever`: docstring bare resultado ↔ conceptual H.2 envelope.
- Director retrieve loop unchanged (`retrieved[cap] = await fetch(...)`).
- ContextBuilder `_is_null_like` untouched — bare `[]` still omitted.

### Soft notes (not GAPS — do not block)

1. Stale pytest nodeid `test_examples_stub_source_has_no_memory_imports` in cache — function renamed to `*_ast`; cache noise only.
2. Dual `get_recent` (History + Context) remains (R7 out of scope).
3. `fuente` not in Director `retrieved` map — intentional L1 bare resultado (arch observation).

### Residuals outside DoD (do not inflate)

- `MVP_COMPONENT_DESIGN.md` §5.7 schedule wording (documentador R10)
- Dirty-tree alembic `002_turns_error` (L10 no-touch)

## Mock Audit

Inventory on item-touched tests:

```text
rg -nE '@patch|patch\(|MagicMock|AsyncMock|Mock\(|monkeypatch|mocker\.' \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_retrievers.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_import_purity.py
→ 0 matches for @patch/MagicMock/AsyncMock/Mock(/mocker
```

| Archivo | Mock / patch | Clasificación | Path de negocio | Acción |
|---------|--------------|---------------|-----------------|--------|
| `test_registry.py` | **none** — real `build_default_registry` + real retrievers + `InMemoryMessageHistory` | — | H.1 resolve / schedule / stubs | ninguna |
| `test_retrievers.py` | **none** — real `HistoryRetriever`/`ContextRetriever`/stubs + InMemory port; `clock=` injection for time | **PERMITIDO (inyección)** | H.3 shapes + L4 formulas; clock is testable edge only | ninguna |
| `test_director.py` (`test_registry_isolation_*`) | `FakeLLM` structured/text queues | **PERMITIDO** | External LLM edge; **real** Director + **real** `build_default_registry` + real History/Context | ninguna |
| `test_director.py` | `InMemoryMessageHistory` / `InMemoryTraceStore` / `InMemoryTurnStatusSink` | **PERMITIDO** | In-memory ports (PLAN L11) | ninguna |
| `test_context_builder.py` | none — real `ContextBuilder` + H.3-shaped fixtures | — | D.5 omit empty history; prompt keys | ninguna |
| `test_planner.py` | none — real `Planner()` | — | schedule still plannable | ninguna |
| `test_import_purity.py` | none (AST) | — | cognitive purity | ninguna |
| Item tests | `@patch` / `MagicMock` / `AsyncMock` on Registry/Retrievers | **0 found** | — | — |

**Resumen mocks:** FakeLLM + InMemory ports + injectable clock only; **0 mocks prohibidos** en scope del ítem.  
**Confianza de realidad:** **alta** — History/Context/Registry unit paths use real classes + real InMemory history (no service doubles); Director isolation exercises real registry retrieve loop; only LLM edge faked (PLAN L11).

## Re-run Results

Executor / SUMMARY evidence (commits `5cc909a`, `f49bfb3`, `163dc5a`) + static re-audit this guardian run (production + tests still aligned; all PLAN nodeids present in `.pytest_cache` except stale renamed examples AST alias):

```text
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_retrievers.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_import_purity.py \
  --tb=short
→ 81 passed

.venv/bin/python -m pytest -q \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/infrastructure/test_sql_repo_shapes.py \
  --tb=short
→ 26 passed

.venv/bin/python -m pytest -q tests/unit --tb=short
→ 425 passed
```

Static re-audit (this run):
- All PLAN-named H.3 history/context/schedule/stub tests present and assert **real fetch outputs** (shapes, empty `[]`, fuente, keys).
- Director isolation asserts bare H.3 shapes in trace `retrieved` (no envelope).
- H.4 AST gates present for cross-peer imports + read-only mutators.
- CB fixtures use H.3 English keys; empty history omit still locked.
- Arch-enforcer: PASS WITH NOTES, 0 critical.

## Pre-existing vs Attributable

- **0 failures** attributable to registry-retrievers-contract.
- Residuals (MVP doc §5.7, dual get_recent, fuente not in trace map) intentional out-of-scope — not regressions.
- Dirty-tree WIP (`alembic/versions/002_turns_error.py`) left untouched per PLAN/SUMMARY.
- Stale `lastfailed` entries (`test_import_purity.py` wrong path, `test_empty_draft_escalates`) outside this item’s node set — do not count as item regression.

## Tests added/changed this guardian run

None. Suite already locks H.1–H.4 shapes, schedule half-register, H.4 AST gates, and director isolation with real registry (no prohibited mocks). No rewrite required.

## Handoff

**Listo para cierre** → **step-6** (final tests / Commit Gate).

```bash
# step-6 final gate (confirm)
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_retrievers.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_import_purity.py \
  --tb=short

.venv/bin/python -m pytest -q \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/infrastructure/test_sql_repo_shapes.py \
  --tb=short

.venv/bin/python -m pytest -q tests/unit --tb=short
```

**next_recommended:** step-6-tests  
**mock_audit:** pass (0 prohibited)  
**verdict:** suite protege adecuadamente
