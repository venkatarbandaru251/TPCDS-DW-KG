import psycopg
from psycopg import sql

from .config import PG_DATABASE, admin_conn_kwargs, dw_conn_kwargs
from .ops_schema import OPS_DDL
from .tpcds_schema import TABLES, bronze_ddl


def create_database() -> None:
    with psycopg.connect(**admin_conn_kwargs(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PG_DATABASE,))
            if cur.fetchone():
                print(f"Database {PG_DATABASE!r} already exists.")
                return
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(PG_DATABASE)))
            print(f"Created database {PG_DATABASE!r}.")


def create_schema_and_tables() -> None:
    with psycopg.connect(**dw_conn_kwargs()) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS bronze")
            for table in TABLES:
                cur.execute(bronze_ddl(table))
            print(f"Applied DDL for {len(TABLES)} bronze table(s).")
            for stmt in OPS_DDL:
                cur.execute(stmt)
            print("Applied DDL for ops schema (ingest_runs, ingest_table_stats, dbt_test_results).")
        conn.commit()


if __name__ == "__main__":
    create_database()
    create_schema_and_tables()
