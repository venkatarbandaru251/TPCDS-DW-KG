"""Write-side helpers for the ops.ingest_runs / ops.ingest_table_stats tables."""
from __future__ import annotations

import psycopg

from .config import dw_conn_kwargs


def start_run() -> int:
    with psycopg.connect(**dw_conn_kwargs()) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ops.ingest_runs (status) VALUES ('running') RETURNING run_id"
        )
        (run_id,) = cur.fetchone()
        conn.commit()
    return run_id


def record_table(
    run_id: int,
    table: str,
    started_at,
    ended_at,
    rows: int,
    bytes_: int,
    duration_s: float,
    status: str,
    error: str | None = None,
) -> None:
    with psycopg.connect(**dw_conn_kwargs()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ops.ingest_table_stats
              (run_id, table_name, started_at, ended_at, rows_loaded,
               bytes_loaded, duration_s, status, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (run_id, table, started_at, ended_at, rows, bytes_, duration_s, status, error),
        )
        conn.commit()


def end_run(
    run_id: int,
    status: str,
    tables_loaded: int,
    rows_loaded: int,
    error: str | None = None,
) -> None:
    with psycopg.connect(**dw_conn_kwargs()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ops.ingest_runs
               SET ended_at = NOW(),
                   status = %s,
                   tables_loaded = %s,
                   rows_loaded = %s,
                   error_message = %s
             WHERE run_id = %s
            """,
            (status, tables_loaded, rows_loaded, error, run_id),
        )
        conn.commit()
