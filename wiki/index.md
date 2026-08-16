# Wiki Index

> Catálogo de contenido. Toda página de la wiki listada bajo su tipo con un resumen de una línea.
> Leer primero para encontrar páginas relevantes ante cualquier consulta.
> Last updated: 2026-08-16 | Total pages: 48

## Entities — Specs

- [[spec-requerimientos]] — REQUERIMIENTOS.md v2.1: qué debe cumplir el sistema (requisitos, BR, criterios AC)
- [[spec-1-1]] — SPEC.md v1.5: contrato de diseño, stack, ADRs, modelo de datos por fase
- [[agents-md]] — AGENTS.md v1.3: límites duros de módulo, flujos canónicos, reglas de comunicación
- [[spec-fase2]] — Fase 2 (MVP+): memoria, zona gris, staging, sandbox, retrievers con pgvector
- [[spec-fase3]] — Fase 3 (Producto Completo): autónomo, recontacto, promo, calibración, métricas
- [[spec-fase4]] — Fase 4: Atención al Cliente General (canal no-VIP), perfil de canal
- [[spec-fase5]] — Fase 5: Perfil de VIP con memoria (backfill + mantenimiento)
- [[spec-evolucion-agente]] — Evolución de agente v1.2: perfil evolutivo, trust budget, detector emocional, mood
- [[spec-fase6]] — Fase 6: aviso Lucien→Diana cuando expulsan a un VIP (flag OFF)
- [[spec-feedback]] — Destacar/Reprender, gold-first, bancos por VIP (flag OFF)
- [[estado-del-proyecto]] — estado 2026-08-16: F4/F5 activas, evo-agente shadow, F6+feedback en código, apply 027-029 sin verificar
- [[changelog]] — historial de cambios del sistema
- [[informe-auditoria]] — auditoría 161 reqs: 139 ✅, 14 ⚠️, 6 🔍, 2 ❌ (AUTH-03, AUTH-07)

## Entities — Módulos

- [[telegram-layer]] — capa aiogram: stack real (Link antes de Owner), handlers de admin/link/calidad
- [[turn-coordinator]] — lock por chat en proceso; máquina de estados del Turn
- [[cognitive-core]] — pipeline puro: Director → … → Decisor; gold-first; augmenter ephemeral
- [[behavior-engine]] — delay, read, typing, split, quirks; progreso de entrega en vivo
- [[learning]] — post-turno; staging + Destacar directo a gold
- [[llm-provider]] — DeepSeek (Anthropic no implementado); thinking solo en drafts
- [[application-services]] — admin, sandbox, recontact, promo, calibración, link, eventos temporales
- [[infrastructure-persistence]] — PostgreSQL; Alembic 001–029; 34 tablas
- [[jobs]] — recontacto, calibración, purga (sin jobs nuevos post-11-ago)

## Entities — Comandos

- [[superficie-admin]] — menú de la dueña: aprobación, doctrina `dr:`, staging, memoria, Destacar/Reprender, link, eventos

## Entities — Tablas

- [[esquema-fase1]] — base F1: vips, message_history, pipeline_traces, turns, escalations, business_connections
- [[esquema-conocimiento]] — F2 + 027/029: memories, policies+vip_id, examples+quality/vip_id, staging, gray_zone, ephemeral_events
- [[esquema-fase3]] — F3: recontact_schedules, promo_triggers/executions, learning_metrics, system_config
- [[esquema-fase4]] — F4: persona_versions.channel_type, daily_message_limits, atencion_cycles
- [[esquema-evolucion]] — evolución de agente: vip_profile(_history), mood, trust_budget, turn_category, emotional_signal, backfill_queue
- [[esquema-fase6]] — F6: link_events (migración 028)

## Concepts

- [[principio-rector]] — el sistema decide, no genera; la respuesta es consecuencia
- [[director-cognitivo]] — orquestador 100 % determinista; conoce capacidades, no módulos
- [[pipeline-cognitivo]] — flujo canónico completo y sus variantes; objeto de Comprensión
- [[perfil-evaluacion-multidimensional]] — vector 7D sin score único; calibración empírica
- [[decisor]] — acciones: seguridad → zona gris → escalate (risk/frustración) → send → approve
- [[capability-registry]] — knowledge.* reales; gold-first; visibilidad vip_id; context = historial
- [[aprendizaje-post-turno]] — post-pipeline; staging + Destacar a gold (confirmación explícita)
- [[anti-contaminacion]] — Memoria VIP privada; bancos examples/policies con eje vip_id (BR-15)
- [[modos-de-operacion]] — supervisado/autónomo/sandbox/pausa/congelación; modos filtran
- [[escalacion]] — cortocircuito determinístico + escalación semántica; triage de la dueña
- [[zona-gris-y-politicas]] — consulta de doctrina, congelación, destilación estructurada
- [[comunicacion-con-producto]] — reglas del chat con la dueña; español neutro obligatorio
- [[feature-flags]] — regla de oro: comportamientos nuevos detrás de flags; rollback sin redeploy
- [[calibracion-de-umbrales]] — ajuste empírico de umbrales; margen autónomo > supervisado; incidente que prohibió auto-calibración
- [[trust-budget]] — confianza por (VIP, categoría); doble puerta del autoenvío; asimétrico por diseño
- [[detector-emocional]] — quiebre emocional heurístico (sin LLM); umbrales 0.5/0.8; escalación shadow-only
- [[perfil-evolutivo]] — stable_traits/recent_trend/sensitivities; resíntesis, decaimiento, versionado; mood
- [[canal-atencion]] — perfil no-VIP: supervisado, límite 20/día, guiones como doctrina, anti-contaminación entre canales
- [[memoria-vip]] — ficha del VIP por secciones; backfill idempotente + mantenimiento post-turno; aprobación de sensibles
- [[ops-single-instance]] — un solo proceso activo; estado process-local; consecuencias multi-réplica
- [[calidad-feedback]] — Destacar/Reprender; gold-first; flag default OFF; Atención bloqueada
- [[vinculo-lucien]] — aviso de expulsión Lucien→Diana; 3 botones; flag default OFF
- [[eventos-temporales]] — contexto con fecha de la dueña; sin flag; no contamina memoria ni ejemplos

## Comparisons

_(vacío por ahora — Pool 2+ puede generar comparaciones entre fases)_

## Queries

_(vacío — se archiva aquí respuestas valiosas)_
