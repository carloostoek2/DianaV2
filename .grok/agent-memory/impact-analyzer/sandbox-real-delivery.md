# Impact Analysis: sandbox-real-delivery

**Date:** 2026-07-27  
**Change:** Stop forcing `DeliveryContext.mode="fake_delivery"` when a sandbox session is active; keep all other sandbox isolation shortcuts (`should_persist`, doctrine demote, recontact skip).  
**Analysis only** — no implementation  
**Source of truth (locked):** `.planning/quick/sandbox-real-delivery/CLARIFY.md`  
**Pool:** hardener-agile / sandbox-real-delivery (pool 1)  
**Depends on:** owner-admin-sandbox item4 (sandbox isolation already shipped)  
**Effort estimate:** 2–3 tasks (orch + admin mode helper; invert 2 unit tests; docs sync)

---

## Executive Summary

Today, sandbox sessions force non-network delivery. Both `TurnOrchestrator._effective_delivery_mode` and `AdminService._effective_delivery_mode` return `"fake_delivery"` whenever `SandboxService.is_active(chat_id)`. That was intentional in item4 so test traffic never hit Telegram. The locked clarify **reverses only that delivery override**: sandbox is now full live E2E for the owner (Director → Decisor → real BehaviorEngine actuation) while **product residue isolation stays** (`should_persist=false` → no post-turn learning, no staging corrections; fixture knowledge via `SandboxKnowledgeAugmenter`; `consult_doctrine` demote when no `vip_id`; recontact skip).

Scope is surgical. Production code change is essentially two methods (optionally collapse helpers to `return self._delivery_mode`) plus log cleanup for `sandbox_fake_delivery` when the mode is no longer sandbox-forced. `BehaviorEngine` fake path, `settings.global_mode="fake_delivery"` as a global ops mode, AMS L2 gating, Learning, Recontact, GrayZone, and catalog fixtures are **no-touch**.

Global risk is **medium**, concentrated in **operator chat targeting**: after this change, `/sandbox on <chat_id>` will cause **real Telegram sends** to that chat when the owner approves (supervised) or when autonomous `send` fires. Mis-targeting a real VIP private chat is no longer blocked by fake delivery. Isolation of knowledge banks remains solid via existing `should_persist` gates. Docs still claim “sandbox implies fake_delivery” and must be updated to avoid regressing product understanding.

---

## Locked product decisions (from CLARIFY)

| ID | Decision |
|----|----------|
| D1 | Sandbox = real E2E owner test: full pipeline (Director, Decisor, delivery actuation) |
| D2 | **Real Telegram delivery** when sandbox active — do **not** force `mode="fake_delivery"` solely because sandbox is active |
| D3 | Knowledge = active fixture profile (`SandboxKnowledgeAugmenter`) — unchanged |
| D4 | Zero **product** residue: keep `should_persist=false` (no learning, no staging/corrections, no live memory/examples) |
| D5 | **Only remove forced fake_delivery.** KEEP: `sandbox_no_vip_doctrine` demote; recontact skip when sandbox active |
| D6 | `fake_delivery` remains valid `global_mode` / BehaviorEngine path; only sandbox-forced override goes away |
| D7 | OOS: multi-replica sessions, new fixtures, gray-zone without vip_id, zero operational DB writes (turns/deliveries allowed) |

**Effective delivery rule after change:**

```
mode_effective = settings.global_mode  # supervised | autonomous | fake_delivery
# sandbox session must NOT override mode_effective to fake_delivery
```

Composition already wires `delivery_mode=settings.global_mode` into orch, admin, recontact, promo.

---

## Consumers / Call Sites Map

### Production — MUST change (forced fake_delivery)

| Site | Path | Lines | Current behavior | Target |
|------|------|-------|------------------|--------|
| Orch helper | `src/diana/application/turn_orchestrator.py` | 103–106 | if sandbox active → `"fake_delivery"` else `_delivery_mode` | always `_delivery_mode` (or delete helper + use field) |
| Orch autonomous job | same | 543–548 | uses helper; logs `sandbox_fake_delivery` when mode is fake | keep mode from helper; log only if still fake via global_mode (optional rename) |
| Admin helper | `src/diana/application/admin_service.py` | 109–112 | if sandbox active → `"fake_delivery"` else `_delivery_mode` | always `_delivery_mode` |
| Admin approve deliver | same | 447–452 | uses helper; logs `sandbox_fake_delivery` | same as orch |

### Production — MUST NOT change (isolation retained)

| Site | Path | Lines | Why keep |
|------|------|-------|----------|
| `should_persist` | `application/sandbox.py` | 185–186 | product residue gate |
| post-turn skip | `application/turn_orchestrator.py` | 108–115 | `post_turn_skipped_sandbox` |
| doctrine demote | `application/turn_orchestrator.py` | 350–373 | `sandbox_no_vip_doctrine` when `vip_id is None` |
| correction skip | `application/staging_service.py` | 55–63 | `correction_skipped_sandbox` |
| recontact hook | `application/recontact_service.py` + `composition.py` 329–340, 358 | `_is_sandbox_vip` | skip recontact on sandboxed VIP chat |
| fixture inject | `application/sandbox_knowledge.py` + composition | augmenter | fixture profile knowledge |
| SANDBOX UX prefix | `admin_service.py` 97–107 | draft/escalate reason marker | owner clarity |
| Behavior fake path | `behavior/engine.py` 198–204 | `ctx.mode == "fake_delivery"` | global ops mode still valid |
| Settings enum | `config/settings.py` 41 | `global_mode` includes fake_delivery | keep |
| DeliveryMode type | `application/ports.py` 151 | Literal includes fake_delivery | keep |
| AMS L2 | `autonomous_mode_service.py` | global_mode autonomous / vip.auto_send | independent of delivery mode |

### Docs — stale (edit recommended in same PR or follow-up task)

| Path | Claim to reverse |
|------|------------------|
| `README.md` ~L28 | Sandbox isolation lists `` `fake_delivery` `` as turn isolation |
| `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md` ~L17, L139, L189 | “Prefer fake_delivery”; “sandbox implies non-delivery” |

Historical contracts (`docs/contratos_restantes.md` fake_delivery for “sandbox futuro”) are design history; optional footnote only — not blocking.

---

## Risks

### Critical

None if operator always activates sandbox on a dedicated test chat. Code cannot distinguish “test chat” vs “real VIP private chat” by itself (session is `chat_id → profile_key` only).

### Medium

| Risk | Evidence | Mitigation |
|------|----------|------------|
| **Real VIP accidental delivery** | After change, approve/send on sandboxed `chat_id` uses real actuator when `global_mode != fake_delivery`. `/sandbox on <real_vip_id>` is valid API today. | Ops: document that sandbox targets the **chat that receives messages**. Optional later: warn on activate if chat is allowlisted VIP (OOS unless planner adds soft warn). |
| **Autonomous sandbox auto-send** | Orch path `action=send` → `_prepare_autonomous_deliver` → real `BehaviorEngine.deliver`. Under sandbox + AMS + thresholds, messages leave without owner approve. | Expected for E2E of autonomous mode. Owner must understand global_mode + auto_send. Tests should cover both supervised approve and autonomous send with `mode != fake_delivery`. |
| **Stale docs reintroduce wrong invariant** | PRODUCT_OWNER doc + arch-enforcer item4 still say fake_delivery isolation | Update docs in-scope; arch-enforcer must re-read CLARIFY not item4 summary |
| **Log name drift** | `sandbox_fake_delivery` logged whenever mode is fake, not only when sandbox forced it | After change, log only fires for global_mode fake_delivery (ops). Rename to `delivery_mode_fake` or gate log on sandbox+fake optional polish |

### Low

| Risk | Mitigation |
|------|------------|
| Tests hard-assert `mode == "fake_delivery"` under sandbox | Invert 2 tests (see below); suite fails loudly until updated |
| Promo/recontact still use `delivery_mode=settings.global_mode` without sandbox override | Correct per D5/D6; recontact already skips sandboxed VIP |
| Operational turns/deliveries rows for sandbox chats | Allowed by D7 / CLARIFY assumptions |
| History SQL still appends for sandbox chats | Pre-existing; not product learning; OOS |

### Sensitive systems (AGENTS.md)

| System | Impact |
|--------|--------|
| Director determinism | None — still invoked fully |
| Behavior outside cognition | None — only `DeliveryContext.mode` source changes |
| Learning post-turn only | Intact via `should_persist` |
| Decider priority order | Intact; doctrine demote remains application-layer demote |
| Feature flags | No new flags; `FEATURE_SANDBOX_ENABLED` unchanged |
| Anti-contamination VIP memory ↔ examples | Intact via should_persist + fixture augmenter |

---

## Affected Tests

### Must update (will fail after code change)

| Test | File | Current assert | Target assert |
|------|------|----------------|---------------|
| `test_sandbox_autonomous_uses_fake_delivery_mode` | `tests/unit/application/test_turn_orchestrator.py` ~1733 | `captured[0].mode == "fake_delivery"` | rename; assert `mode == delivery_mode` (e.g. `"supervised"` or `"autonomous"` per fixture) and **≠** `"fake_delivery"` when sandbox active and delivery_mode not fake |
| `test_sandbox_approve_uses_fake_delivery` | `tests/unit/application/test_admin_service.py` ~718 | `captured[0].mode == "fake_delivery"` | rename; assert real mode from admin `_delivery_mode` under sandbox |

### Must keep green (isolation regression guards)

| Test | File | Invariant |
|------|------|-----------|
| `test_sandbox_skips_learning_post_turn` | `test_turn_orchestrator.py` | no learning when sandbox active |
| `test_sandbox_inactive_still_runs_learning` | `test_turn_orchestrator.py` | learning when inactive |
| `test_sandbox_consult_doctrine_demotes_when_no_vip` | `test_turn_orchestrator.py` | demote → pending_approval + SANDBOX reason |
| `test_sandbox_draft_reason_has_marker` | `test_admin_service.py` | SANDBOX prefix |
| `test_save_correction_skips_when_sandbox_active` | `test_staging_service.py` | no staging insert |
| `test_save_correction_inserts_when_sandbox_inactive` | `test_staging_service.py` | insert when inactive |
| `test_should_persist_inverse_of_active` | `test_sandbox_service.py` | API contract |
| recontact sandbox hooks | `test_recontact_service.py` | skip when active |
| Behavior engine fake path | `test_engine.py` / `test_fake_delivery.py` | global fake_delivery still works |
| `test_fake_delivery_mode_does_not_enable_l2` | `test_autonomous_mode_service.py` | AMS independent of delivery mode |

### Suggested new tests (planner/executor)

1. **Supervised + sandbox + approve** → `DeliveryContext.mode == "supervised"` (or configured delivery_mode), actuator would be called (CaptureBehavior), learning still skipped.
2. **Autonomous + sandbox + send** → mode from `_delivery_mode`, not forced fake; learning skipped.
3. **Sandbox + global_mode=fake_delivery** → still fake (ops mode wins, not removed).
4. Optional: non-sandbox chat still uses `_delivery_mode` unchanged (parity).

### Exact pytest commands

```bash
# Focused — change surface
python -m pytest tests/unit/application/test_turn_orchestrator.py -k sandbox -v
python -m pytest tests/unit/application/test_admin_service.py -k sandbox -v
python -m pytest tests/unit/application/test_staging_service.py -k sandbox -v
python -m pytest tests/unit/application/test_sandbox_service.py -v
python -m pytest tests/unit/application/test_recontact_service.py -k sandbox -v
python -m pytest tests/unit/behavior/test_engine.py -k fake_delivery -v
python -m pytest tests/unit/application/test_autonomous_mode_service.py -k fake_delivery -v

# Isolation pack (recommended CI gate for this item)
python -m pytest \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_admin_service.py \
  tests/unit/application/test_staging_service.py \
  tests/unit/application/test_sandbox_service.py \
  tests/unit/application/test_sandbox_knowledge.py \
  tests/unit/application/test_recontact_service.py \
  tests/unit/behavior/test_engine.py \
  -k "sandbox or fake_delivery" -v

# Full unit safety net after green focused
python -m pytest tests/unit -q
```

Strict TDD: rewrite/invert the two failing asserts first (red), then change `_effective_delivery_mode` (green).

---

## Files Map

### Edit

| File | Change |
|------|--------|
| `src/diana/application/turn_orchestrator.py` | `_effective_delivery_mode`: remove sandbox → fake_delivery branch |
| `src/diana/application/admin_service.py` | same |
| `tests/unit/application/test_turn_orchestrator.py` | invert/rename autonomous sandbox delivery test |
| `tests/unit/application/test_admin_service.py` | invert/rename approve sandbox delivery test |
| `README.md` | flag table: sandbox isolation without forced fake_delivery |
| `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md` | delivery section: real Telegram to sandboxed chat; isolation = should_persist not fake mode |

### Optional polish (same PR if budget allows)

| File | Change |
|------|--------|
| orch + admin log events | rename `sandbox_fake_delivery` → clearer event when logging global fake mode |

### No touch

- `src/diana/application/sandbox.py` (should_persist API)
- `src/diana/application/sandbox_knowledge.py`
- `src/diana/application/staging_service.py` (keep gate)
- `src/diana/application/recontact_service.py` / composition `_is_sandbox_vip`
- `src/diana/behavior/engine.py`, `behavior/fake.py`
- `src/diana/config/settings.py` global_mode enum
- `src/diana/learning/*`
- `src/diana/cognitive/*` (Director/Decider)
- Gray-zone full path / multi-replica / new fixture profiles
- Real VIP profile tables / profile_content real

---

## Proposed task split for planner (2–4 tasks)

1. **TDD: invert delivery assertions** — change the two tests to expect `_delivery_mode` under sandbox; add assert learning still skipped + doctrine demote still works (existing tests already cover latter two).
2. **Implementation: drop sandbox force in orch + admin** — `_effective_delivery_mode` returns `_delivery_mode` only; optional log cleanup.
3. **Docs sync** — README + PRODUCT_OWNER_ADMIN_SANDBOX delivery isolation wording.
4. **(Optional)** supervised + autonomous regression cases if not folded into task 1.

---

## DoD for downstream

### gsd-planner
- PLAN 2–4 tasks; scope = drop sandbox-forced fake_delivery only.
- List exact tests + pytest commands above.
- Do not rewrite doctrine/recontact/learning.
- Forward CLARIFY D1–D7 as non-negotiable.

### gsd-executor
- Strict TDD; English code/comments; conventional commits.
- Only edit orch + admin helpers (+ tests + docs).
- Prove: sandbox + delivery_mode supervised|autonomous → mode not fake; should_persist path still skips learning.

### arch-enforcer
- Behavior still outside cognition; Director deterministic; learning only post-turn and skipped under sandbox.
- Sandbox does not contaminate live knowledge banks.
- Do **not** enforce old item4 “sandbox ⇒ fake_delivery” — CLARIFY supersedes.

### test-guardian
- Assert real delivery path: `mode != "fake_delivery"` when sandbox active and configured mode is supervised/autonomous.
- Assert `should_persist` / post_turn skip / correction skip still hold.
- Assert `sandbox_no_vip_doctrine` demote intact.
- Assert global_mode `fake_delivery` still works without sandbox.
- Assert recontact skip still holds.

---

## Ready for chain

**Handoff to gsd-planner** with tight scope:

> Remove sandbox session override in `TurnOrchestrator._effective_delivery_mode` and `AdminService._effective_delivery_mode` so effective mode = configured `delivery_mode` (`settings.global_mode`). Keep `should_persist` learning/staging skip, `sandbox_no_vip_doctrine`, recontact sandbox skip, fixture augmenter, SANDBOX UX markers. Invert two unit tests; sync README + PRODUCT_OWNER sandbox delivery docs. Do not touch BehaviorEngine fake implementation or Learning/GrayZone/Recontact logic beyond existing wiring.

**next_recommended:** `plan`  
**status:** `complete`  
**skill_resolution:** `none`
