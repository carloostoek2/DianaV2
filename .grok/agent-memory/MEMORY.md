# Agent Memory Index

## Impact Analyzer

- [01-foundation](impact-analyzer/01-foundation.md) — 2026-07-22 — Scaffold + config + DB F1 + domain models (ITEM 1/4)
- [02-cognitive-core](impact-analyzer/02-cognitive-core.md) — 2026-07-22 — Cognitive pipeline + LLMProvider/DeepSeek (ITEM 2/4); ports+DI vs import purity
- [03-application-behavior](impact-analyzer/03-application-behavior.md) — 2026-07-22 — TurnCoordinator/Orchestrator/Admin/Behavior/Learning (ITEM 3/4); no auto-send; supersede+cancel
- [04-telegram-wiring](impact-analyzer/04-telegram-wiring.md) — 2026-07-22 — Telegram/aiogram + composition + SQL adapters + recovery startup + acceptance (ITEM 4/4)
- [analyst-contract](impact-analyzer/analyst-contract.md) — 2026-07-23 — Align Analyst/Comprehension to docs/contrato_analista.md (history input, emotion enum, required needs_*, A.6 retry+fail)
- [evaluator-contract](impact-analyzer/evaluator-contract.md) — 2026-07-23 — Align Evaluator to contrato_evaluador.md Anexo B (EvaluatorInput + bloques_incluidos, B.6 retry+fail, doctrine prompt)

## Arch Enforcer

- [01-foundation](arch-enforcer/01-foundation.md) — 2026-07-22 — **PASS WITH NOTES**, 0 critical → handoff test-guardian
- [02-cognitive-core](arch-enforcer/02-cognitive-core.md) — 2026-07-22 — **PASS WITH NOTES**, 0 critical → handoff test-guardian
- [03-application-behavior](arch-enforcer/03-application-behavior.md) — 2026-07-22 — **PASS WITH NOTES**, 0 critical → handoff test-guardian
- [04-telegram-wiring](arch-enforcer/04-telegram-wiring.md) — 2026-07-22 — **PASS WITH NOTES**, 0 critical → handoff test-guardian
- [analyst-contract](arch-enforcer/analyst-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; pre-fix medium (ValueError→A.6) closed by hardener `36e1fed`
- [evaluator-contract](arch-enforcer/evaluator-contract.md) — 2026-07-23 — **PASS WITH NOTES**, 0 critical → handoff test-guardian; B.1–B.6 + names-only blocks + notify OK

## Test Guardian

- [01-foundation](test-guardian/01-foundation.md) — 2026-07-22 — **suite protege adecuadamente**, 31 passed, 0 mocks prohibidos → paso 6
- [02-cognitive-core](test-guardian/02-cognitive-core.md) — 2026-07-22 — **suite protege adecuadamente**, 122 passed, 0 mocks prohibidos (FakeLLM+MockTransport OK) → paso 6
- [03-application-behavior](test-guardian/03-application-behavior.md) — 2026-07-22 — **suite protege adecuadamente**, 200 passed, 0 mocks prohibidos; +FakeLLM happy path + R2 cancel assert → paso 6
- [04-telegram-wiring](test-guardian/04-telegram-wiring.md) — 2026-07-22 — **suite protege adecuadamente**, 289 passed, 0 mocks prohibidos; +correct callback FSM/auth tests → paso 6
- [analyst-contract](test-guardian/analyst-contract.md) — 2026-07-23 — **suite protege adecuadamente**, 147 passed (critical+TAC), 0 mocks prohibidos; +limit-8 history test → paso 6
- [evaluator-contract](test-guardian/evaluator-contract.md) — 2026-07-23 — **suite protege adecuadamente**, 123 primary / 355 full unit, 0 mocks prohibidos; hardener locks B.6/doctrine → documentador

## Documentador

- [mvp-fase1-pool](documentador/mvp-fase1-pool.md) — 2026-07-22 — Pool MVP Fase 1 closed: 4 items, 297 unit tests, AC/TAC map, F2 residuals
- Consolidated SUMMARY: `.planning/phases/MVP-FASE1-SUMMARY.md`
- [analyst-contract](documentador/analyst-contract.md) — 2026-07-23 — Pool analyst-contract-update closed: 1 item, effort 4, 2 review rounds, 0 open; primary 150; decisions in `.planning/quick/analyst-contract/decisions.md`
- [evaluator-contract](documentador/evaluator-contract.md) — 2026-07-23 — Pool evaluator-contract closed: 1 item, effort 4, 2 review rounds (r1: 5 open fixed, r2: 0), full unit 355; decisions in `.planning/quick/evaluator-contract/decisions.md`
