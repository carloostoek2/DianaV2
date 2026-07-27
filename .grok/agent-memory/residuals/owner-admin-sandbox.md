# owner-admin-sandbox — residual index

**Pool:** owner-admin-sandbox  
**Status:** **CLOSED** (2026-07-27)  
**CLARIFY:** `.planning/quick/owner-admin-sandbox/CLARIFY.md`  
**POOL:** `.planning/quick/owner-admin-sandbox/POOL.md`  
**POOL-SUMMARY:** `.planning/quick/owner-admin-sandbox/POOL-SUMMARY.md`  
**Product:** `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md`  
**Created:** 2026-07-27  

## Pool items (all done)

| # | Item | Status | Path / notes | Key commits |
|---|------|--------|--------------|-------------|
| 1 | profile-write | **done** | facts/notes writers + `/vip_*` + hollow + fence | `5546b61`…`efa9d09`, fix `fa14727`/`9d9fb35`, fence `1064dcb` |
| 2 | vip-crud | **done** | list/rename/remove+purge + private gate | `5346565`, `cc120d2`, `9cd1107`, `bd96939` |
| 3 | sandbox-core | **done** | catalog 6 + SandboxService session | `07952ce` |
| 4 | sandbox-admin | **done** | commands + isolation + recontact skip | `6c1a0ff`, `462fea4`, `610d9a4`, `a0b4b12` |

## Closed in this pool

| Residual / product gap | Closed by | Notes |
|------------------------|-----------|-------|
| Real VIP profile writers (facts/notes) | item1 | Was residuals-polish OOS → promoted product → implemented |
| Prompt fencing owner profile knowledge | item1 fix | SEC-INJ-01 `1064dcb` |
| VIP list / rename / remove cascade (profiles) | item2 | Soft deactivate + best-effort purge |
| Owner private DM admin gate | item2 fix | `is_private_owner_message` `bd96939` |
| Sandbox fixture catalog (6 keys) | item3 | Package JSON + hatch include |
| Sandbox session service (v1 model) | item3 | In-process; `should_persist` |
| Sandbox owner commands / panel text | item4 | `/sandbox on|off|perfil|perfiles|estado|reset` |
| Auth bypass + inject + fake_delivery + learning skip | item4 | Turn-path isolation |
| Recontact skip for sandbox-active chats | item4 fix | `a0b4b12` composition `is_sandbox_vip` |

## Open follow-ups (deferred queue — not auto-created items)

| Residual | Class | Why | Files / origin |
|----------|-------|-----|----------------|
| Orphan profiles if VIP deactivated outside `/remove_vip` | in-scope-followup | Only admin remove path purges | admin.py · item2 |
| Wire StagingService + sandbox at composition / require chat_id on correction | in-scope-followup | Defensive gate on API only today | composition.py, staging_service.py · item4 |
| ProfilesRepo `load_only` exclude embedding | in-scope-followup | perf when writers scale | profiles.py · residuals-polish |

## Explicit OOS (CLARIFY + item SUMMARYs — do not expand without product ask)

| Residual | Origin |
|----------|--------|
| Multi-replica / multi-worker sandbox session store | CLARIFY · PRODUCT §7 · OPS_SINGLE_INSTANCE |
| Live Telegram edit of fixture catalog | CLARIFY · PRODUCT §7 |
| VIP hard-delete + `ON DELETE CASCADE` | item2 |
| Cascade memories / examples / policies / recontact on remove | item2 C1 only |
| Embedding recompute on profile write | item1 |
| Concurrent RMW locks on profile JSONB | item1 · single-instance |
| `pipeline_traces.sandbox=true` metadata | item4 optional |
| Gray-zone full path sandbox + real vip_id | item4 PLAN residual |
| RAM-only sandbox history (no SQL append) | item4 |
| freeze / pause / auto_send admin commands | item2 residual |
| Naturalness multi-retry / Schedule REAL | other residuals |

## Related

- Promoted from: `.grok/agent-memory/residuals/residuals-polish.md` (profile writers + sandbox FakeDelivery UX)
- Documentador report: `.grok/agent-memory/documentador/pool-2026-07-27-owner-admin-sandbox.md`
- Master F3 status: `.planning/quick/F3-PHASE-STATUS.md`
