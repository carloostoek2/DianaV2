# Residuals — pool H7+H9 (+ residuales close 2026-07-28)

**Hardener pool closed:** 2026-07-27  
**Residuals pool closed:** 2026-07-28  
**Items (hardener):** H7 corrections+history · H9 schedule real  
**Items (residuales):** VIP sandbox history · multi-seg history · H9.5 CDMX · recontact history · Promote UI  
**Status:** hardener COMPLETE · residuales COMPLETE · review 0 open · docs updated

## H7 residuals

| Title | Class | Action |
|-------|-------|--------|
| ANEXO-H / README status update for H7 | out-of-scope | **DONE** (documentador hardener 2026-07-27) |
| Promote UI REQ-ADM-08 | was out-of-scope → product item | **DONE** 2026-07-28 — `/staging` list + promote/discard; commits `df0f5fc` `1330dec` `a18d68c` `caa8cf4`; review 0 |
| Recontact owner history | was out-of-scope | **DONE** 2026-07-28 — post-success `role=owner` + sandbox gate; commits `84fcf69` `73eaea6`; review 0 |
| Promo owner history | out-of-scope (CLARIFY) | **documented only — NO** (anti-contaminación / no-VIP; explicit non-goal) |
| Multi-segment message_ids (all segments) | was deferred follow-up | **DONE** (pre-shipped on branch; verify-only) — `16773ee`..`50178c4`; 1 fila/segmento |
| VIP inbound history under sandbox | was out-of-scope pre-H7 | **DONE** 2026-07-28 — `should_persist` gate on VIP append; `0cb21db` `a8212b1`; review 0 |

## H9 residuals

| Title | Class | Action |
|-------|-------|--------|
| ANEXO-H H9 status row | out-of-scope | **DONE** (documentador hardener 2026-07-27) |
| `contratos_restantes.md` half-seat schedule wording | docs polish | **DONE** 2026-07-28 (documentador residuales close) |
| H9.5 `is_first_message_of_day` UTC vs CDMX | was polish residual | **DONE** 2026-07-28 — America/Mexico_City civil day; `65dcc22` `5aae5be`; review 0 |

## Promote UI residuals (from residual-promote-ui SUMMARY — not blocking)

| Title | Class | Action |
|-------|-------|--------|
| Embed on promote (zero vector) | out-of-scope | document only — backlog |
| CAS promote TOCTOU | out-of-scope | document only — keyboard clear mitigates UX |
| Policy promote UI | out-of-scope | CLARIFY example-only |
| Promote buttons on correction notify | out-of-scope | queue `/staging` is MVP |
| README/ANEXO-H staging docs sync | in-scope-followup | **DONE** this documentador pass |

## Queue note

- Residuales del hardener H7+H9 **cerrados** en pool 2026-07-28 (5 ítems + multi-seg pre-shipped).
- Promo history permanece **NO** por decisión CLARIFY (anti-contaminación).
- Sin auto-items nuevos bloqueantes. Backlog opcional: embed on promote, CAS, policy promote UI.
- Anexo H núcleo sigue 10/10; residuales de producto/history/TZ/UI del pool residuales: DONE.
