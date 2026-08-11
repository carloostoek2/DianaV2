# Wiki Index

> Catálogo de contenido. Toda página de la wiki listada bajo su tipo con un resumen de una línea.
> Leer primero para encontrar páginas relevantes ante cualquier consulta.
> Last updated: 2026-08-11 | Total pages: 42

## Entities — Specs

- [[spec-requerimientos]] — REQUERIMIENTOS.md v2.1: qué debe cumplir el sistema (requisitos, BR, criterios AC)
- [[spec-1-1]] — SPEC.md v1.5: contrato de diseño, stack, ADRs, modelo de datos por fase
- [[agents-md]] — AGENTS.md v1.3: límites duros de módulo, flujos canónicos, reglas de comunicación
- [[spec-fase2]] — Fase 2 (MVP+): memoria, zona gris, staging, sandbox, retrievers con pgvector
- [[spec-fase3]] — Fase 3 (Producto Completo): autónomo, recontacto, promo, calibración, métricas
- [[spec-fase4]] — Fase 4: Atención al Cliente General (canal no-VIP), perfil de canal
- [[spec-fase5]] — Fase 5: Perfil de VIP con memoria (backfill + mantenimiento)
- [[spec-evolucion-agente]] — Evolución de agente v1.2: perfil evolutivo, trust budget, detector emocional, mood
- [[estado-del-proyecto]] — estado verificado 2026-08-11: F4 activa, F5 completa, evo-agente shadow, flags, pendientes
- [[changelog]] — historial de cambios del sistema
- [[informe-auditoria]] — auditoría 161 reqs: 139 ✅, 14 ⚠️, 6 🔍, 2 ❌ (AUTH-03, AUTH-07)

## Entities — Módulos

- [[telegram-layer]] — capa de adaptación aiogram: middlewares Auth/Forbidden/Freeze, I/O
- [[turn-coordinator]] — serialización por chat, máquina de estados del Turn, cancelación de obsoletos
- [[cognitive-core]] — pipeline de decisión puro: Director → Analista → … → Decisor
- [[behavior-engine]] — actuación human-like (delay, read, typing, split, quirks); fuera de la cognición
- [[learning]] — aprendizaje post-turno: extracción, staging, destilación, métricas
- [[llm-provider]] — DeepSeek primario / Anthropic respaldo, hot-swap
- [[application-services]] — orquestación de casos de uso (admin, sandbox, recontact, promo, calibración)
- [[infrastructure-persistence]] — PostgreSQL único almacén durable, SQLAlchemy async, Alembic
- [[jobs]] — tareas periódicas (recontacto, calibración, purga)

## Entities — Comandos

- [[superficie-admin]] — superficie de la dueña en DM: handlers reales, aprobación, doctrina, staging, memoria, persona

## Entities — Tablas

- [[esquema-fase1]] — base F1: vips, message_history, pipeline_traces, turns, escalations, business_connections
- [[esquema-conocimiento]] — F2: memories, policies, examples, staging_candidates, gray_zone_queries
- [[esquema-fase3]] — F3: recontact_schedules, promo_triggers/executions, learning_metrics, system_config
- [[esquema-fase4]] — F4: persona_versions.channel_type, daily_message_limits, atencion_cycles
- [[esquema-evolucion]] — evolución de agente: vip_profile(_history), mood, trust_budget, turn_category, emotional_signal, backfill_queue

## Concepts

- [[principio-rector]] — el sistema decide, no genera; la respuesta es consecuencia
- [[director-cognitivo]] — orquestador 100 % determinista; conoce capacidades, no módulos
- [[pipeline-cognitivo]] — flujo canónico completo y sus variantes; objeto de Comprensión
- [[perfil-evaluacion-multidimensional]] — vector 7D sin score único; calibración empírica
- [[decisor]] — orden de prioridades: seguridad → zona gris → frustración → risk → send → approve
- [[capability-registry]] — sustituibilidad total; capacidades knowledge.* y retrievers por fase
- [[aprendizaje-post-turno]] — nunca durante el pipeline; Staging Area + confirmación explícita
- [[anti-contaminacion]] — Memoria VIP privada; banco de ejemplos separado (BR-15)
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

## Comparisons

_(vacío por ahora — Pool 2+ puede generar comparaciones entre fases)_

## Queries

_(vacío — se archiva aquí respuestas valiosas)_
