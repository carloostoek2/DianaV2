# SCOPE CLARIFICATION — sandbox-real-delivery

```
SCOPE CLARIFICATION (--clarify)
- Fecha/run: 2026-07-27 hardener-agile pool sandbox-real-delivery
- Fuente: petición usuario + ronda clarify (2 preguntas)
- Decisiones bloqueadas:
  - Propósito sandbox: prueba E2E real del bot (modelo + flujo completo) por la dueña en el chat con sesión activa.
  - Delivery: SÍ envío real a Telegram al chat con sandbox activo. NO forzar mode=fake_delivery por sandbox.
  - Pipeline de ejecución: Director, Decisor y actuaciones declaradas corren; no omitir el camino de decisión/delivery.
  - Conocimiento: el bot usa el perfil fixture activo (SandboxKnowledgeAugmenter / catalog).
  - Persistencia producto: "cero rastro de producto de la charla" — no learning post-turno, no staging/correcciones, no memoria viva/ejemplos derivados de esa conversación. (Igual que hoy en should_persist=false.)
  - Atajos de ejecución: SOLO quitar fake_delivery forzado por sandbox. Se MANTIENEN:
      - skip learning/staging vía should_persist
      - demote consult_doctrine → approve cuando no hay vip_id (sandbox_no_vip_doctrine)
      - recontact no programa/ejecuta sobre VIP con sandbox activo
  - fake_delivery global (settings.global_mode) sigue existiendo como modo de sistema; no se elimina el modo del BehaviorEngine.
- Fuera de scope (explícito):
  - Multi-replica session store
  - Nuevos perfiles fixture / catálogo
  - Rehacer gray-zone sin vip_id
  - Cero escritura de turns/deliveries operativos en DB (opción descartada)
  - Cambios a VIP reales / profile_content real
- Assumptions:
  - Turnos operativos / pending_deliveries pueden existir (necesarios para cancelación y estados); lo que se bloquea es el *producto* de la conversación (learning/memoria/staging).
  - Delivery mode efectivo en sandbox = settings.global_mode (supervised|autonomous), nunca forzado a fake_delivery.
  - Prefijos/razones UX de admin con [sandbox:profile] se mantienen si ya existen.
- Deferred:
  - Sandbox multi-proceso / Redis session
  - Gray zone full path sin vip_id
- Restricciones para agentes:
  - impact-analyzer: mapear _effective_delivery_mode, fake_delivery, should_persist, tests de sandbox isolation; no proponer reescribir doctrina/recontact salvo bugs colaterales del cambio de delivery.
  - gsd-planner: PLAN 2–4 tasks; foco en dejar de forzar fake_delivery en orch + admin; tests de delivery real bajo sandbox + no-persist intacto.
  - gsd-executor: Strict TDD; conventional commits; English code/comments; no tocar Learning/GrayZone/Recontact salvo wiring de tests.
  - arch-enforcer: Behavior fuera de cognición; Director determinista; learning solo post-turno; sandbox no contamina bancos vivos.
  - test-guardian: asserts de real delivery path (mode != fake_delivery cuando sandbox) + should_persist/learning skip + demote doctrine sin vip_id intacto.
```

## Product one-liner

Sandbox = full live conversation for owner testing with fixture profile; real Telegram delivery; conversation product does not persist.
