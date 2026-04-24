"""Build the knowledge graph (graph.node, graph.edge) from the Silver layer.

Reads ontology.json, materializes ontology metadata, loads one node per
dimension row, and builds FK-based + aggregated-fact edges between them.

Usage: python -m knowledge_graph.build_graph
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from ingestion.config import dw_conn_kwargs

from .graph_schema import apply_graph_ddl

ONTOLOGY_PATH = Path(__file__).resolve().parent / "ontology.json"


def load_ontology() -> dict:
    with open(ONTOLOGY_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _upsert_ontology(conn, ontology: dict) -> None:
    """Replace ontology_class and ontology_relationship with the current
    definition. Nodes/edges reference these via FKs, so we use ON CONFLICT
    rather than TRUNCATE."""
    with conn.cursor() as cur:
        for class_name, spec in ontology["classes"].items():
            cur.execute(
                """
                INSERT INTO graph.ontology_class
                    (class_name, description, source_table, surrogate_key, natural_key, label_expr, properties)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (class_name) DO UPDATE SET
                    description   = EXCLUDED.description,
                    source_table  = EXCLUDED.source_table,
                    surrogate_key = EXCLUDED.surrogate_key,
                    natural_key   = EXCLUDED.natural_key,
                    label_expr    = EXCLUDED.label_expr,
                    properties    = EXCLUDED.properties
                """,
                (
                    class_name,
                    spec.get("description"),
                    spec["source_table"],
                    spec["surrogate_key"],
                    spec.get("natural_key"),
                    spec.get("label_expr"),
                    json.dumps(spec.get("properties", [])),
                ),
            )
        for rel_name, rspec in ontology["relationships"].items():
            cur.execute(
                """
                INSERT INTO graph.ontology_relationship
                    (name, description, from_class, to_class, kind, definition)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    from_class  = EXCLUDED.from_class,
                    to_class    = EXCLUDED.to_class,
                    kind        = EXCLUDED.kind,
                    definition  = EXCLUDED.definition
                """,
                (
                    rel_name,
                    rspec.get("description"),
                    rspec["from"],
                    rspec["to"],
                    rspec["kind"],
                    json.dumps(rspec),
                ),
            )
    conn.commit()


def _property_select_expr(properties: list[dict]) -> str:
    """Build a jsonb_build_object(...) expression for class properties."""
    if not properties:
        return "'{}'::jsonb"
    parts = []
    for prop in properties:
        parts.append(f"'{prop['name']}', {prop['column']}")
    return f"jsonb_strip_nulls(jsonb_build_object({', '.join(parts)}))"


def _load_nodes(conn, class_name: str, spec: dict) -> int:
    """Bulk insert one graph.node row per source dim row. Idempotent via the
    (class_name, source_sk) unique constraint."""
    sk = spec["surrogate_key"]
    nk = spec.get("natural_key")
    label_expr = spec.get("label_expr") or f"{sk}::text"
    props_expr = _property_select_expr(spec.get("properties", []))
    nk_expr = nk if nk else "NULL::text"
    source = spec["source_table"]
    sql = f"""
        INSERT INTO graph.node (class_name, source_sk, natural_id, label, properties)
        SELECT
            %s              AS class_name,
            {sk}::bigint    AS source_sk,
            ({nk_expr})::text AS natural_id,
            ({label_expr})::text AS label,
            {props_expr}    AS properties
        FROM {source}
        WHERE {sk} IS NOT NULL
        ON CONFLICT (class_name, source_sk) DO UPDATE SET
            natural_id = EXCLUDED.natural_id,
            label      = EXCLUDED.label,
            properties = EXCLUDED.properties
    """
    with conn.cursor() as cur:
        cur.execute(sql, (class_name,))
        count = cur.rowcount
    conn.commit()
    return count


def _load_fk_edges(conn, rel_name: str, rspec: dict, ontology: dict) -> int:
    """Edges from a FK column on the `from` class's source table to the `to`
    class's SK. One edge per non-null FK."""
    from_spec = ontology["classes"][rspec["from"]]
    from_sk = rspec["from_column_sk"]
    source = from_spec["source_table"]
    parent_sk = from_spec["surrogate_key"]
    sql = f"""
        INSERT INTO graph.edge (from_node_id, to_node_id, relationship_name, properties)
        SELECT
            fn.node_id      AS from_node_id,
            tn.node_id      AS to_node_id,
            %s              AS relationship_name,
            '{{}}'::jsonb   AS properties
        FROM {source} src
        JOIN graph.node fn
          ON fn.class_name = %s AND fn.source_sk = src.{parent_sk}
        JOIN graph.node tn
          ON tn.class_name = %s AND tn.source_sk = src.{from_sk}
        WHERE src.{from_sk} IS NOT NULL
        ON CONFLICT (from_node_id, to_node_id, relationship_name) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(sql, (rel_name, rspec["from"], rspec["to"]))
        count = cur.rowcount
    conn.commit()
    return count


def _load_aggregate_edges(conn, rel_name: str, rspec: dict) -> int:
    """Top-N aggregate edges from a fact table. One edge per
    (from_sk, to_sk) pair ranked by the first aggregate."""
    source = rspec["source"]
    from_col = rspec["from_column_sk"]
    to_col = rspec["to_column_sk"]
    aggs = rspec["aggregates"]
    top_n = rspec.get("top_n_per_from")

    # Build the aggregate-select expression + a jsonb props object.
    agg_select_parts = []
    props_parts = []
    rank_expr = None
    for i, (name, expr) in enumerate(aggs.items()):
        alias = f"agg_{i}"
        agg_select_parts.append(f"{expr} AS {alias}")
        props_parts.append(f"'{name}', {alias}")
        if rank_expr is None:
            rank_expr = alias
    props_expr = f"jsonb_build_object({', '.join(props_parts)})"

    base_cte = f"""
        WITH agg AS (
            SELECT
                {from_col} AS from_sk,
                {to_col}   AS to_sk,
                {', '.join(agg_select_parts)}
            FROM {source}
            WHERE {from_col} IS NOT NULL AND {to_col} IS NOT NULL
            GROUP BY {from_col}, {to_col}
        )
    """

    if top_n:
        ranked_cte = f"""
            , ranked AS (
                SELECT *,
                       row_number() OVER (PARTITION BY from_sk ORDER BY {rank_expr} DESC NULLS LAST) AS rn
                FROM agg
            )
        """
        source_query = f"SELECT * FROM ranked WHERE rn <= {int(top_n)}"
    else:
        ranked_cte = ""
        source_query = "SELECT * FROM agg"

    sql = f"""
        {base_cte}{ranked_cte}
        INSERT INTO graph.edge (from_node_id, to_node_id, relationship_name, properties)
        SELECT
            fn.node_id,
            tn.node_id,
            %s,
            {props_expr}
        FROM ({source_query}) src
        JOIN graph.node fn
          ON fn.class_name = %s AND fn.source_sk = src.from_sk
        JOIN graph.node tn
          ON tn.class_name = %s AND tn.source_sk = src.to_sk
        ON CONFLICT (from_node_id, to_node_id, relationship_name) DO UPDATE SET
            properties = EXCLUDED.properties
    """
    with conn.cursor() as cur:
        cur.execute(sql, (rel_name, rspec["from"], rspec["to"]))
        count = cur.rowcount
    conn.commit()
    return count


def _start_build_run(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO graph.build_runs (status) VALUES ('running') RETURNING run_id"
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def _end_build_run(conn, run_id: int, status: str, nodes: int, edges: int, error: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE graph.build_runs
               SET ended_at = NOW(), status = %s,
                   nodes_loaded = %s, edges_loaded = %s, error_message = %s
             WHERE run_id = %s
            """,
            (status, nodes, edges, error, run_id),
        )
    conn.commit()


def main() -> int:
    ontology = load_ontology()
    conn = psycopg.connect(**dw_conn_kwargs())
    try:
        apply_graph_ddl(conn)
        run_id = _start_build_run(conn)
        print(f"[kg] build run_id={run_id} started at {datetime.now(timezone.utc).isoformat()}")

        _upsert_ontology(conn, ontology)
        print(f"[kg] ontology: {len(ontology['classes'])} classes, {len(ontology['relationships'])} relationships")

        total_nodes = 0
        for cname, spec in ontology["classes"].items():
            n = _load_nodes(conn, cname, spec)
            total_nodes += n
            print(f"  node  {cname:<22} {n:>10,}")

        total_edges = 0
        for rname, rspec in ontology["relationships"].items():
            if rspec["kind"] == "fk":
                n = _load_fk_edges(conn, rname, rspec, ontology)
            elif rspec["kind"] == "aggregate":
                n = _load_aggregate_edges(conn, rname, rspec)
            else:
                raise ValueError(f"unknown relationship kind: {rspec['kind']}")
            total_edges += n
            print(f"  edge  {rname:<22} {n:>10,}")

        _end_build_run(conn, run_id, "success", total_nodes, total_edges, None)
        print(f"[kg] build run_id={run_id} SUCCESS: {total_nodes:,} nodes, {total_edges:,} edges")
        return 0
    except Exception as exc:
        conn.rollback()
        try:
            _end_build_run(conn, run_id, "failed", 0, 0, f"{type(exc).__name__}: {exc}")
        except Exception:
            pass
        print(f"[kg] build FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
