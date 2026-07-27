# SUMMARY — h6-template-gate

**Item:** h6-template-gate — deterministic TemplateGate (saludo + deteccion_ia)  
**Date:** 2026-07-27  
**Status:** COMPLETE  
**Self-Check:** PASSED  
**Pool close:** COMPLETE (documentador)

## Review stats (hardener-agile)

| Metric | Value | Source |
|--------|-------|--------|
| Effort | **4** (5 slots: 3 general + tests + plan) | `.grok/agent-memory/review/h6-template-gate.md` |
| Review rounds | **3** | same |
| Round 1 open | 11 (4 bug · 4 suggestion · 3 nit) → fixed | same |
| Round 2 open | 1 nit → fixed | same |
| Round 3 open | **0** | same |
| Final open issues | **0** | same |
| Cumulative fixed severities | bug 4 · suggestion 4 · nit 4 | same |
| Arch critical | **0** (PASS WITH NOTES) | `arch-enforcer/h6-template-gate.md` |
| Test-guardian | suite OK · 0 mocks prohibidos · critical 155 · safety-net 723→729 | `test-guardian/h6-template-gate.md` + fix round |

## Objective met

VIP short greetings and annex IA probes resolve in Cognitive Core via pure **TemplateGate** at the top of `CognitiveDirector.handle_turn`, returning supervised `Decision(action="approve", reason=plantilla_*, draft_text=template, evaluation=synthetic zeros)`. Zero LLM on match. J.4 `identidad_ia` removed from middleware short-circuit; pago/compromiso unchanged. Persona style rule cleaned.

## Tasks + commits

| Task | Commit | Message |
|------|--------|---------|
| 1 Pure TemplateGate | `7674aa6` | `feat(cognitive): add pure TemplateGate for deterministic reply templates` |
| 2 Director pre-pipeline | `ce6ab78` | `feat(cognitive): short-circuit Director handle_turn on TemplateGate match` |
| 3 J.4 IA off middleware | `e19865f` | `refactor(j4): stop middleware short-circuit for IA identity probes` |
| 4 Composition + persona | `d6221f7` | `feat(composition): wire TemplateGate and clean persona style rule` |
| Fix round 1 (phrase boundaries) | `271e11d` | `fix(cognitive): tighten TemplateGate phrase boundaries and saludo aliases` |
| Fix round 1 (traza generated_text) | `1aeb4cc` | `fix(cognitive): store generated_text on TemplateGate path for /traza` |
| Fix round 1 (forbidden sanitize) | `6dd3d18` | `fix(forbidden): strip TemplateGate annex phrases from forbidden keywords` |
| Fix round 1–2 (tests + docs nits) | `f8f9166` | `test(h6): hybrid IA+compromiso, J4Hit docs, stale forbidden behavior note` |
| Fix round 2 (docs clarity) | `7d1f1e2` | `docs(cognitive): clarify TemplateGate _kw_hit vs match_keywords` |

**Pool commits (9):** `7674aa6` `ce6ab78` `e19865f` `d6221f7` `271e11d` `1aeb4cc` `6dd3d18` `f8f9166` `7d1f1e2`

## Files changed

### Created
- `src/diana/cognitive/template_gate.py`
- `tests/unit/cognitive/test_template_gate.py`
- `alembic/versions/012_strip_template_gate_from_forbidden.py` (fix round)

### Edited
- `src/diana/cognitive/director.py` — optional `template_gate`; pre-pipeline match; `_handle_template` (+ generated_text, pass gate)
- `src/diana/composition.py` — rules factory (IA first) + inject; unaccented saludo; sanitize on load
- `src/diana/application/j4_triggers.py` — classify no longer returns `identidad_ia`
- `src/diana/telegram/middlewares/forbidden.py` — no IA deliver; sanitize annex phrases
- `src/diana/config/persona_diana.json` — drop `(ver J.2 / examples)`
- `tests/unit/cognitive/test_director.py` — H6.6 director cases
- `tests/unit/application/test_j4_triggers.py` — pure IA → None; hybrid pago/compromiso
- `tests/unit/telegram/test_forbidden_mw.py` — IA pass-through + sanitize regressions
- `tests/unit/test_composition_wiring.py` — gate wired + persona assert

### No touch (verified)
- `turn_orchestrator.py`, `decider.py`, `behavior/**`, `learning/**`


## Test commands + results

```bash
# Per-task suites (all green during TDD)
pytest -q tests/unit/cognitive/test_template_gate.py tests/unit/cognitive/test_import_purity.py -v  # 9 passed
pytest -q tests/unit/cognitive/test_template_gate.py tests/unit/cognitive/test_director.py -v     # 49 passed
pytest -q tests/unit/application/test_j4_triggers.py tests/unit/application/test_deterministic_escalate.py tests/unit/telegram/test_forbidden_mw.py -v  # 31 passed
pytest -q tests/unit/test_composition_wiring.py ... (task 4 matrix)  # 102 passed

# Full safety net (PLAN)
pytest -q tests/unit/cognitive tests/unit/telegram \
  tests/unit/application/test_j4_triggers.py \
  tests/unit/application/test_deterministic_escalate.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_admin_service.py \
  tests/unit/test_composition_wiring.py -v
# → 723 passed (initial); 729 after fix round
```

## H6.6 acceptance

| # | Case | Result |
|---|------|--------|
| 1 | `"Hola"` → plantilla_saludo, draft ∈ pool, 0 Analyst/Gen/Eval | PASS |
| 2 | Long hola (5+ words) → full pipeline | PASS |
| 3 | `"eres una ia?"` → exact IA string | PASS |
| 4 | Template Decision approve only (no send/escalate) | PASS |
| 5 | persona JSON no `(ver J.2 / examples)` | PASS |

## Fix round (review a82c0f48 + rounds 2–3)

- Round 1: 11/11 open issues **fixed** (0 wontfix).
- Round 2: 1 nit fixed (`7d1f1e2` + prior test/docs).
- Round 3: **0 open**.
- Safety net **729 passed**.

## Deviations from PLAN

None. Fix round added alembic data migration 012 (in review scope).

## Residuals

1. **Expand `deteccion_ia` triggers** toward former `IDENTIDAD_IA_KEYWORDS` (sos/chatgpt/humano/…) — class: `out-of-scope`.
2. **Shared pure keyword matcher** across cognitive/application — class: `out-of-scope`.
3. **Remove dead `handle_deterministic_template_escalate`** + Forbidden `behavior=` if fully unused — class: `in-scope-followup`.
4. **ANEXO-H H6.4 docs** still show `evaluation=None` (stale vs synthetic) — class: `out-of-scope`.
5. **Owner UI** soften zero scores for `plantilla_*` — class: `out-of-scope`.
6. **Suite fixture text hygiene** (`hola Diana`) — class: `out-of-scope`.
7. **Hostile short saludo past safety** (`max_words=4` can approve short hostile text as plantilla_saludo) — class: `needs-human` (product tradeoff; deferred by review).

Index: `.grok/agent-memory/residuals/h6-template-gate.md` · Pool close: `POOL-SUMMARY.md`.

## Self-Check: PASSED

- [x] All PLAN tasks completed
- [x] PLAN pytest commands run (safety net 729 passed post-fix)
- [x] 0 regressions attributable
- [x] Project conventions respected (cognitive purity, Director determinism, supervised approve only, no TO edits)
- [x] Atomic conventional commits per work unit
- [x] Review: 3 rounds, final 0 open (R1 11 fixed + R2 1 nit + R3 clean)
- [x] skill_resolution: paths-injected
