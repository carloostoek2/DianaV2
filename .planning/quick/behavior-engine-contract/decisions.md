# behavior-engine-contract — Locked decisions

Source: orchestrator locks + impact-analyzer `behavior-engine-contract.md` + Anexo I (`docs/contratos_restantes.md`).

| ID | Decision | Status |
|----|----------|--------|
| L1 | **I.4 pre-send supersede check** lives **inside `BehaviorEngine`**, immediately before each `send_message` (and before virtual fake send). Task cancel alone is insufficient. | LOCKED |
| L2 | Status read via thin **`TurnStatusReader`** port injected into engine (not Admin wrapper-only). All deliver callers get I.4 free. | LOCKED |
| L3 | Abort without send when status is **missing** or in terminal set: `superseded`, `delivered`, `failed`, `escalated`. Local string frozenset — **no** `diana.cognitive` import. | LOCKED |
| L4 | **Bounded send retries** only for **transient** channel errors; permanent errors fail immediately. Default **max 3 attempts** per text bubble (configurable). | LOCKED |
| L5 | Transient marker: `TransientSendError` in `behavior` package; Fake actuator raises it in tests; production actuator **may** wrap known network/timeout classes later — no `aiogram` import in `behavior/`. | LOCKED |
| L6 | **I.5 failure ownership:** Engine returns `DeliveryResult(success=False, error=...)`. **Admin** marks `Turn.status=failed` + `notify_info` owner. Engine never writes Turn rows. | LOCKED |
| L7 | On permanent deliver fail (not cancelled): Admin does **not** reopen approval as `waiting` (silent drop). Mark approval **cancelled**; turn **failed**; notify owner. | LOCKED |
| L8 | On `result.cancelled`: keep existing post-latch (no revive); do **not** mark failed if turn already terminal; if still live + cancelled, reopen waiting is OK (rare). | LOCKED |
| L9 | **Mode enum:** `Literal["supervised", "autonomous", "fake_delivery"]` (English). Map: supervisado→supervised, autonomo→autonomous. Default `"supervised"`. | LOCKED |
| L10 | **`fake_delivery` F1:** record-only / no-network path — after sequence delays (and pre-send live check), **do not** call actuator send/read/typing; mark delivery `done`; return `success=True` with `message_ids=[]` (or synthetic). Full sandbox UX residual. | LOCKED |
| L11 | Sequence order preserved: **delay → read → typing → send**. Read remains optional when `telegram_message_id is None` (F1 residual note). | LOCKED |
| L12 | **Never-zero delay (REQ-NFR-01):** enforce on production `RandomDelayPolicy` / Settings (`initial_min > 0`). **`FixedDelayPolicy` stays free** for unit speed (may be 0). | LOCKED |
| L13 | Behavior **never** generates text, never imports LLM / cognitive decision modules / aiogram. No dirty alembic. | LOCKED |
| L14 | Keep deliver signature `(texts, ctx, turn_id, decision=)` — multi-text list preserved. | LOCKED |
| L15 | Strict TDD: failing tests for I.4 pre-send, retries, mode, I.5 Admin surface **before** production code. | LOCKED |

## English ↔ Anexo I mapping (docstring only)

| Runtime (English) | Anexo I (Spanish) |
|-------------------|-------------------|
| `mode="supervised"` | `modo: "supervisado"` |
| `mode="autonomous"` | `modo: "autonomo"` |
| `mode="fake_delivery"` | `modo: "fake_delivery"` |
| `DeliveryResult.success` | `ok` |
| `DeliveryResult.error` | `error` |
| `DeliveryResult` fields | `resultado_entrega` |
| `texts: list[str]` | `texto_final` (F1 multi-bubble extension) |
| Pre-send `TurnStatusReader` | I.4 last-mile supersede abort |
| Bounded send retries | I.4 / REQ-NFR-04 |
| Admin `mark_failed` + `notify_info` | I.5 Turn.failed + owner notify |

## Retry defaults (module / settings)

| Knob | Default | Notes |
|------|---------|-------|
| `delivery_max_send_attempts` | `3` | Total attempts per text (1 initial + 2 retries) |
| `delivery_retry_backoff_seconds` | `0.05` | Sleep between transient retries (ImmediateClock records in tests) |
| `RandomDelayPolicy.initial_min` | `4.0` | Must be `> 0` |
| `RandomDelayPolicy.initial_max` | `14.0` | `>= initial_min` |

## Residuals (out of this PR)

1. Full sandbox product / FakeDelivery UX (REQ-COG-14 body beyond enum + record-only stub).
2. Multi-process durable cancel / cross-worker last-mile (G.4 residual).
3. Perfect Telegram partial multi-text idempotency after partial success.
4. Config-driven typing formula beyond current `RandomDelayPolicy` knobs (optional settings ok if trivial).
5. AGENTS.md §5.4 signature reorder to match code (documentador).
6. Making `telegram_message_id` mandatory at deliver gate.
