-- Vigilantes E4 (solo lectura). Correr a diario (cron/job) dentro de BEGIN READ ONLY; ... ROLLBACK;
-- Regla: CUALQUIER fila devuelta con alerta=true => avisar a la dueña/dev. Calibrar umbrales tras 1 semana.

-- V1 Embeddings en ceros (contrato C-EMB-01). Alerta si ceros > 0
SELECT 'examples' t, count(*) FILTER (WHERE embedding = array_fill(0::real, ARRAY[384])::vector) ceros FROM examples
UNION ALL SELECT 'policies', count(*) FILTER (WHERE embedding = array_fill(0::real, ARRAY[384])::vector) FROM policies
UNION ALL SELECT 'memories', count(*) FILTER (WHERE embedding = array_fill(0::real, ARRAY[384])::vector) FROM memories
UNION ALL SELECT 'profiles', count(*) FILTER (WHERE embedding = array_fill(0::real, ARRAY[384])::vector) FROM profiles
UNION ALL SELECT 'contexts', count(*) FILTER (WHERE embedding = array_fill(0::real, ARRAY[384])::vector) FROM contexts;

-- V2 Turnos VIP aplicados SIN fila de sombra (C-SHADOW-01). Alerta si faltan > 0 (ventana: entre 1 h y 2 días atrás)
SELECT count(*) AS turnos_sin_fila, array_agg(t.id) FILTER (WHERE true) AS turn_ids
FROM turns t LEFT JOIN turn_outcome_log o ON o.turn_id = t.id
WHERE t.vip_id IS NOT NULL AND t.status NOT IN ('superseded','failed')
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '1 hour'
  AND o.id IS NULL;

-- V3 Turnos entregados/escalados hace > 2 h sin resultado de la dueña (C-SHADOW-01).
-- Ojo: turnos de plantilla/autoenvío pueden no tener resultado; revisar los primeros resultados y afinar el filtro.
SELECT count(*) AS sin_resultado_duena
FROM turns t JOIN turn_outcome_log o ON o.turn_id = t.id
WHERE t.status IN ('delivered','escalated') AND o.owner_outcome IS NULL
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '2 hours';

-- V4 Entregas sin rastro en historial (C-HIST-01a). Alerta si > 0
SELECT count(*) AS entregas_sin_historial
FROM turns t
WHERE t.status = 'delivered'
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '10 minutes'
  AND NOT EXISTS (SELECT 1 FROM message_history m
                  WHERE m.chat_id = t.chat_id AND m.role = 'owner' AND m.timestamp >= t.created_at);

-- V5 Recarga de historial detenida (C-HIST-01b). Si la bandera debe estar ON, alerta si edad > 3 h
SELECT updated_at AS ultimo_avance, now() - updated_at AS edad
FROM system_config WHERE key = 'history_reimport_cursor';

-- V6 VIP activos sin perfil con huella (C-EMB-01). Verificar nombre de columna vip_id en `profiles` antes de automatizar
SELECT count(*) AS vip_sin_perfil
FROM vips v LEFT JOIN profiles p ON p.vip_id = v.id
WHERE v.is_active AND p.id IS NULL;

-- V7 Recaída del defecto del 10-sep: fila con puntaje y SIN decisión de la dueña tras una aprobación. Alerta si > 0
SELECT count(*) AS recaidas
FROM turn_outcome_log o JOIN turns t ON t.id = o.turn_id
WHERE o.draft_score IS NOT NULL AND o.owner_outcome IS NULL
  AND t.status = 'delivered'
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '2 hours';
