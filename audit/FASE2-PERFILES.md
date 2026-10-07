# Fase 2 — Perfiles y huellas (`profiles`): el camino muerto quedó cerrado

**Contrato:** C-EMB-01 (tramo `profiles`) · **Antecedente:** `audit/INVESTIGACION-B.md`
**Rama:** `audit/perfiles-embeddings` (desde `main`). **Fecha:** 2026-10-07.
**Sin commit a `main`. Sin despliegue. Producción intacta.**

---

## Resumen para la dueña

Diana guarda junto a cada ficha de VIP una "huella" (384 números) pensada para *buscar por parecido*.
La investigación B encontró dos cosas: **esa búsqueda no existe en producción** (nadie la llama), y
**2 de las 3 fichas tienen la huella en ceros** (son de julio, de antes de que el sistema supiera
calcular huellas).

Elegiste la opción más chica: como la búsqueda por parecido de fichas no se usa, **se elimina**. Eso
es lo que se hizo, más tres cosas alrededor:

| Qué se hizo | Para qué sirve en el negocio |
|---|---|
| Se borró la búsqueda por parecido de fichas | Deja de existir una pieza que nadie usa y que la documentación presentaba como activa |
| Se corrigió la documentación (12 lugares) | Nadie va a construir encima creyendo que esa búsqueda funciona. Era el riesgo real: 2 fichas invisibles **sin error ni aviso** |
| Quedó un trámite repetible para arreglar las 2 huellas en ceros | Cuando quieras, se corrigen de una vez. Primero simula, avisa, y solo escribe si se lo pides |
| Si algún día la huella no se puede calcular, **ahora avisa** | Antes se guardaba en ceros en silencio. Es el mismo sintoma que en agosto dejó ejemplos y políticas invisibles sin que nadie se enterara |

**Qué gana o pierde el negocio hoy:** nada cambia para el VIP ni para lo que Diana responde. Lo que
se gana es que un dato incorrecto ya no está disfrazado de función activa, y que la próxima vez que
algo así se desconecte, va a dejar rastro.

**Verificación con efecto real:** se guardó una ficha por el mismo camino que se usa en el menú
(alta del VIP → botón "añadir nota" → el texto), contra una base de datos real, y se comprobó que la
huella guardada es la del motor real. Después se desconectó el motor a propósito **dos veces**: las
dos veces la prueba falló y dejó el aviso. La prueba no es decorativa.

---

## 1. Decisión de producto y su fundamento

**Decisión (dueña, 2026-10-07): opción 2a —** la búsqueda por parecido sobre `profiles` no se usa, así
que se **elimina la función** en vez de blindarla. No hay plan de usarla; blindarla habría conservado
una pieza sin consumidor y con el agujero ciego del cero.

---

## 2. Confirmación previa exigida: la función no tenía llamador

Antes de borrar nada se verificó que `ProfilesRepo.find_by_similarity` fuera código muerto:

| Comprobación | Resultado |
|---|---|
| Único llamador en todo el repositorio | `tests/unit/infrastructure/test_profiles_repo_write.py:204` (su propia prueba) |
| Llamadas reales a un `find_by_similarity` en `src/` | Solo sobre **`ExamplesRepo`** (`cognitive/retrievers/examples.py:55,69`) |
| Acceso dinámico (`getattr`, despacho por cadena) | **No existe** |
| `Protocol` / `ABC` que la declare | **No existe**: `ProfilesRepo` es una clase concreta; los consumidores usan `get_by_vip_id` y los escritores |
| Lock de forma `test_sql_repo_shapes.py:197` | **No la menciona**; sus aserciones siguen intactas y en verde |
| Índice de vector en la tabla | **No hay** (solo `profiles_pkey`) — coherente con "nunca se consulta por parecido" |

Confirmado: **sin llamador de producción.** Se procedió.

---

## 3. Cambios aplicados

### 3.1 Se borró el camino muerto

| Archivo | Cambio |
|---|---|
| `src/diana/infrastructure/db/repositories/profiles.py` | Se eliminó `find_by_similarity` (era ~111-131) y la mención en el docstring de la clase. El docstring ahora dice explícitamente que la huella **se escribe pero no la consume ningún camino de recuperación**. |
| `tests/unit/infrastructure/test_profiles_repo_write.py` | Se eliminó `test_find_by_similarity_returns_matching_rows`. |

**No se tocó:** `_ZERO_EMBEDDING`, `_embed_content`, los escritores, `_content_to_embedding_text`
(lo reutiliza el script de §5) ni el esquema.

### 3.2 La huella en ceros ya no es muda

`_embed_content` sigue devolviendo ceros cuando no puede calcular (el comportamiento **no cambia**; la
columna es `NOT NULL` y hay llamadores previos que dependen de eso), pero ahora **deja registro**
`profile_embedding_zeros` con el motivo:

| Motivo | Nivel | Cuándo |
|---|---|---|
| `no_embedder` | **WARNING** | El motor de huellas no está conectado |
| `embedder_returned_zeros` | **WARNING** | El motor está conectado pero devolvió un vector nulo |
| `empty_text` | DEBUG | Caso legítimo: la ficha quedó sin contenido |

Origen: el incidente de agosto de 2026 con ejemplos y políticas fue exactamente este síntoma —
"sin huella" disfrazado de dato válido, sin error y sin aviso. `profiles.py:104-126`.

### 3.3 Documentación corregida (12 lugares)

La wiki es **mantenida a mano**: `scripts/wiki_graph/*` solo *lee* los `.md` y escribe
`wiki/.ua/knowledge-graph.json` y `dashboard.html`; no hay generador ni paso de CI que reescriba el
markdown. Editar a mano es seguro.

**El grafo derivado se regeneró** (`./scripts/wiki_graph/make-graph.sh`, determinístico). Sin eso, el
artefacto versionado `wiki/.ua/knowledge-graph.json` habría seguido llevando dentro el texto viejo —
las afirmaciones falsas habrían sobrevivido en un archivo que se commitea. El diff es chico (16 líneas
en el `.json`, 1 en el `.html`): las páginas que corregí, más el sello de fecha/commit. **Absorbe
además un arrastre previo**: el nodo de `estado-del-proyecto` en el grafo estaba desactualizado desde
el cambio de historial del 2026-10-07 (la página sí se actualizó entonces; el grafo no). No es un
efecto de este cambio, pero regenerar lo corrige de paso y se declara acá.

| Archivo:línea | Qué decía | Qué dice ahora |
|---|---|---|
| `wiki/concepts/capability-registry.md:39` | "…`find_by_similarity` (característica vectorial de la tabla `profiles` **activa**)" | La huella se escribe; **no está activa** ninguna búsqueda por parecido |
| `wiki/entities/tablas/esquema-conocimiento.md:13` | "Índices HNSW con pgvector (384 dims)" (a todas las tablas F2) | Acotado a `memories`/`policies`/`examples`; `profiles` y `contexts` no tienen índice |
| `wiki/entities/tablas/esquema-conocimiento.md:17` | "(búsqueda semántica sobre perfiles)" | Sin consumidor; la lectura va por PK |
| `wiki/entities/modulos/cognitive-core.md:46` | `profile` (por PK; … + `find_by_similarity`; …) | Se quitó `find_by_similarity` de la descripción del retriever |
| `wiki/entities/modulos/infrastructure-persistence.md:22` | "pgvector con índices HNSW para embeddings" | Acotado a las tablas que sí lo tienen |
| `wiki/index.md:12` | "retrievers con pgvector" (incluía perfil) | Aclarado: el de perfil va por PK |
| `CHANGELOG.md:338,346` | "perfiles semánticos" / "**Añadimos recuperación semántica de perfiles**" | Entrada histórica tachada + nota fechada 2026-10-07 (no se reescribe el pasado en silencio) |
| `docs/Plan_fase2.md:59` | "…expone `find_by_similarity`" junto al contexto que **sí** se consume | + "sin consumidor en producción" |
| `docs/CHANGELOG-DEPRECADO.md:48` | "…for semantic profile lookup" | "no production path ever called it" |
| `docs/SPEC-1.1.md:514` | "Retrievers reales con pgvector (…, perfil, …)" | `perfil` fuera de la lista pgvector |
| `docs/MVP_COMPONENT_DESIGN.md:87,359,1012` | `perfil` agrupado con "memoria pgvector" | Separado: perfil por PK |
| `docs/ARCHITECTURE.md:118`, `docs/SPEC-FASE2.md:101` | "memoria pgvector + perfil"; "`memories` y `profiles` se escriben vía `replace_vip_profile`" | Desagrupado; aclarado que `replace_vip_profile` escribe **`vip_profile`** (síntesis), no `profiles` |

**Se dejaron como están** (verificados correctos): `docs/SPEC-1.1.md:198` ("busca en `profiles` (por
VIP)"), `README.md:454` ("embeddings reales para perfiles") y todo el lenguaje de similitud sobre
`memories`/`examples`/`policies`.

---

## 4. Prueba E2

`tests/audit/test_C_EMB_01.py`. Entra por el **camino real de la dueña** sobre el contenedor armado
por `build_app`, contra Postgres real, sin simular el motor de huellas:

1. `/add_vip <id> <nombre>` → crea el VIP.
2. Callback `encode_menu_vip_action(<id>, "note_add")` (el **mismo** `callback_data` que arma
   producción, no una cadena escrita a mano) → abre la sesión de nota.
3. Mensaje de texto con la nota → `ProfileAdminService.add_note` → `ProfilesRepo.add_note`.

Aserciones sobre la fila persistida, leída en una sesión nueva:

| # | Aserción | Resultado |
|---|---|---|
| a | La nota quedó guardada en `content` (el guardado ocurrió de verdad) | ✅ |
| b | La huella tiene 384 dimensiones y **no** es el vector de ceros | ✅ |
| c | Su norma no es sospechosamente baja (> 0.5) | ✅ |
| d | La huella guardada **coincide** con el mismo texto pasado por `EmbeddingService` (desvío < 1e-6) → salió del motor real, no de otro camino | ✅ |
| e | No se emitió ningún registro `profile_embedding_zeros` | ✅ |
| f | La respuesta del menú salió (el flujo corrió, no fue un no-op) | ✅ |

Se corre **con la bandera de memoria en los dos valores** (§6). `2 passed`. La única pieza no real es
el techo de Telegram (`SpyBotSession`): nada sale de la máquina.

---

## 5. Sabotajes (E3)

Se desconectó cada pieza a propósito, se corrió la misma prueba y se revirtió. Evidencia textual:

| # | Qué se desconectó | Resultado |
|---|---|---|
| **S1** | El motor de huellas: `composition.py:594` → `ProfilesRepo(sf, embedder=None)` | **Las 2 filas de la matriz FALLAN** (`2 failed`): `AssertionError: la ficha quedó con la huella en ceros: el motor de huellas no corrió`. Y deja rastro: `WARNING diana.infrastructure.db.repositories.profiles:profiles.py:112 profile_embedding_zeros` |
| **S2** | La huella que devuelve el motor: `EmbeddingService.embed` → `[0.0] * 384` (motor conectado, vector nulo) | **La prueba FALLA** con el mismo error, y también deja rastro: mismo `WARNING profile_embedding_zeros` |

Ambos sabotajes fueron revertidos; `grep -rn SABOTAJE src/` → sin resultados, y
`git diff src/diana/composition.py src/diana/cognitive/embedding.py` → vacío.

**Conclusión E3:** la prueba no es decorativa. Con la pieza desconectada falla **y** avisa.

---

## 6. Matriz de banderas

**El guardado de la nota y su huella no dependen de ninguna bandera.** `ProfileAdminService` y
`ProfilesRepo` se construyen siempre (`composition.py:1349`, `:594`), sin puerta. Las banderas que
tocan la ficha (`FEATURE_MEMORY_ENABLED`, `FEATURE_TRUST_BUDGET`) gobiernan **secciones opcionales de
lo que se muestra**, no el guardado ni la huella — se comprobó en el código en vez de suponerlo
(`profile_admin.memories = memories_repo if settings.feature_memory_enabled else None`).

Medido, no supuesto: la prueba E2 corre con la bandera de memoria en los dos valores.

| `FEATURE_MEMORY_ENABLED` | Guardado de la nota | Huella | Prueba E2 |
|---|---|---|---|
| `false` (valor actual) | ✅ queda en `profiles` | ✅ real, coincide con el motor | ✅ pasa (y falla bajo S1) |
| `true` | ✅ queda en `profiles` | ✅ real, coincide con el motor | ✅ pasa (y falla bajo S1) |

Efecto esperado y declarado para toda bandera ajena a este camino: **ninguno**. No hay aquí un estado
"apagado por bandera" que reportar — y justamente por eso este camino no tenía ningún mecanismo de
producto que avisara si el motor de huellas se desconectaba. De ahí §3.2.

---

## 7. Trámite para las 2 huellas en ceros

`scripts/regenerate_profile_embeddings.py` (nuevo). **Simula por defecto**: sin `--apply` no escribe
nada. Respalda **todas** las filas afectadas antes de escribir, y es idempotente (segunda corrida:
"0 filas en ceros", salida 0, sin escribir).

**Verificado contra una base de PRUEBAS** (contenedor `pgvector` desechable con 2 fichas en ceros y 1
con huella real, replicando el caso real):

| Comprobación | Resultado |
|---|---|
| Simulación: informa 2 filas (5 y 209 caracteres) y **no escribe** | ✅ (los ceros seguían en 2) |
| `--apply`: respalda, regenera y verifica fila por fila | ✅ (normas 3.77 y 2.84; la fila con huella real quedó intacta) |
| Idempotencia: segunda corrida | ✅ "0 filas en ceros", salida 0, sin respaldo nuevo |
| Respaldo | Contiene las columnas completas, incluido `content` y el vector anterior |
| Solo cambia `embedding` | ✅ `content`, `tipo` y las fechas quedaron iguales |

**No se ejecutó contra producción.** Comandos para ejecutarlo:

```bash
# 1. SIMULACIÓN — lee la dirección de la base del .env. No escribe nada.
.venv/bin/python scripts/regenerate_profile_embeddings.py

# 2. APLICAR — respalda primero (en runtime/, que no se versiona) y después escribe.
.venv/bin/python scripts/regenerate_profile_embeddings.py --apply

# 3. Contra otra base (por ejemplo una copia de pruebas), sin tocar el .env:
.venv/bin/python scripts/regenerate_profile_embeddings.py \
    --database-url "postgresql+asyncpg://usuario:clave@host:puerto/base"
```

El respaldo va a `runtime/backup_profile_embeddings_<fecha>.json`. Se eligió `runtime/` a propósito:
contiene la ficha de un VIP y **no debe entrar al repositorio** (el respaldo del script de agosto sí
quedó versionado en `scripts/`, con texto real de VIP dentro — ver §9).

---

## 8. Límites de esta verificación

- **La huella de una ficha no se consume en ninguna parte.** Lo probado es que el dato **se escribe
  bien**, no que se use. Es coherente con la decisión 2a.
- **No se re-verificó el resto del contrato C-EMB-01** (ejemplos, políticas, memorias por sus flujos
  reales). Este informe cubre **solo el tramo `profiles`**.
- **La prueba corre sobre la copia de la base real** dentro de un contenedor desechable, no sobre la
  base viva. La copia es una foto: si es vieja, sus 2 filas en ceros podrían no coincidir con las de
  producción al momento de correr el script.
- **No se probó el script contra la base real.** Se probó contra una base de prueba con la misma
  forma del caso.
- **El script no toca `updated_at`** (solo `set embedding = …`). En `profiles` no hay disparadores, así
  que ese campo sigue congelado en el alta, como ya documentó la investigación B: este trámite **no
  lo arregla ni lo empeora**.
- La regeneración del grafo (§3.3) arrastra el arrastre previo de `estado-del-proyecto`; el grafo no
  se revisó página por página más allá de confirmar que el diff son las páginas tocadas más los sellos.

---

## 9. Pendientes que se reportan y no se tocan

| Hallazgo | Por qué no se toca |
|---|---|
| `ContextsRepo.find_by_similarity` (`repositories/contexts.py:104`) tiene el **mismo** estado de huérfana: su lector (`ContextRetriever`) usa el snapshot no expirado, no la similitud | Misma clase de hallazgo, decisión de producto aparte. Está fuera del alcance que pediste |
| `profiles.updated_at` nunca se refresca (queda en la fecha de alta) | Ya documentado en la investigación B; no se muestra en el menú |
| `scripts/backup_feedback_embeddings_2026-08.json` está **versionado** y contiene texto real de conversaciones de VIP | Decisión aparte (dato de VIP dentro del repositorio). El script nuevo evita repetirlo usando `runtime/` |
| El *chequeo* del cero en el script y el vigilante V1 usan la misma expresión SQL, pero **V1 cuenta en `profiles` una tabla donde el cero ya no importa** | Sugerencia: dejar V1 (sirve como termómetro de que el motor se desconectó), sin cambiar su umbral |

---

## 10. Vigilante propuesto (E4)

`audit/vigilantes.sql` **V1** ya cubre el síntoma:

```sql
SELECT 'profiles', count(*) FILTER (WHERE embedding = array_fill(0::real, ARRAY[384])::vector) FROM profiles
```

Después de este cambio, lo que V1 vigila en `profiles` ya no es "una búsqueda que devolvería poco":
es **"el motor de huellas dejó de escribir"**. Eso lo vuelve más útil, no menos. Recomendación: dejarlo
como está y, cuando la dueña corra el trámite de §7, **bajar su umbral de alerta a 0** para `profiles`
(con las 2 filas arregladas, cualquier cero nuevo significa que el motor se desconectó).

Complemento barato, ya en el código: el registro `profile_embedding_zeros` (§3.2) es el vigilante
**en el momento**, no al día siguiente.

---

## 11. Estado en producción

**Integrado y activo el 2026-10-07.** La rama `audit/perfiles-embeddings` se fusionó a `main` por
avance rápido (historial lineal, igual que la integración del historial) y se publicó en `origin/main`
en `5a4a26a`. El bot se reinició a las **23:49:33 UTC** sobre ese commit.

Verificación posterior al reinicio:

| Comprobación | Resultado |
|---|---|
| Servicio | `active`, **0 reinicios** (sin bucle de arranque) |
| Salud | `{"status":"ok","checks":{"db":{"ok":true},"bot":{"ok":true,"username":"Dianishbot"}}}` |
| Motor de huellas | Cargado (`embedding_warmup_done`) |
| Errores o trazas en el arranque | Ninguno |
| Registro `profile_embedding_zeros` | **0 apariciones** — el motor está conectado, que es lo esperado |

**Nota operativa (lo que confundió al reportar):** durante la auditoría el árbol de trabajo quedó
**en la rama**, y el bot corre desde **ese mismo directorio**
(`WorkingDirectory=/home/ubuntu/repos/DianaV2`, con el proyecto instalado en modo editable apuntando a
`src/`). El bot no se enteró porque su proceso tenía el código anterior cargado en memoria, pero **un
reinicio fortuito habría cargado el código de auditoría sin que nadie lo aprobara**. Al fusionar y
volver el árbol a `main`, el código en disco y el que corre quedan alineados, y ese riesgo desaparece.

Regla para las próximas auditorías: mientras el trabajo esté en una rama, dejar el árbol en `main` o
avisar explícitamente de que el directorio de producción está apuntando a la rama.

---

## 12. Archivos tocados

| Archivo | Cambio |
|---|---|
| `src/diana/infrastructure/db/repositories/profiles.py` | Se borró `find_by_similarity`; docstring corregido; `profile_embedding_zeros` con motivo |
| `tests/unit/infrastructure/test_profiles_repo_write.py` | Se borró la prueba de la función muerta; +2 pruebas del aviso de ceros |
| `tests/audit/test_C_EMB_01.py` | **Nuevo** — prueba E2 del tramo `profiles` |
| `scripts/regenerate_profile_embeddings.py` | **Nuevo** — trámite de las 2 huellas en ceros |
| `wiki/concepts/capability-registry.md`, `wiki/entities/tablas/esquema-conocimiento.md`, `wiki/entities/modulos/cognitive-core.md`, `wiki/entities/modulos/infrastructure-persistence.md`, `wiki/index.md` | Correcciones + `updated:` a 2026-10-07 |
| `wiki/.ua/knowledge-graph.json`, `wiki/.ua/dashboard.html` | Regenerados (§3.3) |
| `CHANGELOG.md`, `docs/Plan_fase2.md`, `docs/CHANGELOG-DEPRECADO.md`, `docs/SPEC-1.1.md`, `docs/MVP_COMPONENT_DESIGN.md`, `docs/ARCHITECTURE.md`, `docs/SPEC-FASE2.md` | Correcciones (7 archivos) |
| `audit/FASE2-PERFILES.md` | Este informe |
| `audit/contracts/C-EMB-01.md` | Nivel, semáforo y hallazgos del tramo `profiles` |

### Suites ejecutadas (2026-10-07)

| Suite | Resultado |
|---|---|
| `tests/unit` | **4351 passed**. En `main` hoy son 4350; la rama suma **+1 neto** en el único archivo de pruebas tocado (12 → 13: −1 muerta, +2 nuevas). Cero fallos. |
| `tests/e2e` completo | **233 passed** — idéntico a la línea base documentada en `audit/ENTORNO.md` |
| `tests/audit` | **4 passed** (2 de C-HIST-01 + 2 de C-EMB-01: una por valor de la bandera de memoria) |
