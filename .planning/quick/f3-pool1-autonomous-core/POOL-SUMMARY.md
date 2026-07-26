# POOL-SUMMARY — f3-pool1-autonomous-core

**Pool:** f3-pool1-autonomous-core  
**Phase:** Fase 3 — Producto Completo (SPEC-FASE3.md)  
**Mode:** hardener-agile · Strict TDD · effort 5  
**Date closed:** 2026-07-26  
**Status:** **COMPLETE** — items 1–4 + item4b rich quirks; all reviews 0 open  

**Sources:** item SUMMARYs under this directory · `CLARIFY.md` · `POOL.md` · arch-enforcer / test-guardian MEMORY index · hardener HARD_IDs below.

---

## Objective

Ship the **autonomous core** for Fase 3 so a VIP turn can auto-send when flags, AMS enablement, and autonomous thresholds allow — without breaking Fase 2 when flags are off.

In scope (this pool):

| SPEC / roadmap | Scope covered |
|----------------|---------------|
| H3.1 | Decider autonomous `send` rules + dual thresholds |
| H3.2 | AutonomousModeService + near-threshold notify + orch send path |
| H3.6 | Behavior advanced: freeze hard-check, split, light + **rich** human quirks, `deliver_with_sequence` |

Out of scope (deferred pools): H3.3 recontact + H3.8 cancel hook · H3.4 promo · H3.5/H3.7 calibration + metrics · H3.9 admin dashboard DM · H3.10 integration activation.

---

## Items

| # | Title | Status | HARD_ID | Final open | Primary evidence (executor SUMMARY) |
|---|--------|--------|---------|------------|-------------------------------------|
| 1 | Foundation: flags + `Decision.action="send"` + dual thresholds | done | `15fa8330` | 0 | item suite → 162 after review; full unit 630 (+3 pre-existing embedding env fails) |
| 2 | Decider autonomous matrix (unit-inject only) | done | `e78885f2` | 0 | 45 decider / 660 full unit |
| 3 | AMS + orchestrator send + composition | done | `b3ee6a75` | 0 | primary 171 / full unit 686 |
| 4 | Behavior: frozen hard-check + dual-gate split/light quirks + sequence | done | `74d2f5d5` | 0 | primary 135 / full unit 713 |
| 4b | Rich human quirks under FEATURE_ADVANCED_BEHAVIOR | done | `e4a192c5` | 0 | behavior 65 / primary 131 post-fix |

**Aggregate gates:** arch-enforcer **PASS WITH NOTES** (0 critical) on all items · test-guardian **suite protege adecuadamente** on all items · effort-5 review loops closed with 0 open issues each.

---

## Commit themes (by item)

### Item 1 — foundation (`15fa8330`)

- `test+feat(cognitive): accept Decision.action send`
- `test+feat(config): add F3 feature flags and threshold defaults`
- `test+feat(db): seed F3 flags and dual thresholds migration 006`
- Review harden: freeze thresholds, landmine safety vs safety_min, migration key locks

### Item 2 — decider (`e78885f2`)

- `test(cognitive): red matrix for F3 Decider autonomous send gate`
- `feat(cognitive): Decider autonomous send gate after F2 priorities`
- `fix(cognitive): harden Decider autonomous fallback contract` (flag sole enablement, `autonomous_below_threshold`, partial threshold merge, policy edges)

### Item 3 — AMS + orch (`b3ee6a75`)

- AMS + `vip.auto_send` + migration `007_vip_auto_send`
- Orchestrator send path: **deliver outside chat lock**, CAS finalize, fail-closed freeze/empty/AMS-off
- Composition wires Decider autonomous flag + AMS + orch deps
- Fix rounds: freeze/notify gates, auto_send explicit fields, no bare asserts on behavior

### Item 4 — behavior base (`74d2f5d5`)

- `DeliveryContext.is_frozen` hard-check at engine entry (+ pre-send)
- Dual-gate split + light quirk pause (`feature_advanced_behavior ∧ ctx.allow_*`)
- `deliver_with_sequence` with inter-message delay/typing
- Orch + Admin builders + composition wire `FEATURE_ADVANCED_BEHAVIOR`

### Item 4b — rich quirks (`e4a192c5`)

- Pure `behavior/quirks.py`: at most one of `pause` | `natural_split` | `typo_correct`
- Engine integration under dual gate; force/rng hooks for tests
- Fix: noop typo, dual-gate fail-closed, Spanish accented words, invalid force

---

## Architecture decisions (locked)

### 1. Flag sole enablement (Decider send)

- **`FEATURE_AUTONOMOUS_MODE` is the sole unlock** for Decider rule that emits `action="send"`.
- Director `mode` stays external/supervised hardcode (audit residual, intentional — PLAN A1).
- Flag off ≡ Fase 2: Decider never emits `send` regardless of scores or VIP settings.
- Source: item2 SUMMARY hardener G2-6 fix · CLARIFY assumption · item3 residual “Director supervised”.

### 2. AMS L1 / L2 enablement

```text
L1 FEATURE_AUTONOMOUS_MODE (Settings)  → master kill-switch; default false
L2 AMS.is_autonomous_enabled(vip_id)   → L1 AND (global_mode=="autonomous" OR vip.auto_send)
L3 Decider thresholds                  → dims ≥ autonomous mins → action "send"
Orch: send + L2 → deliver; send + !L2 → approve (demote); never deliver if frozen/empty
```

- `fake_delivery` does **not** enable L2.
- Near-threshold notify band `[min, min+0.05)`; notifier errors swallowed.
- Source: item3 SUMMARY enablement lock.

### 3. Deliver outside chat lock

- Autonomous happy path: release/finish cognitive work under chat lock, then **`BehaviorEngine.deliver` outside `chat_scope`**, CAS finalize, optional notify, **single** `run_post_turn`.
- Mid-flight supersede: no `delivered` revive.
- Application-layer freeze re-check before deliver; engine also hard-checks `is_frozen` (defense in depth, item4).
- Source: item3 SUMMARY · AGENTS I.5 / Behavior purity.

### 4. Full FEATURE_ADVANCED quirks (item4 + item4b)

- Dual gate only: `feature_advanced_behavior ∧ ctx.allow_split|allow_human_quirks`.
- Split: pure `split_text` (punct/newline → whitespace → hard cut).
- Quirks (at most one): **pause** | **natural_split** | **typo_correct** (typo bubble then `*{word}`).
- Composition: `quirk_probability=0.05` only when advanced flag on; default engine p=0 for determinism.
- No LLM in Behavior; flags default false.
- Source: item4 + item4b SUMMARYs · AGENTS §4.12 / SPEC F3-06.

### 5. User-facing tone (from CLARIFY)

Product rule for **direct end-user communication** (VIP / no-VIP: generated drafts, recontact templates, promo sequences, re-send intros):

- **First person**
- **Friendly feminine tone** (natural warm Spanish)

**Assumption:** operational owner DMs (admin alerts, threshold notices, metrics summaries, escalations) keep a clear operational register — not forced into chatty brand voice unless the text is literally “as the brand”.

Pool 1 only ships send path plumbing; Generator already produces drafts. Copy rules apply when pools 2–3 write templates.

### 6. Pool partition (from CLARIFY)

1. **Pool 1 (this)** — autonomous core  
2. **Pool 2** — proactivity: recontact + promo + cancel hook  
3. **Pool 3** — calibration + metrics + drift + dashboard DM  
4. Pool 4+ — residual admin config / integration hardening if needed  

Promo re-send policy (Pool 2): **not silence** — full sequence again with a **friendly re-intro** on the first message only (no LLM inventing copy).

---

## Residuals → next pools

### Pool 2 — proactivity (next)

| Residual | Notes | Origin |
|----------|--------|--------|
| RecontactService + scheduled job | Reduced pipeline; no Analyst/Planner; freeze/pause guards | CLARIFY · SPEC H3.3 |
| Recontact cancel hook on new VIP message | TurnCoordinator / app hook | SPEC H3.8 |
| PromoService + `promo_executions` | Exact match, no LLM; sequences via Behavior | SPEC H3.4 |
| Promo re-intro amigable | Full sequence on re-send; friendly first-line variant | CLARIFY decision 2 |

### Pool 3 — calibration / metrics / dashboard

| Residual | Notes | Origin |
|----------|--------|--------|
| CalibrationService | Windowed percentiles; autonomous margin > supervised | SPEC H3.5 |
| Weekly metrics + style drift job | EmbeddingService drift | SPEC H3.7 |
| Admin DM dashboard summary | SPEC §7.3 shape | SPEC H3.9 · CLARIFY decision 4 |

### Documented out-of-scope / deferred (not blocking Pool 1 close)

| Residual | Class | Origin |
|----------|--------|--------|
| Naturalness re-draft / regenerate action | out-of-scope | item2; AGENTS residual |
| `TurnStatus.delivering` intermediate enum | wontfix / optional ops | item3 SUG-3 |
| Multi-worker durable CAS / claim token | out-of-scope | item3; Admin parity single-process |
| Bot history append after autonomous send | out-of-scope | item3 (admin parity) |
| Near-threshold notify rate-limit/dedupe | out-of-scope | item3 |
| Async DB threshold boot merge | out-of-scope (A8 pure DEFAULT_*) | item3 |
| `system_config.behavior` JSON runtime merge | deferred | item4 |
| FreezePort re-query mid-delay inside engine | deferred | item4 |
| `test_embedding.py` needs `sentence_transformers` | pre-existing env | item1 |

---

## Metrics

| Metric | Value |
|--------|--------|
| Items completed | 5 (1–4 + 4b) |
| Critical arch violations | **0** (all items PASS WITH NOTES) |
| Final review open issues | **0** per HARD_ID |
| Feature flags default | **false** (F2-compatible) |
| Last full unit snapshot (item4) | **713 passed** |
| Behavior purity | green (no LLM/cognitive/aiogram imports) |

---

## Files / modules touched (pool aggregate)

| Area | Key paths |
|------|-----------|
| Config / models | `config.py`, `cognitive/models.py`, `cognitive/thresholds.py` |
| Decider | `cognitive/decider.py` |
| Application | `autonomous_mode_service.py` (NEW), `turn_orchestrator.py`, `admin_service.py`, `ports.py` |
| Behavior | `engine.py`, `split.py` (NEW), `quirks.py` (NEW) |
| Infra | migrations `006`, `007`; VIP ORM/mapper; system_config threshold readers |
| Composition | Decider autonomous wire + AMS + advanced behavior flag |
| Tests | unit matrices for models, thresholds, decider, AMS, orch send, composition, behavior/quirks |

---

## Pool close note

Pool `f3-pool1-autonomous-core` closed — 5 items completed (foundation, decider, AMS+orch, behavior advanced base, rich quirks), HARD_IDs all final open 0, tests green, commits done, documentation updated.

**Next:** Pool 2 — recontact + promo (with re-intro amigable) + cancel hook; then Pool 3 — calibration + metrics + dashboard DM.
