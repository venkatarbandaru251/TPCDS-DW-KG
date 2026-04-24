# Roadmap

Small, vertical slices. Each phase is shippable and demo-able on its own. Ship order is top-to-bottom.

## Phase 0 — Raw or Bronze

- Profile the available datasets 
- ingest them using dbt framework into a raw zone (Bronze)
- schedule the ingestion process as a batch job
- perform data quality checks and generate a dashboard
- **Demo:** the dashboard and the schedule

## Phase 1 — Staging or Silver 

- Move the data from the raw zone to the staging area (Silver) creating the neccesary dimension and fact tables
- while moving the data clean the data per the busines rules
- Move any anomaly data to the anomaly tables
- show the output in a dashboard
- **Demo:** the dashboard with the results

## Phase 2 — Consumption or Gold Layer

- Move the data from the staging area to the consumption layer(Gold)
- while moving build the integerated view
- Move any anomaly data to the anomlay tables
- show the output in a dashboard
- **Demo:** the dashboard with the results

## Phase 3 — Performane tuning

- review the logn running queries
- review the explain plan
- Make neccessary changes (jncluding the database settings) to improve based on the plan
- show the improvement on the dashboard.
- **Demo:** the dashboard with the results

## Phase 4- Ontology and Knowledge Graph
-- Define Ontology based on the tables
-- Define Knowlege graph
-- enable querying the knowledge graph through an LLM running on Ollama. The interface can be in php
- **Ontology:** `knowledge_graph/ontology.json` — 15 classes (Customer, Item, Store, …) + 7 relationships (FK + aggregate fact edges).
- **Knowledge graph:** materialized in the Postgres `graph` schema — `graph.node`, `graph.edge`, `graph.ontology_class`, `graph.ontology_relationship`. Built by `knowledge_graph.build_graph`.
- **Query API:** `knowledge_graph.api` — stdlib HTTP server on `:8088`, calls Ollama to translate natural language to read-only SQL over `graph.*` (and `silver.*` / `gold.*` for rollups), executes it, and summarizes the result.
- **UI:** `dashboard/kg.php` — chat page that proxies to the API; live class/relationship counts in the sidebar.
- **Demo:** open `kg.php`, ask “Top 5 customers by total net paid” or “Which stores are in CA?”.

## Phase 5 — Display the knowledge graph in Neo4j

- **Neo4j:** Neo4j 5 Community running via Docker (`infra/docker-compose.neo4j.yml`). Browser on `:7474`, Bolt on `:7687`. Credentials from `.env`.
- **Loader:** `knowledge_graph.push_to_neo4j` — reads `graph.node` / `graph.edge` from Postgres and UNWIND-MERGEs them into Neo4j (`:Entity` + per-class labels like `:Customer`, `:Item`; relationships keep their original names `PURCHASED`, `LIVES_AT`, …). Supports `--sample` (default, top-N customers + 2-hop, ~1.7k nodes so the Browser can render it) and `--full`.
- **Demo cypher** (paste into the Browser):
  - `MATCH (c:Customer)-[p:PURCHASED]->(i:Item) RETURN c, p, i LIMIT 50` — customer/item subgraph
  - `MATCH (c:Customer)-[:PURCHASED]->(i:Item)<-[:PURCHASED]-(c2:Customer) WHERE id(c)<id(c2) RETURN i.product_name, count(*) ORDER BY 2 DESC LIMIT 10` — items bought by multiple top customers
  - `MATCH p=(c:Customer)-[:LIVES_AT]->(:Address), (c)-[:IN_HOUSEHOLD]->(:HouseholdDemographics)-[:IN_INCOME_BAND]->(:IncomeBand) RETURN p LIMIT 20` — customer / address / income-band chains
- **Demo:** `scripts\run_neo4j_up.bat` → `scripts\run_neo4j_push.bat` → open http://localhost:7474

## Later (not scheduled)

- Auth (currently persona-switched via a dev toggle).
- Notifications, reminders, analytics.
