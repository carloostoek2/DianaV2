# SPEC-FASE6.md — Vínculo entre bots: aviso de expulsión VIP (Lucien → Diana) — v1.0

Diana Business Bot / Sistema de Automatización de Chats VIP

| Campo | Valor |
|---|---|
| Nivel | Contrato de diseño e implementación para la Fase 6 |
| Basado en | SPEC-FASE5.md v1.0 + REQUERIMIENTOS.md v2.1 + SPEC-FASE2.md v2.1 + SPEC-FASE3.md v3.0 + AGENTS.md v1.3 + Telegram Bot API (Business Connections) |
| Audiencia | Ingeniería (implementación con DeepSeek en terminal; revisión posterior) |
| Versión | 1.0 — Borrador de diseño aprobado por la dueña de producto |
| Estado | Aprobado para implementación |
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
5. **Lucien no tiene nada de business hoy** (verificado: cero código, solo menciones en docs). Esta Fase agrega el lado emisor en Lucien (conexión + envío del aviso) y el lado receptor/decisor en Diana.

### Estado real verificado (evidencia dura)

| Dato | Valor | Cómo se verificó |
|---|---|---|
| Conexión business activa en Diana | `_-0ieT7GuEewAQAArqdqnipLbXk` → user 6181290784, can_reply=t, is_enabled=t | `psql` sobre `business_connections` |
| Owner de Diana | `OWNER_TELEGRAM_ID=6181290784` | `.env` |
| Puntos de expulsión en Lucien | `vip_service.admin_revoke_subscription` (kick manual, código `"kicked"`) y `scheduler_service._process_expired_subscriptions` (expiración) | grep `ban_chat_member` en lucienbot |
| EventBus interno de Lucien | `services/event_bus.py` (`InternalEventBus`, `EVENT_BESITOS_AWARDED`) — patrón a imitar para el emisor | código lucienbot |
| Campos de estado VIP en Diana | `vips.is_active`, `vips.paused_until`, `vips.frozen_until` (ya existen) | `models.py` |
| Head de migraciones Diana | `026_agent_evolution_turn_category_columns.py` → la nueva será **027** | `ls alembic/versions/` |
| Head de migraciones Lucien | `merge_trivia_config_to_main.py` / `trivia_discount_system.py` | `ls alembic/versions/` |

---

## Resumen de decisiones de producto (dueña)

1. La conexión entre Lucien y Diana se hace por la **vía business** (cuenta business de la dueña conectada a ambos bots), no por mensajes directos bot↔bot.
2. Cuando Lucien expulsa a un suscriptor del canal VIP (kick manual del admin o expiración), **le avisa a Diana** con un mensaje business al chat de coordinación.
3. Diana **verifica si ese usuario es VIP suyo** (tabla `vips` por `telegram_user_id` activo). No todos los suscriptores del canal son VIPs de Diana.
4. Si es VIP de Diana → **notifica a la dueña** indicando que se expulsó a un suscriptor de Diana del canal VIP, con las opciones: **Expulsar** (baja también en Diana), **Inhabilitar** (suspensión temporal), **Mantener** (no hacer nada).
5. Si NO es VIP de Diana → no notifica; registra el evento y termina.
6. De primera instancia las opciones son esas tres; no hay flujo de confirmación de vuelta a Lucien en esta Fase (fuera de alcance).
7. Toda la Fase va detrás de un feature flag `FEATURE_LINK_ENABLED` (default `false`): apagado → comportamiento idéntico al actual.

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
| F6-07 | Acciones: baja (`is_active=false`), suspensión (`paused_until`), mantener (nada) |
| F6-08 | Registro de eventos: tabla `link_events` (migración 027) + callbacks de decisión |
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
  LinkCoordinator (nuevo, capa application/)
        │  1. Dedup por event_id (tabla link_events)
        │  2. Verifica VIP en vips (telegram_user_id + is_active)
        │  3. ¿Es VIP de Diana? ── no ──► registro + fin
        │              │ sí
        │              ▼
        │   notifica a la dueña (DM del bot) con botones
        │              ▼
        │   callback de la dueña: expulsar | inhabilitar | mantener
        ▼
  aplicación sobre vips (is_active=false | paused_until=… | nada) + registro de decisión
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

- **Qué**: nuevo router/handler de `business_message` (y `edited_business_message` NO — los eventos no se editan) que filtra:
  1. `message.chat.id == LINK_CHAT_ID` (nuevo setting en Diana, el chat de coordinación), **y**
  2. `text.startswith("[LINK]")`.
- **Dónde**: `src/diana/telegram/handlers/link.py` (nuevo, estilo `business.py`), incluido en `build_dispatcher` ANTES del router de negocio (o como router propio con registro previo) para que el mensaje de coordinación **nunca** caiga en `build_business_router` (anti-contaminación).
- **Límites**: si el flag `FEATURE_LINK_ENABLED` está OFF, el router no se registra (inert, patrón del proyecto) → el mensaje se ignora.
- **Límites de módulo**: el handler de telegram solo parsea y delega; toda decisión vive en `application/`.

### REQ-LNK-05 — Verificación de VIP

- **Qué**: dado `user_id` del evento, Diana consulta si existe un VIP suyo activo.
- **Dónde**: nuevo servicio `LinkCoordinator` en `src/diana/application/link.py` (o `link_service.py`), usando el repo de vips existente.
- **Regla**: `SELECT … FROM vips WHERE telegram_user_id = :uid AND is_active = true`. Si no existe o está inactivo → registrar evento con `state='ignored_not_vip'` y **no** notificar.
- **Nota**: `paused_until`/`frozen_until` no excluyen de la verificación (un VIP suspendido sigue siendo VIP de Diana; la notificación igual llega).

### REQ-LNK-06 — Notificación a la dueña

- **Qué**: mensaje al DM del bot (owner `6181290784`, patrón existente `AiogramOwnerNotifier`) con teclado inline de 3 botones.
- **Dónde**: reutilizar `AiogramOwnerNotifier` (o su puerto) + teclado nuevo en `telegram/keyboards.py` (`link_kick_keyboard(event_id)`).
- **Texto propuesto** (español neutro, sin voseo):

```
⚠️ Expulsión de suscriptor del canal VIP

Lucien expulsó a un usuario del canal {channel_name}.
El usuario es VIP de Diana: {display_name} {username} (id {user_id})
Motivo: {motivo}

¿Qué hago con su membresía en Diana?
```

- **Callbacks**: `link:expel:<event_id>` | `link:disable:<event_id>` | `link:keep:<event_id>` (prefijo propio, manejado en router de callbacks o en el router link, ANTES del catch-all).
- El mensaje debe permitir identificar al VIP por nombre visible (consultar `vips.display_name`), no solo el id numérico.

### REQ-LNK-07 — Acciones de la dueña

| Botón | Acción en `vips` | Detalle |
|---|---|---|
| Expulsar | `is_active = false` | Baja definitiva: el VIP deja de ser atendido por Diana. Se conserva el registro (trazabilidad). |
| Inhabilitar | `paused_until = now() + 30 días` (configurable) | Suspensión temporal: no se atiende durante el período; la reactivación queda para un flujo posterior/manual. |
| Mantener | sin cambios | El VIP sigue activo en Diana aunque ya no esté en el canal. |

- Si el VIP ya no existe o ya está inactivo al momento del callback (carrera): responder "ya no aplica" y registrar `state='noop'`.
- El callback actualiza el mensaje de la dueña (quitar botones) para indicar la decisión tomada.

### REQ-LNK-08 — Registro de eventos (tabla `link_events`, migración 027)

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

- Diana: `feature_link_enabled: bool = False` en `settings.py` + `.env` `FEATURE_LINK_ENABLED=false` (se activa a `true` en el deploy de la Fase).
- Lucien: `FEATURE_LINK_ENABLED` (default `false`) en su config.
- Ambos lados: flag OFF → cero comportamiento nuevo (Diana ni registra el router; Lucien no emite).
- `LINK_CHAT_ID` en ambos: el id del chat de coordinación (decisión abierta #1).

---

## 6. Cambios de esquema

| Repo | Migración | Cambio | Downgrade |
|---|---|---|---|
| DianaV2 | 027 | Tabla `link_events` (REQ-LNK-08) | drop table |
| lucienbot | nueva | Tabla `business_connections` (REQ-LNK-01) | drop table |

Sin cambios en tablas existentes de Diana (`vips` ya tiene todo lo necesario).

---

## 7. Límites de módulo (cumplimiento AGENTS.md v1.3)

- La **decisión** (verificar VIP, aplicar acción) vive en `application/` (`LinkCoordinator`); `telegram/` solo parsea, filtra y notifica vía puertos existentes.
- Los mensajes de coordinación **no** tocan `cognitive/` (pipeline), `behavior/` (envío de respuestas) ni `learning/`.
- El emisor en Lucien es un servicio de infraestructura (envío), no lógica de negocio: no toca el dominio VIP de Lucien más allá del hook post-expulsión.
- Purity gates, serialización por chat y flags vigentes.
- Nada de voseo en textos nuevos (revisar el barrido en el checklist).

---

## 8. Criterios de aceptación (checklist)

- [ ] La dueña conecta su cuenta business a Lucien (mismo procedimiento que con Diana); Lucien persiste el `business_connection` update.
- [ ] Kick manual del admin en Lucien (`admin_revoke_subscription`, resultado `kicked`) → se envía el payload `[LINK]` al chat de coordinación.
- [ ] Expiración automática en Lucien (única suscripción) → se envía el payload `[LINK]` con `reason:"expired"`.
- [ ] Diana recibe el `business_message` del chat de coordinación, lo reconoce por `[LINK]` y lo procesa sin tocar el pipeline.
- [ ] Si el expulsado es VIP activo de Diana → notificación a la dueña con los 3 botones (nombre visible, motivo, canal).
- [ ] Si el expulsado NO es VIP de Diana → sin notificación; fila `link_events` con `state='ignored_not_vip'`.
- [ ] Botón Expulsar → `vips.is_active=false`, mensaje actualizado sin botones, `state='decided_expel'`.
- [ ] Botón Inhabilitar → `vips.paused_until` = now + 30 días (configurable), `state='decided_disable'`.
- [ ] Botón Mantener → sin cambios en `vips`, `state='decided_keep'`.
- [ ] Mismo `event_id` reenviado → no re-notifica (dedup).
- [ ] Payload malformado → log + descarte, sin crash.
- [ ] Flag OFF en ambos bots → suite completa verde, comportamiento idéntico al actual.
- [ ] Unit + e2e (fakes) verdes; purity gates verdes; sin voseo en textos nuevos.

---

## 9. Decisiones abiertas / pendientes

1. **Chat de coordinación**: se propone un grupo privado de coordinación (p. ej. "Diana↔Lucien") donde la cuenta business de la dueña esté como miembro; Lucien publica ahí y Diana lo lee. Alternativa: usar directamente el `user_chat_id` de la conexión (DM dueña↔cuenta business). Confirmar con la dueña (afecta `LINK_CHAT_ID` en ambos).
2. **Período de "Inhabilitar"**: 30 días propuesto; confirmar (o dejar como setting `LINK_DISABLE_DAYS`).
3. **Texto exacto del aviso a la dueña**: propuesto arriba; ajustable en revisión.
4. **`username`**: solo se incluye si Lucien lo tiene (el `chat_member` del ban puede traerlo; si no, `null`).
5. **Política de reintento del emisor**: best-effort en esta Fase (1 intento, log si falla); reintentos con backoff quedan como mejora.
6. **Actualización de docs** (README, AGENTS.md, tabla de flags) al cierre de la Fase (tarea de cierre).
