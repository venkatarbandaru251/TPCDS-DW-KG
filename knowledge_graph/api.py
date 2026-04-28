"""Ollama-backed HTTP API for question-answering over the knowledge graph.

Flow per /ask request:
  1. Load ontology snapshot from graph.ontology_*.
  2. Build a system prompt that describes graph.node / graph.edge + the ontology.
  3. Ask Ollama to emit a single SELECT over graph.* (or silver/gold for rollups).
  4. Validate the SQL (read-only, single statement, whitelisted schemas).
  5. Execute against Postgres.
  6. Ask Ollama to summarize the rows as a natural-language answer.
  7. Return {sql, rows, answer} to the caller.

Usage: python -m knowledge_graph.api   (listens on http://localhost:8088)
"""
from __future__ import annotations

import json
import logging
import os
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import psycopg

from ingestion.config import dw_conn_kwargs

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
API_HOST = os.getenv("KG_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("KG_API_PORT", "8088"))
MAX_ROWS = 200

ALLOWED_SCHEMAS = ("graph", "silver", "gold")
_FORBIDDEN_WORD = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|comment|call|do)\b",
    re.IGNORECASE,
)

log = logging.getLogger("kg.api")


# --- Ollama wiring --------------------------------------------------------

def _ollama_generate(prompt: str, system: str | None = None, json_mode: bool = False) -> str:
    """Call Ollama /api/generate and return the response text. Non-streaming."""
    body: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    if system:
        body["system"] = system
    if json_mode:
        body["format"] = "json"
    req = urlrequest.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urlerror.URLError as exc:
        raise RuntimeError(f"Ollama unreachable at {OLLAMA_URL}: {exc}") from exc
    return payload.get("response", "")


def _ollama_status() -> dict:
    """Return {reachable, model_present, installed_models[]} — used by /health
    so misconfiguration (Ollama down, or configured model not pulled) is
    obvious before a user submits a question."""
    try:
        with urlrequest.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"reachable": False, "model_present": False, "installed_models": [], "error": str(exc)}
    names = [m.get("name") for m in payload.get("models", []) if m.get("name")]
    return {
        "reachable": True,
        "model_present": OLLAMA_MODEL in names,
        "installed_models": names,
    }


# --- Ontology snapshot ----------------------------------------------------

def _load_ontology_snapshot(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT class_name, description, source_table, surrogate_key, natural_key, label_expr, properties "
            "FROM graph.ontology_class ORDER BY class_name"
        )
        classes = [
            {
                "class": r[0], "description": r[1], "source_table": r[2],
                "surrogate_key": r[3], "natural_key": r[4], "label_expr": r[5],
                "properties": r[6] or [],
            }
            for r in cur.fetchall()
        ]
        cur.execute(
            "SELECT name, description, from_class, to_class, kind, definition "
            "FROM graph.ontology_relationship ORDER BY name"
        )
        rels = [
            {
                "name": r[0], "description": r[1], "from": r[2], "to": r[3],
                "kind": r[4], "definition": r[5],
            }
            for r in cur.fetchall()
        ]
    return {"classes": classes, "relationships": rels}


def _format_ontology_for_prompt(ontology: dict) -> str:
    """Compact, readable summary for the LLM."""
    lines = ["CLASSES (node types):"]
    for c in ontology["classes"]:
        props = ", ".join(p["name"] for p in c["properties"]) or "—"
        lines.append(f"  - {c['class']}: {c['description'] or ''}")
        lines.append(f"      properties: {props}")
    lines.append("")
    lines.append("RELATIONSHIPS (edge types):")
    for r in ontology["relationships"]:
        lines.append(f"  - {r['name']}: {r['from']} -> {r['to']} ({r['kind']}) — {r['description'] or ''}")
        if r["kind"] == "aggregate":
            aggs = list((r["definition"].get("aggregates") or {}).keys())
            if aggs:
                lines.append(f"      edge properties: {', '.join(aggs)}")
    return "\n".join(lines)


SYSTEM_PROMPT_TEMPLATE = """You are a retail knowledge-graph analyst. You answer questions about a \
Postgres-backed knowledge graph materialized from a TPC-DS warehouse.

SCHEMA (use these tables — do NOT invent others):
  graph.node(node_id bigint, class_name text, source_sk bigint, natural_id text, label text, properties jsonb)
  graph.edge(edge_id bigint, from_node_id bigint, to_node_id bigint, relationship_name text, properties jsonb)
  graph.ontology_class(class_name, description, source_table, surrogate_key, natural_key, label_expr, properties)
  graph.ontology_relationship(name, description, from_class, to_class, kind, definition)

You MAY also read silver.* and gold.* for aggregate rollups when the question is about totals over time.

Rules:
  - Emit a SINGLE read-only SELECT statement. No INSERT/UPDATE/DELETE/DDL.
  - No semicolons. No multi-statement. Use LIMIT (<= {max_rows}).
  - Access node properties with JSON operators: n.properties->>'email' returns TEXT.
  - BEFORE aggregating (SUM/AVG/MIN/MAX) a value from jsonb, cast it: (e.properties->>'net_paid')::numeric.
    Never SUM a raw properties->>'x' — Postgres will reject sum(text).
  - Join edges to nodes with graph.edge.from_node_id = graph.node.node_id.
  - Filter by class: graph.node.class_name = 'Customer'.
  - Filter edges: graph.edge.relationship_name = 'PURCHASED'.

ONTOLOGY:
{ontology}

EXAMPLES (exact SQL patterns):
  -- Top 5 customers by total purchased net_paid:
  SELECT c.label AS customer_name,
         SUM((e.properties->>'net_paid')::numeric) AS total_net_paid
    FROM graph.node c
    JOIN graph.edge e ON e.from_node_id = c.node_id
   WHERE c.class_name = 'Customer'
     AND e.relationship_name = 'PURCHASED'
   GROUP BY c.node_id, c.label
   ORDER BY total_net_paid DESC
   LIMIT 5

  -- Count nodes per class:
  SELECT class_name, COUNT(*) AS n FROM graph.node GROUP BY class_name ORDER BY n DESC

Output JSON ONLY with keys: sql (string), rationale (one sentence). No markdown fences."""


ANSWER_PROMPT_TEMPLATE = """A user asked: {question}

The following SQL was run against the knowledge graph:
{sql}

Results (first {n} rows, JSON):
{rows}

Write a concise natural-language answer for the user. If the result set is empty, say so and suggest a \
related question they could try. Do not invent numbers that aren't in the rows."""


# --- SQL validation --------------------------------------------------------

def _strip_json_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _validate_sql(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise ValueError("empty SQL from LLM")
    lower = s.lower()
    if not lower.startswith(("select", "with")):
        raise ValueError("only SELECT / WITH queries are allowed")
    if ";" in s:
        raise ValueError("multiple statements are not allowed")
    if _FORBIDDEN_WORD.search(s):
        raise ValueError("forbidden keyword in SQL")
    # Require at least one allowed schema reference
    if not any(f"{sch}." in lower for sch in ALLOWED_SCHEMAS):
        raise ValueError(f"SQL must reference one of: {', '.join(ALLOWED_SCHEMAS)}")
    # Append a safety LIMIT if none
    if re.search(r"\blimit\s+\d+", lower) is None:
        s = f"{s} LIMIT {MAX_ROWS}"
    return s


def _run_sql(conn, sql: str) -> tuple[list[str], list[list[Any]]]:
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
    # Convert rows to JSON-serializable lists
    safe_rows: list[list[Any]] = []
    for row in rows[:MAX_ROWS]:
        safe_rows.append([_json_safe(v) for v in row])
    return cols, safe_rows


def _json_safe(v: Any) -> Any:
    from datetime import date, datetime
    from decimal import Decimal
    if v is None or isinstance(v, (str, int, float, bool, list, dict)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


# --- Request handler -------------------------------------------------------

class AskHandler(BaseHTTPRequestHandler):
    server_version = "KG-API/1.0"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        log.info("%s - %s", self.address_string(), format % args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            status = _ollama_status()
            self._json(200, {
                "ok": status["reachable"] and status["model_present"],
                "ollama_url": OLLAMA_URL,
                "model": OLLAMA_MODEL,
                "ollama_reachable": status["reachable"],
                "model_present": status["model_present"],
                "installed_models": status["installed_models"],
                "error": status.get("error"),
            })
            return
        if self.path.startswith("/ontology"):
            try:
                with psycopg.connect(**dw_conn_kwargs()) as conn:
                    onto = _load_ontology_snapshot(conn)
                self._json(200, onto)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/ask"):
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON body"})
            return
        question = (body.get("question") or "").strip()
        if not question:
            self._json(400, {"error": "question is required"})
            return
        try:
            response = self._answer(question)
        except Exception as exc:
            log.error("ask failed: %s\n%s", exc, traceback.format_exc())
            self._json(500, {"error": str(exc)})
            return
        self._json(200, response)

    def _answer(self, question: str) -> dict:
        with psycopg.connect(**dw_conn_kwargs()) as conn:
            ontology = _load_ontology_snapshot(conn)
            system = SYSTEM_PROMPT_TEMPLATE.format(
                ontology=_format_ontology_for_prompt(ontology),
                max_rows=MAX_ROWS,
            )
            raw = _ollama_generate(question, system=system, json_mode=True)
            parsed = self._parse_llm_sql(raw)
            sql = _validate_sql(parsed["sql"])
            cols, rows = _run_sql(conn, sql)

            preview = rows[:20]
            answer_prompt = ANSWER_PROMPT_TEMPLATE.format(
                question=question,
                sql=sql,
                n=len(preview),
                rows=json.dumps([dict(zip(cols, r)) for r in preview], default=str),
            )
            answer = _ollama_generate(answer_prompt).strip()

            return {
                "question": question,
                "sql": sql,
                "rationale": parsed.get("rationale"),
                "columns": cols,
                "rows": rows,
                "row_count": len(rows),
                "answer": answer,
            }

    @staticmethod
    def _parse_llm_sql(raw: str) -> dict:
        text = _strip_json_fences(raw)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: extract the first SELECT ... block
            m = re.search(r"(with\s+.*?|select\s+.*)", text, re.IGNORECASE | re.DOTALL)
            if not m:
                raise ValueError(f"could not parse SQL from LLM output: {text[:200]!r}")
            return {"sql": m.group(1), "rationale": None}
        if "sql" not in obj:
            raise ValueError(f"LLM JSON missing 'sql' key: {obj}")
        return obj


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        server = ThreadingHTTPServer((API_HOST, API_PORT), AskHandler)
    except OSError as exc:
        log.error(
            "could not bind %s:%d — %s. "
            "On Windows this often means the port is reserved by Hyper-V/HNS "
            "or held by another process. Set KG_API_PORT to a free port in .env "
            "(e.g. 8089, 8765, 9090) and retry.",
            API_HOST, API_PORT, exc,
        )
        return 2
    log.info("KG API listening on http://%s:%d (ollama=%s, model=%s)",
             API_HOST, API_PORT, OLLAMA_URL, OLLAMA_MODEL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
