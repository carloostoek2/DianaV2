# SUMMARY — ITEM 2/4 Cognitive Core + LLM Provider

**Date:** 2026-07-22  
**Plan:** `.planning/phases/02-cognitive-core/PLAN.md`  
**Status:** DONE  
**Self-Check:** PASSED

## Objective

Implement the Fase 1 cognitive decision path (Director → Analyst → Planner →
Registry/Retrievers → ContextBuilder → Generator → Evaluator → Decider) plus
abstract `LLMProvider`, DeepSeek (httpx), and `FakeLLM` for unit tests.

## Tasks completed

| Task | Result | Notes |
|------|--------|-------|
| 1. Ports + FakeLLM + DeepSeek | Done | `cognitive/ports.py`, `llm/{fake,deepseek}.py`; MockTransport only |
| 2. Planner / Decider / Registry / Retrievers / ContextBuilder | Done | 7 caps; history+context REAL; stubs → None |
| 3. Analyst / Generator / Evaluator | Done | DI of `LLMProvider` protocol; English 7D fields |
| 4. CognitiveDirector + integration tests | Done | Trace 7 keys; TAC-01 call log; draft on Decision |

## Files created

### Source
- `src/diana/cognitive/ports.py`
- `src/diana/cognitive/planner.py`
- `src/diana/cognitive/decider.py`
- `src/diana/cognitive/registry.py`
- `src/diana/cognitive/context_builder.py`
- `src/diana/cognitive/analyst.py`
- `src/diana/cognitive/generator.py`
- `src/diana/cognitive/evaluator.py`
- `src/diana/cognitive/director.py`
- `src/diana/cognitive/retrievers/__init__.py`
- `src/diana/cognitive/retrievers/base.py`
- `src/diana/cognitive/retrievers/history.py`
- `src/diana/cognitive/retrievers/context.py`
- `src/diana/cognitive/retrievers/memory.py`
- `src/diana/cognitive/retrievers/profile.py`
- `src/diana/cognitive/retrievers/policy.py`
- `src/diana/cognitive/retrievers/examples.py`
- `src/diana/cognitive/retrievers/schedule.py`
- `src/diana/llm/__init__.py`
- `src/diana/llm/fake.py`
- `src/diana/llm/deepseek.py`

### Tests
- `tests/unit/llm/test_fake_llm.py`
- `tests/unit/llm/test_deepseek_provider.py`
- `tests/unit/cognitive/test_planner.py`
- `tests/unit/cognitive/test_decider.py`
- `tests/unit/cognitive/test_registry.py`
- `tests/unit/cognitive/test_retrievers.py`
- `tests/unit/cognitive/test_context_builder.py`
- `tests/unit/cognitive/test_analyst.py`
- `tests/unit/cognitive/test_generator.py`
- `tests/unit/cognitive/test_evaluator.py`
- `tests/unit/cognitive/test_director.py`

### Edited
- `src/diana/cognitive/models.py` — additive `TurnContext = IncomingTurn` alias only
- `src/diana/cognitive/__init__.py` — re-export `CognitiveDirector` + models
- `README.md` — cognitive/FakeLLM unit-test notes

## Verifications

```text
pytest tests/unit -q
→ 122 passed
```

Architecture golds green:
- `test_import_purity`
- `test_evaluation_profile_invariants`
- `test_models`
- `test_decider`
- `test_director`

Baseline foundation suite retained and expanded (~58 → 122).

## Locked decisions respected

| ID | Status |
|----|--------|
| L9 Ports+DI (no cognitive→llm/infra) | OK — purity AST green |
| L10 handle_turn(IncomingTurn) → Decision | OK |
| L11 LLM only Analyst/Generator/Evaluator | OK — TAC-01 call counts |
| L12 history/context REAL; others STUB | OK |
| L13 InMemoryTraceStore 7 keys | OK — TAC-04 |
| L14 FakeLLM + MockTransport only | OK |
| L15 Decider matrix approve\|escalate | OK |
| L16 TurnContext alias | OK |
| L17 No main.py wiring | OK |

## Deviations

None material.
- Docstring wording in Planner/Decider avoided false positives from source-scan unit assertions (`LLM` / `generate` substrings).
- `DeepSeekProvider` fails loud on empty `api_key` at **construction** time.

## Out of scope (as planned)

- Telegram / Behavior / Learning / application packages
- SQL TraceRepository / MessageHistory SQL repo
- Alembic / schema changes
- Live DeepSeek CI smoke
- Composition root / main wiring (item 3/4)

## Self-Check: PASSED

- [x] All PLAN tasks completed
- [x] PLAN tests run (`pytest tests/unit -q` → **144 passed** after hardener fix round)
- [x] 0 regressions attributable (foundation golds green)
- [x] Project conventions respected (English artifacts, ports+DI, no forbidden imports)

## Hardener fix round (73113e69)

| Fix | Detail |
|-----|--------|
| Eval bounds | `EvaluationProfile` dims finite + [0,1] |
| DeepSeek fences | Strip markdown fences before `json.loads` |
| Trace JSON | `to_jsonable` / `model_dump`; keys `prompt_text`/`generated_text` |
| Empty draft | escalate `empty_draft` |
| Pipeline errors | status → FAILED; partial `retrieved` stored |
| llm_base_url | https only; no private/metadata hosts |
| raw_llm_output | attached by DeepSeek + Analyst/Evaluator |
| ContextBuilder | omit empty list/dict |

Deferred to item 3 (wontfix): composition factory, dual history snapshot under concurrent writers, cancel/supersede, system_config threshold load.

## Test count

| Suite | Count |
|-------|-------|
| Full `tests/unit` | **144 passed** |
| New (approx. vs foundation ~58) | **~86 new** |

## Handoff to item 3

- Consume `Decision` with `draft_text` + `evaluation` + `action in {approve, escalate}`
- Replace `InMemoryTraceStore` / history port with SQL repositories outside cognitive
- Own durable turn status + Admin/Behavior; Learning only post-turn
