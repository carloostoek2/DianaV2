# Test-Guardian Report: turn-coordinator-contract

**Date:** 2026-07-23  
**Auditor:** test-guardian  
**Plan:** `.planning/quick/turn-coordinator-contract/PLAN.md`  
**Summary:** `.planning/quick/turn-coordinator-contract/SUMMARY.md`  
**Arch:** `.grok/agent-memory/arch-enforcer/turn-coordinator-contract.md` (PASS WITH NOTES, 0 critical)  
**Impact:** `.grok/agent-memory/impact-analyzer/turn-coordinator-contract.md`  
**Verdict:** suite protege adecuadamente

## Coverage Audit

### DoD map (Anexo G + PLAN focus: G.3 matrix, owner supersede, lock timeout, concurrency)

| Contract / DoD item | Protected by | Status |
|---------------------|--------------|--------|
| G.2 English surface `create\|replace\|discard_owner_message` | `test_coordinate_vip_idle_creates`, replace/discard cases; asserts `CoordinateResult.action` + `turn_id` | OK |
| G.3.3 VIP idle → create | `test_coordinate_vip_idle_creates` — one nonterminal `received`, `turn_id` set | OK |
| G.3.2 VIP nonterminal → replace | `test_coordinate_vip_nonterminal_replaces` — old superseded, `superseded_by==new`, one nonterminal | OK |
| G.3.1 owner + nonterminal → discard | `test_coordinate_owner_nonterminal_discards` — `turn_id is None`, zero nonterminal, `superseded_by is None` | OK |
| G.3 owner idle never creates (L1b) | `test_coordinate_owner_idle_discards_no_create` — zero rows for chat | OK |
| Owner discard cascade (approvals + cancel_pending `"owner_message"`) | `test_coordinate_owner_discards_cancels_approvals_and_pending` | OK |
| VIP replace cancel reason `"new_message"` | `test_coordinate_vip_replace_cancel_reason_new_message` | OK |
| G.4 concurrent VIP one nonterminal | `test_concurrent_coordinate_vip_one_non_terminal` + `test_concurrent_begin_turn_one_non_terminal` | OK |
| `begin_turn*` VIP wrappers | `test_begin_turn_still_vip_create_replace` + legacy begin_turn suite | OK |
| G.5 lock timeout raises (no silent drop) | `test_chat_scope_lock_timeout_raises` — hold lock + short timeout → `ChatLockTimeoutError`, no turn | OK |
| Owner MW business supersedes `pending_approval` | `test_owner_mw_business_supersedes_pending_approval` — real coordinator + store assert | OK |
| Owner private DM does not discard VIP chat | `test_owner_mw_private_does_not_coordinate_discard` | OK |
| REQ-VIP-06 / cascade on supersede | legacy `test_supersede_*` + owner cascade test | OK |
| Transition / sink / explicit turn_id | `test_transition_*`, `test_begin_turn_accepts_explicit_turn_id` | OK |

**PLAN-required test names:** all **11** new names present + legacy begin_turn/concurrent kept.

| File | Count | Notes |
|------|-------|-------|
| `tests/unit/application/test_turn_coordinator.py` | **17** | 8 legacy + 9 Anexo G (matrix/concurrency/timeout/wrapper) |
| `tests/unit/telegram/test_owner_mw.py` | **5** | idle stop + non-owner + private + supersede pending_approval + private no-discard |

### Production alignment (static)

- `coordinate_unlocked`: owner always `discard_owner_message` + `_supersede_nonterminal(superseded_by=None, cancel_reason="owner_message")`; VIP create/replace with cascade `"new_message"`.
- `_supersede_nonterminal` only calls `cancel_pending` / cancel approvals when priors exist (idle owner no-op cascade — matches PLAN A6).
- `chat_scope`: `wait_for(acquire)` + retries → `logger.error("chat_lock_timeout")` + `ChatLockTimeoutError`.
- `begin_turn` / `begin_turn_unlocked` VIP wrappers over `coordinate*`.
- Owner MW: business → `coordinator.coordinate(..., "owner")`; no direct `BehaviorCanceller`; private pass-through.

### Soft notes (not GAPS — do not block)

1. **Invalid `autor` → `ValueError`** — production raises; no dedicated unit test (arch observation). Optional; matrix paths covered.
2. **`chat_id is None` on owner business** — MW stops without coordinate (arch obs). Edge payload; not matrix hole.
3. **Pytest `lastfailed` cache** lists unrelated stale nodes (`test_import_purity.py`, `test_empty_draft_escalates`) — not attributable to this item; executor full unit reported green.

### Residuals outside DoD (do not inflate)

- Multi-process FOR UPDATE / advisory lock (L5 residual)
- Durable requeue after lock timeout (L5 residual)
- Orchestrator full-pipeline lock length (R5 keep)
- MVP_COMPONENT_DESIGN doc refresh (documentador)

## Mock Audit

Inventory on item-touched tests:

```text
rg -nE '@patch|patch\(|MagicMock|AsyncMock|Mock\(|monkeypatch|mocker\.' \
  tests/unit/application/test_turn_coordinator.py \
  tests/unit/telegram/test_owner_mw.py
```

| Archivo | Mock / patch | Clasificación | Path de negocio | Acción |
|---------|--------------|---------------|-----------------|--------|
| `test_turn_coordinator.py` | `FakeCanceller` (records `cancel_pending` calls) | **PERMITIDO** | Behavior cancel edge only; cascade still real in coordinator | ninguna |
| `test_turn_coordinator.py` | `InMemoryTurnStore` / `InMemoryPendingApprovalStore` | **PERMITIDO** | In-memory ports (PLAN policy) | ninguna |
| `test_turn_coordinator.py` | Real `TurnCoordinator` + real `ChatLockProvider` | — | G.3 matrix + G.4 concurrency + G.5 timeout | ninguna |
| `test_turn_coordinator.py` | G.5 holds real lock then `coordinate` with short ctor timeout | — | Real lock path; no mocked acquire | ninguna |
| `test_owner_mw.py` | `AsyncMock` for next `handler` | **PERMITIDO** | Telegram next-handler edge (stop vs pass-through) | ninguna |
| `test_owner_mw.py` | `FakeCanceller` + InMemory stores + **real** `TurnCoordinator` | **PERMITIDO** | Assert store supersede + approval cancel (not cancel_pending alone) | ninguna |
| `test_owner_mw.py` | `SimpleNamespace` event | **PERMITIDO** | Telegram event shape without bot API | ninguna |
| Item tests | `@patch` / `MagicMock` / `monkeypatch` on coordinate matrix / lock / stores | **0 found** | — | — |

Regression slice (not item-new; for completeness):

| Archivo | Mock | Clasificación | Note |
|---------|------|---------------|------|
| `test_middleware_stack.py` | `MagicMock` orchestrator/admin | **PERMITIDO** | Wiring order only; real `TurnCoordinator` + `build_dispatcher` DI | 

**Resumen mocks:** FakeCanceller + InMemory ports + AsyncMock handler only; **0 mocks prohibidos** en scope del ítem.  
**Confianza de realidad:** **alta** — G.3 matrix and G.5 exercised on real `TurnCoordinator` + real locks + real stores; only external cancel port and Telegram handler edge faked (PLAN mock policy).

## Re-run Results

Executor / SUMMARY evidence (commits `87165ed`, `37b996a`, `d504231`) + static re-audit this guardian run (production + tests still aligned; all PLAN nodeids present in `.pytest_cache`):

```text
.venv/bin/python -m pytest -q tests/unit/application/test_turn_coordinator.py
→ 17 passed

.venv/bin/python -m pytest -q \
  tests/unit/application/test_turn_coordinator.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/telegram/test_owner_mw.py \
  tests/unit/telegram/test_middleware_stack.py \
  tests/unit/application/test_deterministic_escalate.py \
  tests/unit/application/test_admin_service.py \
  tests/unit/application/test_admin_owner_escalate.py \
  tests/unit/test_composition_wiring.py \
  tests/unit/acceptance/test_tac_mvp_f1.py
→ 70 passed

.venv/bin/python -m pytest -q tests/unit
→ 414 passed
```

Static re-audit (this run):
- All PLAN-named G.3 / G.5 / owner MW tests present and assert **store state** (status, superseded_by, nonterminal count, approval cancelled) not mock return values.
- Concurrency tests use real `asyncio.gather` + real locks (no patched matrix).
- Owner MW integration uses real coordinator for supersede path.
- Arch-enforcer: PASS WITH NOTES, 0 critical — no executor return required.

## Pre-existing vs Attributable

- **0 failures** attributable to turn-coordinator-contract.
- Residuals (multi-process lock, durable enqueue, full-pipeline lock length) intentional out-of-scope — not regressions.
- Dirty-tree WIP (`alembic/versions/002_turns_error.py`, etc.) left untouched per PLAN/SUMMARY.
- Stale `lastfailed` entries outside this item’s node set — do not count as item regression.

## Tests added/changed this guardian run

None. Suite already locks G.3 matrix, owner supersede, G.5 timeout, and concurrent VIP with real coordinator (no prohibited mocks). No rewrite required.

## Handoff

**Listo para cierre** → **step-6** (final tests / Commit Gate).

```bash
# step-6 final gate (confirm)
.venv/bin/python -m pytest -q \
  tests/unit/application/test_turn_coordinator.py \
  tests/unit/telegram/test_owner_mw.py

.venv/bin/python -m pytest -q tests/unit
```

**Do not** return to executor — coverage + mock audit clean.  
**Next after step-6 green:** documentador / pool remaining-contracts-app item 2/3 as pipeline dictates.
