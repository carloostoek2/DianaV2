# Encender la autonomía — informe consolidado para la dueña

Fecha: 2026-10-09. Árbitro: agente de auditoría (`contract-proof`).
Alcance: los cuatro contratos del camino a la autonomía (`C-AUT-01` a `C-AUT-04`), más los
hallazgos del envío, la puerta de recomendación, la matriz de banderas y el rastreo de cableado.
Fuente de los números: base real, copia fresca del 2026-10-09 (la copia vieja que usaban algunas
pruebas estaba congelada en el 6 de octubre: 2.443 turnos contra 2.561 reales).

Regla de lectura: **solo se reporta como verificado lo que tiene prueba de efecto contra la base
real (E2) más un sabotaje que hace fallar esa prueba (E3)**. Lo que solo existe en código es
"sospecha razonada", y se dice así.

---

## 1. Respuesta directa: ¿se puede encender la autonomía hoy?

**Hoy no. Y encender el interruptor maestro tampoco sería encender la autonomía.**

Tres razones, en orden de peso:

1. **La propia puerta de la dueña está cerrada.** La regla que ella misma aprobó exige 95 % de
   coincidencia y la ventana de 14 días mide **92,8 %**. Nada que discutir: el botón "Activar"
   no se dibuja. (Histórico: 87,8 %. Tendencia semanal: 72,4 % → 88,9 % → 88,0 % → 97,1 % →
   91,7 %.)
   > Nota 2026-10-19 (PR #26): estas cifras incluyen turnos de sandbox. Desde la migración 037
   > el panel los excluye; la tasa sin sandbox debe re-medirse (no se re-midió en esta nota).
2. **La evidencia que alimenta la puerta está sucia.** De las 341 señales "positivas" que suben
   la confianza de un VIP, **184 (54 %) cuelgan de mensajes que nunca se le entregaron** (173 de
   turnos reemplazados por un mensaje posterior y 11 de turnos escalados). Cada una suma +0,05.
   Sin esa evidencia, uno de los tres pares VIP/categoría que hoy pasan el umbral de confianza
   caería de 0,920 a ~0,55. Es decir: si la condición de coincidencia no estuviera frenando el
   encendido, la de confianza habría abierto la puerta con evidencia inflada.
3. **El interruptor maestro no cambia nada por sí solo.** Hoy hay **0 de 16 VIPs** con permiso
   de envío automático, y el modo general es "supervisado". Encender el maestro con el permiso
   vacío no manda ni un mensaje: el sistema sigue pidiendo aprobación. Lo que sí hace es **armar
   el botón**: a partir de ese momento, cada VIP que la dueña active empieza a enviar solo, sin
   volver a revisar si sigue cumpliendo las tres condiciones.

**Sí con condiciones**, y son estas, en este orden:

| # | Condición | Por qué |
|---|---|---|
| 1 | Limpiar la confianza: dejar de contar reacciones de turnos no entregados (y, si se puede, recalcular) | Es la condición de confianza de la puerta. Hoy está inflada |
| 2 | Tapar el hueco de la pausa: un VIP pausado a mitad de turno no debe recibir el envío | Confirmado con prueba: hoy sí lo recibe |
| 3 | Hacer que la medición avise cuando deja de escribir (el vigilante V8) | Hoy una confianza congelada se ve igual que una confianza sana |
| 4 | Arreglar el número que la dueña va a mirar: "cuántos mensajes mandó Diana sola" hoy cuenta decisiones, no entregas | Sin eso, el primer reporte después del encendido dirá que Diana envió sola cuando no envió nada |
| 5 | Avisar cada envío automático durante la primera etapa | Hoy no existe; es la red que reemplaza a la aprobación previa |

Las tres primeras son de seguridad de la evidencia. Las dos últimas son de visibilidad: sin
ellas la dueña no puede saber si la autonomía está funcionando.

---

## 2. Semáforo

| Contrato | Qué promete | Qué pasa de verdad | Semáforo |
|---|---|---|---|
| **C-AUT-01** — envío autónomo con dos puertas | Con las dos puertas abiertas el mensaje sale y no pasa por la cola; con cualquiera cerrada no sale nada | Ocurre, y está probado con sabotaje: 9 de 10 escenarios en verde (entrega real, las dos puertas, Atención, congelado). **Una cláusula falla**: un VIP pausado a mitad de turno recibe igual el envío | 🟢 **E3** en la doble puerta · 🔴 en la pausa |
| **C-AUT-02** — la puerta mide y nunca envía sola | Activa solo con las tres condiciones; activar no envía | Ocurre, probado con sabotaje en cada una de las tres condiciones y en "activar no envía". Hoy la puerta está cerrada: 92,8 % < 95 %. El botón dice "Activado" aunque el maestro esté apagado | 🟢 **E3** |
| **C-AUT-03** — la reacción del VIP cierra el círculo | La reacción o el silencio se registran sobre el turno que sí se entregó, y no se cuenta dos veces | El registro sí corre (551 de 552 filas con señal), pero **se cuelga de turnos que nunca salieron** en la mitad de los casos, y nadie probó la idempotencia ni la atribución al turno correcto | ⚪ **sin verificar** (con un defecto medido en producción) |
| **C-AUT-04** — la confianza se ajusta por una sola fuente | Con el camino encendido, la confianza se ajusta por una fuente y no hay doble conteo | La fuente única está probada con sabotaje (un evento por resolución). **Una promesa falla**: si se apaga la medición de calidad, la confianza se congela sin aviso ni error | 🟢 **E3** en la fuente única · 🔴 en "siempre hay una vía de ajuste" |

Leyenda: 🟢 E3/E4 = probado con efecto real y sabotaje · 🟡 E2 = probado con efecto real, sin
sabotaje · 🔴 el efecto no ocurre · ⚪ sin verificar.

Dos de los cuatro contratos tienen encendido verde **en la parte que ya se probó** y una cláusula
en rojo. No son lo mismo: en esos casos la promesa principal ocurre y una condición de borde no.

---

## 3. Hallazgos ordenados por gravedad

### 3.1 Defectos confirmados con prueba de efecto

**D1 — La confianza de los VIP se infla con reacciones a mensajes que nunca se enviaron.**
(C-AUT-03, medido en la base real.)

- Qué pasa en el negocio: la primera condición de la puerta es "la confianza de este VIP ≥ 0,90".
  Esa confianza sube cuando el VIP responde bien a un mensaje de Diana. Hoy sube también cuando
  el VIP responde a un mensaje que **nunca recibió** (porque un mensaje suyo posterior reemplazó
  ese turno, o porque el turno se escaló y no se envió): 173 reacciones positivas de turnos
  reemplazados y 11 de turnos escalados, de 341 positivas.
- Evidencia: conteo sobre `turn_outcome_log` cruzado con el estado del turno. Un par
  (Hug Vbs / informativo) tiene 0,920 y caería a ~0,55 sin esa evidencia; los otros dos pares
  que superan 0,90 se sostienen.
- Qué habría que hacer: que la señal solo se escriba sobre turnos entregados (y no sobre el
  último turno del chat sin señal), y recalcular o descontar lo ya contado. Es un cambio de
  código; hoy no está hecho.

**D2 — Un VIP pausado puede recibir un envío automático si la pausa entra a mitad del turno.**
(C-AUT-01, escenario S4b, en rojo a propósito en la suite.)

- Qué pasa en el negocio: la pausa es una decisión de la dueña (por ejemplo, un VIP que pidió
  que no se le escriba un tiempo). Si ese VIP escribe y la pausa se aplica mientras el mensaje
  ya entró a la máquina, el borrador sale igual. Hoy no pasa porque el envío automático está
  apagado; el día que se encienda, sí.
- Evidencia: prueba sobre la base real con el reloj de pausa en el futuro → turno entregado y
  mensaje real en el registro de envíos. La suite la deja como "falla esperada" para que el
  defecto se vea en cada corrida; se comprobó además que, si alguien lo arregla, la prueba pasa.
- Qué habría que hacer: revisar la pausa justo antes de entregar, igual que ya se revisa la
  congelación.

**D3 — Si se apaga la medición de calidad, la confianza se congela sin aviso.**
(C-AUT-04, H-2, probado por efecto y por sabotaje.)

- Qué pasa en el negocio: con el camino de autonomía encendido (como está hoy), la confianza
  debería ajustarse solo por resultados. Si alguien apaga la bandera de calidad "para dejar de
  medir", quedan suprimidas las dos vías: la confianza **no se mueve más**, la puerta queda
  cerrada para siempre para los VIP nuevos y **nada avisa** (ni mensaje, ni error en el registro
  interno). Se midió: 0,50 → 0,50 → 0,50 tras aprobar y corregir, sin fila de medición y sin un
  solo aviso de la aplicación.
- Evidencia: prueba sobre la base real con la combinación de banderas, más el sabotaje que
  muestra que el congelamiento depende por completo de esa guarda.
- Qué habría que hacer: que la combinación "camino encendido + medición apagada" avise al
  arrancar (hoy no existe ninguna advertencia para ese par).

**D4 — El puntaje de calidad del borrador no distingue un buen borrador de uno rechazado.**
(C2, medido.)

- Qué pasa en el negocio: el círculo de aprendizaje tiene tres piezas: si Diana habría acertado,
  qué tan bueno es el texto y cómo reaccionó el VIP. La del medio no sirve: el puntaje medio del
  borrador es 0,620 cuando la dueña lo aceptó y 0,625 cuando lo corrigió o lo escaló. Es decir,
  no hay red de seguridad adicional por calidad de texto, y ese número no debería usarse para
  decidir el encendido.
- Evidencia: comparación de los puntajes guardados entre aceptados y rechazados.
- Qué habría que hacer: decidir qué se hace con esa pieza (arreglarla o dejar de mostrarla). Hoy
  no bloquea el envío, pero no se puede prometer como garantía.

**D5 — El botón "Activar" dice "Activado" con el interruptor maestro apagado.**
(C-AUT-02, H-6, probado por efecto.)

- Qué pasa en el negocio: el orden natural de encendido es activar VIPs y después el maestro.
  El panel permite activar con el maestro apagado y confirma "Activado el envío autónomo para
  <VIP>", pero no se envía nada. Dos consecuencias: la dueña puede creer que ya está encendido
  (o, al revés, apagarlo y creer que sigue andando), y los VIPs activados quedan armados para
  dispararse solos en el instante en que se encienda el maestro, sin revisar si siguen
  cumpliendo las condiciones.
- Evidencia: prueba sobre la base real: con el maestro apagado, turno en la cola y 0 mensajes al
  VIP; con el maestro encendido, mismo VIP y mismo permiso → entrega y 1 mensaje.
- Qué habría que hacer: que el texto diga el estado real ("quedó activado para este VIP, pero el
  envío automático general está apagado") y que el encendido del maestro re-evalúe a los VIPs
  activados.

**D6 — Una bandera de la coincidencia no existe de verdad.**
(C-AUT-02, H-1, probado por efecto.)

- Qué pasa en el negocio: `FEATURE_AUTONOMY_COINCIDENCE_ENABLED` está en `true`, se documenta
  como control activo, y **ningún módulo la lee**. Apagarla no cambia nada; encenderla tampoco.
  La dueña cree tener un control que no tiene.
- Evidencia: dos ejecuciones con la bandera en ON y en OFF dan el mismo resultado en los seis
  campos de la medición.
- Qué habría que hacer: borrarla (y corregir la documentación) o hacer que gobierne de verdad la
  parte de coincidencia.

**D7 — Nada muestra el estado del interruptor maestro.**
(H-5, verificado en código y configuración.)

- Qué pasa en el negocio: el maestro es la bandera que más le importa a la dueña y no aparece en
  el chequeo de arranque, ni en `/health`, ni en ningún mensaje de Telegram. Hoy no se puede
  distinguir "autonomía apagada a propósito" de "autonomía encendida y sin ningún VIP activado".
- Evidencia: la bandera está clasificada fuera del catálogo de banderas núcleo.
- Qué habría que hacer: publicarla en `/health` y en el panel ("llevas X VIPs activados, pero el
  envío automático general está apagado").

**D8 — El registro interno de configuración contradice al archivo real en 7 banderas.**
(H-8 / P-10, medido.)

- Qué pasa en el negocio: hay filas guardadas que dicen lo contrario del archivo de configuración
  real (zona gris, staging, promo, sandbox, comportamiento avanzado, modo general). Ningún
  módulo las lee. Si alguien "enciende la bandera en la base", no pasa nada.
- Qué habría que hacer: limpiarlas o rotularlas como no operativas.

### 3.2 Sospechas razonadas (código leído, sin prueba de efecto todavía)

**S1 — El número "cuántos mensajes mandó Diana sola" cuenta decisiones, no entregas.**
(P-2.) Con el maestro encendido y 0 VIPs activados, la decisión interna es "enviar" pero el
mensaje va a la cola. La métrica semanal leería esas decisiones y diría que Diana envió sola
cuando no envió nada. Sería el primer dato que la dueña mira para decidir el paso siguiente.
No se probó. **Qué habría que hacer**: probarlo (es barato) y arreglarlo antes del encendido.

**S2 — Encender la calibración automática movería el umbral de seguridad en caliente.**
(H-3.) La calibración comparte el mismo contenedor de umbrales que el decisor vivo y escribe el
mínimo *supervisado* en el gate de *seguridad* de escalación. Hoy el riesgo está neutralizado
porque hay un valor que lo pisa y la calibración está apagada. **Qué habría que hacer**: no
encenderla sin revisar esto.

**S3 — Bordes de la entrega que nadie mira.** Si la entrega se cancela a mitad de camino, o el
turno se vuelve obsoleto justo después de enviar, o falla el registro del envío partido, hay
caminos donde el mensaje sale (o queda a medias) y **la dueña no recibe ningún aviso**. Son
lecturas de código con baja probabilidad (P-3, P-4, P-6, P-7). **Qué habría que hacer**: las
pruebas de borde de la ronda siguiente.

**S4 — El aviso de un borrador que quedó en la cola por falta de permiso muestra un texto
técnico crudo** (`autonomous_mode_disabled`) en lugar de una frase para la dueña (P-9). Cosmético
pero visible justo cuando el maestro esté encendido y la mayoría de los VIPs no tengan permiso.

### 3.3 Rutas de diseño que NO son fallas

- **Atención nunca envía sola.** Probado: con el maestro encendido y el modo general en
  autónomo, un chat que no es VIP queda en la cola. Es el invariante de seguridad del canal.
- **El sandbox no guarda nada.** No deja memoria, ni ejemplos, ni medición: es a propósito, para
  que la dueña pueda probar sin ensuciar el sistema. Si aparece como "sin registro", es diseño.
  > **Actualización 2026-10-19 (PR #26, `4bc5754`):** no era del todo cierto para las métricas.
  > Los turnos de sandbox entregados sin aprobación se contaban en la coincidencia (como aciertos
  > o conservadoras) y movían la confianza. Resuelto con `turns.is_sandbox` (migración 037): la
  > reacción de confianza y los lectores de métricas los excluyen. Sin backfill.
- **Un VIP pausado que escribe no recibe nada, ni entra a la cola.** El mensaje se descarta en
  la entrada, en silencio. Es el comportamiento de la lista blanca, no un defecto de este camino.
- **Ya hay envíos sin aprobación hoy, y no son del camino autónomo.** Los saludos y check-ins
  puros (hola, cómo estás) ya salen directo al VIP sin pasar por la cola, con una bandera
  independiente del maestro. Es una decisión de producto vigente; conviene saberlo, porque
  "nada se envía solo" hoy es falso.
- **La puerta de recomendación no envía.** Probado: activar escribe el permiso y no llama al
  motor de envío. El maestro sigue gobernando.

---

## 4. Lo que NO se pudo verificar (⚪) y por qué

1. **La reacción del VIP de punta a punta (C-AUT-03).** No existe prueba de efecto: no se
   verificó que la señal se escriba sobre el turno correcto (el que sí se entregó) ni que no se
   cuente dos veces. Por eso C-AUT-03 queda ⚪ aunque la mitad "sombra" de la tabla esté en E3/E4.
2. **El clic real en el menú de Telegram.** Las pruebas llaman al mismo servicio que invoca el
   botón, pero no recorren el teclado ni el callback del menú.
3. **El reporte "Autonomía" que aparece dentro del mensaje de borrador** y su degradación
   silenciosa a "aún sin historial" cuando falla la base.
4. **La métrica de envíos autónomos (S1)**: no se corrió la prueba.
5. **Los bordes de la entrega (S3)**: cancelación, turno obsoleto después del envío y envío
   partido. La ventana es estrecha y no se pudo provocar sin ejecutar el sistema.
6. **El comportamiento con el maestro encendido en producción.** No se encendió nada: toda la
   evidencia del envío real viene de contenedores de prueba con el envío simulado.
7. **El contenido de las conversaciones.** Por la regla prioritaria del proyecto solo se leyeron
   conteos, estados y configuración; nunca texto de VIP.
8. **Los vigilantes propuestos aquí no existen todavía** (no hay nada desplegado que avise de una
   confianza congelada ni de un envío sin medición).

---

## 5. Vigilantes E4 propuestos

Formato y reglas: los mismos del archivo de vigilantes activos
(`audit/vigilantes.sql`). Cada bloque lleva su cabecera `-- V<n> | activo|no-activado | <contrato>
| <qué vigila>`, devuelve una columna `alerta` y corre **una vez por día, solo lectura**, dentro
del bot. Si la suma de `alerta` es mayor que 0, **la dueña recibe un mensaje por Telegram** (el
mismo canal que ya usan V1/V2/V3/V7); si es 0, no recibe nada.

**Ninguno se activa hoy.** Quedan como propuesta, en `no-activado`, con el motivo escrito.

### V8 — la confianza dejó de moverse (el síntoma de D3)

Qué vigila: que la medición siga alimentando la confianza de los VIP.
Umbral: en los últimos 2 días hubo al menos una resolución de la dueña (aprobó o corrigió un
borrador) y **ninguna** fila de confianza se movió. Con unas 3 resoluciones por día y una de cada
cinco conservadora, que ninguna mueva la confianza solo pasa si la medición dejó de escribir.
Avisa: la dueña, por Telegram.

```sql
-- V8 | no-activado | C-AUT-04 | la medicion dejo de alimentar la confianza (sintoma de H-2/D3)
-- Mide el EFECTO, no la configuracion: si la medicion dejo de escribir (camino encendido +
-- medicion de calidad apagada, o un fallo tragado), la confianza no se mueve aunque la duena
-- resuelva borradores. Umbral: al menos 1 resolucion en la ventana y CERO movimiento de
-- confianza en toda la ventana. Antes de activarlo hay que medirlo contra la base real y
-- confirmar que hoy da 0. No lleva identidad por caso a proposito: mientras siga congelada,
-- vuelve a avisar todos los dias.
SELECT count(*) AS resoluciones_de_la_duena,
       to_char(max(coalesce(t.updated_at, a.created_at)), 'DD/MM HH24:MI') AS cuando,
       1 AS alerta
FROM pending_approvals a
JOIN turns t ON t.id = a.turn_id
WHERE a.vip_id IS NOT NULL
  AND a.status IN ('approved','corrected')
  AND coalesce(t.updated_at, a.created_at)
      BETWEEN now() - interval '2 days' AND now() - interval '2 hours'
  AND NOT EXISTS (
      SELECT 1 FROM vip_trust_budget b
      WHERE b.updated_at >= now() - interval '2 days'
  )
HAVING count(*) > 0;
```

Copia para el mensaje (bloque nuevo en la tabla de copias del vigilante):

```python
    "V8": _Copy(
        titulo="Dejo de moverse la confianza de tus VIP",
        que_paso=(
            "Resolver borradores ya no mueve la confianza de tus VIP: la medicion dejo de "
            "alimentarla. Con la confianza detenida, ningun VIP nuevo va a poder activarse."
        ),
        ventana="los ultimos 2 dias",
        que_hacer=(
            "Avísame: hay que revisar la medicion de resultados. Mientras tanto, no actives "
            "VIP nuevos (su confianza esta congelada)."
        ),
    ),
```

### V9 — un envío autónomo salió sin dejar su fila de medición

Qué vigila: que cada envío que hizo Diana sola deje su registro (la base con la que se decide si
funciona).
Umbral: 1 o más turnos entregados por decisión de envío automático sin fila de medición en las
últimas 2 días.
Avisa: la dueña, por Telegram.

```sql
-- V9 | no-activado | C-AUT-01 | un envio autonomo salio sin dejar su fila de medicion
-- Exige traza CON evaluacion y descarta las plantillas de saludo/check-in (que responden sin
-- pasar por el motor de decision). Hay que agregar V9 a VIGILANTES_CON_FILTRO_SANDBOX en
-- contract_watchdog_service.py: el sandbox no persiste a proposito y sus envios son directos.
-- ACTUALIZACION 2026-10-19 (PR #26): ya no hace falta la lista del journal; basta con
-- agregar `AND NOT t.is_sandbox` (migracion 037), como V2/V3/V4.
SELECT t.id::text AS turno, t.chat_id AS chat,
       to_char(t.created_at, 'DD/MM HH24:MI') AS cuando, 1 AS alerta
FROM turns t
JOIN pipeline_traces p ON p.turn_id = t.id
LEFT JOIN turn_outcome_log o ON o.turn_id = t.id
WHERE t.vip_id IS NOT NULL
  AND t.status = 'delivered'
  AND p.evaluation IS NOT NULL
  AND coalesce(p.decision->>'action', '') = 'send'
  AND coalesce(p.decision->>'reason', '') NOT LIKE 'plantilla_%'
  AND o.id IS NULL
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '1 hour'
ORDER BY t.created_at DESC;
```

```python
    "V9": _Copy(
        titulo="Un mensaje automatico salio sin su registro",
        que_paso=(
            "Diana respondio sola a un VIP y ese envio no dejo su registro de medicion. "
            "Sin ese registro no se puede saber si acerto."
        ),
        ventana="los ultimos 2 dias",
        que_hacer="Avísame: hay que revisar por que no quedo el registro de ese envio.",
    ),
```

### V10 — un VIP con permiso dado quedó en la cola (el maestro está apagado)

Qué vigila: que el permiso por VIP y el interruptor maestro no se contradigan (hoy la dueña no
tiene forma de verlo: D7 y D5).
Umbral: 1 o más turnos de un VIP con permiso de envío automático que terminaron en la cola de
aprobación en las últimas 2 días.
Avisa: la dueña, por Telegram.

```sql
-- V10 | no-activado | C-AUT-01 | un VIP activado quedo en la cola: el interruptor maestro esta apagado
-- Si el VIP ya tiene permiso de envio automatico y su turno termino en la cola, la unica causa
-- es el interruptor maestro apagado (o recien apagado). Es el aviso que hoy no existe.
SELECT t.id::text AS turno, t.chat_id AS chat,
       to_char(t.created_at, 'DD/MM HH24:MI') AS cuando, 1 AS alerta
FROM turns t
JOIN pending_approvals a ON a.turn_id = t.id
JOIN vips v ON v.id = t.vip_id
WHERE v.auto_send
  AND a.cognitive_summary = 'autonomous_mode_disabled'
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '2 hours'
ORDER BY t.created_at DESC;
```

```python
    "V10": _Copy(
        titulo="Estas activando VIPs, pero el envio automatico general esta apagado",
        que_paso=(
            "Un VIP que ya tiene el permiso de envio automatico quedo esperando tu aprobacion: "
            "el interruptor general del envio automatico esta apagado."
        ),
        ventana="los ultimos 2 dias",
        que_hacer=(
            "Si querias que Diana respondiera sola, hay que encender el interruptor general. "
            "Si no, apaga el permiso de ese VIP para que el panel diga la verdad."
        ),
    ),
```

### V11 — reacciones colgadas de mensajes que nunca salieron (no se activa hoy)

Qué vigila: la contaminación de D1. **No se activa todavía**: hoy da un número mayor que 0
porque el defecto existe y no está corregido, y un vigilante que avisa todos los días de algo ya
conocido entrena a ignorar los avisos (mismo criterio que V4/V5/V6). Se activa el día que D1 se
corrija, y entonces sirve para detectar la recaída.

```sql
-- V11 | no-activado | C-AUT-03 | reacciones del VIP colgadas de turnos que nunca se entregaron
-- NO se activa: hoy da > 0 porque el defecto (D1) sigue abierto. Se activa cuando D1 se
-- corrija; desde ese dia, cualquier fila es una recaida. Solo cuenta; no lee ningun texto.
SELECT count(*) AS reacciones_sin_entrega, 1 AS alerta
FROM turn_outcome_log o
JOIN turns t ON t.id = o.turn_id
WHERE o.vip_signal IN ('positive','negative')
  AND t.status IN ('superseded','escalated')
  AND o.created_at >= now() - interval '2 days'
HAVING count(*) > 0;
```

### Para poner un vigilante en marcha (una vez que la dueña lo apruebe)

Los bloques de arriba solo tienen la consulta. Activarlos de verdad exige cuatro cosas
(preguntas al equipo, no a la dueña): agregar el bloque al archivo de vigilantes activos,
agregar la copia en español, sumar V9 a la lista de chequeos que descartan las sesiones de
prueba (desde 2026-10-19, PR #26: agregar `NOT t.is_sandbox` a su SQL), y actualizar la prueba que hoy fija que los vigilantes activos son exactamente V1, V2,
V3 y V7. La consulta debe medirse contra la base real **antes** de encenderla, para confirmar que
hoy da 0 (como se hizo con los cuatro vigentes).

---

## 6. Siguiente ronda recomendada

Por orden de valor para la decisión de la dueña:

1. **Corregir la contaminación de la reacción del VIP (D1)** y recalcular la confianza. Es el
   único hallazgo que cambia el veredicto de la puerta: sin él, la condición de confianza no es
   confiable. Después, prueba de efecto + sabotaje + encender V11.
2. **Cerrar el hueco de la pausa (D2)** y volver la prueba S4b a verde.
3. **Prueba de la métrica de envíos (S1)**: una prueba barata que decida si el número que la
   dueña va a leer es el bueno. Si se confirma la sospecha, arreglarla antes del encendido.
4. **Reacción del VIP hasta E3 (C-AUT-03)**: prueba de atribución al turno correcto y de no
   duplicación.
5. **Encender V8** (la confianza dejó de moverse) y **V10** (activación sin maestro): son los dos
   avisos que hoy no existen y que cubren los dos defectos confirmados. V9 en cuanto haya envíos
   autónomos reales que vigilar.
6. **Decidir con la dueña** el listón de coincidencia (¿se queda en 95 %, o se baja a un valor
   alcanzable?) y si el puntaje de calidad (D4) se arregla o se deja de mostrar. Ambas son
   decisiones de producto, no de código.

---

## 7. Decisiones que hay que pedirle a la dueña

1. **¿Confirmas que el interruptor maestro sigue apagado hasta que la evidencia esté limpia?**
   (Recomendación del equipo: sí. Encenderlo hoy no envía nada porque no hay VIPs con permiso,
   pero arma el botón para cualquier VIP que se active después, sin re-chequear las condiciones.)
2. **¿Se baja el listón de coincidencia de 95 % a un valor alcanzable?** (Recomendación: no
   todavía. Con la confianza inflada y el puntaje de calidad que no distingue, el 92,8 % no es
   comparable al 95 %: bajar el listón con esta evidencia sería decidir sobre números sucios.)
3. **¿Autorizas que se corrija la contaminación de la confianza** (dejar de contar reacciones de
   mensajes no entregados) **y que la confianza se recalcule?** (Recomendación: sí, es la
   condición 1 del encendido.)
4. **¿Quieres recibir un aviso por cada envío automático** durante la primera etapa, en lugar de
   aprobar antes de cada uno? (Hoy no existe; es la red que reemplaza a la aprobación previa.)
5. **¿Autorizas encender los vigilantes V8 y V10** (solo lectura, un mensaje al día si algo está
   mal, silencio si está todo bien)?
6. **¿Qué hacemos con el puntaje de calidad del borrador (D4)**: arreglarlo o dejar de mostrarlo?
7. **¿En qué orden quieres el pilotaje**: primero un VIP de prueba en sandbox con el envío
   directo, o directamente un VIP real con aviso de cada envío?
