"""Phase 4 — Ontology & Knowledge Graph.

Defines a retail ontology over the TPC-DS Silver dimensions + facts and
materializes it as node/edge tables in a `graph` schema on the same Postgres
warehouse. An Ollama-backed HTTP API answers natural-language questions by
generating SQL against the graph tables.
"""
