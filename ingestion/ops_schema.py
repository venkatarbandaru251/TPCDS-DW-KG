"""Operational schema for pipeline observability: run log + per-table stats."""

OPS_DDL = [
    "CREATE SCHEMA IF NOT EXISTS ops",
    """
    CREATE TABLE IF NOT EXISTS ops.ingest_runs (
        run_id         BIGSERIAL PRIMARY KEY,
        started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ended_at       TIMESTAMPTZ,
        status         TEXT NOT NULL DEFAULT 'running'
                       CHECK (status IN ('running', 'success', 'failed')),
        tables_loaded  INTEGER,
        rows_loaded    BIGINT,
        error_message  TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ops.ingest_table_stats (
        run_id         BIGINT NOT NULL REFERENCES ops.ingest_runs(run_id) ON DELETE CASCADE,
        table_name     TEXT NOT NULL,
        started_at     TIMESTAMPTZ NOT NULL,
        ended_at       TIMESTAMPTZ NOT NULL,
        rows_loaded    BIGINT NOT NULL,
        bytes_loaded   BIGINT NOT NULL,
        duration_s     DOUBLE PRECISION NOT NULL,
        status         TEXT NOT NULL CHECK (status IN ('success', 'failed')),
        error_message  TEXT,
        PRIMARY KEY (run_id, table_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ops.dbt_test_results (
        run_id         BIGINT REFERENCES ops.ingest_runs(run_id) ON DELETE CASCADE,
        recorded_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        test_name      TEXT NOT NULL,
        status         TEXT NOT NULL,
        failures       INTEGER,
        message        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ops.dbt_node_timings (
        run_id            BIGINT NOT NULL REFERENCES ops.ingest_runs(run_id) ON DELETE CASCADE,
        node_id           TEXT NOT NULL,
        node_type         TEXT NOT NULL,
        status            TEXT NOT NULL,
        execution_time_s  DOUBLE PRECISION NOT NULL,
        rows_affected     BIGINT,
        PRIMARY KEY (run_id, node_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ingest_runs_started_at ON ops.ingest_runs(started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ingest_table_stats_run ON ops.ingest_table_stats(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_dbt_test_results_run ON ops.dbt_test_results(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_dbt_node_timings_run ON ops.dbt_node_timings(run_id)",
]
