# Residuals — pool h6-template-gate

**Status:** CLOSED (pool complete; residuals deferred / documented only)  
**Date:** 2026-07-27  
**Sources:** SUMMARY · review · arch-enforcer · test-guardian

| ID | Title | Class | Action |
|----|-------|-------|--------|
| R1 | Delete dead `handle_deterministic_template_escalate` + Forbidden `behavior=` | in-scope-followup | deferred next pool |
| R2 | Expand `deteccion_ia` toward former `IDENTIDAD_IA_KEYWORDS` | out-of-scope | documented |
| R3 | Hostile short saludo past safety (`max_words=4`) | needs-human | product decision |
| R4 | ANEXO-H H6.4 `evaluation=None` doc stale (vs synthetic zeros) | out-of-scope | documented |
| R5 | Shared pure keyword matcher (cognitive ↔ application) | out-of-scope | documented |
| R6 | Owner UI soften zero scores for `plantilla_*` | out-of-scope | documented |
| R7 | Suite fixture text hygiene (`hola Diana`) | out-of-scope | documented |

## Notes

- R1 is the only **in-scope-followup** carry-forward suitable for a small hardener item.
- R3 was explicitly deferred by review (product tradeoff: short hostile text can still match saludo when word count ≤ 4).
- Keyword coverage shrink (R2) accepted by CLARIFY/PLAN; pure non-annex IA probes hit full LLM pipeline.
