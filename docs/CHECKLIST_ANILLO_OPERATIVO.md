# Checklist del anillo operativo (v2 → confianza v1)

**Propósito:** Endurecer lo que rodea la respuesta (turno, espera, cancelación, entrega, recovery, admin), **sin reabrir el cerebro cognitivo** salvo bugs puntuales.

**Regla de oro:** si v1 ya se comporta bien y v2 no → es bug de anillo, prioridad alta, aunque el borrador suene perfecto a Diana.

**Cómo usar:**
- Estado: `OK` | `PARCIAL` | `ABIERTA` | `N/A` (no aplica al producto actual)
- Prioridad: `P0` (rompe confianza día a día) · `P1` (se nota) · `P2` (nice / raro)
- Criterio de paso: escenario real en Telegram (o test automatizado que cubra el mismo camino)
- Marcar fecha y nota al cerrar cada ítem

**Última actualización de referencia de código:** 2026-08-02 (Ola 1 cerrada en código + tests)

---

## Cómo se gana la partida

Cuando los **P0 de las zonas A–E** estén en `OK` de forma estable en operación real, v2 “llena”: respuestas buenas **y** anillo confiable.

No se mide progreso por “más features de LLM”.  
Se mide por: **¿cuántas veces esta semana el sistema se comportó raro alrededor del mensaje?**

---

## Zona A — Ciclo de turno (quién manda el hilo)

| ID | Pri | Escenario | Comportamiento esperado | Estado ref. | Notas |
|----|-----|-----------|-------------------------|-------------|-------|
| A1 | P0 | Dueña escribe en el chat VIP **durante la espera** (antes del pipeline) | Se cancela el turno; el bot no sigue ni manda borrador/envío de ese turno | **OK** | `waiting_delay` + tests pre-delay |
| A2 | P0 | Dueña escribe **mientras genera** (LLM en curso) | Abort limpio; no llega respuesta automática de ese turno | **OK** | Catch `TurnSupersededError` post-Director; test mid-gen |
| A3 | P0 | Dueña escribe **con borrador pendiente de aprobación** | Borrador viejo no se puede aprobar hacia el VIP (stale / cancelado); no “doble voz” | **OK** | Supersede cancela approval + **void DM** |
| A4 | P0 | Dueña escribe **mientras entrega** (read/typing/send) | Delivery se aborta; no envía a medias de forma confusa | **OK** | Pre-send gate + cancel_pending |
| A5 | P0 | VIP manda **segundo mensaje** antes de responder al primero | Turno anterior supersede; solo se responde al más reciente (o a la ventana correcta) | **OK** | `vip_epoch` + e2e supersede |
| A6 | P0 | VIP manda **ráfaga** de 3–5 mensajes | Un solo turno coherente (debounce/reprogramación); no N respuestas | **OK** | Coalesce burst + supersede losers |
| A7 | P1 | VIP **edita** su último mensaje durante el turno | El sistema no contesta al texto viejo; reinicia/actualiza con el texto editado | Mejor que v1 en diseño | v1 ignoraba edits; v2 procesa |
| A8 | P1 | Mensaje duplicado de Telegram (mismo update/msg) | No crea turnos duplicados ni doble draft | Verificar | Dedup middleware |
| A9 | P1 | Dos chats VIP activos a la vez | No se cruzan turnos, gen, ni notificaciones | Verificar | |

---

## Zona B — Espera, timers y “no hay fantasmas”

| ID | Pri | Escenario | Comportamiento esperado | Estado ref. | Notas |
|----|-----|-----------|-------------------------|-------------|-------|
| B1 | P0 | Supervisado: delay humano antes de generar | Hay espera real; no contesta instantáneo | OK diseño | Delays largos configurados (ej. ~2 min) |
| B2 | P0 | Autónomo: delay mayor y variable | Se siente humano; no patrón de reloj | Verificar | |
| B3 | P0 | Reinicio del proceso **en medio de la espera pre-pipeline** | Reanuda la espera restante y sigue el pipeline; si no hay timer, falla predecible | **OK** | D1: `kind=pre_delay` + resume post-missed-updates (2026-08-02) |
| B4 | P0 | Reinicio **con delivery pendiente** (ya aprobado / autónomo en cola) | Reanuda entrega segura o re-notifica; **nunca** auto-aprueba solo | **OK*** | Recover pending; delivering VIP se expira (no re-envío ciego) |
| B4b | P0 | Reinicio **en medio de espera de promo no-VIP** | Retoma el timer restante y envía la secuencia; registra `promo_executions` | **OK** | `promo_pending` + timer recovery + finalize (2026-08-02) |
| B5 | P1 | Timer de un chat no afecta al otro | Cancelar chat A no rompe chat B | Verificar | |
| B6 | P1 | Reloj de recontacto se resetea al hablar el VIP | No recontacta justo después de actividad | Verificar | |

---

## Zona C — Aprobación, zona gris y escalación (lo que ve la dueña)

| ID | Pri | Escenario | Comportamiento esperado | Estado ref. | Notas |
|----|-----|-----------|-------------------------|-------------|-------|
| C1 | P0 | Supervisado: llega borrador en DM con contexto usable | Dueña entiende a quién y qué; puede aprobar/corregir | Verificar UX | |
| C2 | P0 | Aprobar borrador **actual** | Se entrega al VIP con Behavior Engine | Verificar | |
| C3 | P0 | Aprobar borrador **ya supersedido** (hubo mensaje nuevo o dueña habló) | Botón no envía basura; mensaje claro “ya no aplica” | **OK** | No send + toast; DM se void al supersede |
| C4 | P0 | Corregir texto y enviar | VIP recibe la corrección; no el borrador viejo | Verificar | |
| C5 | P1 | Regenerar variante y navegar prev/next | Misma notificación; elige la versión; no spamea el DM | Verificar | Draft variants en v2 |
| C6 | P0 | Zona gris: consulta abierta | **Freeze VIP total**: sin read, typing, envío ni recontacto del bot | Verificar | |
| C7 | P0 | Zona gris: dueña responde doctrina | Se destila política; se descongela; sigue approve/envío según modo | Verificar | |
| C8 | P1 | Zona gris: timeout | Comportamiento definido (ej. usar draft); no deja VIP congelado para siempre sin rastro | Verificar | Job expire |
| C9 | P0 | Escalación por palabra/tema prohibido | No auto-responde; avisa a dueña; triage usable | Verificar | |
| C10 | P1 | Escalación falso positivo marcada | No repite el mismo FP de forma tonta | Verificar | |
| C11 | P1 | Reinicio con **borrador pendiente** | Se re-notifica o recupera; botones válidos (no stale) | **OK** | Rematerialize + owner_message_id |
| C12 | P1 | Zona gris pendiente (reinicio / recordatorio) | Freeze y consulta sobreviven reinicio; recordatorio con botones cuando el VIP congelado vuelve a escribir | **OK** (diseño intencional) | No re-notify masivo al startup. `FreezeCheckMiddleware` → `notify_doctrine` (debounce 20 min) |

---

## Zona D — Delivery human-like (lo que percibe el VIP)

| ID | Pri | Escenario | Comportamiento esperado | Estado ref. | Notas |
|----|-----|-----------|-------------------------|-------------|-------|
| D1 | P0 | Envío normal | read → pausa → typing → send; no instant bot | Verificar | |
| D2 | P0 | Mensaje **largo** (typing > ~5 s) | El “escribiendo…” **se mantiene** hasta cerca del envío | **OK** | `_show_typing` refresh cada 4s; test `test_typing_refresh_*` |
| D3 | P0 | Abort a mitad de delivery (dueña o VIP nuevo) | No llega medio mensaje raro; no “leído” + silencio confuso sin política | **OK*** | Pre-send abort; multi-seg: 1er segmento puede llegar (política documentada) |
| D4 | P1 | Mensaje multi-segmento / split | Huecos y typing entre partes; no muro de texto | Verificar | |
| D5 | P1 | Promo no-VIP multi-mensaje | Misma calidad human-like; sin LLM | OK diseño | |
| D6 | P2 | Quirks humanos (typo + corrección) si están activos | No se activan en freeze/escalación; no rompen cancel | Verificar flag | |

---

## Zona E — Recovery y “enterarme sin adivinar”

| ID | Pri | Escenario | Comportamiento esperado | Estado ref. | Notas |
|----|-----|-----------|-------------------------|-------------|-------|
| E1 | P0 | Caída breve + mensajes VIP mientras estaba down | Al volver, no se pierden (o política clara); no silencio total | OK diseño | missed_message_recovery |
| E2 | P0 | Arranque: resumen a la dueña | DM con qué se recuperó (timers, borradores, zombies) | OK | |
| E3 | P0 | Turno a medias del pipeline al crash | No se envía basura; zombie fallido; dueña puede retomar | OK diseño | fail-closed mid-pipeline |
| E4 | P1 | Business connection enable/disable | Se registra; no envía con connection muerta | OK diseño | |
| E5 | P1 | Fallo de LLM / API caída | Dueña notificada; VIP no recibe basura; se puede reintentar | Verificar | |
| E6 | P2 | Log/archivo de escalaciones legible | Opcional; DB + DM puede bastar | ABIERTA baja | v1 tenía .txt |

---

## Zona F — Datos de continuidad (para que no “olvide el mundo”)

| ID | Pri | Escenario | Comportamiento esperado | Estado ref. | Notas |
|----|-----|-----------|-------------------------|-------------|-------|
| F1 | P1 | VIP con historial previo al bot | Al alta o arranque, se puede hidratar historial | ABIERTA | Backfill al arranque en v1; gap en v2 |
| F2 | P1 | Agenda / “qué está haciendo Diana ahora” | Cuando aplica, las respuestas no inventan disponibilidad absurda | PARCIAL | Retriever existe; inyección condicional |
| F3 | P1 | Sandbox no contamina prod | Memoria/ejemplos reales intactos | Verificar | |
| F4 | P1 | Pausa de datos por VIP | Cero automatización / recolección según regla | OK diseño UI | |
| F5 | P2 | Observar no-VIP para aprender | Opcional producto | ABIERTA | No en v2 |

---

## Zona G — Admin día a día (fricción de la dueña)

| ID | Pri | Escenario | Comportamiento esperado | Estado ref. | Notas |
|----|-----|-----------|-------------------------|-------------|-------|
| G1 | P0 | Ver estado: modo, salud básica | Sin SSH ni logs | Verificar | |
| G2 | P1 | Traza “¿por qué dijo esto?” en un turno reciente | Explicable en lenguaje de producto | Verificar | pipeline_traces |
| G3 | P1 | Staging de ejemplos (promover/descartar) | Correcciones no entran solas al banco vivo | Verificar | |
| G4 | P1 | Notas / facts por VIP | Se reflejan en turnos siguientes del mismo VIP | Verificar | |
| G5 | P2 | Métricas simples (aprobación sin corrección, etc.) | Ver si el sistema mejora o solo acumula ruido | Verificar | |

---

## Orden de ataque recomendado (para recuperar emoción rápido)

Trabajar en **olas de 3–5 escenarios P0**, validar en Telegram real, y solo entonces la siguiente ola.

### Ola 1 — Confianza de cancelación (la que más desanima) — **CERRADA en código 2026-08-02**
- A1–A6, C3, D3  
- Validación restante: **Telegram real / sandbox** (checklist en chat)

### Ola 2 — Reinicios sin miedo — **cerrada en código 2026-08-02**
- B4b promo no-VIP mid-wait: **OK**
- B3 VIP pre-delay durable (D1): **OK**
- B4 / C11 / E1–E3: **OK** en código (validar en prod)
- C12 re-notify gray zone: **pendiente** (ola siguiente si duele)

### Ola 3 — Lo que el VIP *ve* y siente bot
- D2 typing loop: **OK** (ya implementado)
- D1 / D4: verificar en prod si hace falta

### Ola 4 — Continuidad y “cuerpo” de producción
- F1 backfill, F2 schedule, migración de memoria/ejemplos/políticas desde v1 si aplica  

### Ola 5 — Admin y aprendizaje controlado
- G1–G4, C5, C7–C8  

---

## Mini plantilla de validación (copiar por ítem)

```text
ID: 
Fecha:
Canal de prueba: sandbox / VIP real
Pasos:
1.
2.
3.
Resultado: OK / FALLA
Qué se sintió frágil (si falla):
¿v1 lo hacía mejor? sí/no/no sé
Siguiente acción:
```

---

## Fuera de esta checklist (a propósito)

- Mejorar Analista / Generador / Evaluador “porque sí”
- Reescribir prompts del cerebro sin un bug de anillo
- Volver a v1 como producto principal

Si un fallo es “suena poco a Diana” **con** anillo estable → ahí sí es cerebro/persona/datos.  
Si el fallo es “hizo algo raro *alrededor*” → es este documento.

---

## Resumen de huecos ya conocidos (atajo)

| Hueco | IDs | Impacto en “se siente frágil” |
|-------|-----|-------------------------------|
| Typing single-shot (no loop) | D2 | **Cerrado** (refresh 4s) |
| Pre-delay VIP no durable | B3 | **Cerrado** D1 (2026-08-02) |
| Promo mid-wait al reiniciar | B4b | **Cerrado** (2026-08-02) |
| Sin backfill historial al arranque | F1 | Medio (olvida contexto) |
| Schedule condicional vs siempre | F2 | Medio en tono “vida real” |
| Escalación solo DB (sin .txt) | E6 | Bajo |
| Observación no-VIP | F5 | Bajo / opcional |

El resto de la lista es **verificar en operación real** aunque el diseño diga que está cubierto: la confianza se gana en el chat, no en el diseño.
