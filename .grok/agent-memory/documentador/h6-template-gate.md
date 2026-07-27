# Pool Documentation: h6-template-gate

**Items:** 1  
**Date:** 2026-07-27  
**Project:** DianaV2  
**Pool:** h6-template-gate  
**Mode:** hardener-agile · Strict TDD · effort 4  

## Consolidated Outcomes

### Item 1 — h6-template-gate

| Field | Value |
|-------|--------|
| Outcome | Pure `TemplateGate` (deteccion_ia → saludo) pre-pipeline in Director; supervised `approve` + synthetic eval + zero LLM on match; J.4 `identidad_ia` off middleware (pago/compromiso intact); composition wire + persona cleanup; fix-round phrase boundaries, `/traza` generated_text, forbidden annex-phrase sanitize, hybrid tests. |
| Commits (9) | `7674aa6` · `ce6ab78` · `e19865f` · `d6221f7` feat · `271e11d` · `1aeb4cc` · `6dd3d18` · `f8f9166` · `7d1f1e2` fix/docs |
| Tests | TG critical **155** · PLAN safety-net **723** → **729** post-fix · H6.6 5/5 PASS |
| Gates | arch PASS WITH NOTES **0 critical** · TG suite OK **0 mocks prohibidos** · self-check PASSED · review **0 open** after 3 rounds |

### Pool aggregate

| Metric | Value |
|--------|--------|
| Items | **1** complete |
| Review effort / rounds | **4** / **3** |
| Issues fixed (cumulative) | bug **4** · suggestion **4** · nit **4** (R1: 11, R2: 1, R3: 0) |
| Arch critical | **0** |
| TG mocks prohibidos | **0** |
| Product code dirty at documentador close | **none** (`.env.example` pre-existing dirty — left uncommitted) |

## Learnings / Patterns

1. **TemplateGate belongs in Cognitive Core, not Forbidden MW** — greetings/IA probes need supervised draft queue, not silent escalate/deliver (ANEXO-H H6.1; CLARIFY lock).
2. **Cognitive purity forbids importing application matchers** — local `_kw_hit` (or future neutral pure helper) instead of `match_keywords` from `j4_triggers`.
3. **Synthetic evaluation required** — `Decision.evaluation` is non-optional; H4-style zeros unlock TO approve / Admin draft path (ANEXO-H H6.4 text saying `evaluation=None` is stale).
4. **Optional gate in unit fixtures** — default `"hola Diana"` false-fires saludo unless `template_gate=None` in `make_director`.
5. **Annex IA triggers are narrower than historical J.4 keywords** — coverage shrink is intentional residual, not a gate failure.
6. **Forbidden keyword set can still swallow annex phrases** — fix-round sanitize migration/data path keeps TemplateGate phrases out of forbidden lists.

## Residuals

### Auto-items / Deferred

| Residual | Class |
|----------|--------|
| Delete dead `handle_deterministic_template_escalate` + Forbidden `behavior=` wiring | in-scope-followup |
| Hostile short saludo past safety (`max_words=4` can approve short hostile as plantilla_saludo) | needs-human |

### Out of scope (documented only)

| Residual | Class |
|----------|--------|
| Expand `deteccion_ia` toward former `IDENTIDAD_IA_KEYWORDS` | out-of-scope |
| Shared pure keyword matcher across cognitive/application | out-of-scope |
| ANEXO-H H6.4 `evaluation=None` doc stale vs synthetic zeros | out-of-scope |
| Owner UI soften zero scores for `plantilla_*` | out-of-scope |
| Suite fixture text hygiene (`hola Diana`) | out-of-scope |

Full residual log: `.grok/agent-memory/residuals/h6-template-gate.md`.

## Roadmap Updates

- Created `.planning/quick/h6-template-gate/POOL-SUMMARY.md`
- Updated `.planning/quick/h6-template-gate/SUMMARY.md` with review stats + full 9-commit table
- Consolidated residuals index under `.grok/agent-memory/residuals/h6-template-gate.md`
- `MEMORY.md` documentador + residuals pointers
- Added `docs/ANEXO-H.md` (H6 source product annex) to docs tree if previously untracked
- No `HARDENING_ROADMAP.md` in repo — pool close recorded here + POOL-SUMMARY only

## Docs commit

`63b8ef9` — `docs(h6-template-gate): close hardener pool h6-template-gate`

## Next Steps

1. Orchestrator **Commit Gate de pool** after this docs commit.
2. Deferred follow-up candidate: dead J.4 IA helper + Forbidden `behavior=` cleanup (R1).
3. Product decision needed before coding: hostile short saludo vs safety (R3).
4. Optional docs polish: ANEXO-H H6.4 evaluation wording (R4).
