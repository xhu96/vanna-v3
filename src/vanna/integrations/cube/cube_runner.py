import logging
from typing import TYPE_CHECKING

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


class CubeRunner(SqlRunner):
    """
    Runner for executing Semantic Layer queries against Cube.dev SQL API
    via HTTP bridging.
    """

    def __init__(self, cube_api_url: str, security_context_token: str, timeout: int = 15):
        if httpx is None:
            raise ImportError(
                "The `httpx` package is required to use CubeRunner. "
                "You can install it with `pip install httpx`."
            )
        self.cube_api_url = cube_api_url.rstrip("/")
        self.security_context_token = security_context_token
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {self.security_context_token}",
            "Content-Type": "application/json",
        }

    async def run_sql(
        self, args: RunSqlToolArgs, context: "ToolContext"
    ) -> pd.DataFrame:
        """
        Executes a Cube SQL query via the Cube REST API (proxying Cube SQL if needed).
        Note: In real-world enterprise architectures, Cube SQL API speaks Postgres/MySQL wire protocol, 
        and you'd use PostgresRunner. But often semantic queries are passed via Cube REST API POST /cubejs-api/v1/sql.
        """
        
        # User-aware policy enforcement could append a specific security context or header
        if context and context.user:
            logger.info(f"User {context.user.id} executing semantic query")
            
        payload = {
            "query": args.sql
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.cube_api_url}/cubejs-api/v1/sql",
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                
                # Cube SQL API responses over REST usually contain a 'data' array of objects
                rows = data.get("data", [])
                
                if not rows:
                    if "error" in data:
                        raise ValueError(f"Cube.dev Error: {data['error']}")
                    return pd.DataFrame()
                    
                df = pd.DataFrame(rows)
                return df
                
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to execute semantic query against Cube: {e}")
            raise Exception(f"Failed to execute semantic query against Cube: {e}")
