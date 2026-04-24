"""Graph schema (ontology metadata + nodes + edges) living in the `graph`
schema on the same warehouse Postgres. Idempotent DDL."""

GRAPH_DDL = [
    "CREATE SCHEMA IF NOT EXISTS graph",
    """
    CREATE TABLE IF NOT EXISTS graph.ontology_class (
        class_name     TEXT PRIMARY KEY,
        description    TEXT,
        source_table   TEXT NOT NULL,
        surrogate_key  TEXT NOT NULL,
        natural_key    TEXT,
        label_expr     TEXT,
        properties     JSONB NOT NULL DEFAULT '[]'::jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph.ontology_relationship (
        name                  TEXT PRIMARY KEY,
        description           TEXT,
        from_class            TEXT NOT NULL REFERENCES graph.ontology_class(class_name) ON DELETE CASCADE,
        to_class              TEXT NOT NULL REFERENCES graph.ontology_class(class_name) ON DELETE CASCADE,
        kind                  TEXT NOT NULL CHECK (kind IN ('fk', 'aggregate')),
        definition            JSONB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph.node (
        node_id      BIGSERIAL PRIMARY KEY,
        class_name   TEXT NOT NULL REFERENCES graph.ontology_class(class_name) ON DELETE CASCADE,
        source_sk    BIGINT NOT NULL,
        natural_id   TEXT,
        label        TEXT,
        properties   JSONB NOT NULL DEFAULT '{}'::jsonb,
        UNIQUE (class_name, source_sk)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph.edge (
        edge_id            BIGSERIAL PRIMARY KEY,
        from_node_id       BIGINT NOT NULL REFERENCES graph.node(node_id) ON DELETE CASCADE,
        to_node_id         BIGINT NOT NULL REFERENCES graph.node(node_id) ON DELETE CASCADE,
        relationship_name  TEXT NOT NULL REFERENCES graph.ontology_relationship(name) ON DELETE CASCADE,
        properties         JSONB NOT NULL DEFAULT '{}'::jsonb,
        UNIQUE (from_node_id, to_node_id, relationship_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph.build_runs (
        run_id        BIGSERIAL PRIMARY KEY,
        started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ended_at      TIMESTAMPTZ,
        status        TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'success', 'failed')),
        nodes_loaded  BIGINT,
        edges_loaded  BIGINT,
        error_message TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_graph_node_class ON graph.node(class_name)",
    "CREATE INDEX IF NOT EXISTS idx_graph_edge_rel ON graph.edge(relationship_name)",
    "CREATE INDEX IF NOT EXISTS idx_graph_edge_from ON graph.edge(from_node_id)",
    "CREATE INDEX IF NOT EXISTS idx_graph_edge_to ON graph.edge(to_node_id)",
]


def apply_graph_ddl(conn) -> None:
    with conn.cursor() as cur:
        for stmt in GRAPH_DDL:
            cur.execute(stmt)
    conn.commit()
