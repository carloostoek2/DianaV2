# Wiki Schema — Sistema DianaV2

> Esta wiki es la base de conocimiento compilada del sistema Diana Business Bot.
> Patrón: Karpathy LLM Wiki (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
> El agente mantiene la wiki; las fuentes viven en `docs/` del repositorio.

## Domain

Sistema DianaV2 (Diana Business Bot): automatización de chats VIP en Telegram con
pipeline cognitivo (Director determinista + componentes LLM especializados),
aprendizaje controlado (Staging Area), modos supervisado/autónomo, y evolución
por fases (Fase 1 MVP → Fase 3 Producto Completo → Fase 5 Evolución de Agente).

## Convenciones

- Nombres de archivo: minúsculas, guiones, sin espacios (ej. `director-cognitivo.md`).
- Toda página lleva frontmatter YAML (ver plantilla abajo).
- Usar enlaces entre páginas con la sintaxis de doble corchete (dos corchetes de apertura y cierre alrededor del nombre), mínimo 2 enlaces salientes por página.
- Al actualizar una página, subir la fecha `updated`.
- Toda página nueva se agrega a `index.md` bajo su sección.
- Toda acción se registra en `log.md` (append-only, rotar a `log-YYYY.md` a 500 entradas).
- **Idioma: español neutro obligatorio** (regla AGENTS.md §0.6).
- **Provenance:** en páginas que sintetizan 3+ fuentes, anexar `^[docs/<archivo>]` al
  final del párrafo cuya afirmación proviene de esa fuente.
- **Fuentes:** las fuentes NO se duplican en `wiki/raw/` — ya viven versionadas en
  `docs/` y `src/` del repositorio. Las páginas las referencian con `sources:` en el
  frontmatter (ruta relativa desde `wiki/`). `raw/` queda reservado para material
  externo sin versionar que se ingiera en el futuro.

## Frontmatter

```yaml
---
title: Nombre de la Página
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query | summary
tags: [de la taxonomía de abajo]
sources: [../../docs/REQUERIMIENTOS.md]
confidence: high | medium | low   # opcional
contested: true                    # opcional
contradictions: [otra-pagina]      # opcional
---
```

## Taxonomía de tags (16)

Definir aquí TODO tag nuevo ANTES de usarlo. Regla: todo tag de una página debe
aparecer en esta taxonomía.

- **arquitectura** — diseño estructural del sistema (capas, dependencias, sustituibilidad)
- **modulo** — componente/módulo concreto del sistema (Director, Decisor, Behavior, Learning…)
- **contrato** — límites duros y contratos que ningún agente puede romper
- **flujo** — flujos canónicos del pipeline (turno normal, escalación, recontacto, promo…)
- **requisito** — requisitos funcionales (REQ-*) y no funcionales (REQ-NFR-*)
- **regla-negocio** — reglas transversales de producto (BR-*)
- **modo** — modos de operación: supervisado, autónomo, sandbox, pausa
- **aprendizaje** — Staging Area, destilación de políticas, métricas, calibración
- **memoria** — cinco tipos de conocimiento, anti-contaminación, retrieval
- **politica** — doctrina estructurada, zona gris, congelación
- **spec** — documento de diseño del repositorio (SPEC-*, REQUERIMIENTOS, AGENTS)
- **decision** — decisiones de arquitectura registradas (y su justificación)
- **operacion** — despliegue, feature flags, jobs, procedimientos operativos
- **riesgo** — riesgos, excepciones, protección de cuenta y de marca
- **comparacion** — análisis comparativo entre alternativas/fases
- **estado** — estado del proyecto, hitos, versiones

## Umbrales de página

- **Crear página** cuando una entidad/concepto aparece en 2+ fuentes O es central
  para una fuente.
- **Agregar a página existente** cuando una fuente menciona algo ya cubierto.
- **NO crear** páginas para menciones al pasar, detalles menores o fuera del dominio.
- **Dividir** una página que supere ~200 líneas.
- **Archivar** a `_archive/` cuando el contenido quede totalmente superado.

## Páginas de entidad

Una página por entidad notable. Incluir:
- Visión general / qué es
- Hechos y fechas clave
- Relaciones con otras entidades (enlaces doble-corchete a otras páginas)
- Referencias a fuentes (`sources:`)

## Páginas de concepto

Una página por concepto/tema. Incluir:
- Definición / explicación
- Estado actual del conocimiento (qué aplica hoy en el sistema)
- Preguntas abiertas o debates
- Conceptos relacionados (enlaces doble-corchete a otras páginas)

## Política de actualización

1. Verificar fechas — las fuentes más nuevas superan a las antiguas.
2. Si hay contradicción genuina, anotar ambas posiciones con fechas y fuentes.
3. Marcar la contradicción en frontmatter: `contradictions: [pagina]`.
4. Señalarla en el reporte de lint para revisión del dueño.

## Notas de operación de la wiki

- La wiki se versiona en el mismo repo (`wiki/`). El grafo de conocimiento se
  genera con los scripts de `scripts/wiki_graph/` (pipeline Understand Anything:
  parse determinístico + merge; el análisis LLM de relaciones implícitas lo
  ejecuta el agente mantenedor).
- Mantenimiento: ingest puntual en cada sesión de trabajo cuando el sistema cambie;
  lint periódico; regeneración del grafo on-demand. Sin cron de vigilancia.
