# behavior-engine-contract — SUMMARY

**Status:** COMPLETE  
**Mode:** Strict TDD  
**Item:** behavior-engine-contract (Pool remaining-contracts-app · Anexo I · ITEM 3/3)

## Tasks completed

| Task | Result | Commit |
|------|--------|--------|
| 1 Ports + fakes + mode enum | GREEN | `b54b310` feat(behavior): widen DeliveryMode and add I.4 ports/fakes |
| 2 Engine I.4 pre-send + retries + fake_delivery | GREEN | `1430ada` feat(behavior): I.4 pre-send abort, bounded retries, fake_delivery |
| 3 Admin I.5 + composition/config | GREEN | `464f4e7` feat(admin): I.5 permanent delivery fail + mode/settings wiring |
| 4 Purity + full regression | GREEN | (verify-only) |

## What landed

- **I.2 mode:** `DeliveryContext.mode` / Settings `global_mode` = `supervised|autonomous|fake_delivery`
- **I.4 pre-send:** `TurnStatusReader` gate before each send (and fake virtual send); abort → `cancelled=True`, delivery `cancelled`, zero send
- **I.4 retries:** `TransientSendError` only; `max_send_attempts` (default 3) + backoff via `Clock.sleep`
- **I.2 fake_delivery:** record-only, no actuator I/O, honors pre-send + initial delay
- **I.5 Admin:** permanent fail → approval `cancelled`, `mark_failed`, `notify_info`, delivery trace; cancelled-live still reopens `waiting`; terminal latch still no-revive
- **REQ-NFR-01:** `RandomDelayPolicy` rejects `initial_min <= 0`; Settings delay mins `gt=0`; `FixedDelayPolicy` free for tests
- **Wiring:** `TurnStoreStatusReader(turns)` + retry knobs + `delivery_mode=settings.global_mode`

## Files touched (in-scope)

- `src/diana/behavior/ports.py`, `engine.py`, `fake.py`
- `src/diana/application/admin_service.py`
- `src/diana/composition.py`, `src/diana/config.py`
- `tests/unit/behavior/test_engine.py`
- `tests/unit/application/test_admin_service.py`
- `tests/unit/test_config.py`

## NOT touched

- `src/diana/cognitive/**`, `src/diana/llm/**`, `src/diana/learning/**`
- `alembic/**` (dirty tree residual left alone)

## Verifications

```
tests/unit/behavior/                          23 passed
tests/unit/application/test_admin_service.py  + new I.5 cases
tests/unit/test_config.py                     modes + delay knobs
core regression (admin/orch/coord/recovery/CAS) 94 passed
tests/unit/                                   443 passed
tests/unit/acceptance/test_tac_mvp_f1.py      8 passed
tests/unit/behavior/test_behavior_import_purity.py 1 passed
```

## Deviations

- None architectural. Ctor `turn_status` optional (None = always-live) for gradual fixture updates; production composition always injects reader.

## Residuals (document only — do not implement)

1. Full sandbox FakeDelivery UX (REQ-COG-14) — enum + record-only only
2. Multi-process durable cancel / Postgres last-mile (G.4)
3. Telegram partial multi-text idempotency after partial success
4. AGENTS.md §5.4 signature doc sync
5. Mandatory `telegram_message_id` at deliver gate
6. Dirty-tree WIP outside PLAN (`models.py`, `002_turns_error.py`, etc.) — not ours

## Self-Check: PASSED

- [x] All PLAN tasks completed
- [x] PLAN tests run (behavior, admin, config, purity, full unit, TAC)
- [x] 0 regressions attributable
- [x] Project conventions respected (Behavior ↛ cognitive/LLM/aiogram; English artifacts)
- [x] No alembic / no cognitive edits
- [x] Atomic commits per work unit

## Next agent

**`gsd-arch-enforcer`** for behavior-engine-contract architecture gate.
