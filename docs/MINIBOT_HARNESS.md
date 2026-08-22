# Harness de pruebas con minibot

**Fecha:** 2026-08-21
**Repo del harness:** `~/repos/minibot` (userbot Telethon)

## Propósito

`minibot` es un **harness de pruebas** para DianaV2. Corre sobre la cuenta de la
dueña como un **userbot (Telethon)** y simula distintos perfiles de suscriptor
en el chat de prueba, evaluando las respuestas de Diana con un LLM. Al ser un
usuario normal, sí ve y responde los mensajes en el chat de prueba (a diferencia
de un bot, que no recibe los mensajes de otro bot).

No es un componente de DianaV2: es un proceso externo que **se integra con el
sandbox** de DianaV2 y con la **entrega de respuestas** del modo supervisado.

## Modelo de integración

```
minibot (userbot Telethon)                 DianaV2 (aiogram)
─────────────────────────                  ─────────────────
1. Envía mensaje del perfil  ──────────▶  Sandbox activo en el chat de prueba
2. Espera la respuesta        ◀─────────  Turno pipeline → approve/escalate
3. Evalúa contra la rúbrica                Behavior Engine entrega al chat
4. Repite N turnos
5. Guarda resultados (JSONL + SQLite)  y reporta por DM
```

El bucle solo funciona si DianaV2 cumple dos condiciones:

1. **Sandbox activo** en el chat de prueba (aísla la prueba: sin persistencia
   de memoria, aprendizaje ni datos reales).
2. **Entrega de respuestas al chat** (ver abajo).

## Requisitos en DianaV2

### 1. Sandbox activo en el chat de prueba

En el DM de DianaV2 (como dueña):

```
/sandbox on <chat_id> <perfil>
```

Perfiles disponibles en `src/diana/config/sandbox_profiles.json`:
`nuevo`, `cercano`, `distante`, `intenso`, `vip_largo`, `inyeccion_previa`.
También puedes usar `/menu` → "🧪 Modo de prueba" y reenviar un mensaje del
chat objetivo.

### 2. Entrega de respuestas al chat

En modo **supervisado**, DianaV2 retiene los borradores en el DM de la dueña
(no los envía al chat). Para el bucle automático las respuestas deben llegar al
chat de prueba. Dos opciones:

- **Autónomo:** `GLOBAL_MODE=autonomous` + `FEATURE_AUTONOMOUS_MODE=true` en el
  `.env` de DianaV2. Envía automáticamente las respuestas con confianza
  suficiente. ⚠️ Verifica los umbrales para que los turnos de prueba no caigan
  en aprobación.
- **Supervisado manual:** se aprueba cada borrador desde el DM; minibot espera
  (`TURN_TIMEOUT_SEC`) a que llegue la respuesta aprobada.

> Nota: si el bucle no recibe respuestas, revisa primero que DianaV2 esté
> entregando al chat de prueba (mode/entrega real del despliegue).

## Configuración

### DianaV2 (`.env`)

| Variable | Valor para el harness |
| --- | --- |
| `GLOBAL_MODE` | `autonomous` (o `supervised` + aprobación manual) |
| `FEATURE_SANDBOX_ENABLED` | `true` |
| `FEATURE_AUTONOMOUS_MODE` | `true` solo en autónomo (kill-switch maestro) |

### minibot (`.env` — ver repo minibot)

| Variable | Descripción |
| --- | --- |
| `API_ID` / `API_HASH` | Credenciales del userbot (my.telegram.org) |
| `SESSION_STRING` | Sesión del userbot (generar con `python scripts/login.py`) |
| `OWNER_TELEGRAM_ID` | Quien controla el bot por Mensajes guardados |
| `TEST_CHAT_IDS` | Chat(s) con sandbox activo; minibot solo actúa ahí |
| `LLM_PROVIDER` | `deepseek` (default) \| `anthropic` \| `fake` |
| `TURNS_MAX` / `TURN_TIMEOUT_SEC` | Turnos por test (default 5) y timeout (480 s) |

## Flujo de trabajo

1. (Dueña) Activa sandbox en DianaV2 para el chat de prueba y elige perfil.
2. (Dueña) Escribe en tus Mensajes guardados (minibot es un userbot):
   - `/perfiles` — lista los agentes.
   - `/test <perfil> --turns 3` — corre el test del perfil.
   - `/test_all --turns 2` — corre los 5 agentes en secuencia.
   - `/stop` — aborta; `/estado` — test activo; `/resultados` — últimas corridas.
3. minibot envía el mensaje inicial del perfil al chat, espera la respuesta de
   Diana (sandbox), la evalúa contra la rúbrica y continúa N turnos.
4. Al terminar, minibot reporta el resumen por DM y guarda los resultados.

## Mapeo agente → perfil sandbox

| Agente minibot | Perfil sandbox DianaV2 |
| --- | --- |
| `intenso` | `intenso` |
| `romantico` | `cercano` (o fixture `romantico` si se añade) |
| `veterano` | `vip_largo` |
| `nuevo` | `nuevo` |
| `adversarial` | `inyeccion_previa` |

El agente `adversarial` genera un set amplio de probes (inyección de prompt,
jailbreak, manipulación, extracción de información, acoso) para comprobar los
límites del bot. Es una prueba autorizada sobre el bot propio, confinada al
sandbox (sin persistencia real).

## Resultados

- Cada corrida se guarda en `results/runs/<run_id>.jsonl` (auditoría por turno).
- El índice está en `results/results.db` (SQLite); `/resultados` lo consulta.

## Validación sin entorno real

```bash
python scripts/dry_run.py   # en el repo minibot
```

Corre el pipeline completo (persona → respuesta simulada → evaluación) para los
5 agentes sin tocar Telegram.

## Referencias

- Docs del harness: `~/repos/minibot/README.md`, `docs/SETUP_TELEGRAM.md`,
  `docs/TESTING.md`, `docs/INVESTIGACION_TELEGRAM.md`.
- Sandbox de DianaV2: `docs/SPEC-FASE2.md`, `src/diana/application/sandbox.py`,
  `src/diana/config/sandbox_profiles.json`.
- Modos de operación: `wiki/concepts/modos-de-operacion.md`.
