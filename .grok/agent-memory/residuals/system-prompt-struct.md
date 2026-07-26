# Residuals — system-prompt-struct

**Pool:** system-prompt-struct  
**Closed:** 2026-07-26  
**Status:** pool COMPLETE; actionable residuals R1–R4 **RESOLVED** (2026-07-26); remaining items accepted wontfix / out-of-scope  

**Sources:** item1–2 SUMMARYs under `.planning/quick/system-prompt-struct/` · CLARIFY.md · impact/arch/test-guardian · hardener review R1–R2 · gsd logs · residual close pack.

---

## Resolved (residual close pack 2026-07-26)

| Residual | Class | Commit | Notes |
|----------|-------|--------|-------|
| R1 Evaluator `needs_*` payload parity | in-scope-followup | `16b69f5` | `needs_persona_facts` / `needs_voice_patterns` in evaluator user JSON |
| R2 Alembic index `(chat_id, created_at DESC)` on `pipeline_traces` | out-of-scope→done | `92f5cdb` | Migration `011_pipeline_traces_chat_intents_idx` + ORM Index |
| R3 Director timing buckets persona/voice | out-of-scope→done | `3306b15` | `persona_facts_ms` / `voice_patterns_ms` always set with other buckets |
| R4 Owner Spanish copy for H3/H4/J.4 tipos | out-of-scope→done | `3e68176` | `escalation_labels.py`; admin maps reason→tipo; notifier Spanish label |

---

## Open / deferred

*(none actionable — residual close pack complete)*

---

## Accepted wontfix / out-of-scope (do not implement)

### Compromiso short-token false positives

| Field | Value |
|-------|--------|
| **Class** | wontfix / accepted residual |
| **Why** | Short tokens `cita` / `encuentro` / `nos vemos` are Anexo J.4 product terms. Further tightening raises FN risk on real commitment probes. Bare `quedar` already removed in R1. |
| **Where** | `src/diana/application/j4_triggers.py` (compromiso catalog) |
| **Source** | hardener review item2 R2 issue 6 (wontfix) |

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

## Resolved during this pool (fix rounds — historical)

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

1. **Do not reopen** compromiso short tokens unless product accepts higher FN rate.
2. Optional product polish: keyboard labels for persona/voice capabilities.
3. Env: install optional `sentence_transformers` if embedding unit tests are desired in CI.

No auto-created implementation items were opened by this documentador pass.
