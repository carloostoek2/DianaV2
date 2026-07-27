# POOL-SUMMARY — h6-template-gate

**Pool:** h6-template-gate  
**Mode:** hardener-agile · Strict TDD · effort **4**  
**Date closed:** 2026-07-27  
**Status:** **COMPLETE** — 1 item; arch 0 critical; review 0 open after 3 rounds  

**Sources:** `SUMMARY.md` · `CLARIFY.md` · `PLAN.md` · `docs/ANEXO-H.md` (H6) ·  
`.grok/agent-memory/review/h6-template-gate.md` · `residuals/h6-template-gate.md` ·  
`arch-enforcer/h6-template-gate.md` · `test-guardian/h6-template-gate.md` · `impact-analyzer/h6-template-gate.md` · git commits below.

---

## Objective

Ship **ANEXO-H H6** deterministic TemplateGate for short VIP greetings (`saludo_constante`) and annex IA probes (`deteccion_ia`): pure cognitive match at the top of `CognitiveDirector.handle_turn`, supervised `approve` only, **zero LLM** on match. Migrate J.4 `identidad_ia` off ForbiddenKeywordsMiddleware (no auto-deliver+escalate); keep `pago_precio` / `compromiso_real` middleware short-circuits.

| Product area | Scope covered |
|--------------|---------------|
| TemplateGate pure | `cognitive/template_gate.py` — rules ordered deteccion_ia → saludo; local `_kw_hit` |
| Director pre-pipeline | match → `_handle_template` → synthetic eval + `plantilla_*` reason |
| J.4 IA migration | classify no longer returns `identidad_ia`; pure IA → handler → gate |
| Composition + persona | inject gate (IA-first rules); drop persona `(ver J.2 / examples)` |
| Fix round | phrase boundaries, saludo aliases, `generated_text` for /traza, forbidden sanitize, hybrid tests |

Out of scope (documented residuals): expand IA keyword coverage to former `IDENTIDAD_IA_KEYWORDS`, shared pure matcher package, owner UI soften zero scores, multi-replica / unrelated F3 ops.

---

## Items

| # | Title | Status | Primary evidence |
|---|--------|--------|------------------|
| 1 | h6-template-gate | **done** | SUMMARY self-check PASSED · H6.6 5/5 PASS · safety-net **729** post-fix · arch PASS WITH NOTES · TG suite OK · review final 0 open |

**Aggregate gates:** arch-enforcer **0 critical** · test-guardian **0 mocks prohibidos** · review **0 open** (3 rounds).

---

## Review

| Metric | Value |
|--------|-------|
| Effort | 4 (slots: 3 general + tests + plan) |
| Rounds | 3 |
| R1 open | 11 (4 bug · 4 suggestion · 3 nit) → fixed |
| R2 open | 1 nit → fixed |
| R3 open | 0 |
| Cumulative fixed | bug 4 · suggestion 4 · nit 4 |

---

## Commits (9)

| Commit | Message |
|--------|---------|
| `7674aa6` | `feat(cognitive): add pure TemplateGate for deterministic reply templates` |
| `ce6ab78` | `feat(cognitive): short-circuit Director handle_turn on TemplateGate match` |
| `e19865f` | `refactor(j4): stop middleware short-circuit for IA identity probes` |
| `d6221f7` | `feat(composition): wire TemplateGate and clean persona style rule` |
| `271e11d` | `fix(cognitive): tighten TemplateGate phrase boundaries and saludo aliases` |
| `1aeb4cc` | `fix(cognitive): store generated_text on TemplateGate path for /traza` |
| `6dd3d18` | `fix(forbidden): strip TemplateGate annex phrases from forbidden keywords` |
| `f8f9166` | `test(h6): hybrid IA+compromiso, J4Hit docs, stale forbidden behavior note` |
| `7d1f1e2` | `docs(cognitive): clarify TemplateGate _kw_hit vs match_keywords` |

---

## Verification

| Gate | Result | Source |
|------|--------|--------|
| PLAN safety net (pre-fix) | 723 passed | SUMMARY |
| PLAN safety net (post-fix) | **729 passed** | SUMMARY fix round |
| TG critical matrix | 155 passed | test-guardian |
| Arch critical violations | **0** | arch-enforcer |
| Self-check | PASSED | SUMMARY |
| Review final | **0 open** | review/h6-template-gate.md |

---

## Residuals (deferred / documented)

| ID | Title | Class | Next action |
|----|-------|-------|-------------|
| R1 | Delete dead `handle_deterministic_template_escalate` + Forbidden `behavior=` | in-scope-followup | next hardener pool |
| R2 | Expand `deteccion_ia` toward former `IDENTIDAD_IA_KEYWORDS` | out-of-scope | product if coverage gap matters |
| R3 | Hostile short saludo past safety (`max_words=4`) | needs-human | product tradeoff |
| R4 | ANEXO-H H6.4 still shows `evaluation=None` (stale vs synthetic zeros) | out-of-scope | docs polish |
| R5 | Shared pure keyword matcher (cognitive ↔ application) | out-of-scope | future purity package |
| R6 | Owner UI soften zero scores for `plantilla_*` | out-of-scope | owner UX later |
| R7 | Suite fixture text hygiene (`hola Diana`) | out-of-scope | test fixtures |

Full index: `.grok/agent-memory/residuals/h6-template-gate.md`.

---

## Architecture notes (carry-forward)

- Cognitive purity preserved: gate is stdlib-only; composition may import `IA_TEMPLATE` from application.
- Template path: supervised **approve only** — never `send` / `escalate`; TO approve branch unchanged.
- Product flip: former middleware IA deliver+escalate → owner draft queue with fixed template text.
- Default unit `template_gate=None` avoids fixture false-fire on `"hola Diana"`.

---

## Close phrase readiness

> Pool `h6-template-gate` cerrado — 1 ítem completado, tests passing (729 safety-net post-fix), commits hechos (9), documentación actualizada.
