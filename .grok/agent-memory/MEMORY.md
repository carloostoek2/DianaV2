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

## Documentador

- [mvp-fase1-pool](documentador/mvp-fase1-pool.md) — 2026-07-22 — Pool MVP Fase 1 closed: 4 items, 297 unit tests, AC/TAC map, F2 residuals
- Consolidated SUMMARY: `.planning/phases/MVP-FASE1-SUMMARY.md`
- [analyst-contract](documentador/analyst-contract.md) — 2026-07-23 — Pool analyst-contract-update closed: 1 item, effort 4, 2 review rounds, 0 open; primary 150; decisions in `.planning/quick/analyst-contract/decisions.md`
- [evaluator-contract](documentador/evaluator-contract.md) — 2026-07-23 — Pool evaluator-contract closed: 1 item, effort 4, 2 review rounds (r1: 5 open fixed, r2: 0), full unit 355; decisions in `.planning/quick/evaluator-contract/decisions.md`
- [remaining-contracts-cognitive](documentador/remaining-contracts-cognitive.md) — 2026-07-23 — Pool remaining-contracts-cognitive (1/2) closed: 4 items Anexos C–F (planner, context-builder, generator, decider F1-safe); 0 critical arch; final reviews 0 open; handoff Pool 2 = G–I
- [remaining-contracts-app](documentador/remaining-contracts-app.md) — 2026-07-23 — Pool remaining-contracts-app (2/2) closed: 3 items Anexos G–I (turn-coordinator, registry-retrievers, behavior-engine); 0 critical arch; HARD CLEAN all; full unit 443; **C–I complete across both pools**
