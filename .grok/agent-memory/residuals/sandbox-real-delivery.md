# Residuals — pool sandbox-real-delivery

**Status:** CLOSED (pool complete; residuals deferred / documented only)  
**Date:** 2026-07-27  
**Sources:** SUMMARY · CLARIFY · review HARD `351a11fc` · arch-enforcer · test-guardian · PRODUCT_OWNER

| ID | Title | Class | Action |
|----|-------|-------|--------|
| R1 | Soft warn when activating sandbox on allowlisted VIP chat | out-of-scope | documented; PRODUCT_OWNER operator risk |
| R2 | Multi-replica sandbox session store | out-of-scope | documented (CLARIFY) |
| R3 | Gray-zone full path without vip_id | out-of-scope | demote path retained; full path deferred |
| R4 | Historical item4 claim “sandbox forces fake_delivery” | superseded | delivery contract only; isolation via `should_persist` |

## Notes

- **R1** is the main product residual after real delivery: `/sandbox on <chat_id>` targets the chat that **receives** real Telegram messages when mode ≠ `fake_delivery`. Mitigation in docs: dedicated test chat. Soft warn not implemented this pool.
- **R4** does not reopen item4 isolation work — learning skip, doctrine demote without vip_id, staging skip, and recontact skip remain green.
- No **in-scope-followup** auto-item created; next work only if product asks for soft warn UX.
