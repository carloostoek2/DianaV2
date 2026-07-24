---
phase: quick
plan: f2-item2-staging-grayzone
type: auto
item: "Fase 2 — Item 2: StagingService, GrayZoneService y PolicyDistiller"
source: SPEC-FASE2.md (sections 5.6, 6.2, 6.3) + Plan_fase2.md (milestones H3-H4)
mode: standard
---

## Objective

Implement 3 isolated building blocks for F2's controlled-learning pipeline: StagingService (save/promote/discard corrections), GrayZoneService (doctrinal query lifecycle + VIP freeze/unfreeze), and PolicyDistiller (text-to-structured-Policy). These are wired into TurnOrchestrator and AdminService in Item 3. Also add the contract prerequisites the blocks need: migration 004 for `frozen_until` on vips, VipStore freeze methods, pure Policy domain model, and `DeliveryContext.is_frozen`.

## Scope

- **In:**
  - Migration `004_vip_frozen_until.py` — add `frozen_until` column to `vips`
  - `VipRecord.frozen_until` field + `VipStore.freeze_vip()` / `VipStore.unfreeze_vip()` methods
  - `SqlVipStore.freeze_vip()` and `SqlVipStore.unfreeze_vip()` implementations
  - Pure Pydantic `Policy` domain model in `cognitive/models.py` (non-ORM, for PolicyDistiller output)
  - `DeliveryContext.is_frozen: bool = False` in `behavior/ports.py`
  - `StagingCandidateRepo` in `infrastructure/db/repositories/staging.py`
  - `GrayZoneQueryRepo` in `infrastructure/db/repositories/gray_zone.py`
  - `StagingService` in `application/staging_service.py` — `save_correction`, `promote_to_example`, `promote_to_policy`, `discard`
  - `PolicyDistiller` in `cognitive/policy_distiller.py` — `distill_from_text`
  - `GrayZoneService` in `application/gray_zone_service.py` — `create_query`, `resolve_with_doctrine`, `freeze_vip`, `unfreeze_vip`, `expire_old_queries`

- **Out / Non-goals (Items 3-4):**
  - Wiring StagingService/GrayZoneService into TurnOrchestrator, AdminService, composition.py
  - Decider `consult_doctrine` action extension
  - Feature flag reading (`SqlSystemConfigStore.get_feature_flags`)
  - FreezeCheck middleware in Telegram layer
  - BehaviorEngine checking `ctx.is_frozen` in `deliver()`
  - Expiration job scheduling (`main.py` background task)
  - Sandbox mode
  - New test files (handled by a later item per Plan_fase2 H11)
  - Modifying existing stub retrievers or registry

- **Constraints:**
  - StagingService and GrayZoneService are in `application/` — they import domain models from `cognitive/` and repos from `infrastructure/`, but NEVER `telegram/` or `behavior/`
  - PolicyDistiller is in `cognitive/` — must NOT import `aiogram`, `behavior/`, `application/`, or `infrastructure/`
  - `Promote_to_policy` writes directly to the `policies` table — add a write method to the existing `PoliciesRepo` from Item 1 (`insert`). Similarly for `promote_to_example` via `ExamplesRepo.insert`.
  - `resolve_with_doctrine` creates a `StagingCandidate` using `StagingCandidateRepo.insert` — it does NOT call `StagingService.promote_to_policy()` (that happens on owner confirmation, Item 3).
  - `freeze_vip` sets `frozen_until` on the vips row; `unfreeze_vip` clears it to NULL. `is_allowed` is NOT changed — freeze is a middleware-level gate, not an auth gate.

## Assumptions

- A1: `vips.frozen_until` is a nullable `DateTime(timezone=True)` column. NULL = not frozen. Any non-NULL value in the future = frozen until that time.
- A2: `StagingService.promote_to_example()` inserts into `examples` and needs `ExamplesRepo.insert()`. Since ExamplesRepo from Item 1 is read-only, we add a simple `insert(payload)` method to it. Same for `PoliciesRepo.insert()`.
- A3: `PolicyDistiller` does NOT need an LLM call — it mechanically structures the owner-provided generalization into the Policy domain model. The generalization IS the structured input; no extraction needed.
- A4: `GrayZoneService.expire_old_queries()` is a synchronous (no LLM) DB update — mark queries as `expired` and optionally escalate. The configurable action is a simple `Literal["escalate", "use_draft"]` param.
- A5: `freeze_vip` takes a `vip_id (UUID)` not `telegram_user_id`. `VipStore` currently identifies by `telegram_user_id` only — we add a `get_by_id(vip_id)` method and the freeze methods by UUID.

## Architecture Approach

### QUE (comportamiento / contratos)

| Comportamiento | Verdad |
|---|---|
| Migration 004 adds `frozen_until` column to `vips` (nullable timestamp) | `alembic upgrade head` succeeds; schema has column |
| `VipStore.freeze_vip(vip_id, frozen_until)` sets the column | Read-back confirms value |
| `VipStore.unfreeze_vip(vip_id)` sets column to NULL | Read-back confirms NULL |
| Pure `Policy` domain model exists in `cognitive/models.py` | PolicyDistiller imports it without touching ORM |
| `DeliveryContext.is_frozen` defaults to `False` | Existing callers unchanged |
| `StagingCandidateRepo` CRUD on `staging_candidates` table | Insert + read + status update all work |
| `GrayZoneQueryRepo` CRUD on `gray_zone_queries` table | Insert + status update + expire all work |
| `StagingService.save_correction` creates a pending `StagingCandidate` with type='example' | DB row created with status='pending' |
| `StagingService.promote_to_example` activates a candidate into `examples` table + marks promoted | DB: example row created, staging status='promoted' |
| `StagingService.promote_to_policy` creates a `Policy` in `policies` table + marks promoted | DB: policy row created, staging status='promoted' |
| `StagingService.discard` sets candidate status='discarded' | DB status changed |
| `GrayZoneService.create_query` creates an open query + freezes VIP | DB: gray_zone_query inserted, vips.frozen_until set |
| `GrayZoneService.resolve_with_doctrine` creates a StagingCandidate (type='policy') + closes query | DB: staging_candidate inserted, query status='resolved', VIP unfrozen |
| `GrayZoneService.freeze_vip` sets frozen_until | Column set |
| `GrayZoneService.unfreeze_vip` clears frozen_until | Column NULL |
| `GrayZoneService.expire_old_queries` marks expired queries + optionally escalates | Status='expired'; conditions met |
| `PolicyDistiller.distill_from_text` returns structured `Policy` | Fields match input |
| No cognitive module imports aiogram/behavior | Existing import purity tests pass |

### COMO (estructura / patrones)

**Capas / modulos:**

```
infrastructure/db/repositories/vips.py       → EDIT: add freeze_vip/unfreeze_vip/get_by_id
infrastructure/db/repositories/staging.py     → CREATE: StagingCandidateRepo
infrastructure/db/repositories/gray_zone.py   → CREATE: GrayZoneQueryRepo
infrastructure/db/repositories/examples.py    → EDIT: add insert() method
infrastructure/db/repositories/policies.py    → EDIT: add insert() method
alembic/versions/004_vip_frozen_until.py      → CREATE: migration
application/ports.py                          → EDIT: VipRecord.frozen_until + VipStore freeze methods
application/staging_service.py                → CREATE: StagingService
application/gray_zone_service.py              → CREATE: GrayZoneService
behavior/ports.py                             → EDIT: DeliveryContext.is_frozen
cognitive/models.py                           → EDIT: add pure Policy domain model
cognitive/policy_distiller.py                 → CREATE: PolicyDistiller
```

**Pattern to copy:**

| Que copiar | Path analogo | Adaptar |
|---|---|---|
| SQL repo pattern | `repositories/history.py::SqlMessageHistoryRepo` | `__init__(session_factory)`, `async with self._sf() as session:`, `session.execute(select(...))` |
| VipStore method | `repositories/vips.py::SqlVipStore.add()` | `freeze_vip`: `UPDATE vips SET frozen_until = :val WHERE id = :vid`; `unfreeze_vip`: same but SET NULL |
| ORM model addition | `models.py::Vip` existing columns | Add `frozen_until` Mapped column (nullable, DateTime(timezone=True)) |
| Migration pattern | `alembic/versions/002_turns_error.py` | `op.add_column("vips", sa.Column("frozen_until", ...))` — single-column add |
| Application service | `application/turn_orchestrator.py` | Constructor with deps, async methods, `logger = logging.getLogger(...)` |
| PolicyDistiller (cognitive module) | `cognitive/embedding.py` | Pure class, no infra imports, `__all__` export |
| Domain model addition | `cognitive/models.py::Comprehension` | Add `Policy` BaseModel with `model_config = ConfigDict(extra="forbid")` |

**Interfaces / tipos nuevos:**

- `StagingCandidateRepo` — `insert(candidate)`, `get_by_id(id)`, `update_status(id, status)`
- `GrayZoneQueryRepo` — `insert(query)`, `get_by_id(id)`, `update_status(id, status, resolved_at)`, `expire_older_than(timeout_hours, action)`, `list_open()`
- `StagingService` — application-level class with 4 methods
- `GrayZoneService` — application-level class with 5 methods
- `PolicyDistiller` — cognitive-level class with 1 method
- `cognitive.models.Policy` — pure Pydantic model (NOT the ORM model)

### Wiring (composition.py changes — NOT YET, but document the future injection points)

Item 2 builds isolated blocks. Item 3 wires them. For reference, the injection points are:
- `StagingService` needs: `StagingCandidateRepo`, `ExamplesRepo` (for promote), `PoliciesRepo` (for promote)
- `GrayZoneService` needs: `GrayZoneQueryRepo`, `VipStore`, `PolicyDistiller`, `StagingCandidateRepo`
- `PolicyDistiller` needs: nothing (standalone)

**Orden de dependencias entre tasks:**

```
Task 1 (prerequisites + SQL repos) ──── Task 2 (StagingService)
                                       └─ Task 3 (PolicyDistiller + GrayZoneService)
                                               ↑ depends on PolicyDistiller
```

### File Map

| Accion | Path | Notas |
|---|---|---|
| CREATE | `alembic/versions/004_vip_frozen_until.py` | Migration |
| CREATE | `src/diana/infrastructure/db/repositories/staging.py` | StagingCandidateRepo |
| CREATE | `src/diana/infrastructure/db/repositories/gray_zone.py` | GrayZoneQueryRepo |
| CREATE | `src/diana/application/staging_service.py` | StagingService |
| CREATE | `src/diana/application/gray_zone_service.py` | GrayZoneService |
| CREATE | `src/diana/cognitive/policy_distiller.py` | PolicyDistiller |
| EDIT | `src/diana/infrastructure/db/models.py` | Add `frozen_until` column to `Vip` ORM model |
| EDIT | `src/diana/infrastructure/db/repositories/vips.py` | Add `get_by_id`, `freeze_vip`, `unfreeze_vip` methods |
| EDIT | `src/diana/infrastructure/db/repositories/examples.py` | Add `insert()` method for promote_to_example |
| EDIT | `src/diana/infrastructure/db/repositories/policies.py` | Add `insert()` method for promote_to_policy |
| EDIT | `src/diana/application/ports.py` | `VipRecord.frozen_until` + `VipStore.freeze_vip`/`unfreeze_vip` |
| EDIT | `src/diana/behavior/ports.py` | `DeliveryContext.is_frozen` |
| EDIT | `src/diana/cognitive/models.py` | Add pure `Policy` domain model |
| NO-TOUCH | `src/diana/cognitive/retrievers/` | No retriever changes |
| NO-TOUCH | `src/diana/cognitive/director.py` | No pipeline changes |
| NO-TOUCH | `src/diana/cognitive/decider.py` | No decision changes |
| NO-TOUCH | `src/diana/composition.py` | Wiring is Item 3 |
| NO-TOUCH | `src/diana/application/admin_service.py` | Wire gray zone message handling is Item 3 |
| NO-TOUCH | `src/diana/application/turn_orchestrator.py` | Wire consult_doctrine branch is Item 3 |

## Context

Archivos relevantes:

- `docs/SPEC-FASE2.md` — sections 5.6 (service contracts), 6.2 (gray zone flow), 6.3 (correction flow)
- `docs/Plan_fase2.md` — milestones H3-H4, file list
- `AGENTS.md` — module boundaries (sections 3-4), post-turn learning rule (5.6), staging rules (6.4)
- `src/diana/infrastructure/db/models.py` — Vip ORM model (add frozen_until), existing F2 ORM models
- `src/diana/infrastructure/db/repositories/vips.py` — SqlVipStore (add freeze/unfreeze methods)
- `src/diana/infrastructure/db/repositories/history.py` — SQL repo pattern
- `src/diana/application/ports.py` — VipRecord + VipStore protocol
- `src/diana/behavior/ports.py` — DeliveryContext model
- `src/diana/cognitive/models.py` — existing domain models (add pure Policy)
- `src/diana/cognitive/embedding.py` — cognitive module pattern (PolicyDistiller follows this)
- `alembic/versions/002_turns_error.py` — minimal single-column migration pattern
- `alembic/versions/003_f2_knowledge_tables.py` — down_revision target

## Tasks

### Task 1: Contract prerequisites + SQL repos (migration, VipStore freeze, Policy model, DeliveryContext, staging/gray-zone repos)

**type:** auto
**Objective:** All plumbing changes needed by services — migration 004, VipStore freeze methods, pure Policy domain model, DeliveryContext.is_frozen, StagingCandidateRepo, GrayZoneQueryRepo, write methods on ExamplesRepo/PoliciesRepo.

**Files:**
- CREATE `alembic/versions/004_vip_frozen_until.py`
- EDIT `src/diana/infrastructure/db/models.py` (add frozen_until to Vip ORM)
- EDIT `src/diana/application/ports.py` (VipRecord + VipStore protocol)
- EDIT `src/diana/infrastructure/db/repositories/vips.py` (SqlVipStore methods)
- EDIT `src/diana/cognitive/models.py` (pure Policy domain model)
- EDIT `src/diana/behavior/ports.py` (DeliveryContext.is_frozen)
- CREATE `src/diana/infrastructure/db/repositories/staging.py`
- CREATE `src/diana/infrastructure/db/repositories/gray_zone.py`
- EDIT `src/diana/infrastructure/db/repositories/examples.py` (add insert)
- EDIT `src/diana/infrastructure/db/repositories/policies.py` (add insert)

**Action:**

**1a. Migration `004_vip_frozen_until.py`** — Follow `002_turns_error.py` pattern exactly:
- `revision = "004_vip_frozen_until"`, `down_revision = "003_f2_knowledge_tables"`
- `upgrade()`: `op.add_column("vips", sa.Column("frozen_until", sa.DateTime(timezone=True), nullable=True))`
- `downgrade()`: `op.drop_column("vips", "frozen_until")`

**1b. `models.py`** — Add `frozen_until` column to `Vip` class, after `paused_until`:
```python
frozen_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

**1c. `application/ports.py`:**

`VipRecord` — add field after `paused_until`:
```python
frozen_until: datetime | None = None
```

`VipStore` protocol — add 3 new methods after `deactivate`:
```python
async def get_by_id(self, vip_id: UUID) -> VipRecord | None: ...
async def freeze_vip(self, vip_id: UUID, frozen_until: datetime) -> None: ...
async def unfreeze_vip(self, vip_id: UUID) -> None: ...
```

**1d. `repositories/vips.py`** — Add 3 methods to `SqlVipStore`:

`get_by_id(vip_id: UUID) -> VipRecord | None`:
```python
async def get_by_id(self, vip_id: UUID) -> VipRecord | None:
    async with self._sf() as session:
        result = await session.execute(select(Vip).where(Vip.id == vip_id))
        row = result.scalar_one_or_none()
        return vip_orm_to_record(row) if row else None
```

`freeze_vip(vip_id: UUID, frozen_until: datetime) -> None`:
```python
async def freeze_vip(self, vip_id: UUID, frozen_until: datetime) -> None:
    async with self._sf() as session:
        result = await session.execute(select(Vip).where(Vip.id == vip_id))
        row = result.scalar_one_or_none()
        if row is None:
            raise ValueError(f"VIP {vip_id} not found")
        row.frozen_until = frozen_until
        await session.commit()
```

`unfreeze_vip(vip_id: UUID) -> None`:
```python
async def unfreeze_vip(self, vip_id: UUID) -> None:
    async with self._sf() as session:
        result = await session.execute(select(Vip).where(Vip.id == vip_id))
        row = result.scalar_one_or_none()
        if row is None:
            raise ValueError(f"VIP {vip_id} not found")
        row.frozen_until = None
        await session.commit()
```

Also update `vip_orm_to_record` to include `frozen_until`:
```python
return VipRecord(
    id=row.id,
    telegram_user_id=row.telegram_user_id,
    display_name=row.display_name,
    is_active=bool(row.is_active),
    paused_until=row.paused_until,
    frozen_until=row.frozen_until,
)
```

**1e. `cognitive/models.py`** — Add pure `Policy` domain model (before Decision class, or at end of file before `__all__`):
```python
class Policy(BaseModel):
    """Pure domain model for a distilled business policy (non-ORM).

    Used by PolicyDistiller (cognitive/) and StagingService (application/)
    as a shared data contract. NOT the same as db/models.Policy (ORM).
    """

    model_config = ConfigDict(extra="forbid")

    trigger_description: str
    rule: str
    scope: str = "all"
    is_active: bool = True
    source_query_id: UUID | None = None
    created_at: datetime | None = None
    id: UUID | None = None
```

Add `"Policy"` to `__all__`.

**1f. `behavior/ports.py`** — Add `is_frozen` field to `DeliveryContext`:
```python
is_frozen: bool = False
```
Place it after `telegram_message_id`. Set `False` default so existing callers are unaffected.

**1g. `repositories/staging.py`** — `StagingCandidateRepo`:

Follow the `history.py` repo pattern exactly. Three methods:

- `insert(candidate_type: str, payload: dict, turn_id: UUID) -> StagingCandidate` — creates a row with `status='pending'`, returns the ORM object. Uses the ORM `StagingCandidate` model from `diana.infrastructure.db.models`.
  ```python
  async def insert(self, candidate_type: str, payload: dict, turn_id: UUID) -> StagingCandidate:
      async with self._sf() as session:
          row = StagingCandidate(
              candidate_type=candidate_type,
              payload=payload,
              status="pending",
              turn_id=turn_id,
          )
          session.add(row)
          await session.commit()
          await session.refresh(row)
          return row
  ```

- `get_by_id(candidate_id: UUID) -> StagingCandidate | None` — `session.get(StagingCandidate, candidate_id)`.

- `update_status(candidate_id: UUID, status: str) -> bool` — sets `status` column, commits. Returns False if not found.

**1h. `repositories/gray_zone.py`** — `GrayZoneQueryRepo`:

- `insert(vip_id: UUID | None, turn_id: UUID, question: str, draft: str, freeze_until: datetime | None = None) -> GrayZoneQuery` — creates row with `status='open'`. Returns ORM object.
  ```python
  async def insert(self, vip_id, turn_id, question, draft, freeze_until=None) -> GrayZoneQuery:
      async with self._sf() as session:
          row = GrayZoneQuery(
              vip_id=vip_id,
              turn_id=turn_id,
              question=question,
              draft=draft,
              status="open",
              freeze_until=freeze_until,
          )
          session.add(row)
          await session.commit()
          await session.refresh(row)
          return row
  ```

- `get_by_id(query_id: UUID) -> GrayZoneQuery | None` — session.get.

- `update_status(query_id: UUID, status: str, resolved_at: datetime | None = None) -> bool` — sets status and optionally resolved_at. Returns False if not found.

- `expire_older_than(timeout_hours: int, action: str = "escalate") -> list[GrayZoneQuery]`:
  ```python
  async def expire_older_than(self, timeout_hours: int) -> list[GrayZoneQuery]:
      """Mark open queries older than timeout_hours as expired. Returns expired rows."""
      async with self._sf() as session:
          cutoff = func.now() - text(f"interval '{timeout_hours} hours'")
          result = await session.execute(
              select(GrayZoneQuery)
              .where(
                  GrayZoneQuery.status == "open",
                  GrayZoneQuery.created_at < cutoff,
              )
          )
          rows = list(result.scalars().all())
          for row in rows:
              row.status = "expired"
              row.resolved_at = func.now()
          await session.commit()
          return rows
  ```

- `list_open() -> list[GrayZoneQuery]` — `session.execute(select(GrayZoneQuery).where(GrayZoneQuery.status == 'open'))`.

**1i. `repositories/examples.py`** — Add `insert` method to `ExamplesRepo`:

```python
async def insert(self, *, turn_text: str, draft_text: str, corrected_text: str,
                 context: dict, is_counter_example: bool = False,
                 embedding: list[float] | None = None) -> Example:
    async with self._sf() as session:
        row = Example(
            embedding=embedding or [0.0] * 384,
            turn_text=turn_text,
            draft_text=draft_text,
            corrected_text=corrected_text,
            context=context,
            is_counter_example=is_counter_example,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row
```

**1j. `repositories/policies.py`** — Add `insert` method to `PoliciesRepo`:

```python
async def insert(self, *, trigger_description: str, rule: str, scope: str = "all",
                 is_active: bool = True, source_query_id: UUID | None = None,
                 embedding: list[float] | None = None) -> Policy:
    async with self._sf() as session:
        row = Policy(
            embedding=embedding or [0.0] * 384,
            trigger_description=trigger_description,
            rule=rule,
            scope=scope,
            is_active=is_active,
            source_query_id=source_query_id,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row
```

**Verification:**
```bash
alembic upgrade head
python -c "from diana.infrastructure.db.repositories.staging import StagingCandidateRepo; from diana.infrastructure.db.repositories.gray_zone import GrayZoneQueryRepo; print('OK')"
python -c "from diana.cognitive.models import Policy; assert Policy(trigger_description='x', rule='y'); print('OK')"
python -c "from diana.behavior.ports import DeliveryContext; assert DeliveryContext(chat_id=1, business_connection_id='x').is_frozen == False; print('OK')"
```

**Done:**
- [ ] `alembic upgrade head` succeeds (migration 004 adds frozen_until to vips)
- [ ] `Vip` ORM model has `frozen_until` column
- [ ] `VipRecord` has `frozen_until` field
- [ ] `VipStore` protocol has `freeze_vip`/`unfreeze_vip`/`get_by_id`  (ABC compliance enforced by runtime_checkable)
- [ ] `SqlVipStore` has all 3 new methods; raises ValueError on missing VIP
- [ ] `cognitive.models.Policy` exists as pure Pydantic model (no ORM dependency)
- [ ] `DeliveryContext.is_frozen` defaults to `False`
- [ ] `StagingCandidateRepo` with insert/get_by_id/update_status imports cleanly
- [ ] `GrayZoneQueryRepo` with insert/get_by_id/update_status/expire_older_than/list_open imports cleanly
- [ ] `ExamplesRepo.insert()` exists
- [ ] `PoliciesRepo.insert()` exists

---

### Task 2: StagingService + PolicyDistiller

**type:** auto
**Objective:** Full `StagingService` (save, promote, discard) and `PolicyDistiller` (free-text to structured Policy).

**Files:**
- CREATE `src/diana/application/staging_service.py`
- CREATE `src/diana/cognitive/policy_distiller.py`

**Action:**

**2a. `application/staging_service.py`** — `StagingService` class.

Constructor takes all deps:
```python
from __future__ import annotations

import logging
from uuid import UUID

from diana.application.ports import VipStore  # not needed directly, but for future wiring
from diana.cognitive.models import Policy as PolicyDomain
from diana.infrastructure.db.repositories.staging import StagingCandidateRepo
from diana.infrastructure.db.repositories.examples import ExamplesRepo
from diana.infrastructure.db.repositories.policies import PoliciesRepo

logger = logging.getLogger("diana.application")


class StagingService:
    """Captures corrections and promotes them to examples or policies.

    Every new policy (gray zone or manual) must go through promote_to_policy().
    """

    def __init__(
        self,
        *,
        staging_repo: StagingCandidateRepo,
        examples_repo: ExamplesRepo,
        policies_repo: PoliciesRepo,
    ) -> None:
        self._staging = staging_repo
        self._examples = examples_repo
        self._policies = policies_repo

    async def save_correction(
        self,
        turn_id: UUID,
        original_draft: str,
        corrected_text: str,
        context: dict,
    ) -> object:
        """Save a correction as a pending staging candidate (type='example').

        The owner must later confirm promotion for this to become a live example.
        Returns the ORM StagingCandidate row (id, type, payload, status, turn_id).
        """
        payload = {
            "original_draft": original_draft,
            "corrected_text": corrected_text,
            "context": context,
        }
        row = await self._staging.insert("example", payload, turn_id)
        logger.info(
            "correction_saved",
            extra={
                "turn_id": str(turn_id),
                "candidate_id": str(row.id),
            },
        )
        return row

    async def promote_to_example(
        self,
        candidate_id: UUID,
    ) -> object:
        """Promote a staging candidate to a live example in the examples table.

        Returns the ORM Example row.
        """
        candidate = await self._staging.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"StagingCandidate {candidate_id} not found")
        if candidate.status != "pending":
            raise ValueError(f"StagingCandidate {candidate_id} status is {candidate.status!r}, expected 'pending'")

        payload = candidate.payload
        example = await self._examples.insert(
            turn_text=payload.get("context", {}).get("turn_text", ""),
            draft_text=payload.get("original_draft", ""),
            corrected_text=payload.get("corrected_text", ""),
            context=payload.get("context", {}),
            is_counter_example=False,
        )
        await self._staging.update_status(candidate_id, "promoted")
        logger.info(
            "example_promoted",
            extra={
                "candidate_id": str(candidate_id),
                "example_id": str(example.id),
            },
        )
        return example

    async def promote_to_policy(
        self,
        candidate_id: UUID,
        trigger: str,
        rule: str,
        scope: str = "all",
    ) -> PolicyDomain:
        """Promote a staging candidate to a live policy.

        Returns the domain Policy model (not ORM).
        """
        candidate = await self._staging.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"StagingCandidate {candidate_id} not found")
        if candidate.status != "pending":
            raise ValueError(f"StagingCandidate {candidate_id} status is {candidate.status!r}, expected 'pending'")

        orm_policy = await self._policies.insert(
            trigger_description=trigger,
            rule=rule,
            scope=scope,
            is_active=True,
            source_query_id=candidate.payload.get("query_id"),
        )
        await self._staging.update_status(candidate_id, "promoted")
        logger.info(
            "policy_promoted",
            extra={
                "candidate_id": str(candidate_id),
                "policy_id": str(orm_policy.id),
            },
        )
        return PolicyDomain(
            id=orm_policy.id,
            trigger_description=orm_policy.trigger_description,
            rule=orm_policy.rule,
            scope=orm_policy.scope,
            is_active=orm_policy.is_active,
            source_query_id=orm_policy.source_query_id,
            created_at=orm_policy.created_at,
        )

    async def discard(self, candidate_id: UUID) -> None:
        """Mark a staging candidate as discarded (no promotion)."""
        updated = await self._staging.update_status(candidate_id, "discarded")
        if not updated:
            raise ValueError(f"StagingCandidate {candidate_id} not found")
        logger.info(
            "candidate_discarded",
            extra={"candidate_id": str(candidate_id)},
        )


__all__ = ["StagingService"]
```

Key design decisions:
- Returns domain `Policy` from `promote_to_policy`, not ORM row. Maps via `PolicyDomain(id=..., ...)`.
- `promote_to_example` returns the ORM row (no domain model for examples exists yet; callers use it as a data bag).
- Both promote methods validate `status == 'pending'` to prevent double-promotion.
- `discard` raises ValueError if candidate not found.

**2b. `cognitive/policy_distiller.py`** — `PolicyDistiller` class.

```python
"""PolicyDistiller — structures free text into a pure Policy domain model.

Lives in cognitive/ because it produces a cognitive-domain artifact (Policy).
No LLM dependency: the owner's generalization IS the structured input.
"""

from __future__ import annotations

from diana.cognitive.models import Policy

__all__ = ["PolicyDistiller"]


class PolicyDistiller:
    """Distills free-text doctrinal guidance into a structured Policy object.

    The owner provides three inputs:
    - question: the gray zone question (what the VIP asked)
    - answer: the owner's answer to the VIP
    - generalization: the owner's stated generalization/rule

    This is purely mechanical — the generalization provides the structure.
    """

    async def distill_from_text(
        self,
        question: str,
        answer: str,
        generalization: str,
    ) -> Policy:
        """Create a structured Policy from owner-provided text.

        Args:
            question: The original gray zone question (VIP's message).
            answer: The owner's crafted answer.
            generalization: The owner's stated rule (e.g. "Always offer 10% for 3+ units").

        Returns:
            A pure domain Policy with trigger_description derived from the
            generalization, and example_applied showing the concrete case.
        """
        # Mechanical extraction: generalization IS the rule; question provides trigger context.
        # If the owner provides a multi-line generalization, the first line is trigger,
        # remaining lines are rule. Otherwise use question as trigger and generalization as rule.
        lines = generalization.strip().split("\n", 1)
        trigger_candidate = lines[0].strip()
        rule_candidate = lines[1].strip() if len(lines) > 1 else generalization.strip()

        return Policy(
            trigger_description=trigger_candidate,
            rule=rule_candidate,
            scope="all",
            is_active=True,
            source_query_id=None,
        )


__all__ = ["PolicyDistiller"]
```

Design notes:
- Purely mechanical — no LLM call. The generalization already IS the structured output. Splitting generalization into trigger/rule is a reasonable heuristic for MVP. An LLM-powered version can follow later.
- No imports from `application/`, `behavior/`, or `infrastructure/` — passes import purity for cognitive/.
- Returns `cognitive.models.Policy` (domain model).

**Verification:**
```bash
python -c "from diana.application.staging_service import StagingService; print('OK')"
python -c "from diana.cognitive.policy_distiller import PolicyDistiller; pd = PolicyDistiller(); import asyncio; p = asyncio.run(pd.distill_from_text('VIP asks for 3', 'Sure 10% off', 'Always offer 10% for 3+')); assert p.trigger_description == 'Always offer 10% for 3+'; print('OK')"
```

**Done:**
- [ ] `StagingService` imports cleanly (no aiogram, no behavior imports)
- [ ] `StagingService.save_correction()` creates a StagingCandidate with type='example', status='pending'
- [ ] `StagingService.promote_to_example()` inserts into examples, updates staging to 'promoted', raises on not-found or wrong status
- [ ] `StagingService.promote_to_policy()` inserts into policies, returns domain Policy, raises on not-found or wrong status
- [ ] `StagingService.discard()` sets staging to 'discarded', raises on not-found
- [ ] `PolicyDistiller.distill_from_text()` returns `cognitive.models.Policy` with fields filled
- [ ] `PolicyDistiller` imports nothing from outside `cognitive/` (import purity check)

---

### Task 3: GrayZoneService

**type:** auto
**Objective:** Full `GrayZoneService` — query lifecycle (create, resolve with doctrine, freeze/unfreeze VIP, expire old queries).

**Files:**
- CREATE `src/diana/application/gray_zone_service.py`

**Action:**

**3a. `application/gray_zone_service.py`** — `GrayZoneService` class.

```python
"""GrayZoneService — doctrinal query lifecycle and VIP freeze management.

Flows (from SPEC-FASE2 6.2):
1. create_query → insert gray_zone_query (open) + freeze VIP
2. resolve_with_doctrine → create StagingCandidate (type='policy') + close query + unfreeze VIP
3. freeze_vip / unfreeze_vip — direct VIP freeze control
4. expire_old_queries — marks open queries past timeout as expired
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from diana.application.ports import VipStore
from diana.cognitive.policy_distiller import PolicyDistiller
from diana.infrastructure.db.repositories.gray_zone import GrayZoneQueryRepo
from diana.infrastructure.db.repositories.staging import StagingCandidateRepo

logger = logging.getLogger("diana.application")


class GrayZoneService:
    """Manages the gray zone query lifecycle and VIP freezing.

    Injectable deps: GrayZoneQueryRepo (DB), VipStore (freeze VIPs),
    StagingCandidateRepo (create pending policy candidates),
    PolicyDistiller (structure doctrine text).
    """

    def __init__(
        self,
        *,
        query_repo: GrayZoneQueryRepo,
        vip_store: VipStore,
        staging_repo: StagingCandidateRepo,
        distiller: PolicyDistiller,
        default_timeout_hours: int = 24,
    ) -> None:
        self._queries = query_repo
        self._vips = vip_store
        self._staging = staging_repo
        self._distiller = distiller
        self._default_timeout = default_timeout_hours

    async def create_query(
        self,
        vip_id: UUID,
        turn_id: UUID,
        question: str,
        draft: str,
        *,
        freeze_duration_hours: int | None = None,
    ) -> object:
        """Create an open gray zone query and freeze the VIP.

        The VIP remains frozen until the query is resolved or expired.
        Returns the ORM GrayZoneQuery row.
        """
        duration = freeze_duration_hours or self._default_timeout
        frozen_until = datetime.now(UTC) + timedelta(hours=duration)

        row = await self._queries.insert(
            vip_id=vip_id,
            turn_id=turn_id,
            question=question,
            draft=draft,
            freeze_until=frozen_until,
        )
        await self._vips.freeze_vip(vip_id, frozen_until)

        logger.info(
            "gray_zone_query_created",
            extra={
                "query_id": str(row.id),
                "vip_id": str(vip_id),
                "turn_id": str(turn_id),
                "frozen_until": frozen_until.isoformat(),
            },
        )
        return row

    async def resolve_with_doctrine(
        self,
        query_id: UUID,
        generalization: str,
        rule: str,
    ) -> object:
        """Resolve a gray zone query with owner-provided doctrine.

        Creates a StagingCandidate (type='policy') with the distilled policy
        as payload. The candidate must be confirmed by the owner to become
        active (StagingService.promote_to_policy in Item 3).

        Does NOT close the query or unfreeze here — that happens on
        confirmation (Item 3). Returns the StagingCandidate row.
        """
        query = await self._queries.get_by_id(query_id)
        if query is None:
            raise ValueError(f"GrayZoneQuery {query_id} not found")
        if query.status != "open":
            raise ValueError(f"GrayZoneQuery {query_id} status is {query.status!r}, expected 'open'")

        payload = {
            "question": query.question,
            "draft": query.draft,
            "generalization": generalization,
            "rule": rule,
            "query_id": str(query_id),
        }
        candidate = await self._staging.insert("policy", payload, query.turn_id)

        logger.info(
            "gray_zone_resolved_with_doctrine",
            extra={
                "query_id": str(query_id),
                "candidate_id": str(candidate.id),
            },
        )
        return candidate

    async def confirm_and_apply(
        self,
        query_id: UUID,
        candidate_id: UUID,
    ) -> object:
        """Close a gray zone query and unfreeze VIP after policy confirmation.

        This is called AFTER StagingService.promote_to_policy succeeds (Item 3).
        Included here for completeness so the service owns the full lifecycle.
        Returns the updated GrayZoneQuery row.
        """
        now = datetime.now(UTC)
        await self._queries.update_status(query_id, "resolved", resolved_at=now)
        query = await self._queries.get_by_id(query_id)
        if query is None:
            raise ValueError(f"GrayZoneQuery {query_id} disappeared after update")

        if query.vip_id is not None:
            await self._vips.unfreeze_vip(query.vip_id)

        logger.info(
            "gray_zone_query_closed",
            extra={
                "query_id": str(query_id),
                "vip_id": str(query.vip_id),
            },
        )
        return query

    async def discard_and_close(self, query_id: UUID) -> object:
        """Close a gray zone query without a policy (owner said no).

        Unfreezes the VIP and marks the query as resolved with no policy.
        """
        now = datetime.now(UTC)
        query = await self._queries.get_by_id(query_id)
        if query is not None and query.vip_id is not None:
            await self._vips.unfreeze_vip(query.vip_id)

        await self._queries.update_status(query_id, "resolved", resolved_at=now)

        logger.info(
            "gray_zone_query_discarded",
            extra={"query_id": str(query_id)},
        )
        return await self._queries.get_by_id(query_id)

    async def freeze_vip(self, vip_id: UUID, duration_hours: int | None = None) -> None:
        """Freeze a VIP for a given duration (or default timeout)."""
        duration = duration_hours or self._default_timeout
        frozen_until = datetime.now(UTC) + timedelta(hours=duration)
        await self._vips.freeze_vip(vip_id, frozen_until)
        logger.info(
            "vip_frozen",
            extra={
                "vip_id": str(vip_id),
                "frozen_until": frozen_until.isoformat(),
            },
        )

    async def unfreeze_vip(self, vip_id: UUID) -> None:
        """Unfreeze a VIP (clear frozen_until)."""
        await self._vips.unfreeze_vip(vip_id)
        logger.info("vip_unfrozen", extra={"vip_id": str(vip_id)})

    async def expire_old_queries(
        self,
        timeout_hours: int | None = None,
    ) -> list[object]:
        """Mark open queries older than timeout_hours as expired.

        Returns the list of expired GrayZoneQuery rows.
        Unfreezes VIPs for expired queries.
        Returns an empty list if no queries are expired.
        """
        timeout = timeout_hours or self._default_timeout
        expired = await self._queries.expire_older_than(timeout)

        for row in expired:
            if row.vip_id is not None:
                await self._vips.unfreeze_vip(row.vip_id)
            logger.info(
                "gray_zone_query_expired",
                extra={
                    "query_id": str(row.id),
                    "vip_id": str(row.vip_id),
                    "action": "escalate",  # default action; configurable in Item 3
                },
            )

        return expired


__all__ = ["GrayZoneService"]
```

Key design decisions:
- `resolve_with_doctrine` creates a StagingCandidate only. It does NOT close the query or unfreeze — those happen on `confirm_and_apply` or `discard_and_close` (called from Item 3's AdminService wiring).
- `confirm_and_apply` is defined here even though it's wired in Item 3 — it keeps the lifecycle methods co-located.
- `discard_and_close` handles the "no promotion" case from the flow diagram (6.2: "SI NO confirma").
- `expire_old_queries` unfreezes VIPs for each expired query and returns the list for caller notification (Item 3 admin notification).
- `VipStore` is injected as the protocol, not concrete class — testable with InMemoryVipStore.
- `PolicyDistiller` is injected but not used in `resolve_with_doctrine` currently — the owner provides the generalization and rule directly. The distiller is kept as a dep for future enhancement.

**Verification:**
```bash
python -c "from diana.application.gray_zone_service import GrayZoneService; print('OK')"
python -c "from diana.application.gray_zone_service import GrayZoneService; import inspect; src = inspect.getsource(GrayZoneService); assert 'freeze_vip' in src; assert 'unfreeze_vip' in src; assert 'expire_old_queries' in src; assert 'create_query' in src; assert 'resolve_with_doctrine' in src; print('OK')"
```

**Done:**
- [ ] `GrayZoneService` imports cleanly (no aiogram, no behavior imports beyond ports)
- [ ] All 6 methods exist: `create_query`, `resolve_with_doctrine`, `confirm_and_apply`, `discard_and_close`, `freeze_vip`, `unfreeze_vip`, `expire_old_queries`
- [ ] `create_query` inserts gray_zone_query (open) + calls VipStore.freeze_vip
- [ ] `resolve_with_doctrine` inserts StagingCandidate (type='policy'), does NOT close query
- [ ] `confirm_and_apply` closes query (resolved) + unfreezes VIP
- [ ] `discard_and_close` closes query without policy + unfreezes VIP
- [ ] `expire_old_queries` marks expired + unfreezes VIPs + returns expired rows
- [ ] `freeze_vip` / `unfreeze_vip` delegate to VipStore
- [ ] All methods validate state preconditions and raise ValueError with descriptive messages

## Instrucciones para gsd-executor

### Patrones a copiar (paths)

1. **SQL Repo pattern**: `src/diana/infrastructure/db/repositories/history.py::SqlMessageHistoryRepo` — `__init__(session_factory)`, `async with self._sf() as session:`, `session.execute(select(...))`, `session.add(row)` + `commit` + `refresh` for inserts.

2. **VipStore method pattern**: `src/diana/infrastructure/db/repositories/vips.py::SqlVipStore.add()` — select row, mutate, commit pattern.

3. **Migration pattern** (single column add): `alembic/versions/002_turns_error.py` — `op.add_column("table", sa.Column(...))` in upgrade, `op.drop_column(...)` in downgrade.

4. **Application service pattern**: `src/diana/application/turn_orchestrator.py` — `__init__` with keyword deps, async methods, `logger = logging.getLogger("diana.application")`.

5. **Domain model pattern**: `src/diana/cognitive/models.py::Comprehension` — `model_config = ConfigDict(extra="forbid")`, Pydantic BaseModel.

6. **Cognitive module pattern**: `src/diana/cognitive/embedding.py` — no imports from `application/`, `behavior/`, `telegram/` or `infrastructure/`. Pure domain logic.

### Anti-patterns prohibidos

- **Do NOT** import `aiogram` or `diana.behavior` anywhere in `diana.cognitive` — import purity test enforces this.
- **Do NOT** import `diana.cognitive` from `diana.infrastructure` — dependency direction must be outward-to-inward.
- **Do NOT** add wiring to `composition.py` — that's Item 3.
- **Do NOT** modify `TurnOrchestrator`, `AdminService`, `Decider`, or `Director` — that's Item 3.
- **Do NOT** create new test files (handled by H11 in Plan_fase2).
- **Do NOT** modify the `__all__` of existing cognitive modules unless adding exports.
- **Do NOT** modify `VipStore.is_allowed` to check `frozen_until` — freeze is middleware-level, not auth.
- **Do NOT** add LLM calls to PolicyDistiller — it's mechanical for MVP (can be upgraded later).

### Logging / errores / convenciones del proyecto

- Use `logger = logging.getLogger("diana.application")` for application/ modules, `logging.getLogger("diana.cognitive")` for cognitive/ modules.
- Error handling: raise `ValueError` with descriptive messages for precondition failures (not-found, wrong status).
- No `print()` statements anywhere.
- Use `from __future__ import annotations` in every file.
- All async methods: use `async/await`, never `asyncio.run()` in production code.
- Type annotations: use `UUID` for IDs, `datetime` for timestamps, `dict` for JSON payloads.

### Commits

Each task is a work unit = one behaviorally verifiable step. Commit after each task passes its verification.

### Mock policy (tests)

The services accept protocol abstractions (`VipStore`, repos via their class types). Tests can:
- Use `InMemoryVipStore` (if exists) or `unittest.mock.AsyncMock` for VipStore
- Use `async_sessionmaker` with a test DB or mock for repos

No test files are created in this item.

## Test commands

```bash
# Migration
alembic upgrade head

# Import checks
python -c "from diana.infrastructure.db.repositories.staging import StagingCandidateRepo; from diana.infrastructure.db.repositories.gray_zone import GrayZoneQueryRepo; print('repos OK')"
python -c "from diana.cognitive.models import Policy; assert Policy(trigger_description='x', rule='y'); print('domain Policy OK')"
python -c "from diana.cognitive.policy_distiller import PolicyDistiller; import asyncio; p = asyncio.run(PolicyDistiller().distill_from_text('q', 'a', 'Always do X')); assert p.rule == 'Always do X'; print('PolicyDistiller OK')"
python -c "from diana.application.staging_service import StagingService; print('StagingService OK')"
python -c "from diana.application.gray_zone_service import GrayZoneService; print('GrayZoneService OK')"
python -c "from diana.behavior.ports import DeliveryContext; ctx = DeliveryContext(chat_id=1, business_connection_id='x'); assert ctx.is_frozen == False; print('DeliveryContext OK')"

# Existing test suite (must pass unchanged)
pytest tests/unit/infrastructure/test_f1_schema_metadata.py -x
pytest tests/unit/cognitive/test_import_purity.py -x
pytest tests/unit/cognitive/test_retrievers.py -x

# Full suite
pytest tests/ -x
```

## Riesgos + Mitigacion

| Riesgo | Impacto | Mitigacion |
|---|---|---|
| `StagingService.promote_to_policy` needs `PoliciesRepo.insert()` which didn't exist in Item 1 | Task 1 fails | Explicitly added in Task 1i: add insert method to PoliciesRepo. Same for ExamplesRepo. |
| `GrayZoneService.resolve_with_doctrine` creates StagingCandidate but doesn't close query | Owner confusion if query stays open | By design: the query stays open until owner confirms (Item 3). `confirm_and_apply` closes it. Documented in contract. |
| `expire_old_queries` uses `func.now()` with `text()` interval — SQL injection risk | Low: timeout_hours is an int parameter | The interval is a raw SQL string but `timeout_hours` is validated as int. Acceptable for MVP; use parameterized query in F3. |
| GrayZoneService calls `VipStore.freeze_vip` but VipStore protocol currently only has `telegram_user_id` methods | `freeze_vip` takes `vip_id` (UUID) | Mitigated by adding `get_by_id` to VipStore alongside the freeze methods. The lookup by UUID is independent of existing methods. |
| Cognitive import purity test fails if PolicyDistiller accidentally imports something from application/ | Test suite breaks | PolicyDistiller only imports from `cognitive/models.py`. Enforced by verification import check. |
| `confirm_and_apply` and `discard_and_close` are defined but not called in Item 2 | Dead code warnings | These are intentional lifecycle methods. They'll be wired in Item 3's AdminService. Mark with `# noqa` or accept the linter note. |

## Success Criteria

- [ ] `alembic upgrade head` succeeds (migration 004 adds `frozen_until` to vips)
- [ ] All 6 new files exist and import cleanly (2 repos + 2 services + PolicyDistiller + migration)
- [ ] `cognitive.models.Policy` is a pure Pydantic model importable without ORM dependencies
- [ ] `DeliveryContext.is_frozen` defaults to `False` — no existing callers broken
- [ ] `VipStore` protocol and `SqlVipStore` have freeze/unfreeze/get_by_id methods
- [ ] `StagingCandidateRepo` with insert/get_by_id/update_status works
- [ ] `GrayZoneQueryRepo` with insert/get_by_id/update_status/expire_older_than works
- [ ] `StagingService` with 4 methods exists and validates preconditions
- [ ] `GrayZoneService` with 6 methods exists and validates preconditions
- [ ] `PolicyDistiller` with `distill_from_text` returns structured Policy
- [ ] `pytest tests/ -x` passes with zero modifications to existing tests
- [ ] No cognitive module imports `aiogram` or `behavior` (import purity test passes)
