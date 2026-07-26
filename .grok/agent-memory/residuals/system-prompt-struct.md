# Residuals — system-prompt-struct

**Pool:** system-prompt-struct  
**Closed:** 2026-07-26  
**Status:** pool COMPLETE; residuals deferred / documented only / accepted wontfix  

**Sources:** item1–2 SUMMARYs under `.planning/quick/system-prompt-struct/` · CLARIFY.md · impact/arch/test-guardian · hardener review R1–R2 · gsd logs.

---

## Open / deferred

### Evaluator LLM payload parity for new `needs_*`

| Field | Value |
|-------|--------|
| **Class** | in-scope-followup |
| **Why** | Evaluator hardcodes `needs_*` list for LLM payload; new `needs_persona_facts` / `needs_voice_patterns` omitted. Scoring unaffected this pool (Evaluator was no-touch). |
| **Where** | `src/diana/cognitive/evaluator.py` (payload assembly) |
| **Notes** | Promote only if Analyst routinely sets the new flags and Evaluator prompt should mirror them. |
| **Source** | item1 SUMMARY residual · arch-enforcer item1 observation |

### Alembic index `(chat_id, created_at DESC)` on `pipeline_traces`

| Field | Value |
|-------|--------|
| **Class** | out-of-scope |
| **Why** | H4 `get_recent_intents` filters by chat + created_at; current volume low. PLAN left index as residual. |
| **Where** | `alembic/`, `pipeline_traces` table, `SqlTraceStore.get_recent_intents` |
| **Source** | item2 SUMMARY · CLARIFY assumptions · arch-enforcer item2 |

### Compromiso short-token false positives

| Field | Value |
|-------|--------|
| **Class** | wontfix / accepted residual |
| **Why** | Short tokens `cita` / `encuentro` / `nos vemos` are Anexo J.4 product terms. Further tightening raises FN risk on real commitment probes. Bare `quedar` already removed in R1. |
| **Where** | `src/diana/application/j4_triggers.py` (compromiso catalog) |
| **Source** | hardener review item2 R2 issue 6 (wontfix) |

### Director timing buckets for persona_facts / voice_patterns

| Field | Value |
|-------|--------|
| **Class** | out-of-scope |
| **Why** | Observability only; buckets still aggregate memory/policy/examples. Does not affect retrieval or decisions. |
| **Where** | `src/diana/cognitive/director.py` timing map |
| **Source** | item1 SUMMARY · arch-enforcer item1 |

### Owner-facing Spanish copy polish for new `tipo` / reasons

| Field | Value |
|-------|--------|
| **Class** | out-of-scope |
| **Why** | Product copy for notifier payloads (`frustracion_directa`, `pregunta_repetida`, J.4 tipos). Functional escalate path works. |
| **Where** | notifier payloads / owner messages |
| **Source** | item2 SUMMARY residual |

### Fuzzy J.4 / admin-editable keyword lists

| Field | Value |
|-------|--------|
| **Class** | out-of-scope |
| **Why** | Explicit non-goal (CLARIFY). Match stays exact/phrase catalogs, case-insensitive. |
| **Where** | `j4_triggers.py` |
| **Source** | CLARIFY deferred · item2 residuals |

### Admin hot-edit of persona catalog / Telegram keyboard labels

| Field | Value |
|-------|--------|
| **Class** | out-of-scope |
| **Why** | Catalog is static JSON at boot; keyboard display names for new retrievers not required for DoD. |
| **Where** | `persona_diana.json`, telegram admin keyboards |
| **Source** | item1 SUMMARY · CLARIFY deferred |

### VIP-level repetition threshold calibration

| Field | Value |
|-------|--------|
| **Class** | out-of-scope / deferred |
| **Why** | Fixed `RepetitionGuard(threshold=3)` for all VIPs per PLAN A3. |
| **Where** | composition / RepetitionGuard |
| **Source** | CLARIFY deferred |

### Embedding env unit fails (`sentence_transformers` missing)

| Field | Value |
|-------|--------|
| **Class** | out-of-scope (env) |
| **Why** | Pre-existing optional model dep; item suites ignore or full unit excludes embedding module. Not introduced by this pool. |
| **Where** | `tests/unit/cognitive/test_embedding.py` |
| **Source** | item1 SUMMARY |

---

## Resolved during this pool (fix rounds)

| Residual | Resolution | Evidence |
|----------|------------|----------|
| AGENTS.md Decider row for `frustracion_directa` (2b) | Documented priority + justification | `bacf7fe` |
| Dedicated unit for `SqlTraceStore.get_recent_intents` | Unit tests added | `07cc653` |
| Duplicate `BehaviorDeliverer` protocol | Import from `application.ports` only | fix R1 (no local class) |
| H4 early-exit `Decision.evaluation` required | Fresh zeroed `EvaluationProfile` sentinel | `694dc7d` |
| Wheel may omit `persona_diana.json` | hatch force-include | item1 R1 `4a84ed6` / `pyproject.toml` |
| Voice first-list-hit steals multi-signal | Score by largest intersection | item1 R2 `cbfd7f8` |
| Policy DB format outside try drops static | Format/merge fail-soft | item1 R2 `cbfd7f8` |
| Lazy Settings on catalog package import | `__getattr__` export | item1 R2 `cbfd7f8` |

---

## Suggested next work (not auto-created tickets)

1. **Small follow-up:** Evaluator payload list parity for `needs_persona_facts` / `needs_voice_patterns` (docs + one unit).
2. **Ops when volume rises:** Alembic index on `pipeline_traces (chat_id, created_at DESC)`.
3. **Product:** owner Spanish copy for new escalate `tipo`/reasons; optional keyboard labels for new capabilities.
4. **Do not reopen** compromiso short tokens unless product accepts higher FN rate.

No auto-created implementation items were opened by this documentador pass.
