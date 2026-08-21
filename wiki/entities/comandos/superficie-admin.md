---
title: Superficie de Admin
created: 2026-08-11
updated: 2026-08-21
type: entity
tags: [operacion, contrato, modo]
sources: [../../src/diana/telegram/handlers/, ../../docs/UX.md, ../../docs/PRODUCT_OWNER_ADMIN_SANDBOX.md]
confidence: high
---

# Superficie de Admin

Superficie de administración de la dueña en el DM con el bot (REQ-ADM-*). Toda acción de admin exige que el emisor sea el admin configurado (middleware `owner.py`). La vía principal es el **menú** (`/start` o `/menu`); los slash commands son alias.

## Handlers reales (2026-08-16)

- **`menu.py`** — panel `🌸 Panel de Diana` y wizards (TTL 15 min + `/cancelar`).
- **`admin.py`** — comandos legacy, texto libre de Corregir/Reprender/doctrina, estado.
- **`doctrine.py`** — zona gris: `dr:` responder (sesión de texto), `dx:` usar borrador, `de:` escalar (ver [[zona-gris-y-politicas]]).
- **`staging.py`** — cola de candidatos (`sp:` promover, `sd:` descartar en dos pasos; ver [[aprendizaje-post-turno]]).
- **`memory_approval.py`** — hechos sensibles `pending_owner` (F5; ver [[memoria-vip]]).
- **`persona_admin.py`** — `persona_versions` por canal ([[canal-atencion]]); flag `FEATURE_PERSONA_ADMIN_ENABLED`.
- **`callbacks.py`** — teclado del borrador: aprobar / corregir / escalar / versiones / traza / nota; Destacar/Reprender si el flag de [[calidad-feedback]] está ON y el turno es VIP.
- **`link.py`** — decisión sobre VIP expulsado del canal (Fase 6, `link:expel|disable|keep`).
- **`business.py`** — mensajes de negocio (VIP); tags de media `[imagen]`/`[video]`/… para que el modelo vea el tipo de archivo.
- **`business_connection.py`** — gestión de la conexión de negocio.

## Teclado del borrador

| Fila | Botones | Condición |
|---|---|---|
| 1 | ✅ Aprobar · ✏️ Corregir · ⚠️ Escalar | Siempre |
| 2 | Destacar · Reprender | `FEATURE_QUALITY_FEEDBACK_ENABLED` **y** `vip_id` presente (flag **activo** en `.env`, 2026-08-21) |
| 3 | ◀ Anterior · 🔄 Regenerar · Siguiente ▶ | Siempre |
| 4 | 🔍 Traza (`vtd:` vuelve al borrador) · 📝 Agregar nota | Siempre |

Aprobar edita el mismo DM en vivo (`👀 Mensaje visto` → `✍️ Escribiendo…` → `✅ Enviado`). Regenerar muestra `♻️ Regenerando…` solo si el run arranca. Un toque stale usa tokens honestos (`stale_replaced`, `stale_already_sent`, …). El header del DM usa el `display_name` del VIP.

Destacar confirma alcance (General / Este VIP) **antes** de enviar. Reprender **entrega el texto al instante**; el combo posterior solo guarda la lección. Detalle: [[calidad-feedback]] y [[spec-feedback]].

## Menú (`m:`)

Categorías: Mis VIPs · Revisar mensajes · Modo de prueba · Métricas y aprendizaje · Historial y diagnóstico · Eventos temporales · Personalidad y reglas (flag) · Configuración.

Si falla el aviso de doctrina en un turno VIP, el orquestador descongela y degrada a `approve` (`vip_doctrine_notify_failed`) en vez de dejar un freeze de 24 h sin DM.

## Capacidades por área (REQ-ADM)

- Allowlist VIP: añadir/quitar sin redeploy (REQ-AUTH-02); tope configurable (REQ-AUTH-03).
- Estado: modo, LLM activo, salud básica (REQ-ADM-02); hot-swap de proveedor (REQ-ADM-03).
- Pausa de VIP (REQ-ADM-04), sandbox (REQ-ADM-05), traza cognitiva de respuestas (REQ-ADM-07), staging (REQ-ADM-08), métricas de aprendizaje (REQ-ADM-09).
- Notificaciones: escalaciones + triage, doctrina pendiente, perfil generado, intención de pago (canal atención), resumen semanal, expulsión del canal VIP (Fase 6).

## Reglas

- Solo la dueña (admin configurado) opera menús, aprobaciones y comandos (REQ-AUTH-08).
- Sin comandos nuevos para evolución de agente: todo vive en secciones de la ficha del VIP o del menú (EA-06).
- Los textos de la UI son español neutro obligatorio (ver [[comunicacion-con-producto]]).
- Destacar/Reprender no aplican al canal [[canal-atencion]] (REQ-ATN-13).

^[src/diana/telegram/handlers/*, docs/UX.md, docs/REQUERIMIENTOS.md §9.13]
