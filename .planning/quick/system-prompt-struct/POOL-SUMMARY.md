# POOL-SUMMARY — system-prompt-struct

**Pool:** system-prompt-struct  
**Mode:** hardener-agile · Strict TDD · effort 4 (review loop)  
**Date closed:** 2026-07-26  
**Status:** **COMPLETE** — items 1–2; self-checks PASSED; arch 0 critical; test-guardian adequate; review **0 open issues** each item  

**Sources:** `CLARIFY.md` · item SUMMARYs under this directory · impact/arch/test-guardian agent reports · hardener review fix-rounds · git commits listed below.

---

## Objective

Ship **Anexo J system-prompt structure** into production paths:

| Slice | Scope covered |
|-------|---------------|
| Item 1 prompt-data-path | H0–H2 + J.1 + J.5 — optional `needs_persona_facts` / `needs_voice_patterns`, static persona catalog, set-intersection retrievers, planner/registry/context/analyst wiring, Spanish `voz_configurada` + soft policies dual-source |
| Item 2 deterministic-escalation | H3–H5 + J.4 — Decider `frustracion_directa` (molesta), Director `pregunta_repetida` Decision-only early-exit, pre-Director keyword/IA template short-circuits, composition wiring |

**Invariants held (AGENTS.md):** Director 100% deterministic; Decider pure matrix; cognitive ↛ telegram/behavior; EscalationStore/Notifier stay in application; learning post-turn only; no-touch Evaluator/Generator/TurnCoordinator/ExamplesRetriever.

Out of scope (deferred residuals): admin hot-edit catalog · embeddings for persona/voice · fuzzy J.4 · Alembic intents index · Evaluator `needs_*` payload parity · multi-VIP repetition calibration.

---

## Items

| # | Title | Status | Primary evidence |
|---|--------|--------|------------------|
| 1 | prompt-data-path (H0–H2 + J.1 + J.5) | done | Commits `5432541`…`cbfd7f8`; primary suite **211→266→229** through fix rounds; review **0 open** after R3 |
| 2 | deterministic-escalation (H3–H5 + J.4) | done | Commits `2159c20`…`e6ad357`; item2 **182→197→203** through fix rounds; unit **1139** (embedding ignored); review **0 open** after R2 |

**Aggregate gates:** executor self-checks **PASSED** both items · arch-enforcer **PASS WITH NOTES**, **0 critical** · test-guardian **suite adequate**, 0 prohibited mocks · hardener review **0 open issues** at pool close (effort 4).

---

## Commit themes (by item)

### Item 1 — prompt-data-path

| Commit | Message |
|--------|---------|
| `5432541` | `feat(cognitive): add persona catalog and optional comprehension needs flags` |
| `dda48ab` | `feat(cognitive): add persona_facts and voice_patterns retrievers` |
| `a95a76b` | `feat(cognitive): wire persona/voice capabilities and static soft policies` |
| `ecafeb1` | `feat(composition): wire voz_configurada and persona catalogs at boot` |
| `4a84ed6` | `fix(cognitive): hardener review round1 prompt-data-path` (14/14) |
| `cbfd7f8` | `fix(cognitive): hardener review round2 voice score and policy fail-soft` (4/4) |

### Item 2 — deterministic-escalation

| Commit | Message |
|--------|---------|
| `2159c20` | `feat(decider): escalate on emotion molesta (H3)` |
| `281f104` | `feat(cognitive): add pure RepetitionGuard for H4` |
| `89274fd` | `feat(cognitive): H4 pregunta_repetida early-exit Decision-only` |
| `c4a5e92` | `feat(application): J.4 triggers and typed deterministic escalate` |
| `c3d67da` | `feat(composition): wire repetition guard and j4 escalate path` |
| `dbdca09` | `fix(application): log soft IA deliver fail and still escalate` |
| `5a3e5ca` | `fix(application): expand J.4 pago/IA phrases; tighten compromiso` |
| `80321c1` | `fix(telegram): Auth before Forbidden; VIP gate on J.4 escalate` |
| `07cc653` | `test(infrastructure): unit cover SqlTraceStore.get_recent_intents` |
| `694dc7d` | `fix(cognitive): fresh zero EvaluationProfile on H4 early exit` |
| `bacf7fe` | `docs(agents): document Decider frustracion_directa priority 2b` |
| `e6ad357` | `fix(application): J.4 pago FNs, hybrid IA+pago motivo, IA phrases` (R2 residual close) |

---

## What shipped (pool truth)

### Prompt data path (item1)

- `Comprehension.needs_persona_facts` / `needs_voice_patterns` default `False` (original six still required).
- Package catalog `src/diana/config/persona_diana.json` + pure `load_persona_catalog()`; hatch force-include for wheel.
- `PersonaFactsRetriever` / `VoicePatternsRetriever` (set intersection; max 1 voice; never `nota_privada`; voice scores by largest intersection).
- Planner map order: history → context → persona_facts → voice_patterns → memory → policy → examples → schedule; universe **8** caps.
- `PolicyRetriever` dual-source static + optional pgvector; DB format fail-soft preserves static.
- Production persona = Spanish Anexo J.1; `style_rules` Director → ContextBuilder.
- Settings live at `config/settings.py` with lazy package re-export.

### Deterministic escalation (item2)

- **H3:** `emotion=="molesta"` → `escalate` / `frustracion_directa` after gray zone, before risk_high (AGENTS 2b documented in `bacf7fe`).
- **H4:** `RepetitionGuard(3)` + `RecentIntentsPort` / `SqlTraceStore.get_recent_intents` + Director Decision-only early-exit `pregunta_repetida` (fresh zeroed `EvaluationProfile` sentinel).
- **J.4:** Pre-Director catalogs; order identidad_ia → pago_precio → compromiso_real → forbidden; IA template exact string via deliver-then-escalate; hybrid motivo when IA+pago co-hit; Auth before Forbidden + VIP gate.
- **H5:** Composition injects recent_intents, guard, behavior for middleware.

---

## Review loop summary

| Item | Rounds | Issues fixed | Wontfix | Open at close | Artifacts |
|------|--------|--------------|---------|---------------|-----------|
| 1 | 3 (fix→re-review→fix→clean) | R1 **14**, R2 **4**, R3 **0** | 0 | **0** | `.grok/agent-memory/review/system-prompt-struct-item1*.md` |
| 2 | 2 (fix→re-review→fix residual→0 open) | R1 **10**, R2 **5** | R2 **1** (compromiso short tokens Anexo fidelity) | **0** | `.grok/agent-memory/review/system-prompt-struct-item2.md` · gsd log |

---

## Architecture / test gates

| Gate | Item 1 | Item 2 |
|------|--------|--------|
| arch-enforcer | PASS WITH NOTES · **0 critical** | PASS WITH NOTES · **0 critical** |
| test-guardian | suite adequate · 0 mock prohibidos | suite adequate · 0 mock prohibidos |
| Cognitive purity | held | held (no EscalationStore in Director) |
| No-touch list | evaluator/generator/TC/examples | same + item1 catalog stable |

---

## Residuals (consolidated)

Full log: `.grok/agent-memory/residuals/system-prompt-struct.md`

| Residual | Class | Notes |
|----------|-------|-------|
| Evaluator LLM payload parity for new `needs_*` | in-scope-followup | Scoring unaffected; Evaluator no-touch this pool |
| Alembic index `(chat_id, created_at DESC)` on `pipeline_traces` | out-of-scope | Volume low; PLAN residual |
| Compromiso short-token FPs (`cita`/`encuentro`/`nos vemos`) | wontfix / accepted residual | Anexo J.4 product fidelity (review R2 issue 6) |
| AGENTS.md frustracion 2b | **done** | `bacf7fe` |
| SqlTraceStore `get_recent_intents` unit | **done** | `07cc653` |
| BehaviorDeliverer protocol dupe | **done** | imports from `application.ports` only |
| Director timing buckets persona/voice | out-of-scope | observability only |
| Admin hot-edit catalog / fuzzy J.4 / keyboard labels | out-of-scope | CLARIFY deferred |
| Owner Spanish copy polish for new `tipo`/reasons | out-of-scope | product copy |
| `sentence_transformers` embedding unit fails | out-of-scope (env) | pre-existing |

---

## Learnings / patterns

1. **Layer split for hard stops** — Pure Decider rules (H3) + Decision-only Director early-exit (H4) + application pre-Director keywords (J.4) keep cognitive free of EscalationStore/Notifier.
2. **IA template is deliver-then-escalate** — Orchestrator escalate does not send `draft_text`; Behavior.deliver must run first with exact product constant.
3. **Static catalog + dual-source policy** — Persona/voice stay set-intersection (no embeddings); Policy static tema-match coexists with optional pgvector without breaking F2 gray-zone (`None`/`[]` falsy).
4. **Package data coexists with Settings** — Move `config.py` → `config/settings.py` + lazy `__getattr__` + hatch force-include so catalog load does not pull pydantic-settings and wheels ship JSON.
5. **J.4 order + hybrid motivo** — Classification priority must stay identity-first; owner motivo should still surface co-occurring pago keywords.

---

## Docs / handoff

| Artifact | Path |
|----------|------|
| This summary | `.planning/quick/system-prompt-struct/POOL-SUMMARY.md` |
| Item SUMMARYs | `item1-prompt-data-path/SUMMARY.md`, `item2-deterministic-escalation/SUMMARY.md` |
| Residuals | `.grok/agent-memory/residuals/system-prompt-struct.md` |
| Documentador report | `.grok/agent-memory/documentador/system-prompt-struct.md` |

## Next steps

1. Orchestrator **Commit Gate de pool** after docs commit.
2. Optional follow-up: Evaluator `needs_*` payload parity (small, no scoring change).
3. Defer Alembic intents index until volume justifies.
4. Accept compromiso FP residual unless product wants FN-heavy tighten.
5. Pause system-prompt-struct work unless new residuals are promoted to tickets.

---

**Pool close:** Pool `system-prompt-struct` cerrado — 2 ítems completados, tests passing, commits hechos, documentación actualizada.

---

## Residual close pack (2026-07-26)

Actionable residuals R1–R4 closed. Evidence: `.planning/quick/system-prompt-struct/RESIDUALS-CLOSED.md` · `.grok/agent-memory/residuals/system-prompt-struct.md`.

| ID | Commit | Message |
|----|--------|---------|
| R1 | `16b69f5` | Evaluator payload `needs_persona_facts` / `needs_voice_patterns` |
| R2 | `92f5cdb` | Index `pipeline_traces (chat_id, created_at DESC)` |
| R3 | `3306b15` | Director timings `persona_facts_ms` / `voice_patterns_ms` |
| R4 | `3e68176` | Spanish owner labels + tipo map for system escalate reasons |

Accepted closed without code: compromiso short-token FPs, fuzzy J.4, admin hot-edit catalog, VIP repetition threshold, embedding env fails.

