# SPEC-FASE6.md — Vínculo entre bots: aviso de expulsión VIP (Lucien → Diana) — v1.1

Diana Business Bot / Sistema de Automatización de Chats VIP

| Campo | Valor |
|---|---|
| Nivel | Contrato de diseño e implementación para la Fase 6 |
| Basado en | SPEC-FASE5.md v1.0 + REQUERIMIENTOS.md v2.1 + SPEC-FASE2.md v2.1 + SPEC-FASE3.md v3.0 + AGENTS.md v1.3 + Telegram Bot API (Business Connections) |
| Audiencia | Ingeniería (implementación con DeepSeek en terminal; revisión posterior) |
| Versión | 1.1 — Implementado y desplegado (revisión al estado actual 2026-08-21) |
| Estado | Implementado y desplegado (verificado 2026-08-21) |
| Idioma | Español |

---

## Contexto: cómo se comunican dos bots de Telegram (vía oficial investigada)

La dueña pidió investigar la forma **oficial** de conectar dos bots. Hallazgos verificados en la documentación oficial (core.telegram.org/bots/faq + /bots/api):

1. **Los bots NO pueden verse mensajes entre sí.** El FAQ oficial es explícito: *"Bots talking to each other could potentially get stuck in unwelcome loops. To avoid this, we decided that bots will not be able to see messages from other bots regardless of mode."* → un bot no puede recibir `message`/`channel_post` de otro bot en ningún modo (ni admin, ni privacy off).
2. **La vía oficial es la conexión business (Telegram Business API).** Un usuario conecta su cuenta business a un bot; el bot recibe el update `business_connection` y a partir de ahí los updates `business_message` (mensajes de la cuenta business conectada) y puede **enviar mensajes en nombre de la cuenta business** pasando `business_connection_id` en `sendMessage`.
3. **Dos bots conectados a la MISMA cuenta business se comunican por esa vía**: el bot A envía un mensaje con su `business_connection_id` a un chat de la cuenta business; el bot B, conectado a la misma cuenta, recibe ese mensaje como `business_message`. El mensaje viaja como "mensaje de la cuenta business", no como "mensaje de un bot", por lo que la restricción del punto 1 no aplica. Esto es exactamente lo que la dueña describió: *"no se comunican directamente mediante mensajes sino por llamadas de manera interna... mediante business"*.
4. **DianaV2 ya tiene toda la infraestructura business operativa** (verificada en código y DB real):
   - Tabla `business_connections` (repo `SqlBusinessConnectionStore`) con **1 conexión activa**: `user_id=6181290784` (la dueña), `can_reply=true`, `is_enabled=true` — la cuenta business de la dueña ya está conectada a Diana.
   - `allowed_updates` incluye `business_connection`, `business_message`, `edited_business_message`.
   - `AiogramTelegramActuator` exige `business_connection_id` para enviar/leer (toda la operación VIP es por business).
   - `recover_missed_updates` recupera mensajes business caídos durante el apagado del bot.
   - Router `business_connection` persiste el alta/baja de la conexión.
5. **Lucien no tenía nada de business al arrancar esta Fase** (verificado: cero código, solo menciones en docs). Esta Fase agregó el lado emisor en Lucien (conexión + envío del aviso) y el lado receptor/decisor en Diana.

### Estado real verificado (evidencia dura)

| Dato | Valor | Cómo se verificó |
|---|---|---|
| Conexión business activa en Diana | `_-0ieT7GuEewAQAArqdqnipLbXk` → user 6181290784, can_reply=t, is_enabled=t | `psql` sobre `business_connections` |
| Owner de Diana | `OWNER_TELEGRAM_ID=6181290784` | `.env` |
| Puntos de expulsión en Lucien | `vip_service.admin_revoke_subscription` (kick manual, código `"kicked"`) y `scheduler_service._process_expired_subscriptions` (expiración) | grep `ban_chat_member` en lucienbot |
| EventBus interno de Lucien | `services/event_bus.py` (`InternalEventBus`, `EVENT_BESITOS_AWARDED`) — patrón a imitar para el emisor | código lucienbot |
| Campos de estado VIP en Diana | `vips.is_active`, `vips.paused_until`, `vips.frozen_until` (ya existen) | `models.py` |
| Head de migraciones Diana | `029_feedback_quality` (cadena 001→029; `link_events` es **028**, 027 se usó para eventos temporales) | `ls alembic/versions/` |
| Head de migraciones Lucien | `merge_trivia_config_to_main.py` / `trivia_discount_system.py` | `ls alembic/versions/` |

---

## Resumen de decisiones de producto (dueña)

1. La conexión entre Lucien y Diana se hace por la **vía business** (cuenta business de la dueña conectada a ambos bots), no por mensajes directos bot↔bot.
2. Cuando Lucien expulsa a un suscriptor del canal VIP (kick manual del admin o expiración), **le avisa a Diana** con un mensaje business al chat de coordinación.
3. Diana **verifica si ese usuario es VIP suyo** (tabla `vips` por `telegram_user_id` activo). No todos los suscriptores del canal son VIPs de Diana.
4. Si es VIP de Diana → **notifica a la dueña** indicando que se expulsó a un suscriptor de Diana del canal VIP, con las opciones: **Expulsar** (baja también en Diana), **Inhabilitar** (inhabilitación indefinida), **Mantener** (no hacer nada).
5. Si NO es VIP de Diana → no notifica; registra el evento y termina.
6. De primera instancia las opciones son esas tres; no hay flujo de confirmación de vuelta a Lucien en esta Fase (fuera de alcance).
7. Toda la Fase va detrás de un feature flag `FEATURE_LINK_ENABLED` (default `false` en código; **activo en `.env`**): apagado → comportamiento idéntico al actual.

### Decisiones cerradas en revisión (2026-08-11)

- **Chat de coordinación**: define `LINK_CHAT_ID` en ambos bots. En el despliegue actual es el **DM con el bot de Lucien** (`LINK_CHAT_ID=7360762013` en `.env`, user id del bot de Lucien), no el DM dueña↔cuenta business; el flujo bot↔bot quedó verificado E2E. <!-- VERIFY: el lado emisor (repo lucienbot) y el chat desplegado no son verificables desde este repo; ver docs/ESTADO-PROYECTO.md -->
- **Duración de "Inhabilitar"**: **indefinida** — el VIP queda inhabilitado sin fecha de fin (puede que nunca vuelva). Reactivación solo manual/por flujo posterior. Implementación: `frozen_until` con fecha lejana fija (el runtime ya descarta mensajes de VIPs con `frozen_until > now`, ver `FreezeCheckMiddleware`).
- **Texto del aviso a la dueña**: "⚠️ ATENCIÓN ⚠️\nEl suscriptor {nombre} ha sido expulsado del Canal VIP. ¿Quieres inhabilitarlo aquí?" con los 3 botones Expulsar / Inhabilitar / Mantener.

---

## 1. Propósito de esta Fase

Conectar los dos bots del negocio — **Lucien** (administra los canales, expulsa suscriptores) y **Diana** (atiende VIPs) — para que la expulsión de un suscriptor del canal VIP dispare, en Diana, una verificación y una decisión de la dueña sobre el estado de ese VIP en el sistema de Diana. La dueña recupera el control: si alguien salió del canal, decide si sigue siendo VIP de Diana, se suspende o se da de baja.

Principios rectores:

1. **La vía business es la única oficial** para bot↔bot; no se intenta comunicación directa por mensajes (prohibida por Telegram).
2. **Anti-contaminación**: los mensajes de coordinación jamás entran al pipeline cognitivo ni a `message_history`; son un canal aparte.
3. **Control humano**: la baja/suspensión de un VIP de Diana siempre la decide la dueña (nada automático destructivo).
4. **Trazabilidad**: cada evento de expulsión recibido queda registrado con su estado y decisión.
5. **Idempotencia**: el mismo evento no notifica dos veces (dedup por `event_id`).

---

## 2. Alcance de la Fase 6

### 2.1 Dentro de alcance

| ID | Área |
|---|---|
| F6-01 | Conexión business en Lucien: handler del update `business_connection` + persistencia del id |
| F6-02 | Emisor de aviso en Lucien: hook en los 2 puntos de expulsión (kick manual y expiración) |
| F6-03 | Formato del payload de coordinación (evento JSON con prefijo reservado) |
| F6-04 | Receptor en Diana: handler `business_message` filtrado por chat de coordinación + formato |
| F6-05 | Verificación de VIP en Diana (`vips` por `telegram_user_id` activo) |
| F6-06 | Notificación a la dueña con botones: Expulsar / Inhabilitar / Mantener |
| F6-07 | Acciones: baja (`is_active=false`), inhabilitación indefinida (`frozen_until`), mantener (nada) |
| F6-08 | Registro de eventos: tabla `link_events` (migración 028) + callbacks de decisión |
| F6-09 | Idempotencia (dedup por `event_id`) y anti-contaminación (fuera del pipeline) |
| F6-10 | Feature flag `FEATURE_LINK_ENABLED` en ambos bots + cableado |

### 2.2 Fuera de alcance (postergado)

| ID | Exclusión |
|---|---|
| F6-O1 | Confirmación/ack de Diana hacia Lucien (resultado de la decisión de la dueña) |
| F6-O2 | Detección de expulsiones hechas manualmente en Telegram por el admin (fuera del bot, vía `chat_member` updates) |
| F6-O3 | Sincronización inversa (baja de VIP en Diana → aviso a Lucien) |
| F6-O4 | Expulsión de Diana por otros eventos (impago, queja) — sigue siendo manual como hoy |
| F6-O5 | Más opciones de decisión (p. ej. "expulsar y reportar", "enviar aviso al VIP") |

---

## 3. Arquitectura de la conexión

```
[Lucien bot — Railway]
  admin_revoke_subscription ─┐
  scheduler (expiración) ────┼──► Evento de expulsión (user_id, canal, motivo)
                             │
                    LinkNotifier (nuevo)
                             │  sendMessage(business_connection_id=..., chat_id=CHAT_COORD, texto=payload)
                             ▼
              ┌───────────────────────────────┐
              │  Cuenta business de la dueña   │  (la misma conectada a ambos bots)
              │  (chat de coordinación)        │
              └───────────────────────────────┘
                             ▼
[Diana bot — EC2]
  business_message (chat de coordinación + prefijo [LINK])
        │
        ▼
  LinkCoordinatorMiddleware (consumo temprano, antes de OwnerDetection)
        │
        ▼
  LinkCoordinator (capa application/)
        │  1. Dedup por event_id (tabla link_events)
        │  2. Verifica VIP en vips (telegram_user_id + is_active)
        │  3. ¿Es VIP de Diana? ── no ──► registro + fin
        │              │ sí
        │              ▼
        │   notifica a la dueña (DM del bot) con botones
        │              ▼
        │   callback de la dueña: expulsar | inhabilitar | mantener
        ▼
  aplicación sobre vips (is_active=false | frozen_until=<fecha lejana> | nada) + registro de decisión
```

---

## 4. Lado Lucien (emisor)

### REQ-LNK-01 — Conexión business en Lucien

- **Qué**: Lucien debe tener la cuenta business de la dueña conectada y persistir el id para poder enviar avisos en su nombre.
- **Dónde**: nuevo handler `business_connection` en el dispatcher de Lucien (aiogram 3: `router.business_connection()`) + tabla nueva `business_connections` (espejo de la de Diana: `business_connection_id` text PK, `user_id` bigint, `user_chat_id` bigint, `is_enabled` bool, `created_at` timestamptz).
- **Límites**: solo persiste el estado de la conexión; no modifica modelos de negocio existentes.
- **Cableado**: `allowed_updates` de Lucien debe incluir `business_connection`. La dueña conecta su cuenta business a Lucien desde la app de Telegram (mismo procedimiento que ya usó con Diana).
- **Config**: nuevas claves de entorno en Lucien: `LINK_CHAT_ID` (id del chat de coordinación) y `FEATURE_LINK_ENABLED` (default `false`).

### REQ-LNK-02 — Puntos de emisión (hooks de expulsión)

- **Qué**: tras cada expulsión real del canal VIP, Lucien emite el aviso.
- **Dónde** (2 puntos verificados en el código real):
  1. `services/vip_service.py::admin_revoke_subscription` — solo cuando el resultado es `"kicked"` (ban real hecho; NO para `deactivated_only` ni `channel_inactive`).
  2. `services/scheduler_service.py::_process_expired_subscriptions` — solo cuando se ejecuta el `ban_chat_member` (línea ~218, expiración de la única suscripción activa).
- **Patrón**: imitar el `InternalEventBus` existente (`services/event_bus.py`) o llamar directo a un nuevo `LinkNotifier` tras el `ban_chat_member` exitoso. El notificador es best-effort: si el envío falla, loguea y NO rompe el flujo de expulsión.
- **Datos del evento**: `user_id` (telegram), `username` si está disponible, `channel_id` y `channel_name` del canal, `motivo` (`admin_revoke` | `expired`), `timestamp`, `event_id` (uuid generado en Lucien).

### REQ-LNK-03 — Formato del payload (contrato entre bots)

Mensaje de texto enviado por Lucien al chat de coordinación, con **prefijo reservado + JSON** en una sola línea:

```
[LINK] {"v":1,"event":"vip_kicked","event_id":"<uuid>","user_id":123456789,"username":"@user","channel_id":-1001234567890,"channel_name":"VIP Kinky","reason":"admin_revoke|expired","ts":1789123456}
```

- El prefijo `[LINK]` es el discriminador: Diana solo procesa mensajes del chat de coordinación que empiecen con él.
- Campos obligatorios: `event`, `event_id`, `user_id`, `reason`, `ts`. Opcionales: `username`, `channel_id`, `channel_name`.
- Sin emojis ni markdown alrededor del JSON (parseo estricto).

---

## 5. Lado Diana (receptor y decisor)

### REQ-LNK-04 — Receptor del aviso

- **Qué**: consume el `business_message` del chat de coordinación (y `edited_business_message` NO — los eventos no se editan) filtrando:
  1. `message.chat.id == LINK_CHAT_ID` (setting `link_chat_id` en Diana, el chat de coordinación), **y**
  2. `text.startswith("[LINK]")`.
- **Dónde (implementado)**: `LinkCoordinatorMiddleware` en `src/diana/telegram/middlewares/link.py`, registrado en `setup.py` **antes** de `OwnerDetectionMiddleware` (la implementación corrige el router planteado originalmente). El router de callbacks de decisión vive en `src/diana/telegram/handlers/link.py` (`build_link_callback_router`, incluido ANTES del catch-all). El mensaje de coordinación se consume (return None) y **nunca** llega al router de negocio ni al pipeline (anti-contaminación).
- **Límites**: si el flag `FEATURE_LINK_ENABLED` está OFF, el middleware es pass-through (no-op) → el mensaje se ignora.
- **Límites de módulo**: la capa de telegram solo parsea y delega; toda decisión vive en `application/`.

### REQ-LNK-05 — Verificación de VIP

- **Qué**: dado `user_id` del evento, Diana consulta si existe un VIP suyo activo.
- **Dónde**: nuevo servicio `LinkCoordinator` en `src/diana/application/link.py` (o `link_service.py`), usando el repo de vips existente.
- **Regla**: `SELECT … FROM vips WHERE telegram_user_id = :uid AND is_active = true`. Si no existe o está inactivo → registrar evento con `state='ignored_not_vip'` y **no** notificar.
- **Nota**: `paused_until`/`frozen_until` no excluyen de la verificación (un VIP suspendido sigue siendo VIP de Diana; la notificación igual llega).

### REQ-LNK-06 — Notificación a la dueña

- **Qué**: mensaje al DM del bot (owner `6181290784`, patrón existente `AiogramOwnerNotifier`) con teclado inline de 3 botones.
- **Dónde**: reutilizar `AiogramOwnerNotifier` (o su puerto) + teclado nuevo en `telegram/keyboards.py` (`link_kick_keyboard(event_id)`).
- **Texto aprobado por la dueña** (español neutro, sin voseo):

```
⚠️ ATENCIÓN ⚠️
El suscriptor {nombre} ha sido expulsado del Canal VIP. ¿Quieres inhabilitarlo aquí?
```

- `{nombre}` = `vips.display_name` del VIP (si existe) + `username` si vino en el payload; si no hay display_name, el id numérico. En el mensaje NO se repite el motivo (decisión de la dueña: aviso corto y directo); el detalle queda en `link_events` para consulta.
- **Callbacks**: `link:expel:<event_id>` | `link:disable:<event_id>` | `link:keep:<event_id>` (prefijo propio, manejado en router de callbacks o en el router link, ANTES del catch-all).

### REQ-LNK-07 — Acciones de la dueña

| Botón | Acción en `vips` | Detalle |
|---|---|---|
| Expulsar | `is_active = false` | Baja definitiva: el VIP deja de ser atendido por Diana. Se conserva el registro (trazabilidad). |
| Inhabilitar | `frozen_until = <fecha lejana fija>` | **Indefinido** (decisión de la dueña: puede que nunca vuelva). El runtime ya descarta los mensajes de VIPs con `frozen_until > now` (`FreezeCheckMiddleware`), así que el efecto es inmediato y sin fin. La reactivación queda para un flujo posterior/manual (limpiar el campo). |
| Mantener | sin cambios | El VIP sigue activo en Diana aunque ya no esté en el canal. |

- Fecha lejana (centinela): `2099-12-31T00:00:00Z`, default de `link_disable_frozen_until` en `settings.py` (fallback equivalente en `application/link.py`).
- Si el VIP ya no existe o ya está inactivo al momento del callback (carrera): responder "ya no aplica" y registrar `state='noop'`.
- El callback actualiza el mensaje de la dueña (quitar botones) para indicar la decisión tomada.

### REQ-LNK-08 — Registro de eventos (tabla `link_events`, migración 028)

| Columna | Tipo | Uso |
|---|---|---|
| `id` | uuid PK (default `gen_random_uuid()`) | PK |
| `event_id` | text UNIQUE NOT NULL | Idempotencia: el mismo evento de Lucien solo se procesa una vez |
| `user_id` | bigint NOT NULL | Telegram id del expulsado |
| `username` | text NULL | @username si vino en el payload |
| `channel_id` | bigint NULL | Canal de origen (payload) |
| `channel_name` | text NULL | Nombre del canal |
| `reason` | text NOT NULL | `admin_revoke` \| `expired` |
| `vip_id` | uuid NULL (FK blanda → `vips.id`) | VIP de Diana encontrado, si aplica |
| `state` | text NOT NULL default `'pending'` | `pending` \| `notified` \| `ignored_not_vip` \| `decided_expel` \| `decided_disable` \| `decided_keep` \| `noop` |
| `decision_at` | timestamptz NULL | Cuándo decidió la dueña |
| `created_at` | timestamptz NOT NULL default now() | Ingreso del evento |

- Downgrade: drop de la tabla.
- El dedup es: si `event_id` ya existe → registrar log y descartar (no re-notificar).

### REQ-LNK-09 — Idempotencia y anti-contaminación

- Dedup por `event_id` (UNIQUE) en el receptor, antes de notificar.
- El mensaje de coordinación **nunca** se inserta en `message_history` ni dispara `TurnOrchestrator`.
- Si el payload está malformado (JSON inválido, `event != "vip_kicked"`): log `link_malformed` y descartar, sin crash.

### REQ-LNK-10 — Feature flag y cableado

- Diana: `feature_link_enabled: bool = False` (default en `settings.py`, overridable por env) + `.env` `FEATURE_LINK_ENABLED=true` (activo).
- Lucien: `FEATURE_LINK_ENABLED` (default `false`) en su config, activado en el deploy.
- Ambos lados: flag OFF → cero comportamiento nuevo (Diana: middleware pass-through; Lucien: no emite).
- `LINK_CHAT_ID` en ambos: el id del chat de coordinación (decisión cerrada — en `.env` de Diana, `LINK_CHAT_ID=7360762013`).

---

## 6. Cambios de esquema

| Repo | Migración | Cambio | Downgrade |
|---|---|---|---|
| DianaV2 | 028 | Tabla `link_events` (REQ-LNK-08) | drop table |
| lucienbot | nueva | Tabla `business_connections` (REQ-LNK-01) | drop table |

Sin cambios en tablas existentes de Diana (`vips` ya tiene todo lo necesario). Nota: la migración **027** de Diana se usó para eventos temporales (`ephemeral_events`); `link_events` es la **028**.

---

## 7. Límites de módulo (cumplimiento AGENTS.md v1.3)

- La **decisión** (verificar VIP, aplicar acción) vive en `application/` (`LinkCoordinator`); `telegram/` solo parsea, filtra y notifica vía puertos existentes.
- Los mensajes de coordinación **no** tocan `cognitive/` (pipeline), `behavior/` (envío de respuestas) ni `learning/`.
- El emisor en Lucien es un servicio de infraestructura (envío), no lógica de negocio: no toca el dominio VIP de Lucien más allá del hook post-expulsión.
- Purity gates, serialización por chat y flags vigentes.
- Nada de voseo en textos nuevos (revisar el barrido en el checklist).

---

## 8. Criterios de aceptación (checklist)

> **Cumplido**: la Fase 6 está implementada y desplegada; aceptación real pasada (bot-to-bot DM verificado E2E, 2026-08-21). <!-- VERIFY: aceptación E2E y estado del deploy no son verificables desde el repo; ver docs/ESTADO-PROYECTO.md -->

- [x] La dueña conecta su cuenta business a Lucien (mismo procedimiento que con Diana); Lucien persiste el `business_connection` update.
- [x] Kick manual del admin en Lucien (`admin_revoke_subscription`, resultado `kicked`) → se envía el payload `[LINK]` al chat de coordinación.
- [x] Expiración automática en Lucien (única suscripción) → se envía el payload `[LINK]` con `reason:"expired"`.
- [x] Diana recibe el `business_message` del chat de coordinación, lo reconoce por `[LINK]` y lo procesa sin tocar el pipeline.
- [x] Si el expulsado es VIP activo de Diana → notificación a la dueña con el texto aprobado (REQ-LNK-06) y los 3 botones.
- [x] Si el expulsado NO es VIP de Diana → sin notificación; fila `link_events` con `state='ignored_not_vip'`.
- [x] Botón Expulsar → `vips.is_active=false`, mensaje actualizado sin botones, `state='decided_expel'`.
- [x] Botón Inhabilitar → `vips.frozen_until` = fecha lejana fija (indefinido), mensaje actualizado sin botones, `state='decided_disable'`.
- [x] Botón Mantener → sin cambios en `vips`, `state='decided_keep'`.
- [x] Mismo `event_id` reenviado → no re-notifica (dedup).
- [x] Payload malformado → log + descarte, sin crash.
- [x] Flag OFF en ambos bots → suite completa verde, comportamiento idéntico al actual.
- [x] Unit + e2e (fakes) verdes; purity gates verdes; sin voseo en textos nuevos.

---

## 9. Decisiones abiertas / pendientes

**Cerradas (2026-08-11) y reflejadas en la implementación**: "Inhabilitar" = indefinido (`frozen_until` fecha lejana) · texto del aviso = el aprobado en REQ-LNK-06 · chat de coordinación = `LINK_CHAT_ID` (en despliegue, el DM con el bot de Lucien; la decisión original de un grupo privado quedó superada por la implementación).

Sin pendientes de esta Fase (todo implementado y desplegado). Resolución de los ítems que estaban abiertos:

1. **Fecha lejana de "Inhabilitar"**: **decisión tomada** — `2099-12-31T00:00:00Z` es la **fecha centinela de diseño**, implementada como default de `link_disable_frozen_until` en `settings.py` (`datetime(2099, 12, 31, tzinfo=UTC)`, con fallback equivalente en `application/link.py`). No es una fecha de reactivación: marca "inhabilitado indefinido" (efecto inmediato y sin fin vía `FreezeCheckMiddleware`).
2. **`username`**: **implementado** como campo **opcional** — el receptor lo parsea si Lucien lo envía (`null` si no viene); se persiste en `link_events.username` y se usa en el nombre del aviso a la dueña (`@{username}`).
3. **Política de reintento del emisor**: **decisión tomada** — **best-effort** (1 intento, log si falla; nunca rompe el flujo de expulsión). Reintentos con backoff: **no implementados** (mejora posible; sin compromiso de implementación).
4. **Actualización de docs (tarea de cierre)**: en curso — este documento se está actualizando al estado implementado/desplegado (2026-08-21).
