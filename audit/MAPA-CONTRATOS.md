# Mapa de contratos — qué promete Diana y qué está realmente probado

**Fecha:** 2026-10-10 · **Método:** skill `contract-proof` · **Alcance:** todo el sistema, contra el nivel
de evidencia de hoy. **Solo lectura:** no se ejecutó nada contra la base real, no se tocó código, no hay
commit ni despliegue.

**Fuentes:** `AGENTS.md`, `docs/REQUERIMIENTOS.md`, `docs/SPEC-FASE2..6.md`, `docs/SPEC-FEEDBACK.md`,
`docs/SPEC-AUTONOMIA-CALIBRACION.md`, `docs/SPEC-EVOLUCION-AGENTE.md`, `docs/ANEXO-H.md`,
`docs/ANEXO_T-TRAZABILIDAD.md`, `docs/contratos_restantes.md`, `docs/contrato_analista.md`, `wiki/`,
`docs/INFORME_AUDITORIA.md`, `faltantes.md`, `docs/ESTADO-PROYECTO.md`, las fichas previas de
`audit/contracts/` (C-SHADOW-01, C-EMB-01, C-CTX-01, C-HIST-01, C-AUT-01..04), los informes `audit/AUTONOMIA-*.md`, `audit/FASE2-*.md`, `audit/vigilantes.sql`,
`tests/audit/`, `tests/e2e/`, `tests/unit/` y el `.env` real.

---

## 0. Cómo se lee el nivel de evidencia

| Nivel | Qué prueba | ¿Vale como "cumple"? |
|---|---|---|
| **E0** | Existe el código y el documento | **No** |
| **E1** | Prueba con piezas simuladas (`InMemory*`, `FakeDirector`, servicios armados a mano) | **No** — prueba la pieza sola, no que esté conectada |
| **E2** | Camino real desde la entrada hasta una fila/mensaje en Postgres real | Casi |
| **E3** | E2 + sabotaje: al desconectar la pieza, la prueba falla | **Sí** |
| **E4** | E3 + un vigilante en producción que avisa si el efecto deja de ocurrir | Ideal |

Regla dura del método: **solo E3/E4 se reporta como ✅**. Todo lo demás es "sin verificar", por bien
escrito que esté.

---

## 1. El titular: el "143 de 161 cumple" es lectura de código

`docs/INFORME_AUDITORIA.md` compara **código contra requisitos**. No ejecuta el sistema, no mira una
fila escrita, no comprueba que un mensaje salga. El propio piloto de esta auditoría ya lo había
anotado (`audit/PILOT-REPORT.md`, H6: *"no demuestra ejecución. Conviene tratarla como E0"*).

Con el nivel de evidencia que exige el método, el panorama real hoy es:

- **Con prueba de efecto real (E2/E3/E4): 5 áreas.** Sombra y confianza, huellas semánticas, contexto
  temporal, alta de VIP con historial, y el camino a la autonomía + aviso de banderas. Todas nacieron
  de esta auditoría, no del informe de 143.
- **Sin ninguna prueba de efecto (E0/E1): el resto del sistema**, incluido el núcleo: responder a un
  VIP, escalar, consultar doctrina, recordar, aprender de una corrección, filtrar una foto con
  documento, promocionar y atender. Todo eso está cubierto hoy por pruebas con **piezas simuladas**
  (un director falso, almacenes en memoria) o por pruebas que solo comprueban que **los objetos
  existen y están conectados**.

Detalle que importa: en `tests/e2e/` hay tres niveles y **ninguno de los tres prueba un efecto de
flujo**, salvo los repositorios:

| Suite | Qué es en realidad | Nivel |
|---|---|---|
| `tests/e2e/tier1/` (11 archivos) | `FakeDirector` + almacenes en memoria. Ahí viven escalación, zona gris, aprobación, staging, supersede, falso positivo | **E1** |
| `tests/e2e/tier2/` (34) | Repositorios contra Postgres real | **E2 del repositorio**, no del flujo |
| `tests/e2e/tier3/` (5) | `build_app` con Postgres real, pero asierta **presencia**: "el orquestador existe", "el motor tiene `deliver`" | **E0/E1 de efecto** |
| `tests/unit/` (226 archivos) | Piezas aisladas | **E1** |
| `tests/audit/` (11 archivos) | Entrada real → efecto persistido, Postgres real | **E2/E3** |

En otras palabras: hoy **la única evidencia de que el sistema hace lo que promete, y no solo de que el
código lo dice, vive en `tests/audit/`**.

---

## 2. Tabla maestra — todas las promesas con efecto observable

Leyenda de nivel: 🟢 E3/E4 · 🟡 E2 · 🔴 el efecto no ocurre · ⚪ sin verificar (E0/E1).
La columna **"¿solo código?"** responde: *¿el "cumple" del informe original se apoyaba únicamente en
leer el código?*

### 2.1 Ya cubiertos — no volver a auditarlos

| Contrato | Qué promete (negocio) | Fuente | Nivel hoy | ¿Solo código? |
|---|---|---|---|---|
| **C-SHADOW-01** · sombra y decisiones de la dueña | Por cada turno queda qué habría hecho Diana sola, qué hizo la dueña y la diferencia | SPEC-AUTONOMIA §Fila 4 | 🟢 **E3 + E4** (V2/V3/V7 diarios) | Sí, hasta 2026-10-08 |
| **C-EMB-01** · huellas semánticas | Lo que Diana "recuerda" tiene una huella real y se puede recuperar por parecido | wiki pipeline/memoria/calidad | 🟢 **E3 + E4** (V1 diario) | Sí, hasta 2026-10-08 |
| **C-CTX-01** · contexto temporal | La foto del contexto se guarda con vigencia, se lee al turno siguiente y se retira al vencer | SPEC-FASE2, REQ-MEM-06 | 🟢 **E3** | Sí, hasta 2026-10-07 |
| **C-HIST-01(b)** · alta de VIP con historial | Al registrar un VIP, el alta no consulta la cuenta vieja y deja el motivo escrito | SPEC-FASE5/6 | 🟢 **E3** | Sí, hasta 2026-10-07 |
| **Banderas núcleo y `/health`** | Una bandera núcleo apagada avisa al arrancar y se publica en `/health` | AGENTS §1 (regla de prioridad) | 🟢 **E2** (9 pruebas, servidor real) | Sí, hasta 2026-10-08 |
| **C-AUT-01** · envío autónomo (doble puerta) | Solo envía solo con el interruptor maestro y el permiso del VIP abiertos; si no, cae en la cola | AGENTS §4.8 | 🟢 **E3** en la doble puerta · 🔴 en la pausa a mitad de turno | Sí, hasta 2026-10-09 |
| **C-AUT-02** · puerta de recomendación | Activa un VIP solo si cumple las tres condiciones, y activar no envía nada | SPEC-AUTONOMIA §C6, AGENTS §4.19 | 🟢 **E3** | Sí, hasta 2026-10-09 |
| **C-AUT-04** · una sola fuente de confianza | La confianza se ajusta por resultados, sin contar dos veces el mismo turno | AGENTS §4.18 | 🟢 **E3** · 🔴 en "siempre hay una vía de ajuste" | Sí, hasta 2026-10-09 |
| **C-AUT-03** · reacción del VIP | La reacción (o el silencio) se registra sobre el turno que sí se entregó | SPEC-AUTONOMIA §C3 | ⚪ **sin verificar** — con un defecto medido (54 % de las señales positivas cuelgan de turnos no entregados) | Sí |

### 2.2 Propuestos en las rondas de §3 — sin prueba de efecto hoy

| Contrato | Área | Qué promete (negocio) | Fuente | Nivel hoy | ¿Solo código? | Riesgo si falla callado |
|---|---|---|---|---|---|---|
| **C-ESC-01** | Escalación | Cuando el bot no se anima a responder, la dueña se entera y puede resolver; marcar "falso positivo" reanuda el flujo en vez de cerrar el caso | AGENTS §4.2, §4.21; REQ-ESC-01..06 | **E1** (tier1 con director falso) | Sí | **Alto** — el VIP queda sin respuesta y nadie se entera |
| **C-GRZ-01** | Zona gris / doctrina | Sin doctrina, el chat se congela, la dueña escribe la norma y la respuesta sale del mismo turno; nada se descongela hasta que el mensaje salga de verdad | AGENTS §4.5, §4.16; REQ-GAP-01..11 | **E1** el flujo · **E2** la entrega supervisada (servicio contra Postgres real, pero no desde la entrada) | Sí | **Alto** — VIP congelado (no recibe nada) por una regla que no se aplicó |
| **C-SUP-01** | Un turno vivo por chat | Si el VIP manda otro mensaje, el turno anterior se cancela y no salen dos respuestas | AGENTS §4.3; REQ-VIP-06/08, NFR-02 | **E1** (tier1 supersede) | Sí | **Medio** — respuesta obsoleta o duplicada al VIP |
| **C-PRV-01** | Privacidad (fotos) | Una foto con documento de identidad o con tarjeta/cuenta/clave **no sale del servidor**; lo demás se describe | AGENTS §4.22 | **E1** (unit con OCR simulado) | Sí | **Crítico** — un documento de identidad enviado a Google no se puede deshacer |
| **C-PRV-02** | Privacidad (video) | Un video se revisa fotograma a fotograma y si trae un dato fuerte no sale; solo salen los cuadros ya limpios | AGENTS §4.24 | **E1** | Sí | **Crítico** — igual que arriba, sin posibilidad de tapar |
| **C-PII-01** | Privacidad (texto) | Correos, teléfonos, tarjetas y enlaces no viajan al proveedor del modelo, y lo que el modelo repita vuelve intacto al VIP | ESTADO-PROYECTO §Privacidad | **E1** (20 pruebas unitarias) | Sí | **Alto** — fuga de datos o texto deformado en la respuesta |
| **C-MEM-01** | Memoria del VIP | Lo que el VIP cuenta queda guardado y disponible; lo sensible espera la aprobación de la dueña; un VIP nunca ve la memoria de otro | Fase 5; REQ-MEM-02..12, BR-15 | **E1** el flujo · **E2/E3** "la fila queda con huella" · **E2** la visibilidad (repo) | Sí | **Alto** — Diana "olvida", o lo sensible entra al contexto sin aprobación |
| **C-STG-01** | Aprendizaje | La corrección de la dueña no enseña sola: queda como candidata y solo se promueve con confirmación | AGENTS §4.6; REQ-TRN-07, ADM-08, BR-13 | **E1** · **E2** el repositorio | Sí | **Medio** — el bot aprende de una corrección que la dueña no confirmó |
| **C-FB-01** | Feedback de calidad | "Destacar" guarda un ejemplo bueno; "Reprender" entrega la corrección ya y después se elige el alcance; Atención no puede destacar ni reprender | AGENTS §4.13; SPEC-FEEDBACK | **E3** parcial ("Destacar" guarda con huella) · **E1** el resto | Sí | **Medio** — se enseña mal, o Atención contamina el banco VIP |
| **C-PRF-01** | Perfil evolutivo | El perfil del VIP se re-sintetiza con señales fuertes y **nunca** contamina el banco de ejemplos | SPEC-EVOLUCION F1; EA-05 | **E1** · **E2** el repositorio | Sí | **Medio-bajo** (hoy es sombra: mide, no decide) |
| **C-PHT-01** | Saludo / check-in | Un "hola" o un "cómo estás" puro se responde solo, con sus propias frases; si hay sustancia, vuelve al pipeline | AGENTS §4.17 | **E1** | Sí | **Alto** — **es envío real que ya ocurre hoy**, y "nada se envía solo" es falso |
| **C-APR-01** | Aprobación → entrega | Aprobar entrega de verdad, con la forma humana: espera, "escribiendo…", división en varios mensajes | AGENTS §4.1, §4.12; REQ-HUM-*, Anexo I | **E1** (tier1, almacenes en memoria) | Sí | **Alto** — la respuesta no llega, o llega de golpe y sin forma humana |
| **C-SBX-01** | Sandbox | El chat de prueba no ensucia nada: ni memoria, ni ejemplos, ni métricas | AGENTS §4.7, §4.20 | **E1** | Sí | **Medio** — las pruebas de la dueña contaminan los datos reales · **Actualización 2026-10-19 (PR #26):** resuelto para métricas y aprendizaje con `turns.is_sandbox` (migración 037); sin backfill de turnos anteriores |
| **C-PRM-01** | Promoción no-VIP | Un disparo exacto responde una vez por ventana; después varía; nunca repite en bucle | AGENTS §4.10; REQ-PRO-01..04 | **E1** | Sí | **Medio** — spam al interesado (dinero) o silencio permanente tras un fallo |
| **C-ATN-01** | Atención general | El canal no-VIP respeta su ciclo de un día, su tope de 20 mensajes y el pago cierra el ciclo | Fase 4; REQ-ATN-01..14 | **E2** los contadores (repo) · **E1** el flujo | Sí | **Medio** — se atiende a quien ya no corresponde, o se deja de atender por un contador roto |
| **C-LNK-01** | Vínculo Lucien → Diana | Si expulsan a un VIP, la dueña recibe el aviso con tres opciones, una sola vez | AGENTS §4.14; REQ-LNK-01..10 | **E1** | Sí | **Medio** — aviso duplicado o pérdida de la decisión |

### 2.3 Resto del catálogo — con efecto observable, aún sin ronda asignada

| Contrato | Área | Qué promete | Nivel hoy | Nota |
|---|---|---|---|---|
| **C-OPN-01** | Arranque de VIP nuevo | Al registrar un VIP, Diana contesta los mensajes que quedaron sin responder y deja el borrador en la cola (nunca envía sola) | **E1** | La importación de historial (mismo camino) sí está en E3 |
| **C-HIST-01(a)** | Historial (captura) | Cada mensaje que la dueña envía por Diana queda en el historial del chat | 🟡 **E2 parcial** (15.688 filas, todas con id; sin prueba de efecto) | El vigilante V4 está escrito pero **no activado** (hoy da 18) |
| **C-HIST-01(b-recarga)** | Historial (recarga) | El historial previo de un VIP ya registrado se recupera | ⚪ **apagado a propósito** (6-sep) | Bandera `FEATURE_HISTORY_REIMPORT_ENABLED=false`, declarada |
| **C-TRC-01** | Trazabilidad | Cada respuesta se puede reconstruir paso a paso (`/traza`) | **E1** | El informe lo da por cumplido por lectura |
| **C-MET-01** | Métricas de aprendizaje | Los números que la dueña lee cuentan lo que dicen contar | **E1** | Sospecha abierta (S1): "cuántos mandó Diana sola" cuenta **decisiones**, no entregas |
| **C-DED-01** | Deduplicación | El mismo mensaje de Telegram no se procesa dos veces | **E1** | VIP-07 declarado abierto en el informe (ventana de duplicados) |
| **C-EVE-01** | Eventos temporales | Un dato con fecha de la dueña entra al contexto mientras está vigente y no contamina memoria ni ejemplos | **E1** | Sin bandera, siempre cableado |
| **C-HSW-01** | Cambio de modelo en caliente | La dueña cambia el modelo de IA sin reiniciar | **E1** | ADM-03 cerrado por código |
| **C-SCH-01** | Agenda / rutina | El planificador pide la agenda cuando corresponde | **E1** | Brecha #8: inyección condicional, parcial por diseño |
| **C-WCH-01** | Vigilante de contratos | Si un efecto prometido deja de ocurrir, la dueña recibe un aviso al día | 🟢 **E2** (16 pruebas; servicio real) | Es una herramienta de auditoría, no una promesa de negocio |
| **C-REC-01** | Recontacto | Un VIP en silencio recibe un mensaje personalizado, nunca si está pausado o congelado | ⚪ **apagado a propósito** | `FEATURE_RECONTACT_ENABLED=false` **sin declarar** → `/health` en `ok:false` permanente (H-9) |
| **C-CAL-01** | Calibración | Los umbrales se ajustan solos con el uso real | ⚪ **apagado a propósito** | Encenderla mueve el umbral de seguridad del modo supervisado al gate de escalación (H-3) |

---

## 3. Rondas propuestas

Criterio de orden: **núcleo del negocio × posibilidad de fallar en silencio × sin prueba de efecto**.
En todas, el trabajo es el mismo: rastrear el camino, escribir una prueba E2 desde la entrada real,
sabotear, y proponer el vigilante.

### 🔴 Ronda 1 — El VIP esperando (lo que ya puede estar roto hoy)

| # | Contrato | Por qué primero |
|---|---|---|
| 1 | **C-ESC-01** Escalación y falso positivo | Es la red de seguridad del negocio: si el bot no responde, la dueña tiene que enterarse. Tiene **más de diez ramas que fallan cerrado dejando solo un registro técnico** (`escalation_reply_behavior_not_wired`, `escalation_fp_resume_*`, `owner_escalate_missing_turn`…). Hoy se prueba con un director falso |
| 2 | **C-GRZ-01** Zona gris y doctrina viva | Un VIP congelado es un VIP que no recibe nada. El flujo tiene cuatro finales distintos (regla aplicada, regen fallido, aprobación fallida, notificación caída) y ninguna prueba de efecto. Además el contrato cambió de diseño (regla viva + regen) y **los requisitos originales todavía describen el camino viejo por staging** |
| 3 | **C-SUP-01** Un solo turno vivo por chat | Es el invariante que el propio diseño marca como no negociable, y hoy solo lo prueba un almacén en memoria |

### 🔴 Ronda 2 — La privacidad de lo que entra

| # | Contrato | Por qué aquí |
|---|---|---|
| 1 | **C-PRV-01** Fotos | Es el único contrato cuyo fallo **no se puede revertir**: un documento de identidad enviado al proveedor externo ya salió. Hoy se prueba con OCR simulado, sin Postgres ni entrada real |
| 2 | **C-PRV-02** Video | Igual, con el agravante de que un video no se puede tapar: la única defensa es no enviarlo |
| 3 | **C-PII-01** Texto | El enmascarado es un único punto por el que pasan **todas** las llamadas al modelo. 20 pruebas unitarias, ninguna de efecto |

### 🟠 Ronda 3 — Lo que Diana recuerda y aprende

| # | Contrato | Por qué aquí |
|---|---|---|
| 1 | **C-MEM-01** Memoria del VIP | Es la propuesta de valor de la Fase 5 y está **best-effort de punta a punta**: cualquier fallo se traga y el turno sigue. Lo único probado con efecto es que la fila queda con huella, no que el contenido sea correcto ni que lo sensible espere aprobación |
| 2 | **C-STG-01** Corrección → revisión | El aprendizaje es el otro pilar. Hay que probar que una corrección **no** enseña sin confirmación, y que la promoción respeta el alcance del canal |
| 3 | **C-FB-01** Destacar / Reprender | Enseña de inmediato, sin pasar por revisión. Falta probar que Reprender entrega el texto ya, que Atención está bloqueada y que el contraejemplo queda bien marcado |
| 4 | **C-PRF-01** Perfil evolutivo | El riesgo es la contaminación entre el perfil y el banco de ejemplos (EA-05). Hoy es sombra, así que la severidad es menor |

### 🟡 Ronda 4 — Los envíos que ya salen solos

| # | Contrato | Por qué aquí |
|---|---|---|
| 1 | **C-PHT-01** Saludo / check-in | **Es el único envío real sin aprobación que ocurre hoy** (bandera viva, independiente del interruptor maestro). Nadie probó que el corte a plantilla solo ocurra con saludo puro, ni que un check-in con sustancia vuelva al pipeline |
| 2 | **C-APR-01** Aprobación → entrega | Es el camino que la dueña usa todos los días. Hoy se prueba con almacenes en memoria: no hay evidencia de que el mensaje llegue al VIP ni de que la forma humana (espera, typing, división) se respete |
| 3 | **C-SBX-01** Sandbox aislado | La dueña lo usa para probar; si el aislamiento se rompe, sus pruebas ensucian memoria, ejemplos y métricas reales |

### 🟡 Ronda 5 — Los canales de negocio

| # | Contrato | Por qué aquí |
|---|---|---|
| 1 | **C-PRM-01** Promoción | Es dinero: un disparo que no se silencia es spam; un silencio tras un fallo es una venta perdida. Tiene contrato de repetición y reclamo temprano, sin prueba de efecto |
| 2 | **C-ATN-01** Atención | Los contadores sí están probados contra Postgres real, pero el flujo no: ciclo de un día, tope de 20 y cierre por pago. El tope es **fail-open** si falla la base |
| 3 | **C-LNK-01** Vínculo Lucien | Está activo en producción y decide sobre VIP reales (expulsar / desactivar / mantener). La idempotencia por `event_id` no tiene prueba de efecto |

**Después de estas cinco rondas** quedan C-OPN-01, C-HIST-01(a), C-TRC-01, C-MET-01 y C-DED-01 como
rondas cortas (una o dos cada una), y las capacidades apagadas a propósito (recontacto, calibración,
recarga de historial) que **no se auditan hasta que la dueña decida encenderlas**.

---

## 4. Contradicciones entre documentos

Ordenadas por cuánto afectan una decisión de producto.

| # | Qué dice un documento | Qué dice otro / la realidad | Impacto |
|---|---|---|---|
| **1** | `faltantes.md` §7 (2026-09-14): la importación de historial al alta de un VIP nuevo está **apagada a propósito** (`FEATURE_VIP_HISTORY_SEED_ENABLED=false`) | El `.env` real la tiene en **`true`** con el comentario "VIVO", y la ficha `C-HIST-01` la da por 🟢 desde el 2026-10-07 | **Alto**: quien lea el catálogo de faltantes creerá que el alta no toca Telegram. Hoy sí lo toca |
| **2** | `faltantes.md` §2, `docs/ESTADO-PROYECTO.md` §3 y `C-SHADOW-01`: `FEATURE_AUTONOMY_COINCIDENCE_ENABLED` es un control activo de la medición | **Ningún módulo la lee** (probado por efecto: encendida y apagada dan el mismo resultado). La coincidencia corre siempre | **Alto**: la dueña cree tener un interruptor que no existe |
| **3** | `docs/SPEC-AUTONOMIA-CALIBRACION.md` v1.0 (2026-08-22): *"Estado: DISEÑO aprobado — **no implementado**"*, migración 030 *"pendiente de implementar"* | La 030 está aplicada (head 036), las cuatro banderas están en `true`, hay 552 filas de medición y los contratos C-AUT-01..04 están en E3 | **Alto**: el spec que se lee para entender la autonomía describe algo que ya está en producción. No quedó actualizado |
| **4** | `docs/INFORME_AUDITORIA.md` (los "143 cumple"): AUTH-03 ❌ P1, GAP-11 ⚠️ P1, REE-02/COG-15 ⚠️ P2, AUTH-07 ❌ P2 | `faltantes.md` y `ESTADO-PROYECTO.md` (2026-09-14): AUTH-03 **descartado por producto**; GAP-11 y REE-02/COG-15 **implementados**; AUTH-07 **diferido** | **Medio**: el informe de auditoría es la fuente que se cita, y está desactualizado en 4 de sus 8 pendientes |
| **5** | `docs/ESPEC` de zona gris en los requisitos (REQ-TRN-06/07, BR-13, NFR-16): resolver la doctrina **pasa por staging con confirmación** | `SPEC-FASE2` §6.2 lo declara **superseded**: el resolve inserta la política viva y regenera el mismo turno, sin `staging_candidates` | **Medio**: quien audite contra los requisitos originales va a exigir un paso que el diseño retiró a propósito. (Destacar/Reprender tiene el mismo choque: REQ-TRN-07 exige staging, FB-05 promueve directo) |
| **6** | `docs/ESTADO-PROYECTO.md` §2: *"El bot sigue 100 % supervisado… nada se autoenvía"* | `AGENTS.md` §4.17 y `audit/AUTONOMIA-BANDERAS.md` (H-7): los saludos y check-ins puros **ya se envían solos** al VIP, con bandera propia e independiente del interruptor maestro | **Medio**: cambia la respuesta a "¿el bot manda solo?" — hoy la respuesta es sí, en un carril acotado |
| **7** | `wiki/concepts/canal-atencion.md` (2026-08-11): al llegar al tope diario hay *"una única respuesta de cierre"* | `docs/SPEC-FASE4.md` §5/§235/§248: esa plantilla **se retiró el 2026-09-08**; ahora el mensaje 21+ se descarta en silencio | **Medio-bajo**: describe un aviso al cliente que ya no existe |
| **8** | `wiki/entities/modulos/jobs.md`: *"sin jobs nuevos post-11-ago"*; `wiki/index.md`: *"Alembic 001–029"*, *"apply 027-029 sin verificar"* | `src/diana/jobs/` tiene `contract_watchdog`, `outcome_reaction` y `profile_synthesis_job`; `ESTADO-PROYECTO.md` verifica el head **036** | **Bajo**: wiki desactualizada |
| **9** | `docs/contratos_restantes.md` Anexo F.3: el Decisor evalúa 3 reglas, sin `consult_doctrine` ni `risk alto` | `AGENTS.md` §4.1 y el código real: 5 prioridades (seguridad → zona gris → riesgo → frustración → autónomo → aprobar) | **Medio**: es el contrato que un implementador leería para tocar el Decisor |
| **10** | `system_config` en la base: 7 banderas `FEATURE_*` dicen `false` (zona gris, staging, promo, sandbox, comportamiento avanzado, modo general, persona admin) | El `.env` real las tiene en `true`. Ningún módulo lee esas filas (`get_feature_flags` no tiene llamadores) | **Bajo-medio**: quien audite leyendo la base obtiene un estado falso |
| **11** | `AGENTS.md` se titula **v1.3** en el encabezado | El pie del mismo archivo dice **v1.5** | **Trivial**, pero conviene arreglarlo: es el documento que se cita como autoridad |
| **12** | `docs/contratos_restantes.md` Anexo I.2: `fake_delivery` está *"reservado para sandbox futuro"* | Anexo I.4 del mismo archivo: implementado y activo | **Trivial**: inconsistencia interna del mismo documento |

---

## 5. Lo que NO entra en este mapa (y por qué)

El método solo audita promesas con **efecto observable**. Quedan fuera, y no por eso son menos
importantes — pero no se pueden probar con una fila o un mensaje:

- **El Director es 100 % determinista** y cada componente responde una sola pregunta (AGENTS §1).
  Se protege con pruebas de pureza e importación, no con evidencia de efecto.
- **Las reglas de dependencia entre capas** (Cognitive no importa Telegram, Behavior no importa
  cognición). Hay *purity gates* unitarios.
- **La serialización por chat** en sí misma (el lock) — su efecto observable es C-SUP-01.
- **La calibración de umbrales** y el **recontacto**: apagados a propósito. Se auditan el día que se
  enciendan, y en el caso de la calibración hay un riesgo declarado que debe resolverse *antes* (H-3).
- **El contenido de las conversaciones**: por la regla prioritaria del proyecto (`AGENTS.md`,
  PRIORITARIO 1) no se leyó texto de ningún VIP. Todo lo anterior sale de código, documentos,
  configuración y conteos.

---

## 6. Cómo se cierra cada contrato (recordatorio del método)

1. **Extraer** — la ficha ya existe en `audit/contracts/` con las cinco primeras líneas llenas.
2. **Rastrear** — entrada real → paso → paso → efecto, anotando cada punto donde la cadena se rompe en
   silencio. Herramienta: `python audit/tools/wiring_scan.py`.
3. **Probar (E2)** — prueba en `tests/audit/`, arrancando por `build_app`, contra Postgres real
   (contenedor + copia de la base real). Prohibido simular la pieza bajo prueba.
4. **Sabotear (E3)** — desconectar la pieza a propósito y exigir que la prueba falle. Sin esto, no hay
   verde.
5. **Banderas** — correr el contrato con cada bandera relevante en ON y OFF.
6. **Vigilante (E4)** — una consulta diaria de solo lectura que avise si el efecto deja de ocurrir.
7. **Reportar** — semáforo en lenguaje de negocio y decisión para la dueña.

**Regla de oro:** una prueba que pasa a la primera es sospechosa. Primero se sabotea.

---

*Mapa generado en modo solo lectura. No se modificó código, no se ejecutó nada contra la base real y no
hubo commit ni despliegue.*
