-- Vigilantes E4 — chequeo diario de que los efectos prometidos siguen ocurriendo.
-- SOLO LECTURA: el ejecutor (scripts/vigilantes.py) corre cada consulta dentro de
-- una transacción READ ONLY y nunca escribe.
--
-- Formato de cada bloque:   -- V<n> | activo|no-activado | <contrato> | <qué vigila>
-- Regla: cada consulta devuelve una columna entera `alerta`. Si la suma de `alerta`
-- de un vigilante es > 0, el ejecutor avisa a la dueña por Telegram. Si es 0, silencio.
-- Un vigilante `no-activado` no se ejecuta: queda documentado con el motivo.
--
-- Calibración (2026-10-08, contra la base real — ver audit/FASE2-SABOTAJE.md §9):
-- los activos se midieron antes de encenderlos y hoy dan 0, para que el aviso
-- signifique "algo cambió", no "hay datos viejos".

-- V1 | activo | C-EMB-01 | huellas semánticas NUEVAS en ceros (el incidente de agosto)
-- Alerta solo por ceros escritos en los últimos 2 días: las filas históricas ya
-- conocidas no vuelven a avisar todos los días (hoy: 2 históricas en `profiles`,
-- documentadas y pendientes de decisión de la dueña, con 0 nuevas).
SELECT t AS tabla, nuevos AS alerta, total AS historico
FROM (
    SELECT 'examples' AS t, count(*) AS total,
           count(*) FILTER (WHERE created_at > now() - interval '2 days') AS nuevos
    FROM examples WHERE embedding = array_fill(0::real, ARRAY[384])::vector
    UNION ALL
    SELECT 'policies', count(*),
           count(*) FILTER (WHERE created_at > now() - interval '2 days')
    FROM policies WHERE embedding = array_fill(0::real, ARRAY[384])::vector
    UNION ALL
    SELECT 'memories', count(*),
           count(*) FILTER (WHERE created_at > now() - interval '2 days')
    FROM memories WHERE embedding = array_fill(0::real, ARRAY[384])::vector
    UNION ALL
    SELECT 'profiles', count(*),
           count(*) FILTER (WHERE created_at > now() - interval '2 days')
    FROM profiles WHERE embedding = array_fill(0::real, ARRAY[384])::vector
    UNION ALL
    SELECT 'contexts', count(*),
           count(*) FILTER (WHERE created_at > now() - interval '2 days')
    FROM contexts WHERE embedding = array_fill(0::real, ARRAY[384])::vector
) s;

-- V2 | activo | C-SHADOW-01 | turnos VIP que pasaron por el pipeline y NO dejaron fila de sombra
-- Exige traza CON evaluación: así las rutas que no pasan por el pipeline
-- (escalación determinística, saludo de plantilla) no cuentan — su hueco es diseño.
-- El ejecutor descarta además las sesiones de sandbox, que no persisten a propósito
-- (§4.20 de AGENTS.md): el motivo queda en el journal como `post_turn_skipped_sandbox`.
SELECT t.chat_id AS chat, t.id::text AS turno, t.status AS estado,
       to_char(t.created_at, 'DD/MM HH24:MI') AS cuando, 1 AS alerta
FROM turns t
JOIN pipeline_traces p ON p.turn_id = t.id
LEFT JOIN turn_outcome_log o ON o.turn_id = t.id
WHERE t.vip_id IS NOT NULL
  AND t.status NOT IN ('superseded','failed')
  AND p.evaluation IS NOT NULL
  AND o.id IS NULL
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '1 hour'
ORDER BY t.created_at DESC;

-- V3 | no-activado | C-SHADOW-01 | turnos entregados/escalados sin resolución de la dueña
-- NO se activa: alertaría por diseño todos los días. Una escalación que la dueña
-- responde escribiendo directo en el chat queda sin `owner_outcome` para siempre
-- (decisión de producto del 2026-10-06), y los envíos automáticos y de plantilla
-- tampoco tienen resolución de la dueña. El caso real —"ella aprobó y no quedó
-- registrado"— lo cubre V7, más preciso. Se deja la consulta como referencia.
SELECT count(*) AS sin_resultado_duena, 0 AS alerta
FROM turns t JOIN turn_outcome_log o ON o.turn_id = t.id
WHERE t.status IN ('delivered','escalated') AND o.owner_outcome IS NULL
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '2 hours';

-- V4 | no-activado | C-HIST-01 | entregas sin rastro en el historial del chat
-- NO se activa todavía: hoy devuelve 18 y la cláusula (a) del contrato sigue en E0
-- (nunca verificada con efecto real). Antes de encenderlo hay que separar el hueco
-- por diseño (sandbox) del hueco real, en la ronda de C-HIST-01.
SELECT count(*) AS entregas_sin_historial, 0 AS alerta
FROM turns t
WHERE t.status = 'delivered'
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '10 minutes'
  AND NOT EXISTS (SELECT 1 FROM message_history m
                  WHERE m.chat_id = t.chat_id AND m.role = 'owner' AND m.timestamp >= t.created_at);

-- V5 | no-activado | C-HIST-01 | recarga de historial detenida
-- NO se activa: la recarga de VIP existentes está apagada A PROPÓSITO desde el
-- 2026-09-06 (la sesión de Telethon es de la cuenta anterior). Encendido así
-- avisaría todos los días de una decisión de producto, no de una falla.
SELECT updated_at AS ultimo_avance, now() - updated_at AS edad, 0 AS alerta
FROM system_config WHERE key = 'history_reimport_cursor';

-- V6 | no-activado | C-EMB-01 | VIP activos sin fila de perfil
-- NO se activa: (a) la consulta original estaba rota (`p.id` no existe en
-- `profiles`, cuya clave es `vip_id`) y (b) ya arreglada devuelve 12, un número
-- que dejó de ser una falla cuando la ronda anterior quitó la búsqueda por
-- parecido de `profiles` por ser huérfana. Falta que la dueña defina si un VIP
-- sin perfil sigue importando; hasta entonces, contarlo no avisa de nada.
SELECT count(*) AS vip_sin_perfil, 0 AS alerta
FROM vips v LEFT JOIN profiles p ON p.vip_id = v.id
WHERE v.is_active AND p.vip_id IS NULL;

-- V7 | activo | C-SHADOW-01 | recaída del defecto del 10-sep: la dueña aprobó y su decisión no quedó
-- Es el caso real de "el efecto dejó de ocurrir" para la mitad de la dueña, con
-- la firma exacta del defecto (fila con nota y sin resolución, en un turno entregado).
SELECT t.id::text AS turno, t.chat_id AS chat,
       to_char(t.created_at, 'DD/MM HH24:MI') AS cuando, 1 AS alerta
FROM turn_outcome_log o JOIN turns t ON t.id = o.turn_id
WHERE o.draft_score IS NOT NULL AND o.owner_outcome IS NULL
  AND t.status = 'delivered'
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '2 hours'
ORDER BY t.created_at DESC;
