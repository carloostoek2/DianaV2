# SCOPE CLARIFICATION — owner-admin-sandbox

**Fecha:** 2026-07-27  
**Producto canónico:** `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md`  
**Estado:** LOCKED (ready for plan)

## Decisiones bloqueadas

| ID | Decisión |
|----|----------|
| G1 | Solo la dueña administra suscriptores (CRUD completo). |
| G2 | Todo admin/ops por Telegram; comandos primero; menú unificado después. |
| G3 | Day-0 sin suscriptores reales; se agregan cuando la dueña los da de alta. |
| P1 | Perfil real editable = **hechos + notas** únicamente; identidad fija no se edita ahí. |
| S1 | Sandbox reutiliza **6 perfiles v1** (`nuevo`, `cercano`, `distante`, `intenso`, `vip_largo`, `inyeccion_previa`). |
| S2 | Aislamiento: catálogo estático en repo + sesión in-process; **sin** persistir aprendizaje; delivery no real. |
| S3 | Activación simple: panel/comandos tipo v1 (`on/off/perfil/perfiles/estado/reset`). |
| U1 | VIP real + sandbox en el **mismo flujo admin** (mismo router/menú). |

## Fuera de scope (este cambio)

- Multi-réplica sandbox  
- Edición live del catálogo fixture por Telegram  
- Seed SQL de VIPs reales  
- Schedule REAL / naturalness multi-retry  

## Assumptions

- Adaptar shape v1 `facts`/`notes` → `profiles.content` en V2.  
- Estilo de comandos alineado al admin actual del repo.  
- `FEATURE_SANDBOX_ENABLED` gatea la superficie sandbox.

## Next

**Done.** Pool `owner-admin-sandbox` CLOSED 2026-07-27 — see `POOL-SUMMARY.md`.
