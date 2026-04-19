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

## Later (not scheduled)

- Auth (currently persona-switched via a dev toggle).
- Notifications, reminders, analytics.
