# Vanna: The Data Engineering Operating System (Vision / Roadmap)

> [!NOTE]
> **This is a vision and roadmap document**, not a description of shipped features.
> The integrations below represent the intended direction of the project and are
> planned across future releases. See [`CHANGELOG.md`](../CHANGELOG.md) and
> [`docs/v3/implementation-plan.md`](../docs/v3/implementation-plan.md) for
> what is currently implemented.

## Abstract

Traditional NL2SQL tools treat data pipelines as static assets, reading from warehouses and returning tables. **Vanna** aims to shift this paradigm by positioning the LLM Agent at the center of the Modern Data Stack (MDS). By wrapping core Data Engineering tools into composable, user-aware capabilities, Vanna could operate as a "Data Engineering OS" that can proactively monitor, protect, and build pipelines in response to conversational insights.

## Roadmap & Status

### Implemented (v3.2)

- **Action-Oriented ETL Generation**: When a user discovers an insight, it shouldn't die in the chat interface. Vanna translates analytical queries into deployable `dbt` models, orchestrating pull requests directly. (See `DbtDeployTool`).
- **Column-level Data Lineage**: Extracting column-level lineage from generated queries using SQLGlot.

### Planned (v3.3+)

1. **Webhook Ingestion Endpoint**: Generic HTTP endpoint to ingest semantic events or queries asynchronously.
2. **Data Contract Hook (Pandera)**: Integration with Pandera to validate data structures returned from standard queries before LLM manipulation.
3. **Approval Lifecycle Hook**: Pluggable governance phase where certain query classifications require human-in-the-loop review.
4. **Watch Goal Tool + APScheduler**: Background task orchestration for conversational analytics; agents autonomously track a metric over time and alert on deviation.
5. **Self-Improving Skill Drafts**: Feedback loops where the system automatically drafts improvements to existing skill packs based on query correction history.
6. **Governed Knowledge Syncing**: Integrations with enterprise Data Catalogs (DataHub, Collibra) to bridge the semantic divide.
7. **Pre-Query Observability**: Using Data Observability platforms (Monte Carlo, Great Expectations), Vanna would implement a "Health Check" lifecycle hook—refusing to query stale or compromised datasets.
8. **Real-time Analytics Bridging**: Integrating engines like Apache Flink would transform Vanna from batch queries to streaming dashboards via SSE.
9. **Absolute Privacy via Dynamic Scrubbing**: By embedding Microsoft Presidio, Vanna would guarantee that retrieved PII never reaches third-party LLM providers, scrubbing DataFrames at the edge.

See [`CHANGELOG.md`](../CHANGELOG.md) for the detailed version-by-version breakdown of shipped features.
