# Semantic Layer Integration

Integrating Vanna with a Semantic Layer (like Cube.dev or dbt Semantic Layer) ensures that all metrics reported by the LLM match your internal dashboards exactly.

## The Architecture

Without a Semantic Layer, an LLM generates a query like:

```sql
SELECT SUM(revenue) - SUM(cogs) AS margin FROM raw_orders;
```

With `CubeRunner` or `SemanticRunner`, the LLM instead produces:

```sql
SELECT * FROM Cube_Measure_Margin;
```

The complex JOIN logic, filter arrays, and aggregations are offloaded safely to the Semantic Engine.

## Using `CubeRunner`

```python
from vanna import Agent
from vanna.integrations.cube import CubeRunner
from vanna.core.registry import ToolRegistry
from vanna.tools import RunSqlTool

# Bind Vanna's SQL runner to Cube's SQL API
cube_runner = CubeRunner(
    cube_api_url="https://your-cube-deployment.com",
    security_context_token="<JWT_TOKEN_FOR_CUBE>"
)

tools = ToolRegistry()
tools.register(RunSqlTool(sql_runner=cube_runner))

agent = Agent(llm_service=..., tool_registry=tools, user_resolver=...)
```

## Security

When users ask questions, `CubeRunner` can intercept `context.user` properties and pass them in the HTTP headers to Cube.dev, ensuring Cube's own Row-Level-Security (tenant filters) are automatically enforced.
