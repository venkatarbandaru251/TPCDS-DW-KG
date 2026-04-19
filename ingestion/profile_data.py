"""Profile the raw TPC-DS files (file size, row count, delimiter column count)
and sanity-check each against the declared schema.

Run: python -m ingestion.profile_data
"""
import sys

from .config import DATA_DIR
from .tpcds_schema import TABLES


def count_lines(path) -> int:
    n = 0
    with path.open("rb") as f:
        for _ in f:
            n += 1
    return n


def first_line_columns(path) -> int:
    with path.open("rb") as f:
        line = f.readline().rstrip(b"\n").rstrip(b"\r")
    if not line:
        return 0
    return line.count(b"|") + 1


def main() -> int:
    rows = []
    for table, (filename, columns) in TABLES.items():
        path = DATA_DIR / filename
        if not path.exists():
            rows.append((table, filename, "MISSING", 0, 0, len(columns), "FAIL"))
            continue
        size = path.stat().st_size
        n_rows = count_lines(path)
        file_cols = first_line_columns(path)
        declared = len(columns)
        status = "OK" if file_cols == declared else "MISMATCH"
        rows.append((table, filename, size, n_rows, file_cols, declared, status))

    header = ("table", "file", "size_bytes", "rows", "file_cols", "decl_cols", "status")
    print(f"{header[0]:<25}{header[1]:<27}{header[2]:>14}{header[3]:>12}{header[4]:>10}{header[5]:>10}  {header[6]}")
    fail = 0
    for r in rows:
        table, filename, size, n_rows, file_cols, declared, status = r
        size_s = f"{size:>14,}" if isinstance(size, int) else f"{str(size):>14}"
        print(f"{table:<25}{filename:<27}{size_s}{n_rows:>12,}{file_cols:>10}{declared:>10}  {status}")
        if status != "OK":
            fail += 1
    print(f"\n{len(rows)} file(s) profiled, {fail} issue(s).")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
