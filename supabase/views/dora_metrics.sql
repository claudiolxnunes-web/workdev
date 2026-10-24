-- Views para métricas DORA no Engineering Graph (Supabase)
-- Estas views devem ser criadas no projeto Supabase do grafo (cxqfwswartqqwsanceaj)
-- para calcular as 4 métricas DORA a partir dos nós graph_nodes.

-- ============================================================================
-- 1. DEPLOYMENT FREQUENCY (frequência de deploy por semana)
-- Conta deploys bem-sucedidos por semana nos últimos 90 dias.
-- ============================================================================

-- View auxiliar: extrai metadados dos deployments
CREATE OR REPLACE VIEW deployment_weekly AS
SELECT
    n.id AS deployment_id,
    n.entity_id,
    n.project_id,
    -- Extrai a data criada_at do nó (assumindo que está no metadata JSON)
    (n.metadata->>'created_at')::timestamptz AS deployed_at,
    date_trunc('week', (n.metadata->>'created_at')::timestamptz) AS week_start,
    -- Extrai o outcome do metadata (success, rolled_back, hotfixed, degraded)
    n.metadata->>'outcome' AS outcome
FROM graph_nodes n
WHERE n.type = 'Deployment'
  AND (n.metadata->>'created_at')::timestamptz >= now() - interval '90 days';

-- View principal: contagem semanal de deploys bem-sucedidos
CREATE OR REPLACE VIEW deployment_frequency_weekly AS
SELECT
    week_start,
    project_id,
    COUNT(*) FILTER (WHERE outcome = 'success') AS successful_deploys,
    COUNT(*) FILTER (WHERE outcome = 'degraded') AS degraded_deploys,
    COUNT(*) FILTER (WHERE outcome IN ('rolled_back', 'hotfixed')) AS failed_deploys,
    COUNT(*) AS total_deploys
FROM deployment_weekly
GROUP BY week_start, project_id
ORDER BY week_start DESC;

-- ============================================================================
-- 2. CHANGE FAILURE RATE (taxa de falha em mudança)
-- Percentual de deploys com falha (rolled_back ou hotfixed) nos últimos 30 dias.
-- ============================================================================

CREATE OR REPLACE VIEW change_failure_rate_30d AS
SELECT
    project_id,
    COUNT(*) FILTER (WHERE outcome IN ('rolled_back', 'hotfixed'))::numeric AS failed_count,
    COUNT(*)::numeric AS total_count,
    CASE
        WHEN COUNT(*) = 0 THEN 0
        ELSE ROUND(
            COUNT(*) FILTER (WHERE outcome IN ('rolled_back', 'hotfixed'))::numeric /
            COUNT(*)::numeric * 100,
            2
        )
    END AS failure_rate_percent
FROM deployment_weekly
WHERE deployed_at >= now() - interval '30 days'
GROUP BY project_id;

-- ============================================================================
-- 3. MTTR (Mean Time To Recovery / Median Time To Recovery)
-- Mediana do tempo entre detecção e resolução de incidentes.
-- Usa eventos do tipo 'incident_detected' e 'incident_resolved' de AgentRunEvent.
-- ============================================================================

-- View auxiliar: pares de detecção/resolução de incidentes
CREATE OR REPLACE VIEW incident_pairs AS
SELECT
    COALESCE(detected.project_id, resolved.project_id) AS project_id,
    detected.entity_id AS incident_id,
    (detected.metadata->>'created_at')::timestamptz AS detected_at,
    (resolved.metadata->>'created_at')::timestamptz AS resolved_at,
    EXTRACT(EPOCH FROM (
        (resolved.metadata->>'created_at')::timestamptz -
        (detected.metadata->>'created_at')::timestamptz
    )) / 60 AS recovery_time_minutes
FROM graph_nodes detected
JOIN graph_nodes resolved
    ON detected.entity_id = resolved.entity_id
    AND detected.project_id = resolved.project_id
WHERE detected.type = 'AgentEvent'
  AND resolved.type = 'AgentEvent'
  AND detected.metadata->>'event_type' = 'incident_detected'
  AND resolved.metadata->>'event_type' = 'incident_resolved'
  AND (resolved.metadata->>'created_at')::timestamptz > (detected.metadata->>'created_at')::timestamptz;

-- View principal: MTTR (mediana) por projeto nos últimos 30 dias
CREATE OR REPLACE VIEW mttr_30d AS
WITH incident_data AS (
    SELECT
        project_id,
        recovery_time_minutes
    FROM incident_pairs
    WHERE detected_at >= now() - interval '30 days'
      AND recovery_time_minutes IS NOT NULL
      AND recovery_time_minutes > 0
    ORDER BY recovery_time_minutes
),
ranked AS (
    SELECT
        project_id,
        recovery_time_minutes,
        ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY recovery_time_minutes) AS rn,
        COUNT(*) OVER (PARTITION BY project_id) AS cnt
    FROM incident_data
)
SELECT
    project_id,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY recovery_time_minutes) AS mttr_median_minutes,
    AVG(recovery_time_minutes) AS mttr_mean_minutes,
    COUNT(*) AS incident_count
FROM incident_data
GROUP BY project_id;

-- ============================================================================
-- 4. LEAD TIME FOR CHANGES
-- Mediana do tempo entre criação e conclusão de uma task/feature.
-- Conta todo o tempo de fila + execução.
-- ============================================================================

-- View auxiliar: pares de criação/conclusão de tasks
CREATE OR REPLACE VIEW task_lifecycle AS
SELECT
    created.project_id,
    created.entity_id AS task_id,
    created.type AS task_type,
    (created.metadata->>'created_at')::timestamptz AS created_at,
    (completed.metadata->>'completed_at')::timestamptz AS completed_at,
    EXTRACT(EPOCH FROM (
        (completed.metadata->>'completed_at')::timestamptz -
        (created.metadata->>'created_at')::timestamptz
    )) / 3600 AS lead_time_hours
FROM graph_nodes created
JOIN graph_nodes completed
    ON created.entity_id = completed.entity_id
    AND created.project_id = completed.project_id
WHERE created.type IN ('Task', 'Feature', 'Subtask')
  AND completed.type IN ('Task', 'Feature', 'Subtask')
  AND completed.metadata->>'status' = 'done'
  AND (completed.metadata->>'completed_at')::timestamptz > (created.metadata->>'created_at')::timestamptz;

-- View principal: Lead time (mediana) por projeto nos últimos 30 dias
CREATE OR REPLACE VIEW lead_time_30d AS
WITH task_data AS (
    SELECT
        project_id,
        lead_time_hours
    FROM task_lifecycle
    WHERE created_at >= now() - interval '30 days'
      AND lead_time_hours IS NOT NULL
      AND lead_time_hours > 0
    ORDER BY lead_time_hours
)
SELECT
    project_id,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY lead_time_hours) AS lead_time_median_hours,
    AVG(lead_time_hours) AS lead_time_mean_hours,
    MIN(lead_time_hours) AS lead_time_min_hours,
    MAX(lead_time_hours) AS lead_time_max_hours,
    COUNT(*) AS completed_tasks
FROM task_data
GROUP BY project_id;

-- ============================================================================
-- VIEW CONSOLIDADA: Executive Dashboard
-- Retorna todas as 4 métricas DORA em uma única consulta.
-- ============================================================================

CREATE OR REPLACE VIEW executive_dashboard_metrics AS
SELECT
    COALESCE(df.project_id, cfr.project_id, mt.project_id, lt.project_id) AS project_id,
    -- Deployment Frequency (últimas 4 semanas)
    COALESCE(df.weekly_deploys, 0) AS deploys_per_week,
    COALESCE(df.weekly_successful_deploys, 0) AS successful_deploys_per_week,
    -- Change Failure Rate
    COALESCE(cfr.failure_rate_percent, 0) AS change_failure_rate_percent,
    -- MTTR
    COALESCE(mt.mttr_median_minutes, 0) AS mttr_median_minutes,
    mt.incident_count,
    -- Lead Time
    COALESCE(lt.lead_time_median_hours, 0) AS lead_time_median_hours,
    lt.completed_tasks
FROM (
    SELECT
        project_id,
        SUM(successful_deploys) / 4.0 AS weekly_deploys,
        SUM(successful_deploys) / 4.0 AS weekly_successful_deploys
    FROM deployment_frequency_weekly
    WHERE week_start >= now() - interval '28 days'
    GROUP BY project_id
) df
FULL OUTER JOIN change_failure_rate_30d cfr USING (project_id)
FULL OUTER JOIN mttr_30d mt USING (project_id)
FULL OUTER JOIN lead_time_30d lt USING (project_id);

-- ============================================================================
-- ÍNDICES PARA PERFORMANCE
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_graph_nodes_type_entity ON graph_nodes(type, entity_id);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_type_project ON graph_nodes(type, project_id);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_metadata_created ON graph_nodes USING gin(metadata jsonb_path_ops);

-- ============================================================================
-- COMENTÁRIOS
-- ============================================================================

COMMENT ON VIEW deployment_frequency_weekly IS 'Frequência de deploy semanal - métrica DORA #1';
COMMENT ON VIEW change_failure_rate_30d IS 'Taxa de falha em mudança (30d) - métrica DORA #2';
COMMENT ON VIEW mttr_30d IS 'MTTR mediana (30d) - métrica DORA #3';
COMMENT ON VIEW lead_time_30d IS 'Lead time mediana (30d) - métrica DORA #4';
COMMENT ON VIEW executive_dashboard_metrics IS 'Dashboard executivo consolidado com todas as métricas DORA';
