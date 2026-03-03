# Vanna 3.2: Data Engineering Integrations

Vanna 3.2 has evolved from a "Smart BI tool" into a "Data Engineering Operating System". This document outlines the core Data Engineering integrations that safely map Natural Language insights to true Enterprise Data Governance.

## 1. Data Catalog Sync (DataHub / OpenMetadata)

The `DataHubContextEnhancer` allows Vanna to query DataHub's GraphQL API to pull enterprise glossary terms.

- **Benefit:** Resolves disambiguation (e.g. "What is ARR?") accurately according to the enterprise glossary, rather than hallucination.
- **Config:** Hook it up to the `LlmContextEnhancer` in your `Agent` setup.

## 2. Headless BI / Semantic Layers (Cube.dev & dbt)

Generating raw SQL against massive fact tables can be tricky.

- **CubeRunner:** Intercepts LLM-generated requests and maps them to a Cube subset query.
- **dbt Skill Pack:** Vanna can declare a `dbt_pipeline_generator` skill, allowing the user to say "save this insight as a dbt model."

## 3. Data Observability (Great Expectations)

- **GreatExpectationsQualityGate:** Plugs into the `LifecycleHook` architecture. Checks the latest validation status of a table using GE Cloud or API before letting `run_sql` query it, protecting stakeholders from stale data.

## 4. Continuous Queries & Streaming (Apache Flink)

- **FlinkRunner:** Vanna isn't constrained to batch SQL (Postgres/BigQuery). It can speak Streaming SQL through the Flink SQL Gateway API to build real-time monitoring charts.

## 5. Dynamic Data Masking (Microsoft Presidio)

- **PresidioRedactor:** Rather than just hiding columns based on user identity, Presidio ensures an extra layer. Any PII retrieved (SSN, Emails, Credit Cards) is automatically scrubbed from the `pd.DataFrame` locally _before_ being sent back to the LLM or UI.
