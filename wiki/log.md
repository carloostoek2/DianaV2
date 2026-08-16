# Wiki Log

> Registro cronológico de todas las acciones de la wiki. Append-only.
> Formato: `## [YYYY-MM-DD] acción | tema`
> Acciones: ingest, update, query, lint, create, archive, delete
> Al superar 500 entradas, rotar: renombrar a log-YYYY.md y empezar una nueva.

## [2026-08-11] create | Wiki inicializada

- Dominio: Sistema DianaV2 (Diana Business Bot)
- Estructura creada: SCHEMA.md, index.md, log.md, entities/{modulos,specs,tablas,comandos,personas}, concepts/, comparisons/, queries/, _archive/
- Decisión: fuentes referenciadas vía frontmatter `sources:` (no duplicadas en raw/) — ver SCHEMA.md
- Scripts del grafo copiados a scripts/wiki_graph/ (parse-knowledge-base.py, merge-knowledge-graph.py, pipeline Understand Anything)

## [2026-08-11] ingest | Pool 1 — Contrato (REQUERIMIENTOS.md v2.1 + AGENTS.md v1.3 + SPEC-1.1.md v1.5)

- Creadas 21 páginas:
  - Concepts (13): principio-rector, director-cognitivo, pipeline-cognitivo, perfil-evaluacion-multidimensional, decisor, capability-registry, aprendizaje-post-turno, anti-contaminacion, modos-de-operacion, escalacion, zona-gris-y-politicas, comunicacion-con-producto, feature-flags
  - Entities/specs (3): spec-requerimientos, spec-1-1, agents-md
  - Entities/modulos (8): telegram-layer, turn-coordinator, cognitive-core, behavior-engine, learning, llm-provider, application-services, infrastructure-persistence, jobs
- index.md actualizado (21 páginas), log.md actualizado

## [2026-08-11] ingest | Pool 2 — Specs por fase (SPEC-FASE2/3/4/5 + SPEC-EVOLUCION-AGENTE)

- Creadas 11 páginas:
  - Entities/specs (5): spec-fase2, spec-fase3, spec-fase4, spec-fase5, spec-evolucion-agente
  - Concepts (6): calibracion-de-umbrales (resuelve wikilink pendiente del Pool 1), trust-budget, detector-emocional, perfil-evolutivo, canal-atencion, memoria-vip
- index.md actualizado (32 páginas), log.md actualizado
- Wikilink pendiente restante: [[estado-del-proyecto]] (Pool 5)

## [2026-08-11] ingest | Pool 3 — Arquitectura real en código (src/diana/*)

- Inventario estructural de src/diana (173 archivos, ~40K LOC) vía docstrings AST
- Actualizadas 8 páginas de módulos con la implementación real: cognitive-core (retrievers reales, template_gate, repetition_guard, runtime_thresholds), application-services (47 archivos, familias reales, componentes shadow), jobs (8 jobs reales), llm-provider (solo DeepSeek implementado; Anthropic sin implementar), telegram-layer (handlers/middlewares reales), behavior-engine, learning (módulo mínimo; staging en application/), infrastructure-persistence (~30 repos)
- Creada 1 página: entities/comandos/superficie-admin
- index.md actualizado (33 páginas), log.md actualizado

## [2026-08-11] ingest | Pool 4 — Datos y migraciones (alembic/versions 001-026)

- Inventario real: 32 tablas en migraciones (30 en ORM models.py)
- Creadas 5 páginas de esquema por familia:
  - esquema-fase1 (base: vips, message_history, pipeline_traces, pending_deliveries, turns, escalation_events, business_connections, pending_approvals)
  - esquema-conocimiento (F2: profiles, memories, contexts, policies, examples, staging_candidates, gray_zone_queries)
  - esquema-fase3 (recontact_schedules, promo_triggers, promo_executions, learning_metrics, system_config, runtime_timers, owner_marks)
  - esquema-fase4 (persona_versions.channel_type, daily_message_limits, atencion_cycles)
  - esquema-evolucion (vip_profile, vip_profile_history, vip_mood_state, vip_trust_budget, turn_category_log, emotional_signal_log, backfill_queue)
- index.md actualizado (38 páginas), log.md actualizado

## [2026-08-11] ingest | Pool 5 — Operación y estado (ESTADO-PROYECTO, OPS_SINGLE_INSTANCE, CHANGELOG, INFORME_AUDITORIA)

- Creadas 4 páginas:
  - estado-del-proyecto (resuelve el último wikilink pendiente): F4 activa, F5 completa, evo-agente shadow con datos reales, flags en medición, pendientes
  - ops-single-instance (inventario process-local, consecuencias multi-réplica)
  - changelog (historial de cambios)
  - informe-auditoria (161 reqs: 139 ✅, 14 ⚠️, 6 🔍, 2 ❌)
- index.md actualizado (42 páginas), log.md actualizado
- **Wiki de ingesta completa: 42 páginas, 0 wikilinks unresolved**

## [2026-08-11] graph | Grafo de conocimiento completo (pipeline Understand Anything + LLM)

- Parse determinístico: 47 artículos, 7 topics, 154 wikilinks (0 unresolved)
- Análisis LLM (article-analyzer, DeepSeek vía delegación): 4 batches, 37 nodos nuevos (24 entidades + 13 claims), 50 edges implícitos (relaciones entre specs, dependencias de fases, claims del sistema)
- Merge final: **90 nodos, 238 edges, 8 layers, 7 tour steps, 0 edges rotos, 0 duplicados**
- Salidas en wiki/.ua/: knowledge-graph.json (se commitea), dashboard.html (vis.js, estático), scan/merge en intermediate/ (gitignored)
- Scripts de regeneración: scripts/wiki_graph/{parse-knowledge-base.py, merge-knowledge-graph.py, render-dashboard.py, make-graph.sh}
- Viewer oficial disponible: npx understand-anything-viewer.tgz wiki/ (Node 22)

## [2026-08-11] deploy | Telegram Mini App del grafo (grafo.srtakinky.pics)

- Dashboard v2 enriquecido: panel lateral con contenido markdown de cada página, filtros por tipo, buscador, tema claro/oscuro según Telegram WebApp, wikilinks clicables (render-dashboard.py v2, 197KB autónomo)
- Infraestructura: servidor estático systemd user (diana-graph-web.service, 127.0.0.1:8081) + Cloudflare Tunnel systemd user (cloudflared-diana-graph.service → grafo.srtakinky.pics), ambos con linger
- Bot: comando /grafo (owner-only) en admin.py con botón web_app → abre la mini app dentro de Telegram; bot reiniciado (PID nuevo, polling OK)
- Repo GitHub diana-graph (privado) creado como respaldo del dashboard (Pages no disponible en plan Free para privados)

## [2026-08-16] ingest | Auditoría profunda post-freeze (5 agentes por dominio)

- Dominio: docs vs código desde el freeze 2026-08-11 (`a80e0d9`)
- Informes: `.planning/quick/docs-audit-2026-08-16/{duena-telegram-feedback,vinculo-eventos,cognicion-conocimiento,esquema-flags,modulos}.md`
- Creadas 6 páginas:
  - Concepts: calidad-feedback, vinculo-lucien, eventos-temporales
  - Specs: spec-fase6, spec-feedback
  - Tablas: esquema-fase6 (link_events / 028)
- Actualizadas páginas de módulos (telegram, application, jobs, behavior, llm, turn-coordinator, cognitive-core, learning, infrastructure), conceptos (anti-contaminacion, capability-registry, zona-gris, decisor, feature-flags, aprendizaje-post-turno), tablas 001-026 corregidas a columnas reales + 027/029, superficie-admin
- Fuentes `docs/`: ESTADO-PROYECTO, UX, PRODUCT_OWNER_ADMIN_SANDBOX, CHANGELOG, SPEC-FEEDBACK (banner), AGENTS.md (flujos 4.13-4.16 + flags)
- index.md: 48 páginas
- Grafo Understand-Anything **no** regenerado (residual)

## [2026-08-16] update | Estado y operación

- estado-del-proyecto y changelog de wiki alineados al snapshot 2026-08-16
- Apply prod 027-029 marcado SIN VERIFICAR
- Flags Destacar/Reprender y Lucien documentados como OFF por default
