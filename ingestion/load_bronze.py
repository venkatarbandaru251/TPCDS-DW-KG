import sys
import time
import traceback
from datetime import datetime, timezone

import psycopg

from .config import DATA_DIR, dw_conn_kwargs
from .run_log import end_run, record_table, start_run
from .tpcds_schema import TABLES


def load_table(table: str) -> tuple[int, int, float, datetime, datetime]:
    """Load a single .dat file into bronze.<table>. Returns (rows, bytes, secs, t0, t1)."""
    filename, columns = TABLES[table]
    path = DATA_DIR / filename
    size = path.stat().st_size
    col_list = ", ".join(columns)
    copy_sql = (
        f"COPY bronze.{table} ({col_list}) "
        "FROM STDIN WITH (FORMAT csv, DELIMITER '|', NULL '', "
        "HEADER false, QUOTE E'\\x01')"
    )
    t0 = datetime.now(timezone.utc)
    start = time.perf_counter()
    with psycopg.connect(**dw_conn_kwargs()) as conn:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE bronze.{table}")
            with cur.copy(copy_sql) as copy, path.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    copy.write(chunk)
            cur.execute(f"SELECT COUNT(*) FROM bronze.{table}")
            (rows,) = cur.fetchone()
        conn.commit()
    secs = time.perf_counter() - start
    t1 = datetime.now(timezone.utc)
    return rows, size, secs, t0, t1


def main(argv: list[str]) -> int:
    targets = argv[1:] or list(TABLES)
    unknown = [t for t in targets if t not in TABLES]
    if unknown:
        print(f"Unknown table(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"Known: {', '.join(TABLES)}", file=sys.stderr)
        return 2

    run_id = start_run()
    print(f"run_id={run_id}")
    total_rows = 0
    total_secs = 0.0
    failed_table: str | None = None
    failure_msg: str | None = None

    for table in targets:
        try:
            rows, size, secs, t0, t1 = load_table(table)
            record_table(run_id, table, t0, t1, rows, size, secs, "success")
            total_rows += rows
            total_secs += secs
            print(f"  bronze.{table:<25} {rows:>12,} rows  ({secs:>6.1f}s)")
        except Exception as exc:
            tb = traceback.format_exc()
            t1 = datetime.now(timezone.utc)
            try:
                record_table(run_id, table, t1, t1, 0, 0, 0.0, "failed", tb[-4000:])
            except Exception:
                pass
            failed_table = table
            failure_msg = f"{type(exc).__name__}: {exc}"
            print(f"  bronze.{table:<25} FAILED: {failure_msg}", file=sys.stderr)
            break

    if failed_table is None:
        end_run(run_id, "success", len(targets), total_rows)
        print(f"Total: {total_rows:,} rows in {total_secs:.1f}s across {len(targets)} table(s). run_id={run_id}")
        return 0
    else:
        end_run(
            run_id,
            "failed",
            sum(1 for t in targets if t != failed_table and targets.index(t) < targets.index(failed_table)),
            total_rows,
            f"{failed_table}: {failure_msg}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
