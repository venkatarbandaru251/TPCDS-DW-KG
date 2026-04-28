# Datwarehosuing for a Business Entity

## Input from stakeholders

- Mr. Reliablity is Data Relibility Engineer wants a dashboard for monitoing the progress og the jobs, data quality and failures
- Mrs. Busines Analyst wants data in the consumption layer to do anlysis. Some of the data in the Gold layer should be 
 ├─ mart_sales_performance (daily/monthly rollups)
 ├─ mart_customer_360 (LTV, RFM, segments)
 ├─ mart_product_analytics (top sellers, returns rate)
 └─ mart_channel_comparison (store vs web vs catalog)
- Mrs. CEO wants data available everyday by 7:00 AM

## Phases

- **Phase 0 — Bronze:** CSV → Postgres via Python (`ingestion/`); dbt source tests; dashboard at `dashboard/index.php`.
- **Phase 1 — Silver:** dim/fact models + `__anomalies` sidecars (`transform/models/silver/`).
- **Phase 2 — Gold:** 4 marts in `transform/models/gold/` — sales performance, channel comparison, customer 360, product analytics.
- **Phase 3 — Perf tuning:** post-build indexes + storage params applied in `ingestion/run_pipeline.py`.
- **Phase 4 — Ontology + Knowledge Graph:** `knowledge_graph/` — JSON ontology, `graph.node` / `graph.edge` tables, Ollama-backed Q&A API, PHP chat UI at `dashboard/kg.php`.

## Phase 4 quickstart

```bash
# 1. (Re)build the graph from Silver
scripts\run_kg_build.bat

# 2. Pull an Ollama model (once)
ollama pull llama3.1

# 3. Start the KG API and dashboard
scripts\run_kg_api.bat
scripts\run_dashboard.bat
# open http://localhost:8080/kg.php
```
