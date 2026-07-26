# Pool Documentation: system-prompt-struct

**Items:** 2  
**Date:** 2026-07-26  
**Project:** DianaV2  
**Pool:** system-prompt-struct  
**Mode:** hardener-agile · system-prompt structure (Anexo J + SPEC H0–H5) · effort 4  

## Consolidated Outcomes

### Item 1 — prompt-data-path (H0–H2 + J.1 + J.5)

| Field | Value |
|-------|--------|
| Outcome | Optional Comprehension needs flags; static persona catalog (9 facts / 11 voice / 6 soft policies + voz_configurada); set-intersection PersonaFacts/VoicePatterns retrievers; planner universe 8 + emission order; Policy dual-source; Spanish persona + style_rules; Settings package move + hatch force-include. Review: voice largest-intersection + policy fail-soft + lazy Settings. |
| Commits | `5432541` … `ecafeb1` feat path; `4a84ed6` R1 (14/14); `cbfd7f8` R2 (4/4) |
| Tests | primary **211** → post-R1 **266** → post-R2 **229**; unit ~1093 with 3 embedding env fails pre-existing |
| Self-check | PASSED · review **0 open** after R3 |
| Arch / TG | PASS WITH NOTES · 0 critical · suite adequate |

### Item 2 — deterministic-escalation (H3–H5 + J.4)

| Field | Value |
|-------|--------|
| Outcome | Decider molesta→`frustracion_directa` (2b); RepetitionGuard+RecentIntentsPort+Director Decision-only `pregunta_repetida`; J.4 pre-Director catalogs (IA template deliver-then-escalate, pago/compromiso typed escalate); composition H5 wire; Auth→Forbidden order + VIP gate; AGENTS 2b docs. |
| Commits | `2159c20` … `c3d67da` feat path; R1 fixes `dbdca09`…`bacf7fe` (10 fixed); R2 `e6ad357` (5 fixed, 1 wontfix) |
| Tests | item2 **182** → R1 **197** → R2 **203**; unit **1139** (ignore embedding) |
| Self-check | PASSED · review **0 open** after R2 |
| Arch / TG | PASS WITH NOTES · 0 critical · suite adequate · 0 mock prohibidos |

### Pool aggregate

| Metric | Value |
|--------|--------|
| Items | **2** complete |
| Arch critical | **0** ×2 |
| Review open at close | **0** ×2 |
| Cognitive purity | held (no EscalationStore in Director; J.4 I/O in application/telegram) |
| No-touch | Evaluator, Generator, TurnCoordinator, ExamplesRetriever |

## Learnings / Patterns

1. **Three-layer hard stops** — Pure Decider (emotion), Decision-only Director early-exit (repetition), application middleware (keyword/IA) — keep I/O of escalate out of cognitive.
2. **IA path = Behavior.deliver then escalate** — escalate alone does not send draft; template constant only; empty template falls back to product string.
3. **Static catalog coexists with Settings** — package data under `diana.config` needs lazy Settings export + hatch force-include for wheels.
4. **Dual-source policy fail-soft** — malformed DB rows must not wipe static soft policies (J.5).
5. **Voice multi-signal** — score by `|signals ∩ tags|`, not first list hit.
6. **J.4 hybrid motivo** — identity wins classification order but owner should still see co-hit pago keywords.
7. **Anexo fidelity vs FP** — short compromiso tokens accepted as wontfix residual rather than FN-heavy tighten.

## Residuals

### Auto-items / Deferred

| Residual | Class |
|----------|--------|
| Evaluator `needs_*` payload parity | in-scope-followup |

### Out of scope / accepted (documented only)

| Residual | Class |
|----------|--------|
| Alembic intents index on `pipeline_traces` | out-of-scope |
| Compromiso short-token FPs | wontfix / accepted |
| Director timing buckets persona/voice | out-of-scope |
| Admin hot-edit / fuzzy J.4 / keyboard labels | out-of-scope |
| Owner Spanish copy polish | out-of-scope |
| VIP-level repetition calibration | deferred |
| Embedding env unit fails | out-of-scope (env) |

### Resolved in-pool (not residual anymore)

AGENTS frustracion 2b · SqlTraceStore unit · BehaviorDeliverer dupe · H4 EvaluationProfile sentinel · hatch JSON include · voice intersection · policy fail-soft · lazy Settings.

Full residual log: `.grok/agent-memory/residuals/system-prompt-struct.md`.

## Roadmap Updates

- Created consolidated pool summary: `.planning/quick/system-prompt-struct/POOL-SUMMARY.md`
- Updated item2 SUMMARY with review-loop stats + residual resolution table
- Residual log: `.grok/agent-memory/residuals/system-prompt-struct.md`
- No `HARDENING_ROADMAP.md` / F3 phase status mutation (pool is system-prompt structure hardener, not a F3 product slice)
- AGENTS.md 2b already committed in-pool (`bacf7fe`) — not re-committed here

## Docs commit

`docs(system-prompt): close hardener pool system-prompt-struct` (docs-only; no production code).
`MEMORY.md` left unstaged (agent-memory index noise unrelated to this docs set).

## Next Steps

1. Orchestrator **Commit Gate de pool** after this docs commit.
2. Optional small follow-up: Evaluator `needs_*` payload parity.
3. Defer Alembic intents index until query volume justifies.
4. Pause system-prompt-struct work unless product reopens compromiso FP policy.
