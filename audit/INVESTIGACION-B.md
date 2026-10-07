# Investigación B — Los perfiles con la "huella" en ceros

Fecha: **2026-10-06** · Autor: auditoría de contratos (skill `contract-proof`, contrato **C-EMB-01**)
Alcance: **solo lectura**. No se cambió código, ni banderas, ni datos. No hay commit.
Contenido de los perfiles: **no se muestra**. Solo se reportan claves, longitudes y conteos.

---

## Resumen para la dueña (lo que importa)

Diana guarda, junto a cada ficha de VIP, una "huella" del texto de esa ficha (un vector de 384
números) que en teoría sirve para *buscar por parecido*. En 2 de las 3 fichas esa huella quedó
**todo en ceros**.

La pregunta de negocio era: **¿eso afecta a lo que Diana lee hoy?** La respuesta es **no**.
Y el motivo es más de fondo que el dato en sí:

> **La búsqueda por parecido sobre las fichas no existe en producción. Nunca se usa.**

Hoy Diana lee las fichas **por nombre de VIP** (va directo a la fila de ese VIP). El vector no
participa en nada de lo que llega al modelo. Lo único que sí usa búsqueda por parecido son las
**memorias**, los **ejemplos**, las **políticas** y el **contexto** — y en esas cuatro tablas el
recuento de ceros es **cero**.

| Pregunta | Qué encontramos | Veredicto |
|---|---|---|
| **1. ¿Alguien busca por parecido sobre las fichas?** | **No.** La función existe escrita y con prueba unitaria, pero **ningún código de producción la llama**. Solo la llaman sus propios tests. La tabla además no tiene índice de vector: solo la llave por VIP. | **Probado** |
| **2. ¿Qué escribe las fichas y cuándo?** | **Solo la acción manual**, desde `/vip_profile` (datos y notas). La síntesis automática escribe **otra tabla** distinta (`vip_profile`). El 22-sep-2026 se registró un VIP nuevo a las 00:37 y a las 05:21 se le guardó una nota: fila nueva, normal. | **Probado** |
| **3. ¿Los ceros son texto vacío o falla del motor?** | **Ni una cosa ni la otra.** Las 2 fichas **sí tienen texto** (5 y 203 caracteres). Se escribieron el **28 y 29 de julio**, cuando el sistema **todavía no tenía motor de huellas**: en esa época toda ficha se guardaba en ceros por diseño. | **Probado** |
| **4. ¿El cero tiene efecto real?** | **Ninguno, hoy.** Diana lee igual las 3 fichas (verificado contra la base real). Ni siquiera un buscador futuro las rompería: pgvector simplemente las ignora. | **Probado** |
| **5. Arreglo propuesto** | Regenerar esas 2 huellas (trámite de una vez, sin tocar el esquema) **+** que la búsqueda de fichas no pueda devolver ceros **+** un vigilante diario. **No aplicado.** | Propuesta |

**Lo que gana o pierde el negocio hoy:** nada. No hay mensaje mal enviado, ni decisión torcida,
ni ficha invisible. Es un **dato incorrecto sin consecuencia**, no un incendio.

**Lo que sí conviene decidir:** la wiki y los documentos dicen que la búsqueda por parecido sobre
fichas está **"activa"**. No lo está. Si algún día alguien construye encima confiando en esa
frase, esas 2 fichas quedarían **invisibles en silencio** (sin error, sin aviso) — es exactamente
el tipo de falla que ya pasó en agosto de 2026 con ejemplos y políticas y que obligó a escribir un
script de recuperación. El arreglo chico de hoy evita repetir esa historia.

---

## Cómo accedí a los datos (transparencia)

- **Base de datos real**: conexión **de solo lectura** (transacción marcada como *read only*),
  tomando la dirección que el propio bot usa (`.env`). Ninguna escritura. Las credenciales no se
  copiaron a ningún archivo ni salida.
- **Código**: lectura directa del repositorio, más `git log` para fechar los cambios.
- **Logs**: **no disponibles para el 22-sep**. El journal del sistema solo conserva desde el
  **30-sep** (`journalctl -t diana-bot --since 2026-09-21 --until 2026-09-23` → *No entries*). Por
  eso el "qué pasó el 22-sep" se responde con la base y el código, no con logs.
- **Nivel de prueba alcanzado**: **E2 parcial**. Corrí los componentes **reales** (el lector de
  perfiles y las consultas de parecido) contra la **base real**, sin simular nada. **No** corrí un
  turno completo de punta a punta ni hice la prueba de sabotaje (E3): eso queda pendiente si se
  quiere cerrar el contrato C-EMB-01 como 🟢.

---

## 1. ¿Alguien busca por parecido sobre las fichas?

**No. La búsqueda semántica de fichas es una función huérfana: está escrita, está probada, y no la
llama nadie.**

Evidencia:

- La única función que consulta el vector es `ProfilesRepo.find_by_similarity`
  (`src/diana/infrastructure/db/repositories/profiles.py:111-131`). Ahí está el `ORDER BY` y el
  operador de distancia.
- **Barrido exhaustivo** de `find_by_similarity` en todo el repositorio (excluyendo `venv/`,
  `.git/` y la wiki generada): las únicas apariciones en `src/` son
  (a) su propia definición, y (b) una **mención en un comentario** (`profiles.py:75`).
  Los únicos llamadores son **pruebas unitarias**
  (`tests/unit/infrastructure/test_profiles_repo_write.py:221`).
- El lector real de perfiles, `ProfileRetriever`
  (`src/diana/cognitive/retrievers/profile.py:87-119`), lee **solo por VIP**:
  `get_by_vip_id` en las líneas `:123` y `:141` → `SELECT ... WHERE vip_id = :vip_id`.
- Se descartó el llamado dinámico: **no existe** ningún `getattr(..., "find_by_similarity")`
  en el código.
- La tabla **no tiene índice de vector**: en la base real, `pg_indexes` para `profiles` devuelve
  únicamente `profiles_pkey` (árbol B sobre `vip_id`). Es coherente con "nunca se consulta por
  parecido".
- Los `find_by_similarity` que **sí** existen y **sí** se usan pertenecen a **otras tablas**:
  ejemplos (`repositories/examples.py:88`, llamado desde `retrievers/examples.py:55` y `:69`),
  contextos (`repositories/contexts.py:104`), y por otra vía memorias
  (`repositories/memories.py:47 find_by_vip_and_similarity`) y políticas
  (`repositories/policies.py:76 find_active_by_similarity`).

**Contraste que importa:** memorias, ejemplos, políticas y contextos **sí** buscan por parecido en
tiempo real. Perfiles **no**. Por eso el cero duele en aquellas tablas y no en esta.

---

## 2. ¿Qué escribe en `profiles` y cuándo?

**Un solo escritor: la acción manual desde el menú `/vip_profile`.** No hay ningún proceso automático que toque
esta tabla.

Evidencia:

- Los únicos métodos que escriben son `set_fact` / `add_note` / `delete_fact` / `delete_note`
  (`repositories/profiles.py:133-215`), y los únicos insertadores son dos (`:140` y `:182`).
- Sus únicos llamadores son `ProfileAdminService`
  (`src/diana/application/profile_admin_service.py:246, :304, :348, :397`), que es la capa del menú
  de la dueña (`composition.py:1328-1329`).
- La **síntesis automática de perfil escribe OTRA tabla**, `vip_profile`
  (`infrastructure/db/models.py:738`), no `profiles`. No se cruzan.
- El **re-import de historial** al arrancar (`memory_backfill_queue.py:280`) escribe **memorias**,
  no fichas.
- Corrí el barrido de escritores en `src/diana/jobs/`: **cero** referencias a `profiles`.

### Las 3 filas (sin mostrar contenido)

| # | VIP (id abreviado) | Fila creada (UTC) | Fechas de las notas | Notas | Datos | Huella |
|---|---|---|---|---|---|---|
| 1 | `410c71a9…` | **2026-07-28 19:32** | 2026-07-28 | 1 | 0 | **ceros** |
| 2 | `86fab784…` | **2026-07-29 21:18** | 2026-07-29 y **2026-08-04** | 2 | 0 | **ceros** |
| 3 | `97623d5f…` | **2026-09-22 05:21** | 2026-09-22 | 1 | 0 | **real** (norma 3.6716) |

### Qué pasó el 22-sep-2026

Nada raro: **es la fila más nueva y la única con huella real.**

- El VIP se registró ese mismo día a las **00:37**; a las **05:21** se le guardó **una nota** desde
  `/vip_profile`. La fila nació con huella real porque el motor de huellas ya estaba conectado.
- Es, de hecho, la mejor prueba de que **hoy el sistema sí calcula la huella bien**.

### Ojo con "última actualización" (hallazgo secundario)

Ese "última actualización 22-sep" que figura en el contrato **no es una fecha de última
actualización**: es la fecha en que **nació la fila**. El sistema **nunca refresca** ese campo.

Evidencia:
- El modelo de la tabla no tiene `onupdate` (`infrastructure/db/models.py:267-283`), el repositorio
  nunca lo asigna, y la base **no tiene triggers** (`pg_trigger` sobre `profiles` → vacío).
- Prueba con la fila 2: su **segunda nota está fechada 2026-08-04**, pero su `updated_at` sigue
  diciendo **2026-07-29**. El campo quedó congelado en el alta.
- Buena noticia: la ficha que se ve en el menú **no muestra** ese campo
  (`telegram/handlers/menu.py:388-446` solo pinta datos y notas), así que hoy no muestra un dato
  falso. Solo confunde a quien lea la base o los informes.

---

## 3. ¿Las 2 filas en ceros tienen texto vacío o fue falla del motor?

**Ninguna de las dos. Tienen texto, y los ceros vienen de la época en que el motor no existía.**

El código de hoy devuelve ceros solo en dos casos (`repositories/profiles.py:89-97`):
(a) no hay motor de huellas, o (b) el texto a convertir queda vacío. Ninguna fila cae en (b).

| # | Claves del JSON `content` | Caracteres del texto que se habría convertido | ¿`is_hollow_content` lo considera vacío? | Huella |
|---|---|---|---|---|
| 1 | `facts`, `notes` | **5** | **No** (falso) | 384/384 en cero, norma 0.0 |
| 2 | `facts`, `notes` | **203** | **No** (falso) | 384/384 en cero, norma 0.0 |
| 3 | `facts`, `notes` | **56** | **No** (falso) | real, norma 3.6716 |

Las tres tienen `facts` vacío y al menos una nota.

**La causa real es histórica**, y está fechada:

- El commit que **introdujo** el cálculo de la huella y conectó el motor es **`fe0a7d7`
  (2026-08-23 04:03 UTC)** — ahí nacen `_embed_content` y el cableado
  `ProfilesRepo(sf, embedder=embedding_svc)` (`composition.py:573`).
- **Antes** de ese commit, el escritor guardaba ceros **siempre y sin condiciones**
  (`git show fe0a7d7^:src/diana/infrastructure/db/repositories/profiles.py`, líneas 76 y 116:
  `embedding=list(_ZERO_EMBEDDING)`).
- Las filas 1 y 2 se crearon el **28 y 29 de julio**, y la última escritura de la fila 2 fue el
  **4 de agosto**: **todas anteriores al 23-ago**. Por eso quedaron en ceros.
- Los ceros guardados son exactamente la constante de relleno `_ZERO_EMBEDDING = [0.0] * 384`
  (`profiles.py:29`), que es la firma del camino "no hay motor".

**Conclusión:** no fue una falla del motor ni un texto vacío. Fue **el comportamiento correcto de
un sistema que todavía no calculaba huellas**. Nadie borró nada; simplemente esas dos fichas
nunca se re-escribieron desde agosto.

---

## 4. ¿El cero tiene efecto real en lo que lee Diana?

**No. Hoy es un dato incorrecto sin consecuencia.** Tres razones, cada una medida.

**(a) El vector no llega ni a la puerta.** La única forma en que el perfil sale hacia el modelo es
`profile_to_dict` (`profiles.py:32-48`), y **no incluye la clave `embedding`**. Verificado corriendo
el componente real contra la base real — las claves devueltas son exactamente:
`content`, `created_at`, `tipo`, `updated_at`, `vip_id`.

**(b) La ficha se lee igual, con cero o sin cero.** Corrí el lector real de perfiles
(`ProfileRetriever`, el que Diana usa) contra la base real, con las 3 filas:

```
410c71a9… | bloque de perfil presente: True | secciones manuales: facts, notes | síntesis: True
86fab784… | bloque de perfil presente: True | secciones manuales: facts, notes | síntesis: True
97623d5f… | bloque de perfil presente: True | secciones manuales: facts, notes | síntesis: True
```

Las 3 fichas entran al contexto (ninguna es "hueca": `is_hollow_content` da **falso** en las tres).

**(c) Aunque alguien buscara, el cero no rompe nada: se ignora solo.** Medido sobre las filas
reales, con pgvector:

```
fila 410c71a9… → distancia coseno = NaN   ¿pasaría el umbral? false
fila 86fab784… → distancia coseno = NaN   ¿pasaría el umbral? false
fila 97623d5f… → distancia coseno = 0.998 ¿pasaría el umbral? false   (huella real)
```

El vector en ceros da **NaN** (no un número), y **NaN nunca cumple un umbral**, así que esas filas
**nunca aparecerían** en un resultado. Además, en el ordenamiento quedan **al final**, sin poder
desplazar a las filas buenas. Es decir: el cero no contamina a nadie; solo se autoexcluye.

**(d) Control cruzado — las tablas donde el vector SÍ se usa están limpias:**

| Tabla | Filas | Con huella en ceros | ¿Se busca por parecido? |
|---|---|---|---|
| `profiles` | **3** | **2** | **No** |
| `memories` | 351 | 0 | Sí |
| `examples` | 3984 | 0 | Sí |
| `policies` | 10 | 0 | Sí |
| `contexts` | 22 | 0 | Sí |

El problema está **exactamente en la única tabla donde el vector no se usa**. No es casualidad.

**El riesgo es latente, no activo:** la wiki afirma que la búsqueda por parecido de fichas está
"activa" (`wiki/entities/tablas/esquema-conocimiento.md:17`,
`wiki/concepts/capability-registry.md:39`, `docs/Plan_fase2.md:59`). Si alguien construye sobre esa
frase, esos 2 VIP quedarían **invisibles sin error ni aviso** — la misma clase de falla que el
incidente de agosto de 2026 con ejemplos y políticas, que necesitó un script de recuperación.

---

## 5. Arreglo más chico propuesto (NO aplicado)

Tres opciones sobre la mesa:

| Opción | Costo | Veredicto |
|---|---|---|
| **A. Que el cero no se guarde** (fallar la escritura) | Bajo en apariencia, **alto en riesgo** | ❌ La columna no admite vacío y hoy *no hay motor garantizado* al escribir: romperías el guardado de la ficha por un dato que nadie lee. |
| **B. Que la huella pueda ser "vacío"** (cambio de esquema) | **Alto** (migración + todos los escritores y lectores) | ❌ Es el cambio más grande para el beneficio más chico: cero consumidores afectados. |
| **C. Regenerar las 2 huellas + blindaje chico** | **Bajo, sin tocar el esquema** | ✅ **Recomendado** |

### Recomendación (tres pasos, de menor a mayor)

1. **Regenerar las 2 huellas** (una sola vez). Se recalcula la huella del contenido de esas 2 filas
   con el mismo motor que ya usa el sistema. No cambia comportamiento, no cambia esquema, no
   cambia lo que Diana lee: solo deja el dato correcto. Es un trámite, no una cirugía.
2. **Blindar el camino muerto.** El cero ya es una convención conocida en este sistema: políticas
   la usa como marca de "pendiente de recalcular" (`repositories/policies.py:17-19
   zero_embedding_clause`, con su servicio de reparación) y ejemplos tiene su script de rescate.
   Para fichas hay dos caminos chicos:
   - **(2a) Borrar `ProfilesRepo.find_by_similarity`** (nadie la llama) — el más chico de todos, y
     elimina la trampa de raíz.
   - **(2b) Dejarla, pero que excluya las filas en ceros**, igual que hace políticas — conserva la
     función por si algún día se quiere la búsqueda semántica de fichas, pero sin el agujero ciego.
   Si no hay plan de usar la búsqueda de fichas, **2a**. Si la hay, **2b**.
3. **Vigilante diario (E4).** Una consulta al día:
   `SELECT count(*) FROM profiles WHERE embedding = <ceros>` → si es > 0, avisar. Conviene
   hacerla para **las cinco tablas** (perfiles, memorias, ejemplos, políticas, contextos), porque
   convierte un hueco silencioso en una alerta. Es la única forma de que "el vector dejó de
   calcularse" no vuelva a pasar inadvertido.

**Aparte y menor:** corregir el `updated_at` que nunca se refresca (§2), o directamente **dejar de
usarlo en informes** como si fuera "última actualización". No es urgente porque no se muestra en el
menú, pero hoy induce a error a quien lea la base.

---

## Qué falta para cerrar el contrato C-EMB-01

| Nivel | Estado |
|---|---|
| **E0** — existe código y doc | ✅ (y hay más: la doc afirma de más) |
| **E1** — prueba unitaria con piezas simuladas | ✅ existe, pero **no ve el cableado**: la prueba de `find_by_similarity` pasa y la función no se usa en producción. Es exactamente el patrón "prueba que no ve el cableado". |
| **E2** — flujo real hasta la base real | 🟡 **parcial**: corrí el lector real y las consultas reales contra la base real (sin simular), pero **no** un turno completo desde el mensaje. |
| **E3** — sabotaje | ❌ **no ejecutado** en esta investigación. |
| **E4** — vigilante en producción | ❌ pendiente (propuesto en §5.3). |

**Conclusión honesta:** el hecho auditado ("la huella del perfil se usa para buscar") es **🔴 no
ocurre**, y la consecuencia del cero en las 2 filas es **nula hoy**. Para dar el contrato por
cerrado con evidencia dura faltaría correr la prueba E2 de punta a punta y su sabotaje E3.

---

## Anexo — Índice de evidencia

**Código (lectura por VIP, no por vector)**
- `src/diana/infrastructure/db/repositories/profiles.py:105-109` — `get_by_vip_id` (la que Diana usa)
- `src/diana/infrastructure/db/repositories/profiles.py:32-48` — `profile_to_dict` (sin `embedding`)
- `src/diana/cognitive/retrievers/profile.py:123, :141` — el lector llama a `get_by_vip_id`
- `src/diana/cognitive/registry.py:135-141` — registro del lector de perfiles
- `src/diana/composition.py:899` — inyección `profile_repo=profiles_repo`

**Código (la función huérfana)**
- `src/diana/infrastructure/db/repositories/profiles.py:111-131` — `find_by_similarity` (sin llamadores de producción)
- `src/diana/infrastructure/db/repositories/profiles.py:75` — única otra mención (comentario)
- `tests/unit/infrastructure/test_profiles_repo_write.py:204-226` — único llamador (prueba unitaria)

**Código (el cero)**
- `src/diana/infrastructure/db/repositories/profiles.py:29` — `_ZERO_EMBEDDING = [0.0] * 384`
- `src/diana/infrastructure/db/repositories/profiles.py:89-97` — `_embed_content` (dos salidas en ceros)
- `src/diana/infrastructure/db/models.py:275` — columna `Vector(384)` NOT NULL
- `alembic/versions/003_f2_knowledge_tables.py:33-43` — creación de la tabla
- `git show fe0a7d7^:…/profiles.py` líneas 76, 116 — ceros incondicionales antes del 23-ago
- `git show fe0a7d7` (2026-08-23) — introducción de `_embed_content` + `composition.py:573`

**Código (escritores)**
- `src/diana/application/profile_admin_service.py:246, :304, :348, :397` — únicos escritores
- `src/diana/application/profile_admin_service.py:346` — la fecha de nota es la del día
- `src/diana/telegram/handlers/menu.py:388-446` — la ficha no muestra huella ni `updated_at`

**Medido en la base real (solo lectura)**
- `profiles`: 3 filas, 2 en ceros · `memories` 351/0 · `examples` 3984/0 · `policies` 10/0 · `contexts` 22/0
- `pg_indexes('profiles')` → solo `profiles_pkey` (sin índice de vector)
- `pg_trigger('profiles')` → vacío (nada refresca `updated_at`)
- distancia coseno contra vector en ceros → `NaN` en las 2 filas; ordenamiento deja los `NaN` al final
- lector real de perfiles sobre las 3 filas → bloque presente y contenido incluido en las 3
