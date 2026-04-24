"""Push graph.node / graph.edge from Postgres into a Neo4j instance so
operators can browse the knowledge graph visually in the Neo4j Browser.

Two modes:
  - `--sample` (default): Top-200 customers by PURCHASED net_paid + their
    1-hop neighbors. Bounded at ~5k nodes so the Browser can render it.
  - `--full`: Everything (~2.1M nodes, ~1.2M edges). Takes minutes and the
    Browser will only visualize small result sets, but cypher queries work.

Usage:
  python -m knowledge_graph.push_to_neo4j                 # sample (default)
  python -m knowledge_graph.push_to_neo4j --full          # full push
  python -m knowledge_graph.push_to_neo4j --wipe --sample # reset then sample
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Iterator

import psycopg
from neo4j import GraphDatabase

from ingestion.config import dw_conn_kwargs

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

NODE_BATCH = 2000
EDGE_BATCH = 5000
TOP_CUSTOMERS_SAMPLE = 200


# --- Postgres readers ------------------------------------------------------

def _sampled_node_ids(pg, top_customers: int) -> set[int]:
    """Seed with top-N customers by PURCHASED net_paid, then expand OUTBOUND
    only over each customer's edges (PURCHASED item, LIVES_AT address, etc.).
    We don't backscatter through small dims — a single Store seed would pull
    in every customer that ever shopped there (~100k) and blow up the sample.
    """
    with pg.cursor() as cur:
        cur.execute(
            """
            WITH top_cust AS (
                SELECT c.node_id
                  FROM graph.node c
                  JOIN graph.edge e ON e.from_node_id = c.node_id
                 WHERE c.class_name = 'Customer'
                   AND e.relationship_name = 'PURCHASED'
                 GROUP BY c.node_id
                 ORDER BY SUM((e.properties->>'net_paid')::numeric) DESC NULLS LAST
                 LIMIT %s
            ),
            one_hop_out AS (
                SELECT e.to_node_id AS node_id
                  FROM graph.edge e
                  JOIN top_cust s ON e.from_node_id = s.node_id
            ),
            -- HouseholdDemographics -> IncomeBand is an outbound FK we want
            -- to reach through; same for chained FKs in general. One extra
            -- hop from one_hop_out keeps those chains intact.
            two_hop_out AS (
                SELECT e.to_node_id AS node_id
                  FROM graph.edge e
                  JOIN one_hop_out oho ON e.from_node_id = oho.node_id
            )
            SELECT node_id FROM top_cust
            UNION SELECT node_id FROM one_hop_out
            UNION SELECT node_id FROM two_hop_out
            """,
            (top_customers,),
        )
        return {r[0] for r in cur.fetchall()}


def _iter_nodes(pg, node_ids: set[int] | None) -> Iterator[dict]:
    """Yield nodes as plain dicts. If node_ids is given, restrict to them."""
    sql = (
        "SELECT node_id, class_name, source_sk, natural_id, label, properties FROM graph.node"
    )
    params: tuple = ()
    if node_ids is not None:
        sql += " WHERE node_id = ANY(%s)"
        params = (list(node_ids),)
    with pg.cursor(name="nodes_cur") as cur:
        cur.itersize = NODE_BATCH
        cur.execute(sql, params)
        for row in cur:
            yield {
                "node_id": row[0],
                "class_name": row[1],
                "source_sk": int(row[2]),
                "natural_id": row[3],
                "label": row[4],
                "properties": row[5] or {},
            }


def _iter_edges(pg, node_ids: set[int] | None) -> Iterator[dict]:
    sql = (
        "SELECT e.from_node_id, e.to_node_id, e.relationship_name, e.properties, "
        "       fn.class_name AS from_class, fn.source_sk AS from_sk, "
        "       tn.class_name AS to_class,   tn.source_sk AS to_sk "
        "  FROM graph.edge e "
        "  JOIN graph.node fn ON fn.node_id = e.from_node_id "
        "  JOIN graph.node tn ON tn.node_id = e.to_node_id"
    )
    params: tuple = ()
    if node_ids is not None:
        sql += " WHERE e.from_node_id = ANY(%s) AND e.to_node_id = ANY(%s)"
        params = (list(node_ids), list(node_ids))
    with pg.cursor(name="edges_cur") as cur:
        cur.itersize = EDGE_BATCH
        cur.execute(sql, params)
        for row in cur:
            yield {
                "from_class": row[4],
                "from_sk": int(row[5]),
                "to_class": row[6],
                "to_sk": int(row[7]),
                "relationship_name": row[2],
                "properties": _stringify_numeric(row[3] or {}),
            }


def _stringify_numeric(props: dict) -> dict:
    """Neo4j doesn't take Decimals; coerce to float/int where possible."""
    from decimal import Decimal
    out = {}
    for k, v in props.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def _batched(iterable: Iterable, n: int) -> Iterator[list]:
    batch: list = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch


# --- Neo4j writers ---------------------------------------------------------

_CONSTRAINTS = [
    # One uniqueness key per class. Using generic :Entity label so the
    # constraint catches any class_name/source_sk collision; plus per-class
    # labels for pretty visualization in the Browser.
    "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (n:Entity) REQUIRE (n.node_class, n.source_sk) IS UNIQUE",
]


def _apply_constraints(session) -> None:
    # Drop any older constraint that keyed on `class` (now renamed to
    # `node_class` because `class` collided with the Item.class property).
    for row in session.run("SHOW CONSTRAINTS YIELD name, properties"):
        if row.get("properties") == ["class", "source_sk"]:
            session.run(f"DROP CONSTRAINT {row['name']}")
    for stmt in _CONSTRAINTS:
        session.run(stmt)


def _wipe(session) -> None:
    # CALL { } IN TRANSACTIONS auto-commits per batch so the wipe fits in
    # Neo4j's default 700 MB per-transaction memory pool even on big graphs.
    session.run(
        "MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 2000 ROWS"
    ).consume()


# APOC-free approach: one MERGE per class label via a small CASE/CALL dispatch
# would need APOC (not installed). Instead we write nodes in one UNWIND with a
# generic :Entity label plus set a second label by class using apoc-free
# string-driven Cypher (dynamic labels aren't supported natively), so we issue
# one query per distinct class per batch. In practice batches are class-homogeneous
# because we sort the iterator by class.

_UPSERT_NODE_CYPHER = (
    "UNWIND $rows AS row\n"
    "MERGE (n:Entity {{node_class: row.class_name, source_sk: row.source_sk}})\n"
    "SET n:{label}, n.label = row.label, n.natural_id = row.natural_id, n += row.properties"
)

_UPSERT_EDGE_CYPHER = (
    "UNWIND $rows AS row\n"
    "MATCH (a:Entity {{node_class: row.from_class, source_sk: row.from_sk}})\n"
    "MATCH (b:Entity {{node_class: row.to_class,   source_sk: row.to_sk}})\n"
    "MERGE (a)-[r:{rel}]->(b)\n"
    "SET r += row.properties"
)


def _safe_label(name: str) -> str:
    """Only allow [A-Za-z0-9_] in dynamically-interpolated labels."""
    safe = "".join(c for c in name if c.isalnum() or c == "_")
    if not safe or not safe[0].isalpha():
        safe = f"C_{safe}"
    return safe


def _push_nodes(session, nodes: Iterable[dict]) -> int:
    """Group by class so each batch uses one homogeneous dynamic label."""
    buckets: dict[str, list[dict]] = {}
    total = 0
    for node in nodes:
        buckets.setdefault(node["class_name"], []).append(node)
        if len(buckets[node["class_name"]]) >= NODE_BATCH:
            total += _flush_node_bucket(session, node["class_name"], buckets[node["class_name"]])
            buckets[node["class_name"]] = []
    for cls, rows in buckets.items():
        if rows:
            total += _flush_node_bucket(session, cls, rows)
    return total


def _flush_node_bucket(session, class_name: str, rows: list[dict]) -> int:
    cypher = _UPSERT_NODE_CYPHER.format(label=_safe_label(class_name))
    session.run(cypher, rows=rows)
    return len(rows)


def _push_edges(session, edges: Iterable[dict]) -> int:
    buckets: dict[str, list[dict]] = {}
    total = 0
    for edge in edges:
        buckets.setdefault(edge["relationship_name"], []).append(edge)
        if len(buckets[edge["relationship_name"]]) >= EDGE_BATCH:
            total += _flush_edge_bucket(session, edge["relationship_name"], buckets[edge["relationship_name"]])
            buckets[edge["relationship_name"]] = []
    for rel, rows in buckets.items():
        if rows:
            total += _flush_edge_bucket(session, rel, rows)
    return total


def _flush_edge_bucket(session, rel_name: str, rows: list[dict]) -> int:
    cypher = _UPSERT_EDGE_CYPHER.format(rel=_safe_label(rel_name))
    session.run(cypher, rows=rows)
    return len(rows)


# --- Driver glue -----------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Push KG from Postgres to Neo4j.")
    parser.add_argument("--full", action="store_true", help="Push the full graph (slow).")
    parser.add_argument("--sample", action="store_true", help="Push a bounded sample (default).")
    parser.add_argument("--wipe", action="store_true", help="DETACH DELETE all nodes before loading.")
    parser.add_argument("--top-customers", type=int, default=TOP_CUSTOMERS_SAMPLE,
                        help="Number of top customers to seed the sample.")
    args = parser.parse_args()
    sample_mode = not args.full  # default to sample

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver, psycopg.connect(**dw_conn_kwargs()) as pg, \
         driver.session(database=NEO4J_DATABASE) as session:

        _apply_constraints(session)
        print(f"[neo4j] connected to {NEO4J_URI} (db={NEO4J_DATABASE})")

        if args.wipe:
            print("[neo4j] wiping existing graph...")
            _wipe(session)

        if sample_mode:
            print(f"[neo4j] computing sample (top {args.top_customers} customers + 1-hop)...")
            node_ids = _sampled_node_ids(pg, args.top_customers)
            print(f"[neo4j] sample: {len(node_ids):,} nodes")
        else:
            node_ids = None
            print("[neo4j] full push (all nodes + all edges)")

        total_nodes = _push_nodes(session, _iter_nodes(pg, node_ids))
        print(f"[neo4j] nodes pushed: {total_nodes:,}")

        total_edges = _push_edges(session, _iter_edges(pg, node_ids))
        print(f"[neo4j] edges pushed: {total_edges:,}")

        counts = session.run(
            "MATCH (n) RETURN count(n) AS nodes"
        ).single()
        rel_counts = session.run("MATCH ()-[r]->() RETURN count(r) AS rels").single()
        print(f"[neo4j] in database: {counts['nodes']:,} nodes, {rel_counts['rels']:,} relationships")
        print(f"[neo4j] open http://localhost:7474 (user: {NEO4J_USER})")
        return 0


if __name__ == "__main__":
    sys.exit(main())
