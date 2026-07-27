---
phase: quick
plan: sandbox-real-delivery
type: auto
item: sandbox-real-delivery
source: clarify
mode: standard
---

## Objective

When a sandbox session is active, **delivery uses the configured `delivery_mode`** (`settings.global_mode` composition wiring: supervised | autonomous | fake_delivery) so the owner gets **real Telegram E2E** for that chat. Sandbox must **stop forcing** `DeliveryContext.mode="fake_delivery"`. Product isolation stays: `should_persist` skips learning/staging; doctrine demote without `vip_id` stays; recontact skip stays; global `fake_delivery` ops mode remains valid.

## Scope

- **In:**
  - `TurnOrchestrator._effective_delivery_mode` — remove sandbox → fake override
  - `AdminService._effective_delivery_mode` — same
  - Invert/rename the two unit tests that assert forced fake under sandbox
  - Optional coverage: sandbox + configured `fake_delivery` still yields fake (ops mode)
  - Optional log polish: rename `sandbox_fake_delivery` event (misleading after change)
  - Docs: `README.md` + `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md` delivery isolation wording

- **Out / Non-goals (locked D5–D7):**
  - Do **not** change `SandboxService.should_persist` or learning/staging gates
  - Do **not** remove `sandbox_no_vip_doctrine` demote
  - Do **not** change recontact sandbox skip / composition `_is_sandbox_vip`
  - Do **not** remove BehaviorEngine fake path or `global_mode=fake_delivery`
  - Multi-replica session store, new fixture profiles, gray-zone without vip_id
  - Zero operational DB writes (turns/deliveries allowed)
  - Changes to real VIP profiles / `profile_content` real paths
  - Soft warn on activate when chat is allowlisted VIP (deferred)

- **Constraints:**
  - Application layer only (orch + admin helpers + tests + docs)
  - Feature flag `FEATURE_SANDBOX_ENABLED` unchanged
  - Strict TDD: failing tests first, then production change
  - AGENTS.md: Behavior outside cognition; learning only post-turn; Director deterministic

## Assumptions

- A1: Effective rule after change is `mode_effective = self._delivery_mode` always; sandbox session does **not** participate in mode selection (CLARIFY + impact).
- A2: Composition already injects `delivery_mode=settings.global_mode` into orch/admin; no composition change required for real Telegram when ops mode is supervised/autonomous.
- A3: Admin default `_delivery_mode` is `"supervised"` (`AdminService.__init__`); inverted approve test expects `"supervised"` unless the graph is constructed with another mode.
- A4: Orch inverted autonomous-path test currently builds with `delivery_mode="supervised"` + `global_mode="autonomous"`; after change, captured `ctx.mode` must equal `"supervised"` (delivery_mode field), **not** `"fake_delivery"` and not AMS global_mode.
- A5: Operational turns/pending_deliveries for sandbox chats remain allowed; “zero residue” means product learning/memory/staging only.
- A6: Log event rename is polish-only; if time-boxed, keep name but accept it fires only when configured mode is already fake.

## Architecture Approach

### QUÉ (behavior / contracts)

**Effective delivery under sandbox (locked):**

```
mode_effective = configured delivery_mode  # supervised | autonomous | fake_delivery
# sandbox active MUST NOT override mode_effective to fake_delivery
```

**Observable truths after change:**

1. Sandbox active + `delivery_mode="supervised"` + owner approve → `DeliveryContext.mode == "supervised"` (real actuator path when mode ≠ fake).
2. Sandbox active + orch autonomous `action=send` + `delivery_mode` not fake → `DeliveryContext.mode == delivery_mode` (≠ `"fake_delivery"`).
3. Sandbox active + `delivery_mode="fake_delivery"` → still `mode == "fake_delivery"` (global ops mode preserved).
4. Sandbox active → post-turn learning still skipped (`should_persist` / `post_turn_skipped_sandbox`).
5. Sandbox active, no `vip_id`, `consult_doctrine` → still demotes via `sandbox_no_vip_doctrine`.
6. Non-sandbox chats unchanged: mode remains `_delivery_mode`.
7. BehaviorEngine still honors `ctx.mode == "fake_delivery"` for real fake path; no engine edits.

**Contracts:**

| Surface | Input | Output / side-effect |
|---------|-------|----------------------|
| `TurnOrchestrator._effective_delivery_mode(chat_id)` | any chat_id | always `self._delivery_mode` |
| `AdminService._effective_delivery_mode(chat_id)` | any chat_id | always `self._delivery_mode` |
| Call sites building `DeliveryContext` | mode from helper | no sandbox force |
| Learning / staging / recontact / doctrine demote | sandbox active | **unchanged** isolation |

### CÓMO (structure / patterns)

- **Layers:** Application only (`application/turn_orchestrator.py`, `application/admin_service.py`). No cognitive, behavior, learning, or telegram layer changes.
- **Pattern to copy:** Existing helper shape in both services — keep method for single call-site clarity; body becomes identity of `_delivery_mode`:

```python
def _effective_delivery_mode(self, chat_id: int) -> DeliveryMode:
    return self._delivery_mode
```

  - Keep `chat_id` parameter to avoid call-site churn (orch ~L543, admin ~L447). If ruff/`ARG002` flags unused arg: prefix `_chat_id` **or** add `# noqa: ARG002` — do not reintroduce sandbox branch.
  - **Do not** inline-delete helpers unless both call sites are updated in the same commit; prefer keep helpers (impact: “or delete helper + use field” is alternative, not required).

- **Log polish (same PR if budget):** where `mode == "fake_delivery"` logs `"sandbox_fake_delivery"`, rename event to `"delivery_mode_fake"` (or keep string and leave as-is). Do not gate log on sandbox is_active after change (would hide legitimate global fake ops).

- **Tests pattern to copy:** existing CaptureBehavior + sandbox activate fixtures in:
  - `tests/unit/application/test_turn_orchestrator.py::test_sandbox_autonomous_uses_fake_delivery_mode` (~L1733)
  - `tests/unit/application/test_admin_service.py::test_sandbox_approve_uses_fake_delivery` (~L718)
  - Isolation golds already present: `test_sandbox_skips_learning_post_turn`, `test_sandbox_consult_doctrine_demotes_when_no_vip`, staging/recontact sandbox tests — **must stay green, no logic edits**.

- **Wiring:** no composition change. Call graph unchanged: orch autonomous job / admin approve → `_effective_delivery_mode` → `DeliveryContext(mode=...)` → `BehaviorEngine.deliver`.

- **File map:**

| Action | Path |
|--------|------|
| Edit | `src/diana/application/turn_orchestrator.py` |
| Edit | `src/diana/application/admin_service.py` |
| Edit | `tests/unit/application/test_turn_orchestrator.py` |
| Edit | `tests/unit/application/test_admin_service.py` |
| Edit | `README.md` (~L28 flag table) |
| Edit | `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md` (isolation/delivery claims) |
| No-touch | `sandbox.py`, `sandbox_knowledge.py`, `staging_service.py`, `recontact_service.py`, `behavior/engine.py`, `behavior/fake.py`, `config/settings.py`, `learning/*`, `cognitive/*`, composition recontact hooks |

## Context

- Locked clarify: `.planning/quick/sandbox-real-delivery/CLARIFY.md` (D1–D7)
- Impact: `.grok/agent-memory/impact-analyzer/sandbox-real-delivery.md`
- Module limits: `AGENTS.md` (Behavior outside cognition; learning post-turn only; sandbox feature-flagged)
- Prior item: owner-admin-sandbox item4 forced fake_delivery intentionally — **this item supersedes that delivery override only**

## Tasks

### Task 1: TDD — invert sandbox delivery assertions (RED)

**type:** auto  
**Objective:** Tests encode “sandbox does not force fake_delivery”; suite fails on current production code.  
**Files:**
- `tests/unit/application/test_turn_orchestrator.py`
- `tests/unit/application/test_admin_service.py`

**Action:**

1. **Rename + invert** orch test `test_sandbox_autonomous_uses_fake_delivery_mode` →  
   `test_sandbox_autonomous_uses_configured_delivery_mode` (or equivalent clear name).  
   - Keep setup: sandbox activate, `wire_autonomous=True`, `feature_autonomous_mode=True`, `global_mode="autonomous"`, `delivery_mode="supervised"`, CaptureBehavior, `action="send"`.  
   - **Replace** `assert captured[0].mode == "fake_delivery"` with:
     - `assert captured[0].mode == "supervised"`  # equals configured delivery_mode
     - `assert captured[0].mode != "fake_delivery"`

2. **Rename + invert** admin test `test_sandbox_approve_uses_fake_delivery` →  
   `test_sandbox_approve_uses_configured_delivery_mode`.  
   - Keep sandbox activate + CaptureBehavior + approve path.  
   - Default AdminService `delivery_mode` is `"supervised"`.  
   - **Replace** `assert captured[0].mode == "fake_delivery"` with:
     - `assert captured[0].mode == "supervised"`
     - `assert captured[0].mode != "fake_delivery"`

3. **Optional but recommended (same file, orch or admin):** add one case  
   `test_sandbox_respects_global_fake_delivery_mode` — sandbox active + construct with `delivery_mode="fake_delivery"` → `captured[0].mode == "fake_delivery"`. Proves D6 (ops mode not removed).

4. Do **not** weaken isolation tests. Do not edit learning/demote/staging tests.

**Verification (expect RED on inverted asserts):**

```bash
python -m pytest \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_admin_service.py \
  -k "sandbox and (delivery or fake_delivery or configured)" -v
```

If `-k` filter misses renamed tests, run by node id:

```bash
python -m pytest \
  tests/unit/application/test_turn_orchestrator.py::test_sandbox_autonomous_uses_configured_delivery_mode \
  tests/unit/application/test_admin_service.py::test_sandbox_approve_uses_configured_delivery_mode \
  -v
```

**Done:**
- [ ] Renamed tests assert configured mode under sandbox (not forced fake)
- [ ] Running them against **unchanged** production code fails (RED)
- [ ] Isolation tests not deleted/edited beyond renames of the two delivery tests

---

### Task 2: Implementation — drop sandbox force in orch + admin (GREEN)

**type:** auto  
**Objective:** `_effective_delivery_mode` never returns fake solely because sandbox is active.  
**Files:**
- `src/diana/application/turn_orchestrator.py` (helper ~L103–106; call ~L543–548)
- `src/diana/application/admin_service.py` (helper ~L109–112; call ~L447–452)

**Action:**

1. In **both** helpers, remove the sandbox branch:

```python
# BEFORE
def _effective_delivery_mode(self, chat_id: int) -> DeliveryMode:
    if self._sandbox_active(chat_id):  # orch
    # or: if self._sandbox is not None and self._sandbox.is_active(chat_id):  # admin
        return "fake_delivery"
    return self._delivery_mode

# AFTER
def _effective_delivery_mode(self, chat_id: int) -> DeliveryMode:
    return self._delivery_mode
```

2. **Do not** change `_maybe_post_turn` sandbox skip, doctrine demote block, SANDBOX reason prefix, or recontact hooks.

3. **Optional polish:** rename log event `"sandbox_fake_delivery"` → `"delivery_mode_fake"` in orch + admin when `mode == "fake_delivery"`. Keep log condition as `mode == "fake_delivery"` only.

4. Leave BehaviorEngine, settings enum, ports `DeliveryMode` Literal untouched.

**Verification:**

```bash
# Focused inverted tests → GREEN
python -m pytest \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_admin_service.py \
  -k "sandbox" -v

# Isolation pack must stay green
python -m pytest \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_admin_service.py \
  tests/unit/application/test_staging_service.py \
  tests/unit/application/test_sandbox_service.py \
  tests/unit/application/test_sandbox_knowledge.py \
  tests/unit/application/test_recontact_service.py \
  tests/unit/behavior/test_engine.py \
  tests/unit/application/test_autonomous_mode_service.py \
  -k "sandbox or fake_delivery" -v
```

**Done:**
- [ ] Both helpers return only `_delivery_mode`
- [ ] Task 1 tests GREEN
- [ ] Isolation pack GREEN (learning skip, doctrine demote, staging skip, recontact skip, fake engine path, AMS fake independent)
- [ ] No edits under no-touch list

---

### Task 3: Docs sync — sandbox delivery isolation wording

**type:** auto  
**Objective:** Product docs no longer claim “sandbox ⇒ fake_delivery”; state real Telegram + product non-persist.  
**Files:**
- `README.md` (~L28 sandbox flag row)
- `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md` (~L17 table, ~L138–139 isolation, ~L189 FakeDelivery claim)

**Action:**

1. **README.md** sandbox row: remove `` `fake_delivery` `` from turn isolation list. Isolation bullets should reflect: auth bypass, profile inject, **learning skip / should_persist**, recontact skip — **not** forced fake delivery. Keep note that global `global_mode=fake_delivery` is a **separate** ops mode.

2. **PRODUCT_OWNER_ADMIN_SANDBOX.md:**
   - Item4 summary (~L17): drop `` `fake_delivery` `` as isolation feature; say real delivery under session + product residue gates.
   - Isolation table (~L138–139): replace “Prefer fake_delivery…” with: **Delivery uses configured `global_mode` / delivery_mode (real Telegram when supervised|autonomous).** Isolation of product knowledge = `should_persist=false`, not delivery mode.
   - Residual claim (~L189): reverse “sandbox implies non-delivery”; document operator risk: `/sandbox on <chat_id>` targets the chat that **receives** messages — use a dedicated test chat.

3. Do **not** rewrite historical `docs/contratos_restantes.md` (optional footnote only; OOS).

**Verification:**

```bash
# Docs-only: grep inverted claims should not assert forced fake under sandbox
rg -n "sandbox.*fake_delivery|fake_delivery.*sandbox|implies non-delivery|Prefer.*fake_delivery" \
  README.md docs/PRODUCT_OWNER_ADMIN_SANDBOX.md

# Full unit safety net after all code+docs tasks
python -m pytest tests/unit -q
```

Manual: remaining hits must only refer to **global** `fake_delivery` ops mode or historical notes — not “sandbox forces fake”.

**Done:**
- [ ] README isolation list accurate
- [ ] PRODUCT_OWNER delivery section matches CLARIFY D1–D2 + D4
- [ ] Operator chat-targeting risk documented
- [ ] Unit suite still green if code already merged in Task 2

## Instrucciones para gsd-executor

### Strict TDD (mandatory)

- Project: **Strict TDD Mode enabled**. Runner: `pytest`.
- Order: **Task 1 (RED) → Task 2 (GREEN) → Task 3 (docs)**. Do not change production helpers before inverted tests exist and fail for the right reason.

### Patterns to copy

- Helper identity return: keep `_effective_delivery_mode` API; body = `return self._delivery_mode`.
- Test golds: CaptureBehavior capturing `ctx`; sandbox `activate(chat_id, profile)`; inject via `g["orch"]._sandbox` / `g["admin"]._sandbox`.
- Isolation tests already in suite — re-run, do not rewrite.

### Anti-patterns (forbidden)

- Touching `should_persist`, staging gate, recontact skip, doctrine demote “to simplify”
- Forcing real Telegram by hardcoding mode `"supervised"` instead of respecting `_delivery_mode`
- Removing BehaviorEngine fake path or `fake_delivery` from settings/ports
- Changing Decider priority, Director, Learning promotion, cognitive modules
- Reintroducing sandbox → fake in a different call site

### Logging / conventions

- English code/comments; conventional commits; **no** AI co-author trailers
- Work-unit commits: (1) test invert RED, (2) helpers GREEN, (3) docs — or single commit only if pipeline requires one unit with tests green at end; prefer 2–3 work units with verifiable steps
- Log event rename optional; do not add noisy new logs

### Mock policy

- Unit tests mock **external** Telegram via CaptureBehavior / FakeTelegramActuator only (existing pattern).
- Do not mock Director decision path for delivery-mode asserts; use FakeDirector with fixed Decision as existing tests do.

### Skills / project rules

- Obey `AGENTS.md` module boundaries
- Persona does **not** apply to code/docs artifacts (English technical prose)
- Engram project `dianav2`: after non-obvious discoveries, `mem_save` with project dianav2

### No-touch enforcement

If a fix seems to require learning/recontact/behavior/engine/settings — **stop**; that is out of scope per CLARIFY. Fix only delivery mode source.

## Test commands

```bash
# Primary change surface
python -m pytest tests/unit/application/test_turn_orchestrator.py -k sandbox -v
python -m pytest tests/unit/application/test_admin_service.py -k sandbox -v

# Isolation regression pack
python -m pytest \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_admin_service.py \
  tests/unit/application/test_staging_service.py \
  tests/unit/application/test_sandbox_service.py \
  tests/unit/application/test_sandbox_knowledge.py \
  tests/unit/application/test_recontact_service.py \
  tests/unit/behavior/test_engine.py \
  tests/unit/application/test_autonomous_mode_service.py \
  -k "sandbox or fake_delivery" -v

# Full unit safety net
python -m pytest tests/unit -q
```

### Golds that must remain green (do not invert)

| Test | File | Invariant |
|------|------|-----------|
| `test_sandbox_skips_learning_post_turn` | test_turn_orchestrator | no learning when sandbox |
| `test_sandbox_inactive_still_runs_learning` | test_turn_orchestrator | learning when inactive |
| `test_sandbox_consult_doctrine_demotes_when_no_vip` | test_turn_orchestrator | demote + SANDBOX reason |
| `test_sandbox_draft_reason_has_marker` | test_admin_service | SANDBOX prefix |
| `test_save_correction_skips_when_sandbox_active` | test_staging_service | no staging |
| `test_should_persist_inverse_of_active` | test_sandbox_service | API contract |
| recontact sandbox hooks | test_recontact_service | skip when active |
| fake path / AMS fake | test_engine / test_autonomous_mode_service | global fake still works |

## Risks + Mitigation

| Risk | Level | Mitigation in plan |
|------|-------|--------------------|
| Real VIP accidental delivery if owner sandboxes a real chat_id | Medium | Task 3 docs: document chat-targeting; OOS soft warn |
| Autonomous sandbox auto-send without owner approve | Medium | Expected for E2E; Task 1 covers mode under autonomous path; owner must understand global_mode + auto_send |
| Stale docs reintroduce old invariant | Medium | Task 3 mandatory in same item |
| Log name `sandbox_fake_delivery` misleading | Low | Optional rename in Task 2 |
| Test hard-asserts break CI | Low | Task 1 first (Strict TDD); focused pytest commands |

## Success Criteria

- [ ] Sandbox active does **not** force `DeliveryContext.mode="fake_delivery"`
- [ ] Configured `delivery_mode` (supervised|autonomous|fake_delivery) is what reaches BehaviorEngine under sandbox
- [ ] `should_persist` / post-turn skip / staging skip still hold
- [ ] `sandbox_no_vip_doctrine` demote intact
- [ ] Recontact sandbox skip intact
- [ ] Global `fake_delivery` ops mode still works (with or without sandbox)
- [ ] README + PRODUCT_OWNER docs match CLARIFY (real delivery + product non-persist)
- [ ] Isolation pack + full `tests/unit` green
- [ ] No-touch list respected

## Self-check (planner gate)

- [x] QUÉ dimensioned (outcome, scope, truths, contracts)
- [x] CÓMO dimensioned (helpers, pattern, files, order, TDD)
- [x] Locked CLARIFY D1–D7 as non-negotiable / non-goals
- [x] Assumptions A1–A6 explicit
- [x] 3 tasks with Files + Action + Verification + Done
- [x] Exact pytest commands + golds list
- [x] Risks from impact amarrados a tasks/docs
- [x] Executor instructions: Strict TDD, anti-patterns, no-touch
- [x] Scope = drop sandbox-forced fake_delivery only (no doctrine/recontact rewrite)
