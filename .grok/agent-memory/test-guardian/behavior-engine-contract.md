# Test-Guardian Report: behavior-engine-contract

**Date:** 2026-07-23  
**Auditor:** test-guardian  
**Plan:** `.planning/quick/behavior-engine-contract/PLAN.md`  
**Summary:** `.planning/quick/behavior-engine-contract/behavior-engine-contract-SUMMARY.md`  
**Arch:** `.grok/agent-memory/arch-enforcer/behavior-engine-contract.md` (PASS WITH NOTES, 0 critical)  
**Impact:** `.grok/agent-memory/impact-analyzer/behavior-engine-contract.md`  
**Decisions:** `.planning/quick/behavior-engine-contract/decisions.md`  
**Focus:** I.4 pre-send supersede · I.4 retries · fake_delivery · I.5 Admin fail surface  
**Verdict:** suite protege adecuadamente

## Coverage Audit

### DoD map (Anexo I + PLAN Tasks 1–4 · focus gates)

| Contract / DoD item | Protected by | Status |
|---------------------|--------------|--------|
| **I.3** sequence delay→read→typing→send | `test_happy_path_sequence_order` — ops order + `clock.sleeps` + delivery `done` | OK |
| I.3 multi-text | `test_multi_text_sends_each` | OK |
| **I.4 pre-send superseded** → zero send | `test_presend_superseded_aborts_without_send` — `SequenceTurnStatusReader(["superseded"])`, `send_count==0`, delivery `cancelled` | OK |
| **I.4 pre-send terminal** (`failed`) | `test_presend_terminal_failed_aborts` | OK |
| **I.4 pre-send missing turn** (`None`) | `test_presend_missing_turn_aborts` | OK |
| **I.4 transient then success** | `test_transient_then_success_within_budget` — Flaky N=1, `send_attempts>=2`, success, backoff in `clock.sleeps` | OK |
| **I.4 retries exhausted** | `test_transient_exhausted_returns_error` — max=2, `success=False`, delivery `error`, attempts==2 | OK |
| **I.4 permanent no retry** | `test_permanent_error_no_retry` — RuntimeError once, attempts==1 | OK |
| **I.2 mode enum** | `test_delivery_context_accepts_autonomous_mode`, `…_fake_delivery_mode`, `…_rejects_invalid_mode` | OK |
| **I.2/I.4 fake_delivery** no network | `test_fake_delivery_no_network_send` — `actuator.calls==[]`, `success=True`, delivery `done`, initial delay only | OK |
| **I.2/I.4 fake + pre-send abort** | `test_fake_delivery_presend_abort` — cancelled, not done | OK |
| Settings modes + retry/delay knobs | `test_settings_accepts_delivery_modes`, `test_settings_rejects_invalid_global_mode`, `test_settings_delivery_retry_and_delay_defaults`, `test_settings_rejects_non_positive_delay_min` | OK |
| REQ-NFR-01 never-zero prod delay | `test_random_delay_policy_rejects_zero_initial_min` | OK |
| **I.5** permanent fail → Turn.failed + notify + not waiting | `test_permanent_deliver_fail_marks_failed_and_notifies` — real Admin+Engine+BoomActuator; assert turn `failed`, approval `cancelled`≠waiting, `notify_info` contains fail, delivery trace set | OK |
| **I.5/L8** supersede does not force failed | `test_supersede_mid_flight_does_not_mark_failed` — status `superseded`, send 0, no `delivery_failed` notify | OK |
| REQ-VIP-06 cancel mid-delay | `test_cancel_pending_during_delay_no_send` | OK |
| CAS cancelled sticky | `test_cancelled_status_not_overwritten_by_done` | OK |
| bc fail-closed | `test_missing_business_connection_id_fail_closed`, whitespace variant | OK |
| Import purity (no llm/cognitive decision/aiogram) | `test_behavior_package_has_no_forbidden_imports` | OK |
| Concurrent double-approve single send | `test_concurrent_double_approve_single_send` (regression) | OK |
| Approve after supersede no deliver | `test_handle_approve_after_supersede_no_deliver` (regression) | OK |
| Recovery never auto-deliver | `test_startup_never_calls_deliver_or_approve` + recovery suite | OK |

**PLAN-required Task 2 table:** all 9 named cases present in `test_engine.py` (+ cancel regression).  
**Task 3 I.5:** both permanent-fail and supersede-no-failed present in `test_admin_service.py`.

| File | Count | Notes |
|------|-------|-------|
| `tests/unit/behavior/test_engine.py` | **19** | I.2 modes + I.3 happy/multi + cancel/CAS/bc + I.4 pre-send×3 + retries×3 + fake×2 |
| `tests/unit/behavior/test_fake_delivery.py` | **3** | Fake actuator order + clock/policy |
| `tests/unit/behavior/test_behavior_import_purity.py` | **1** | AST purity |
| `tests/unit/application/test_admin_service.py` | **12** | +2 I.5 (`permanent_deliver_fail…`, `supersede_mid_flight…`) |
| `tests/unit/test_config.py` | modes + delay/retry + RandomDelayPolicy | I.2 / REQ-NFR-01 |

### Production alignment (static)

- `engine.py`: `_presend_abort_if_not_live` **before each** `send_message` and before fake virtual completion; `_TERMINAL_SEND_ABORT` local strings; `_send_with_retries` only `TransientSendError`; `fake_delivery` skips actuator I/O.
- `ports.py`: `DeliveryMode` tri-state; `TransientSendError`; `TurnStatusReader`.
- `fake.py`: `AlwaysLiveTurnStatusReader`, `SequenceTurnStatusReader`, `FlakySendActuator` (records failed attempts).
- `admin_service.py`: permanent fail → approval `cancelled` + `mark_failed` + `notify_info` + trace; cancelled-live reopens waiting; terminal latch no-revive.
- `composition.py`: always injects `TurnStoreStatusReader(turns)` + retry knobs + `delivery_mode=settings.global_mode`.
- `config.py`: `global_mode` tri-state; delay mins `gt=0`; max attempts 1–10.

### Soft notes (not GAPS — do not block)

1. **Terminal statuses `delivered` / `escalated`** not named as separate tests — same frozenset branch as `failed`/`superseded`; covered by implementation + one terminal sample.
2. **Multi-text mid-loop pre-send abort after partial success** not explicit — PLAN residual (partial multi-text idempotency).
3. **Composition wiring of `TurnStoreStatusReader`** not unit-asserted — verified by arch-enforcer + source review; production ctor always injects.
4. **Production actuator does not raise `TransientSendError` yet** — decisions L5 residual; engine retry path fully locked with FlakySendActuator.
5. **Stale pytest nodeids** (`test_settings_rejects_non_supervised_global_mode`, `test_import_purity.py` under behavior) — cache noise only; functions removed/renamed.
6. **`turn_status=None` fail-open** — intentional fixture default (A13); arch observation, not test gap for F1.

### Residuals outside DoD (do not inflate)

- Full sandbox FakeDelivery UX (REQ-COG-14)
- Multi-process durable cancel last-mile (G.4)
- Telegram partial multi-text idempotency
- AGENTS.md §5.4 signature doc sync
- Mandatory `telegram_message_id`
- Dirty-tree alembic / models WIP

## Mock Audit

Inventory on item-touched tests:

```text
rg -nE '@patch|patch\(|MagicMock|AsyncMock|Mock\(|monkeypatch|mocker\.' \
  tests/unit/behavior/ \
  tests/unit/application/test_admin_service.py \
  tests/unit/test_config.py
```

| Archivo | Mock / patch | Clasificación | Path de negocio | Acción |
|---------|--------------|---------------|-----------------|--------|
| `test_engine.py` | **none** `@patch`/`MagicMock` | — | — | — |
| `test_engine.py` | Real `BehaviorEngine` | — | I.3 sequence, I.4 gate/retries, fake | ninguna |
| `test_engine.py` | `FakeTelegramActuator` / `FlakySendActuator` / `BoomActuator` | **PERMITIDO** | Telegram I/O edge (no network); records real call order/attempts | ninguna |
| `test_engine.py` | `ImmediateClock` / `FixedDelayPolicy` | **PERMITIDO** | Clock/policy edge; records sleeps for order/backoff asserts | ninguna |
| `test_engine.py` | `AlwaysLiveTurnStatusReader` / `SequenceTurnStatusReader` | **PERMITIDO (inyección)** | Injects **status sequence** for race tests; does **not** mock engine gate logic | ninguna |
| `test_engine.py` | `InMemoryPendingDeliveryStore` | **PERMITIDO** | In-memory port; asserts real CAS status (`cancelled`/`error`/`done`) | ninguna |
| `test_fake_delivery.py` | Fake actuator + ImmediateClock | **PERMITIDO** | Test doubles for order recording | ninguna |
| `test_behavior_import_purity.py` | AST only | — | No mocks | ninguna |
| `test_admin_service.py` | Real `AdminService` + real `BehaviorEngine` + real `TurnCoordinator` | — | I.5 fail + latch + approve paths | ninguna |
| `test_admin_service.py` | `FakeTelegramActuator` / BoomActuator / Sequence reader | **PERMITIDO** | Delivery edge + I.4 status inject | ninguna |
| `test_admin_service.py` | `FakeOwnerNotifier` | **PERMITIDO** | Owner notify edge; assert message text contains delivery fail | ninguna |
| `test_admin_service.py` | InMemory Turn/Approval/Delivery/Trace stores | **PERMITIDO** | Assert **store state** (failed/cancelled/waiting) not mock returns | ninguna |
| `test_config.py` | `monkeypatch.setenv` / `delenv` | **PERMITIDO** | Env injection for Settings; validates real Pydantic Settings | ninguna |
| Item tests | `@patch` / `MagicMock` / `AsyncMock` on engine internals | **0 found** | — | — |

**Resumen mocks:** N≈12 permitidos (fakes/ports/env); **0 mocks prohibidos** en scope del ítem.  
**Confianza de realidad:** **alta** — real `BehaviorEngine` + real `AdminService` + real stores; only external Telegram/owner-notify/clock edges faked; pre-send race uses injected status sequence (no wall-clock flakiness); asserts on `send_count`, delivery status, turn status, notifier texts.

## Re-run Results

Executor / SUMMARY evidence (commits `b54b310`, `1430ada`, `464f4e7`) + static re-audit this guardian run (production + tests still aligned; all PLAN nodeids present in `.pytest_cache`):

```text
# Executor Task4 (log + SUMMARY)
tests/unit/behavior/                          23 passed
tests/unit/application/test_admin_service.py  12 (incl. I.5)
tests/unit/test_config.py                     modes + delay knobs
core regression (admin/orch/coord/recovery/CAS) 94 passed
tests/unit/                                   443 passed
tests/unit/acceptance/test_tac_mvp_f1.py      8 passed
tests/unit/behavior/test_behavior_import_purity.py 1 passed
```

Static re-audit (this run):
- All PLAN-named I.3 / I.4 pre-send / retries / fake_delivery / I.2 mode / I.5 Admin tests present.
- Asserts bind to **real state** (actuator counts, store rows, turn.status, notifier.infos) — not mock return values.
- Pre-send tests use `SequenceTurnStatusReader` (deterministic, non-flaky).
- Arch-enforcer: PASS WITH NOTES, 0 critical — no executor return required.
- Purity AST forbids llm / cognitive decision modules / aiogram under `behavior/`.

## Pre-existing vs Attributable

- **0 failures** attributable to behavior-engine-contract.
- Stale `lastfailed` cache entries (`test_import_purity.py`, `test_empty_draft_escalates`) — pre-existing / other items; not this suite.
- Residuals (full FakeDelivery UX, multi-process cancel, partial multi-text, production TransientSendError mapping) intentional out-of-scope — not regressions.
- Dirty-tree WIP (`alembic/versions/002_turns_error.py`, etc.) left untouched per PLAN/SUMMARY.

## Tests added/changed this guardian run

None. Suite already locks I.4 pre-send, I.4 retries, fake_delivery, and I.5 Admin surface with real engine/admin and permitted edge fakes only. No rewrite required.

## Handoff

**Listo para cierre** → **step-6** (final tests / Commit Gate).

```bash
# step-6 final gate (confirm)
PYTHONPATH=src python -m pytest tests/unit/behavior/ -q --tb=short

PYTHONPATH=src python -m pytest \
  tests/unit/application/test_admin_service.py \
  tests/unit/test_config.py \
  tests/unit/behavior/test_behavior_import_purity.py \
  -q --tb=short

PYTHONPATH=src python -m pytest \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_turn_coordinator.py \
  tests/unit/application/test_recovery.py \
  tests/unit/application/test_recovery_startup.py \
  tests/unit/infrastructure/test_delivery_transitions.py \
  -q --tb=short

PYTHONPATH=src python -m pytest tests/unit/ -q --tb=line
PYTHONPATH=src python -m pytest tests/unit/acceptance/test_tac_mvp_f1.py -q --tb=short
```

**Do not** return to executor — coverage + mock audit clean.  
**Next after step-6 green:** documentador / pool remaining-contracts-app close (ITEM 3/3 Anexo I).
