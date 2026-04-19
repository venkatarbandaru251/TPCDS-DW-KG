"""End-to-end Phase 0 pipeline: load Bronze, run dbt source tests,
record everything in ops tables. One run_id ties it all together.

Usage: python -m ingestion.run_pipeline
Exit code: 0 on full success; 1 if any step failed.
"""
import os
import sys
from datetime import datetime, timezone

import psycopg

from .config import REPO_ROOT, dw_conn_kwargs
from .load_bronze import load_table
from .run_log import end_run, record_table, start_run
from .tpcds_schema import TABLES

TRANSFORM_DIR = REPO_ROOT / "transform"


_DBT_OK = {"pass", "success"}
_DBT_FAIL = {"fail", "error", "runtime error"}


def _record_test_results(run_id: int, dbt_result) -> tuple[int, int]:
    passed = failed = 0
    rows = []
    timing_rows = []
    for r in getattr(dbt_result, "result", None) or []:
        node = getattr(r, "node", None)
        test_name = getattr(node, "name", "unknown")
        unique_id = getattr(node, "unique_id", test_name)
        resource_type = getattr(node, "resource_type", "unknown")
        status = str(getattr(r, "status", "unknown"))
        failures = getattr(r, "failures", None)
        message = getattr(r, "message", None)
        exec_time = float(getattr(r, "execution_time", 0) or 0)
        rows_affected = getattr(r, "adapter_response", {})
        if isinstance(rows_affected, dict):
            rows_affected = rows_affected.get("rows_affected")
        else:
            rows_affected = None
        rows.append((run_id, test_name, status, failures, message))
        timing_rows.append(
            (run_id, unique_id, str(resource_type), status, exec_time, rows_affected)
        )
        if status in _DBT_OK:
            passed += 1
        elif status in _DBT_FAIL:
            failed += 1
    if rows:
        with psycopg.connect(**dw_conn_kwargs()) as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO ops.dbt_test_results
                  (run_id, test_name, status, failures, message)
                VALUES (%s, %s, %s, %s, %s)
                """,
                rows,
            )
            cur.executemany(
                """
                INSERT INTO ops.dbt_node_timings
                  (run_id, node_id, node_type, status, execution_time_s, rows_affected)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, node_id) DO UPDATE
                   SET status = EXCLUDED.status,
                       execution_time_s = EXCLUDED.execution_time_s,
                       rows_affected = EXCLUDED.rows_affected
                """,
                timing_rows,
            )
            conn.commit()
    return passed, failed


_POST_BUILD_INDEXES = [
    # Silver intermediates (scanned by every Gold mart)
    ("silver.int_sales_unified",   "idx_int_sales_unified_customer", "customer_sk", False),
    ("silver.int_sales_unified",   "idx_int_sales_unified_item",     "item_sk",     False),
    ("silver.int_sales_unified",   "idx_int_sales_unified_date",     "sold_date_sk", False),
    ("silver.int_returns_unified", "idx_int_returns_unified_customer", "customer_sk", False),
    ("silver.int_returns_unified", "idx_int_returns_unified_item",     "item_sk",     False),
    ("silver.int_returns_unified", "idx_int_returns_unified_date",     "returned_date_sk", False),
    # Gold marts (BA point-query and filter patterns)
    ("gold.mart_customer_360",       "idx_mart_customer_360_sk",        "c_customer_sk", True),
    ("gold.mart_customer_360",       "idx_mart_customer_360_segment",   "segment",       False),
    ("gold.mart_product_analytics",  "idx_mart_product_analytics_sk",   "i_item_sk",     True),
    ("gold.mart_sales_performance",  "idx_mart_sales_perf_date_channel","sale_date, channel", False),
    ("gold.mart_sales_performance",  "idx_mart_sales_perf_year_month",  "sale_year, sale_month", False),
    ("gold.mart_channel_comparison", "idx_mart_channel_cmp_period",     "d_year, d_moy", True),
]

_POST_BUILD_STORAGE = [
    ("silver.int_sales_unified", "parallel_workers = 4"),
    ("silver.fact_store_sales",  "parallel_workers = 4"),
    ("silver.fact_inventory",    "parallel_workers = 4"),
]


def _apply_post_build_tuning() -> None:
    """Create indexes and set per-table storage params after dbt has built
    tables. Done here (not as dbt post_hooks) because dbt-postgres 1.10's
    table-swap rename drops post-hook-created indexes."""
    with psycopg.connect(**dw_conn_kwargs(), autocommit=True) as conn, conn.cursor() as cur:
        for table, idx, cols, unique in _POST_BUILD_INDEXES:
            cur.execute(
                f"CREATE {'UNIQUE ' if unique else ''}INDEX IF NOT EXISTS {idx} "
                f"ON {table} ({cols})"
            )
        for table, setting in _POST_BUILD_STORAGE:
            cur.execute(f"ALTER TABLE {table} SET ({setting})")


def _analyze_silver_and_gold() -> None:
    """Refresh Postgres table statistics so pg_class.reltuples is accurate
    for the dashboard's approximate row counts."""
    with psycopg.connect(**dw_conn_kwargs(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT format('ANALYZE %I.%I', n.nspname, c.relname) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname IN ('silver', 'gold') AND c.relkind = 'r'"
        )
        stmts = [row[0] for row in cur.fetchall()]
        for s in stmts:
            cur.execute(s)


def _run_dbt_build(run_id: int) -> tuple[int, int]:
    """Run `dbt build` — materializes Silver models and runs all tests
    (source tests on Bronze + schema tests on Silver). Returns (passed, failed)
    across all tests recorded. Model-build steps are counted as 'pass'/'fail'
    alongside tests in ops.dbt_test_results."""
    from dbt.cli.main import dbtRunner

    os.environ["DBT_PROFILES_DIR"] = str(TRANSFORM_DIR)
    cwd = os.getcwd()
    os.chdir(TRANSFORM_DIR)
    try:
        result = dbtRunner().invoke(["build"])
    finally:
        os.chdir(cwd)
    return _record_test_results(run_id, result)


def main() -> int:
    run_id = start_run()
    print(f"[pipeline] run_id={run_id} started at {datetime.now(timezone.utc).isoformat()}")

    total_rows = 0
    total_secs = 0.0
    load_failed: str | None = None
    error_msg: str | None = None

    for table in TABLES:
        try:
            rows, size, secs, t0, t1 = load_table(table)
            record_table(run_id, table, t0, t1, rows, size, secs, "success")
            total_rows += rows
            total_secs += secs
            print(f"  bronze.{table:<25} {rows:>12,} rows  ({secs:>6.1f}s)")
        except Exception as exc:
            now = datetime.now(timezone.utc)
            record_table(run_id, table, now, now, 0, 0, 0.0, "failed", str(exc))
            load_failed = table
            error_msg = f"{type(exc).__name__}: {exc}"
            print(f"  bronze.{table:<25} FAILED: {error_msg}", file=sys.stderr)
            break

    if load_failed:
        end_run(run_id, "failed", 0, total_rows, f"load failed at {load_failed}: {error_msg}")
        print(f"[pipeline] run_id={run_id} FAILED during load")
        return 1

    print(f"[pipeline] Bronze load done: {total_rows:,} rows in {total_secs:.1f}s. Running dbt build (Silver + tests)...")
    try:
        passed, failed = _run_dbt_build(run_id)
    except Exception as exc:
        end_run(run_id, "failed", len(TABLES), total_rows, f"dbt build error: {exc}")
        print(f"[pipeline] dbt build step errored: {exc}", file=sys.stderr)
        return 1

    final_status = "success" if failed == 0 else "failed"
    msg = None if failed == 0 else f"{failed} dbt node(s) failed"
    end_run(run_id, final_status, len(TABLES), total_rows, msg)
    print(f"[pipeline] dbt build: {passed} passed, {failed} failed")
    try:
        _apply_post_build_tuning()
        _analyze_silver_and_gold()
    except Exception as exc:
        print(f"[pipeline] post-build tuning warning: {exc}", file=sys.stderr)
    print(f"[pipeline] run_id={run_id} {final_status.upper()}")
    return 0 if final_status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
