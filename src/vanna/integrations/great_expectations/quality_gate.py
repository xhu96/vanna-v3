"""Great Expectations quality-gate lifecycle hook.

.. warning::
    **Experimental integration.** Requires production tuning of table
    extraction logic and API configuration before deployment. The current
    implementation uses simplistic keyword-based table detection.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict

try:
    import httpx
except ImportError:
    httpx = None

from vanna.core.lifecycle.base import LifecycleHook

if TYPE_CHECKING:
    from vanna.core.tool import Tool
    from vanna.models.tool import ToolContext

logger = logging.getLogger(__name__)


class GreatExpectationsQualityGate(LifecycleHook):
    """
    A lifecycle hook that acts as a Data Quality Gate before executing SQL queries.
    It checks Great Expectations (Cloud or mapped API) to ensure the target tables
    are healthy before allowing the LLM's generated query to run.
    """

    def __init__(self, gx_api_url: str, gx_token: str, strict: bool = False, timeout: int = 5):
        if httpx is None:
            raise ImportError(
                "The `httpx` package is required to use GreatExpectationsQualityGate. "
                "You can install it with `pip install httpx`."
            )
        self.gx_api_url = gx_api_url.rstrip("/")
        self.gx_token = gx_token
        self.strict = strict
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {self.gx_token}",
            "Content-Type": "application/vnd.api+json",
        }

    async def _check_table_health(self, table_name: str) -> Dict[str, Any]:
        """
        Mocked check against a Great Expectations or Data Observability API
        to see if the latest daily validation suite passed for this table.
        """
        try:
            async with httpx.AsyncClient() as client:
                # In reality, this would query the exact expectations suite for the table
                response = await client.get(
                    f"{self.gx_api_url}/api/v1/validations?table={table_name}",
                    headers=self.headers,
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                
                # Assume the API returns {"status": "passing" | "failing"}
                return data
        except Exception as e:
            logger.warning(f"Failed to fetch Great Expectations status for {table_name}: {e}")
            return {"status": "unknown"}

    async def before_tool(self, tool: "Tool[Any]", context: "ToolContext") -> None:
        """
        Intercepts tool execution. If the tool is 'run_sql', we check data quality.
        """
        if tool.name == "run_sql":
            # For a proper implementation, we'd parse the SQL to extract table names.
            # Here we do a simplistic mock extraction or assume a generic check.
            sql = getattr(context.tool_args, "sql", "").lower()
            
            # Simple heuristic: check if common tables are failing
            # e.g., if 'sales' is in query, check 'sales' health
            if "sales" in sql:
                health = await self._check_table_health("sales")
                if health.get("status") == "failing":
                    warning_msg = (
                        "Data Quality Gate Intersect: The 'sales' table recently failed "
                        "Great Expectations validation. Data might be stale or incorrect."
                    )
                    logger.warning(warning_msg)
                    if self.strict:
                        raise Exception(f"Strict Quality Gate: {warning_msg}")
                    else:
                        # Append a warning to the evidence panel if we had context.evidence
                        if hasattr(context, "evidence"):
                            context.evidence.append({"type": "warning", "message": warning_msg})
