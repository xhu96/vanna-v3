import logging
from typing import TYPE_CHECKING
import json

import pandas as pd

try:
    import httpx
except ImportError:
    httpx = None

from vanna.capabilities.sql_runner.base import SqlRunner
from vanna.capabilities.sql_runner.models import RunSqlToolArgs

if TYPE_CHECKING:
    from vanna.core.tool import ToolContext

logger = logging.getLogger(__name__)


class FlinkRunner(SqlRunner):
    """
    Runner for executing Apache Flink SQL queries via the Flink SQL Gateway REST API.
    Used for streaming queries and real-time Materialized Views.
    """

    def __init__(self, flink_sql_gateway_url: str, session_id: str = None, timeout: int = 30):
        if httpx is None:
            raise ImportError(
                "The `httpx` package is required to use FlinkRunner. "
                "You can install it with `pip install httpx`."
            )
        self.flink_sql_gateway_url = flink_sql_gateway_url.rstrip("/")
        self.session_id = session_id
        self.timeout = timeout

    async def _get_or_create_session(self, client: httpx.AsyncClient) -> str:
        """Get existing session or create a new one."""
        if self.session_id:
            return self.session_id
            
        try:
            response = await client.post(
                f"{self.flink_sql_gateway_url}/v1/sessions",
                json={"sessionName": "vanna-agent-session"},
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            self.session_id = data.get("sessionHandle")
            return self.session_id
        except Exception as e:
            raise Exception(f"Failed to execute streaming query against Flink: Failed to create session: {e}")

    async def run_sql(
        self, args: RunSqlToolArgs, context: "ToolContext"
    ) -> pd.DataFrame:
        """
        Executes a Flink SQL query. Supports both batch and mock-streaming response.
        For true streaming UI, this should ideally yield results or connect to a Kafka topic.
        Here we fetch the first N materialized rows.
        """
        try:
            async with httpx.AsyncClient() as client:
                session_id = await self._get_or_create_session(client)
                
                # 1. Execute statement
                exec_response = await client.post(
                    f"{self.flink_sql_gateway_url}/v1/sessions/{session_id}/statements",
                    json={"statement": args.sql},
                    timeout=self.timeout
                )
                exec_response.raise_for_status()
                operation_handle = exec_response.json().get("operationHandle")
                
                if not operation_handle:
                    raise ValueError("No operation handle returned from Flink")
                
                # 2. Fetch results (Simplified: just one synchronous poll)
                fetch_response = await client.get(
                    f"{self.flink_sql_gateway_url}/v1/sessions/{session_id}/operations/{operation_handle}/result/0",
                    timeout=self.timeout
                )
                fetch_response.raise_for_status()
                result_data = fetch_response.json()
                
                # Format Flink Gateway JSON into a Pandas DataFrame
                results = result_data.get("results", {})
                columns = [col["name"] for col in results.get("columns", [])]
                data = results.get("data", [])
                
                # Flink data rows are list of dicts: {"kind": "INSERT", "fields": [val1, val2]}
                rows = [row["fields"] for row in data if row.get("kind") in ("INSERT", "+I")]
                
                if not rows:
                    return pd.DataFrame()
                    
                df = pd.DataFrame(rows, columns=columns)
                return df
                
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to execute streaming query against Flink: {e}")
            raise Exception(f"Failed to execute streaming query against Flink: {e}")
