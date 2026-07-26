# Agent Memory Index

## Impact Analyzer

- [01-foundation](impact-analyzer/01-foundation.md) — 2026-07-22 — Scaffold + config + DB F1 + domain models (ITEM 1/4)
- [02-cognitive-core](impact-analyzer/02-cognitive-core.md) — 2026-07-22 — Cognitive pipeline + LLMProvider/DeepSeek (ITEM 2/4); ports+DI vs import purity
- [03-application-behavior](impact-analyzer/03-application-behavior.md) — 2026-07-22 — TurnCoordinator/Orchestrator/Admin/Behavior/Learning (ITEM 3/4); no auto-send; supersede+cancel
- [04-telegram-wiring](impact-analyzer/04-telegram-wiring.md) — 2026-07-22 — Telegram/aiogram + composition + SQL adapters + recovery startup + acceptance (ITEM 4/4)
- [analyst-contract](impact-analyzer/analyst-contract.md) — 2026-07-23 — Align Analyst/Comprehension to docs/contrato_analista.md (history input, emotion enum, required needs_*, A.6 retry+fail)
- [evaluator-contract](impact-analyzer/evaluator-contract.md) — 2026-07-23 — Align Evaluator to contrato_evaluador.md Anexo B (EvaluatorInput + bloques_incluidos, B.6 retry+fail, doctrine prompt)
- [planner-contract](impact-analyzer/planner-contract.md) — 2026-07-23 — Align Planner to docs/contratos_restantes.md Anexo C (remove forced knowledge.history; C.3 minimum knowledge)
- [context-builder-contract](impact-analyzer/context-builder-contract.md) — 2026-07-23 — Align ContextBuilder to docs/contratos_restantes.md Anexo D (D.4 order current-turn last; BuiltContext dual return; contexto_excede_limite)
- [generator-contract](impact-analyzer/generator-contract.md) — 2026-07-23 — Align Generator to docs/contratos_restantes.md Anexo E (E.4 empty retry→failed; remove empty_draft escalate; typed generador_salida_vacia)
- [decider-contract](impact-analyzer/decider-contract.md) — 2026-07-23 — Align Decider to docs/contratos_restantes.md Anexo F (F1 approve\|escalate only; regenerate residual; safety+risk matrix; optional mode_restriction + thresholds wiring)
- [turn-coordinator-contract](impact-analyzer/turn-coordinator-contract.md) — 2026-07-23 — Align TurnCoordinator to docs/contratos_restantes.md Anexo G (G.2/G.3.1 owner discard gap; G.4 in-process OK; G.5 lock timeout residual)
- [registry-retrievers-contract](impact-analyzer/registry-retrievers-contract.md) — 2026-07-23 — Align Registry+Retrievers to docs/contratos_restantes.md Anexo H (Context H.3 fields; History empty []; schedule half-register; stubs null; no cross-retriever)
- [behavior-engine-contract](impact-analyzer/behavior-engine-contract.md) — 2026-07-23 — Align BehaviorEngine to docs/contratos_restantes.md Anexo I (I.3 sequence OK; I.4 pre-send supersede + bounded retries missing; mode enum; I.5 fail surface)
- [f3-item1-foundation](impact-analyzer/f3-item1-foundation.md) — 2026-07-25 — F3 Pool1 item1: flags + thresholds + Decision.action `send` (type/config only; no Decider/orchestrator send path)
- [f3-item2-decider](impact-analyzer/f3-item2-decider.md) — 2026-07-25 — F3 Pool1 item2: Decider autonomous rules H3.1 (send iff flag+*_min; no orchestrator/AutonomousModeService)
- [f3-item3-ams](impact-analyzer/f3-item3-ams.md) — 2026-07-25 — F3 Pool1 item3: AMS + orch send→Behavior.deliver + composition wire; auto_send schema gap; deliver-outside-lock
- [f3-item4-behavior](impact-analyzer/f3-item4-behavior.md) — 2026-07-25 — F3 Pool1 item4: Behavior is_frozen hard-check + DeliveryContext allow_split/quirks + deliver_with_sequence + FEATURE_ADVANCED_BEHAVIOR wiring (H3.6 parcial)
- [telegram-hardener-3w-item1-error-safety](impact-analyzer/telegram-hardener-3w-item1-error-safety.md) — 2026-07-26 — ErrorHandler outermost + callback/business guards + FreezeCheck fail-CLOSED on lookup error
- [telegram-hardener-3w-item2-ops-surface](impact-analyzer/telegram-hardener-3w-item2-ops-surface.md) — 2026-07-26 — GET /health + RateLimitMiddleware + DedupMiddleware (telegram/ops edge only; ErrorHandler stays outermost)
- [telegram-hardener-3w-item3-thin-handlers](impact-analyzer/telegram-hardener-3w-item3-thin-handlers.md) — 2026-07-26 — Extract trace/metrics presentation from thick handlers into AdminTraceService/AdminMetricsService (plain text/DTOs; no aiogram in application)
- [telegram-hardener-3w-item4-scale-debt](impact-analyzer/telegram-hardener-3w-item4-scale-debt.md) — 2026-07-26 — Single-instance docs + CorrectSession UX/logging + modest orch extract + log_swallowed (no Redis)

## Arch Enforcer

- [01-foundation](arch-enforcer/01-foundation.md) — 2026-07-22 — **PASS WITH NOTES**, 0 critical → handoff test-guardian
- [02-cognitive-core](arch-enforcer/02-cognitive-core.md) — 2026-07-22 — **PASS WITH NOTES**, 0 critical → handoff test-guardian
- [03-application-behavior](arch-enforcer/03-application-behavior.md) — 2026-07-22 — **PASS WITH NOTES**, 0 critical → handoff test-guardian
- [04-telegram-wiring](arch-enforcer/04-telegram-wiring.md) — 2026-07-22 — **PASS WITH NOTES**, 0 critical → handoff test-guardian
- [analyst-contract](arch-enforcer/analyst-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; pre-fix medium (ValueError→A.6) closed by hardener `36e1fed`
- [evaluator-contract](arch-enforcer/evaluator-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; B.1–B.6 + names-only blocks + notify OK
- [planner-contract](arch-enforcer/planner-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; C.3 no force-history; empty plan legal
- [context-builder-contract](arch-enforcer/context-builder-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; D.4 order + dual BuiltContext + contexto_excede_limite notify
- [generator-contract](arch-enforcer/generator-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; E.4 empty fail closed + no empty_draft escalate + purity
- [decider-contract](arch-enforcer/decider-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; F1 approve|escalate only; matrix safety→risk→approve; mode_restriction audit; purity
- [turn-coordinator-contract](arch-enforcer/turn-coordinator-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; G.2/G.3 matrix + owner MW supersede + G.5 lock timeout; no cognitive/alembic
- [registry-retrievers-contract](arch-enforcer/registry-retrievers-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; H.1–H.4 bare resultado + schedule half-register + no cross-retriever; D.5 intact
- [behavior-engine-contract](arch-enforcer/behavior-engine-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; I.4 pre-send + no cognitive import + I.5 Admin fail path; fake_delivery record-only
- [f3-item1-foundation](arch-enforcer/f3-item1-foundation.md) — 2026-07-25 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; type/config only; Decider matrix untouched; flags default false; migration 006 chain OK
- [f3-item2-decider](arch-enforcer/f3-item2-decider.md) — 2026-07-25 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; AGENTS priority + dual thresholds + flag-gated send; composition/orchestrator fail-closed until item3
- [f3-item3-ams](arch-enforcer/f3-item3-ams.md) — 2026-07-25 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; AMS L2 + orch deliver outside lock + composition; learning post-turn; flags default false
- [f3-item4-behavior](arch-enforcer/f3-item4-behavior.md) — 2026-07-25 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; engine is_frozen hard-check + dual-gate split/quirks + deliver_with_sequence + FEATURE_ADVANCED_BEHAVIOR wiring; Behavior purity OK
- [f3-item4b-rich-quirks](arch-enforcer/f3-item4b-rich-quirks.md) — 2026-07-26 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; three kinds pause|natural_split|typo_correct under dual gate; pure quirks.py; no LLM; composition p=0.05
- [f3-p2-item1-schema](arch-enforcer/f3-p2-item1-schema.md) — 2026-07-26 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; 008 recontact/promo schema+ORM+thin repos; zero runtime; flags stay false
- [f3-pool2-proactivity](arch-enforcer/f3-pool2-proactivity.md) — 2026-07-26 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; pool items 1–4: no LLM recontact/promo, promo exact match, TC BR-07 cancel, Behavior acts-only, flags default false, layers OK; medium residual claimed approvals in is_blocked
- [f3-pool3-metrics](arch-enforcer/f3-pool3-metrics.md) — 2026-07-26 — **PASS WITH NOTES**, 0 critical; calibration jobs-only + flag-gated threshold writes; metrics observational; dashboard pure; margin 0.05; EAV; residuals: hourly cal job / baseline cache / no hot-reload
- [f3-residuals](arch-enforcer/f3-residuals.md) — 2026-07-26 — **PASS WITH NOTES**, 0 critical (re-audit); RuntimeThresholds in cognitive; App→Cog only; AMS mins still ctor-frozen (medium); handoff test-guardian
- [telegram-hardener-3w-item1-error-safety](arch-enforcer/telegram-hardener-3w-item1-error-safety.md) — 2026-07-26 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; ErrorHandler outermost + Freeze fail-closed + callback/business edge guards; telegram-only scope
- [telegram-hardener-3w-item2-ops-surface](arch-enforcer/telegram-hardener-3w-item2-ops-surface.md) — 2026-07-26 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; Dedup+RateLimit order + health stdlib at telegram edge; F3 flags intact; no cognitive
- [telegram-hardener-3w-item3-thin-handlers](arch-enforcer/telegram-hardener-3w-item3-thin-handlers.md) — 2026-07-26 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; no aiogram in application; keyboards only telegram; handlers thin; no cognitive
- [telegram-hardener-3w-item4-scale-debt](arch-enforcer/telegram-hardener-3w-item4-scale-debt.md) — 2026-07-26 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; single-instance docs honest; learning post-turn; deliver outside lock; log_swallowed purity

## Test Guardian

- [01-foundation](test-guardian/01-foundation.md) — 2026-07-22 — **suite protege adecuadamente**, 31 passed, 0 mocks prohibidos → paso 6
- [02-cognitive-core](test-guardian/02-cognitive-core.md) — 2026-07-22 — **suite protege adecuadamente**, 122 passed, 0 mocks prohibidos (FakeLLM+MockTransport OK) → paso 6
- [03-application-behavior](test-guardian/03-application-behavior.md) — 2026-07-22 — **suite protege adecuadamente**, 200 passed, 0 mocks prohibidos; +FakeLLM happy path + R2 cancel assert → paso 6
- [04-telegram-wiring](test-guardian/04-telegram-wiring.md) — 2026-07-22 — **suite protege adecuadamente**, 289 passed, 0 mocks prohibidos; +correct callback FSM/auth tests → paso 6
- [analyst-contract](test-guardian/analyst-contract.md) — 2026-07-23 — **suite protege adecuadamente**, 147 passed (critical+TAC), 0 mocks prohibidos; +limit-8 history test → paso 6
- [evaluator-contract](test-guardian/evaluator-contract.md) — 2026-07-23 — **suite protege adecuadamente**, 123 primary / 355 full unit, 0 mocks prohibidos; hardener locks B.6/doctrine → documentador
- [planner-contract](test-guardian/planner-contract.md) — 2026-07-23 — **suite protege adecuadamente**, Anexo C.1–C.4 locked (13 planner + director omit-history), 0 mocks prohibidos; FakeLLM only on director LLM edge → paso 6
- [context-builder-contract](test-guardian/context-builder-contract.md) — 2026-07-23 — **suite protege adecuadamente**, D.4 order + dual BuiltContext + size-fail notify locked, 0 mocks prohibidos; full unit 388 → paso 6
- [generator-contract](test-guardian/generator-contract.md) — 2026-07-23 — **suite protege adecuadamente**, E.4 empty retry + typed fail notify + no empty_draft, 0 mocks prohibidos; tightened E.1 prompt assert; full unit 396 → paso 6
- [decider-contract](test-guardian/decider-contract.md) — 2026-07-23 — **suite protege adecuadamente**, residual naturalness→approve + mode_restriction + F1 action lock + matrix order, 0 mocks prohibidos; primary 21+10+4+1+11 → paso 6
- [turn-coordinator-contract](test-guardian/turn-coordinator-contract.md) — 2026-07-23 — **suite protege adecuadamente**, G.3 matrix + owner supersede + G.5 timeout + concurrency, 0 mocks prohibidos; 17 coordinator + 5 owner MW + 70 related / 414 full unit → paso 6
- [registry-retrievers-contract](test-guardian/registry-retrievers-contract.md) — 2026-07-23 — **suite protege adecuadamente**, H.1–H.4 bare resultado + schedule half-register + Context H.3 + empty history [] + H.4 AST gates, 0 mocks prohibidos; primary 81 / wiring 26 / full unit 425 → paso 6
- [behavior-engine-contract](test-guardian/behavior-engine-contract.md) — 2026-07-23 — **suite protege adecuadamente**, I.4 pre-send+retries + fake_delivery + I.5 Admin fail, 0 mocks prohibidos; behavior 23 / full unit 443 / TAC 8 → paso 6
- [f3-item1-foundation](test-guardian/f3-item1-foundation.md) — 2026-07-25 — **suite protege adecuadamente**, Decision.send + 5 F3 flags false + dual thresholds SPEC + migration 006 seeds + Decider no-send, 0 mocks prohibidos; item suite 149 (executor) → run-tests orchestrator
- [f3-item2-decider](test-guardian/f3-item2-decider.md) — 2026-07-25 — **suite protege adecuadamente**, F3 Decider autonomous matrix (flag/mins/fallback/priorities/boundary/dual surfaces), 0 mocks prohibidos; 45 primary (executor) → run-tests orchestrator
- [f3-item3-ams](test-guardian/f3-item3-ams.md) — 2026-07-25 — **suite protege adecuadamente**, AMS L1/L2 + orch send outside lock + composition wire + auto_send schema, 0 mocks prohibidos; primary 171 / full unit 686 (executor) → run-tests orchestrator
- [f3-item4-behavior](test-guardian/f3-item4-behavior.md) — 2026-07-25 — **suite protege adecuadamente**, C1–C6 frozen hard-check + dual-gate split/quirks + deliver_with_sequence + FEATURE_ADVANCED_BEHAVIOR wiring, 0 mocks prohibidos; primary 135 / full unit 713 (executor) → run-tests orchestrator
- [f3-item4b-rich-quirks](test-guardian/f3-item4b-rich-quirks.md) — 2026-07-26 — **suite protege adecuadamente**, three quirk kinds (pause/natural_split/typo) + dual-gate + purity, 0 mocks prohibidos; primary 124 (executor) → run-tests orchestrator
- [f3-p2-item1-schema](test-guardian/f3-p2-item1-schema.md) — 2026-07-26 — **suite protege adecuadamente**, migration 008+ORM19+ports/repos surface+seeds, 0 mocks prohibidos; executor 68 passed → run-tests + review
- [f3-pool2-proactivity](test-guardian/f3-pool2-proactivity.md) — 2026-07-26 — **suite protege adecuadamente**, pool2 items1–4 (schema+recontact matrix+BR-07 cancel+promo re-intro), 0 mocks prohibidos; executor packages 68/133/113/139 → run-tests + review/documentador
- [f3-pool3-metrics](test-guardian/f3-pool3-metrics.md) — 2026-07-26 — **suite protege adecuadamente**, pool3 items1–4 (calibrate margin/drift, §7.1 EAV, /resumen, composition+main jobs flags), 0 mocks prohibidos; executor packs ~90/24/20+/113 → documentador/review
- [telegram-hardener-3w-item1-error-safety](test-guardian/telegram-hardener-3w-item1-error-safety.md) — 2026-07-26 — **suite protege adecuadamente**, freeze fail-closed + ErrorHandler + callback/business guards; 0 mocks prohibidos; item 32 + telegram 134 + full unit 987 → paso 6 / commit gate
- [telegram-hardener-3w-item2-ops-surface](test-guardian/telegram-hardener-3w-item2-ops-surface.md) — 2026-07-26 — **suite protege adecuadamente**, Dedup+RateLimit+health+Freeze@6; 0 mocks prohibidos; focused 62 + telegram 153 + full unit 1011 → paso 6 / item3 gate
- [telegram-hardener-3w-item3-thin-handlers](test-guardian/telegram-hardener-3w-item3-thin-handlers.md) — 2026-07-26 — **suite protege adecuadamente**, format goldens list/summary/step + caps 200/80/1800; thin handlers; 0 mocks prohibidos; focused 121 → paso 6 / item4 gate
- [telegram-hardener-3w-item4-scale-debt](test-guardian/telegram-hardener-3w-item4-scale-debt.md) — 2026-07-26 — **suite protege adecuadamente**, log_swallowed + CorrectSession resolve/expired UX + orch/TC counters + OPS docs; 0 mocks prohibidos; item bundle 109 → paso 6 / pool close

## Documentador

- [mvp-fase1-pool](documentador/mvp-fase1-pool.md) — 2026-07-22 — Pool MVP Fase 1 closed: 4 items, 297 unit tests, AC/TAC map, F2 residuals
- Consolidated SUMMARY: `.planning/phases/MVP-FASE1-SUMMARY.md`
- [analyst-contract](documentador/analyst-contract.md) — 2026-07-23 — Pool analyst-contract-update closed: 1 item, effort 4, 2 review rounds, 0 open; primary 150; decisions in `.planning/quick/analyst-contract/decisions.md`
- [evaluator-contract](documentador/evaluator-contract.md) — 2026-07-23 — Pool evaluator-contract closed: 1 item, effort 4, 2 review rounds (r1: 5 open fixed, r2: 0), full unit 355; decisions in `.planning/quick/evaluator-contract/decisions.md`
- [remaining-contracts-cognitive](documentador/remaining-contracts-cognitive.md) — 2026-07-23 — Pool remaining-contracts-cognitive (1/2) closed: 4 items Anexos C–F (planner, context-builder, generator, decider F1-safe); 0 critical arch; final reviews 0 open; handoff Pool 2 = G–I
- [remaining-contracts-app](documentador/remaining-contracts-app.md) — 2026-07-23 — Pool remaining-contracts-app (2/2) closed: 3 items Anexos G–I (turn-coordinator, registry-retrievers, behavior-engine); 0 critical arch; HARD CLEAN all; full unit 443; **C–I complete across both pools**
- [trazabilidad](documentador/pool-2026-07-25-trazabilidad.md) — 2026-07-25 — Pool trazabilidad closed: 1 item (modulo de trazabilidad Anexo T, 17 commits, 43 new tests, 566 unit, 0 critical arch, 6 reviewers effort 5, 2 review rounds 0 open final)
- [trazabilidad-polish](documentador/pool-2026-07-25-trazabilidad-polish.md) — 2026-07-25 — Pool trazabilidad-polish closed: 3 improvements (fechas relativas, filtro VIP, purge job), 4 commits, 62 new tests, 628 unit, effort 3, 0 plan issues, 0 regressions
- [f3-pool1-autonomous-core](documentador/f3-pool1-autonomous-core.md) — 2026-07-26 — Pool f3-pool1-autonomous-core CLOSED: items 1–4 + 4b rich quirks (H3.1/H3.2/H3.6); HARD 15fa8330·e78885f2·b3ee6a75·74d2f5d5·e4a192c5 all 0 open; flag sole enablement; AMS L1/L2; deliver outside lock; full FEATURE_ADVANCED quirks; CLARIFY tone 1ª persona amigable femenino; residuals → pool2 recontact/promo, pool3 calibration/metrics/dashboard
- Consolidated SUMMARY: `.planning/quick/f3-pool1-autonomous-core/POOL-SUMMARY.md`
- [f3-pool2-proactivity](documentador/f3-pool2-proactivity.md) — 2026-07-26 — Pool f3-pool2-proactivity CLOSED: items 1–4 (H3.3 recontact + H3.4 promo + H3.8 BR-07 cancel); arch 0 critical; TG suite OK; no LLM; flags default false; residuals → is_blocked claimed approvals (follow-up), schedule-on-message OOS, pool3 calibration/metrics/dashboard
- Consolidated SUMMARY: `.planning/quick/f3-pool2-proactivity/POOL-SUMMARY.md`
- [f3-pool3-metrics](documentador/f3-pool3-metrics.md) — 2026-07-26 — Pool f3-pool3-metrics CLOSED: items 1–4 (H3.5 calibration + H3.7 metrics/drift + H3.9 /resumen); migration 009; A2 detect_drift observational when flag off; flags default false; **F3 Pools 1–3 complete** → ops gradual flag enable
- Consolidated SUMMARY: `.planning/quick/f3-pool3-metrics/POOL-SUMMARY.md`
- Master phase status: `.planning/quick/F3-PHASE-STATUS.md`
- [telegram-hardener-3w](documentador/pool-2026-07-26-telegram-hardener-3w.md) — 2026-07-26 — Pool telegram-hardener-3w CLOSED: items 1–4 (error-safety + ops-surface + thin-handlers + scale-debt); arch 0 critical; review 0 open; single-instance OPS; residuals → Redis multi-replica, health disable flag, full orch split, recontact log_swallowed
- Consolidated SUMMARY: `.planning/quick/telegram-hardener-3w/POOL-SUMMARY.md`
- Residuals: `.grok/agent-memory/residuals/telegram-hardener-3w.md`

## Residuals

- [residuals-polish](residuals/residuals-polish.md) — pool residual index (docs-sync /fp /naturalness /profile)
