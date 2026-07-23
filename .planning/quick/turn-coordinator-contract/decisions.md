# turn-coordinator-contract — Locked decisions

Source: orchestrator locks + impact-analyzer `turn-coordinator-contract.md` + Anexo G.

| ID | Decision | Status |
|----|----------|--------|
| L1 | Owner (dueña) **never** creates a Turn; G.3.1 supersede nonterminal + discard message from pipeline | LOCKED |
| L1b | Owner + no nonterminal → still `discard_owner_message` (no create) — F1 refinement of literal G.3.3 | LOCKED |
| L2 | VIP nonterminal → supersede + create (`replace`); none → `create` | LOCKED |
| L3 | Serialize by `chat_id` via existing `ChatLockProvider` / `chat_scope` / `asyncio.Lock` (F1 single-worker) | LOCKED |
| L4 | Prefer unified `coordinate` API; keep `begin_turn` / `begin_turn_unlocked` as VIP wrappers (no massive rename) | LOCKED |
| L5 | G.5 F1: lock acquire timeout + bounded retry + **loud fail** (raise); never silent drop. Durable enqueue + multi-process `FOR UPDATE` = **residual** | LOCKED residual |
| L6 | Wire owner business middleware path through coordinator supersede cascade (not only `cancel_pending`) | LOCKED |
| L7 | No cognitive rewrite; no dirty alembic residual | LOCKED |
| L8 | English identifiers; Spanish map in docs/docstring only | LOCKED |

## Token constants (runtime English)

| Runtime | Anexo G (Spanish) |
|---------|-------------------|
| `autor="vip"` | `autor: "vip"` |
| `autor="owner"` | `autor: "dueña"` |
| `action="create"` | `accion: "crear"` |
| `action="replace"` | `accion: "reemplazar"` |
| `action="discard_owner_message"` | `accion: "descartar_mensaje_dueña"` |
| `CoordinateResult` | `CoordinatorOutput` |
| `coordinate(...)` | entry decision (G.2) |
| `ChatLockTimeoutError` | G.5 lock failure (loud) |

## Cascade reasons

| Path | `cancel_pending` reason |
|------|-------------------------|
| VIP create/replace | `"new_message"` (existing) |
| Owner discard | `"owner_message"` |

## Owner discard `superseded_by`

G.3.1 creates no new turn → set `superseded_by=None` on each superseded prior (log reason `owner_message`). Do **not** invent a sentinel id.

## Residuals (out of this PR)

1. Multi-process G.4 — Postgres `SELECT … FOR UPDATE` / advisory lock across workers.
2. G.5 durable message requeue/outbox after lock timeout exhausts retries.
3. Shortening orchestrator full-pipeline lock (zombie guard stays).
4. Doc refresh of `MVP_COMPONENT_DESIGN` begin_turn-only shape (documentador).
