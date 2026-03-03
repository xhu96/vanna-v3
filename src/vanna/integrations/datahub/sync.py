import logging
from typing import Any, Dict, List, Optional
import json

try:
    import httpx
except ImportError:
    httpx = None

from vanna.core.enhancer.base import LlmContextEnhancer
from vanna.core.user.models import User
from vanna.core.llm.models import LlmMessage

logger = logging.getLogger(__name__)


class DataHubContextEnhancer(LlmContextEnhancer):
    """
    Fetches glossary terms and metadata context from a DataHub instance
    to enhance the LLM system prompt.
    """

    def __init__(self, datahub_url: str, token: str, timeout: int = 10):
        if httpx is None:
            raise ImportError(
                "The `httpx` package is required to use DataHubContextEnhancer. "
                "You can install it with `pip install httpx`."
            )
        self.datahub_url = datahub_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _fetch_glossary_terms(self, query: str) -> List[Dict[str, Any]]:
        """
        Queries the DataHub GraphQL endpoint for glossary terms matching the user query.
        """
        graphql_query = """
        query search($input: SearchInput!) {
          search(input: $input) {
            searchResults {
              entity {
                ... on GlossaryTerm {
                  urn
                  name
                  properties {
                    description
                  }
                }
              }
            }
          }
        }
        """
        variables = {
            "input": {
                "type": "GLOSSARY_TERM",
                "query": query,
                "start": 0,
                "count": 5,
            }
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.datahub_url}/api/graphql",
                    json={"query": graphql_query, "variables": variables},
                    headers=self.headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                
                # Check for GraphQL errors
                if "errors" in data:
                    logger.warning(f"DataHub GraphQL returned errors: {data['errors']}")
                    return []
                    
                results = data.get("data", {}).get("search", {}).get("searchResults", [])
                terms = []
                for result in results:
                    entity = result.get("entity", {})
                    if entity:
                        name = entity.get("name")
                        description = entity.get("properties", {}).get("description", "")
                        if name and description:
                            terms.append({"name": name, "description": description})
                return terms
        except Exception as e:
            logger.warning(f"Failed to fetch glossary terms from DataHub: {e}")
            return []

    async def enhance_system_prompt(
        self, system_prompt: str, user_message: str, user: User
    ) -> str:
        """
        Retrieves enterprise glossary definitions based on the user's initial message
        and injects them into the system prompt.
        """
        terms = await self._fetch_glossary_terms(user_message)

        if not terms:
            return system_prompt

        enhancement = "\\n\\nEnterprise Glossary Context (from DataHub):\\n"
        for term in terms:
            enhancement += f"- **{term['name']}**: {term['description']}\\n"

        return system_prompt + enhancement
