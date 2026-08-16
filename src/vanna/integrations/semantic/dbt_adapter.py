"""dbt Semantic Layer GraphQL adapter with bounded, typed execution."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import re
import time
from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    FrozenSet,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)
from urllib.parse import urlsplit

import httpx

from vanna.capabilities.semantic import (
    SemanticAdapter,
    SemanticPlanHint,
    SemanticQueryRequest,
    SemanticQueryResult,
)
from vanna.core.tool import ToolContext
from vanna.core.user import principal_scope_for_user

TokenProvider = Callable[[ToolContext], Union[str, Awaitable[str]]]
EnvironmentIdProvider = Callable[[ToolContext], Union[str, Awaitable[str]]]
TenantValueProvider = Callable[[ToolContext], Any]
Sleep = Callable[[float], Awaitable[None]]
Monotonic = Callable[[], float]

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_ORDER_BY = re.compile(
    r"^(?P<prefix>[+-]?)(?P<name>[A-Za-z_][A-Za-z0-9_.:-]{0,127})"
    r"(?::(?P<direction>asc|desc))?$",
    flags=re.IGNORECASE,
)

_FILTER_OPERATORS = {
    "equals": "EQUALS",
    "not_equals": "NOT_EQUALS",
    "greater_than": "GREATER_THAN",
    "greater_or_equal": "GREATER_OR_EQUAL",
    "less_than": "LESS_THAN",
    "less_or_equal": "LESS_OR_EQUAL",
    "in": "IN",
    "not_in": "NOT_IN",
}
_CATEGORICAL_OPERATORS = frozenset({"equals", "not_equals", "in", "not_in"})
_ORDERED_OPERATORS = frozenset(_FILTER_OPERATORS)
_TIME_GRAIN_TERMS = {
    "day": ("day", "daily", "by day"),
    "week": ("week", "weekly", "by week"),
    "month": ("month", "monthly", "by month"),
    "quarter": ("quarter", "quarterly", "by quarter"),
    "year": ("year", "yearly", "annual", "annually", "by year"),
}
_RUNNING_STATUSES = frozenset({"accepted", "pending", "queued", "running"})
_SUCCESS_STATUSES = frozenset({"complete", "completed", "success", "successful"})
_FAILURE_STATUSES = frozenset({"cancelled", "canceled", "error", "failed"})

_CATALOG_QUERY = """
query GetSemanticCatalog($environmentId: BigInt!, $first: Int!, $after: String) {
  metrics(environmentId: $environmentId, first: $first, after: $after) {
    edges {
      node {
        name
        label
        description
        synonyms
        dimensions {
          name
          label
          type
          operators
          queryableGranularities
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_CREATE_QUERY = """
mutation CreateSemanticQuery(
  $environmentId: BigInt!
  $metrics: [MetricInput!]!
  $groupBy: [GroupByInput!]
  $where: [WhereInput!]
  $orderBy: [OrderByInput!]
  $limit: Int
) {
  createQuery(
    environmentId: $environmentId
    metrics: $metrics
    groupBy: $groupBy
    where: $where
    orderBy: $orderBy
    limit: $limit
  ) { queryId }
}
"""

_QUERY_STATUS = """
query GetSemanticQueryStatus($environmentId: BigInt!, $queryId: String!) {
  query(environmentId: $environmentId, queryId: $queryId) {
    queryId
    status
  }
}
"""

_QUERY_RESULTS = """
query GetSemanticQueryResults(
  $environmentId: BigInt!
  $queryId: String!
  $first: Int!
  $after: String
) {
  queryResult(
    environmentId: $environmentId
    queryId: $queryId
    first: $first
    after: $after
  ) {
    rows
    pageInfo { hasNextPage endCursor }
  }
}
"""


class DbtSemanticLayerError(RuntimeError):
    """Stable public error that never includes upstream diagnostics."""

    def __init__(self, code: str, request_id: Optional[str] = None) -> None:
        self.code = code
        reference = (
            f" Reference request ID {request_id}."
            if request_id and _REQUEST_ID.fullmatch(request_id)
            else ""
        )
        super().__init__(f"dbt Semantic Layer request failed ({code}).{reference}")


@dataclass(frozen=True)
class _SemanticDimension:
    name: str
    aliases: FrozenSet[str]
    dimension_type: str
    operators: FrozenSet[str]
    granularities: FrozenSet[str]


@dataclass(frozen=True)
class _SemanticMetric:
    name: str
    aliases: FrozenSet[str]
    dimensions: Mapping[str, _SemanticDimension]


def _normalize_phrase(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _contains_phrase(message: str, aliases: Sequence[str]) -> bool:
    padded_message = f" {message} "
    return any(f" {_normalize_phrase(alias)} " in padded_message for alias in aliases)


def _safe_identifier(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("semantic identifier is not a string")
    normalized = value.strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError("semantic identifier is invalid")
    return normalized


def _connection_nodes(connection: Any) -> List[Any]:
    if isinstance(connection, list):
        return connection
    if not isinstance(connection, dict):
        raise ValueError("GraphQL connection is invalid")
    edges = connection.get("edges")
    if isinstance(edges, list):
        nodes: List[Any] = []
        for edge in edges:
            if not isinstance(edge, dict) or "node" not in edge:
                raise ValueError("GraphQL edge is invalid")
            nodes.append(edge["node"])
        return nodes
    raw_nodes = connection.get("nodes")
    if isinstance(raw_nodes, list):
        return raw_nodes
    raise ValueError("GraphQL connection has no nodes")


def _page_info(connection: Any) -> Tuple[bool, Optional[str]]:
    if not isinstance(connection, dict):
        return False, None
    page_info = connection.get("pageInfo")
    if not isinstance(page_info, dict):
        return False, None
    has_next = page_info.get("hasNextPage") is True
    cursor = page_info.get("endCursor")
    return has_next, cursor if isinstance(cursor, str) and cursor else None


class DbtSemanticLayerAdapter(SemanticAdapter):
    """SemanticAdapter for dbt's asynchronous GraphQL query workflow."""

    def __init__(
        self,
        *,
        endpoint: str,
        token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
        environment_id: Optional[str] = None,
        environment_id_provider: Optional[EnvironmentIdProvider] = None,
        tenant_filter_dimension: str = "tenant_id",
        tenant_value_provider: Optional[TenantValueProvider] = None,
        request_timeout_seconds: float = 10.0,
        query_timeout_seconds: float = 30.0,
        poll_initial_seconds: float = 0.1,
        poll_max_seconds: float = 2.0,
        max_poll_attempts: int = 100,
        metadata_page_size: int = 100,
        result_page_size: int = 1000,
        max_metadata_pages: int = 100,
        max_result_pages: int = 100,
        max_response_bytes: int = 8 * 1024 * 1024,
        catalog_ttl_seconds: float = 300.0,
        sleep: Sleep = asyncio.sleep,
        monotonic: Monotonic = time.monotonic,
    ) -> None:
        parsed_endpoint = urlsplit(endpoint)
        if (
            parsed_endpoint.scheme != "https"
            or not parsed_endpoint.hostname
            or parsed_endpoint.username
            or parsed_endpoint.password
            or parsed_endpoint.fragment
        ):
            raise ValueError(
                "dbt Semantic Layer endpoint must be an HTTPS URL without "
                "credentials or fragments"
            )
        if (environment_id is None) == (environment_id_provider is None):
            raise ValueError(
                "Configure exactly one of environment_id or environment_id_provider"
            )
        if environment_id is not None and not re.fullmatch(
            r"[0-9]{1,20}", environment_id
        ):
            raise ValueError("environment_id must be a numeric dbt environment ID")
        if request_timeout_seconds <= 0 or query_timeout_seconds <= 0:
            raise ValueError("semantic timeouts must be positive")
        if poll_initial_seconds <= 0 or poll_max_seconds < poll_initial_seconds:
            raise ValueError("semantic polling bounds are invalid")
        if max_poll_attempts <= 0:
            raise ValueError("max_poll_attempts must be positive")
        if not 1 <= metadata_page_size <= 500:
            raise ValueError("metadata_page_size must be between 1 and 500")
        if not 1 <= result_page_size <= 5000:
            raise ValueError("result_page_size must be between 1 and 5000")
        if max_metadata_pages <= 0 or max_result_pages <= 0:
            raise ValueError("semantic pagination bounds must be positive")
        if not 1024 <= max_response_bytes <= 64 * 1024 * 1024:
            raise ValueError("max_response_bytes must be between 1 KiB and 64 MiB")
        if catalog_ttl_seconds < 0:
            raise ValueError("catalog_ttl_seconds cannot be negative")

        self.endpoint = endpoint
        self.environment_id = environment_id
        self.environment_id_provider = environment_id_provider
        self.token_provider = token_provider
        self.tenant_filter_dimension = _safe_identifier(tenant_filter_dimension)
        self.tenant_value_provider = tenant_value_provider
        self.http_client = http_client
        self.request_timeout_seconds = request_timeout_seconds
        self.query_timeout_seconds = query_timeout_seconds
        self.poll_initial_seconds = poll_initial_seconds
        self.poll_max_seconds = poll_max_seconds
        self.max_poll_attempts = max_poll_attempts
        self.metadata_page_size = metadata_page_size
        self.result_page_size = result_page_size
        self.max_metadata_pages = max_metadata_pages
        self.max_result_pages = max_result_pages
        self.max_response_bytes = max_response_bytes
        self.catalog_ttl_seconds = catalog_ttl_seconds
        self.sleep = sleep
        self.monotonic = monotonic
        self._catalogs: Dict[str, Tuple[Dict[str, _SemanticMetric], float]] = {}
        self._catalog_lock = asyncio.Lock()

    @staticmethod
    def _request_id(context: Optional[ToolContext]) -> Optional[str]:
        return context.request_id if context is not None else None

    def _error(
        self,
        code: str,
        context: Optional[ToolContext],
    ) -> DbtSemanticLayerError:
        return DbtSemanticLayerError(code, self._request_id(context))

    async def _token(self, context: ToolContext) -> str:
        try:
            supplied = self.token_provider(context)
            if inspect.isawaitable(supplied):
                token = await supplied
            else:
                token = supplied
        except Exception:
            raise self._error("semantic_auth_error", context) from None
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 8192
            or token.strip() != token
            or any(ord(character) < 32 or ord(character) == 127 for character in token)
        ):
            raise self._error("semantic_auth_error", context)
        return token

    async def _environment_id(self, context: ToolContext) -> str:
        resolved: object
        try:
            if self.environment_id_provider is None:
                supplied: Union[str, Awaitable[str], None] = self.environment_id
            else:
                supplied = self.environment_id_provider(context)
            if inspect.isawaitable(supplied):
                resolved = await supplied
            else:
                resolved = supplied
        except Exception:
            raise self._error("semantic_environment_error", context) from None
        if not isinstance(resolved, str) or not re.fullmatch(r"[0-9]{1,20}", resolved):
            raise self._error("semantic_environment_error", context)
        return resolved

    def _tenant_value(self, context: ToolContext) -> Union[str, int]:
        try:
            value = (
                self.tenant_value_provider(context)
                if self.tenant_value_provider is not None
                else context.user.metadata.get("tenant_id")
            )
        except Exception:
            raise self._error("semantic_policy_denied", context) from None
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise self._error("semantic_policy_denied", context)
        if isinstance(value, str) and (
            not value.strip()
            or value != value.strip()
            or len(value) > 256
            or any(ord(character) < 32 for character in value)
        ):
            raise self._error("semantic_policy_denied", context)
        return value

    @staticmethod
    def _catalog_scope_key(context: ToolContext, environment_id: str) -> str:
        scope = {
            "environment_id": environment_id,
            "principal": principal_scope_for_user(context.user),
            "groups": sorted(context.user.group_memberships),
        }
        encoded = json.dumps(
            scope, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    async def _graphql(
        self,
        *,
        operation_name: str,
        query: str,
        variables: Dict[str, Any],
        context: ToolContext,
    ) -> Dict[str, Any]:
        token = await self._token(context)
        try:
            async with self.http_client.stream(
                "POST",
                self.endpoint,
                json={
                    "operationName": operation_name,
                    "query": query,
                    "variables": variables,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=self.request_timeout_seconds,
                follow_redirects=False,
            ) as response:
                # Redirects are rejected before a client can replay the GraphQL
                # body to another origin, regardless of its configured default.
                if not 200 <= response.status_code < 300:
                    raise self._error("semantic_http_error", context)
                if response.history or response.url != httpx.URL(self.endpoint):
                    raise self._error("semantic_http_error", context)

                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self.max_response_bytes:
                        raise self._error("semantic_response_too_large", context)
                    content.extend(chunk)
        except DbtSemanticLayerError:
            raise
        except httpx.HTTPError:
            raise self._error("semantic_transport_error", context) from None

        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, ValueError):
            raise self._error("semantic_response_error", context) from None
        if not isinstance(payload, dict):
            raise self._error("semantic_response_error", context)
        if payload.get("errors"):
            raise self._error("semantic_graphql_error", context)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise self._error("semantic_response_error", context)
        return cast(Dict[str, Any], data)

    async def refresh_catalog(
        self,
        context: ToolContext,
    ) -> Mapping[str, _SemanticMetric]:
        """Force a bounded metadata refresh from dbt."""
        self._tenant_value(context)
        environment_id = await self._environment_id(context)
        scope_key = self._catalog_scope_key(context, environment_id)
        async with self._catalog_lock:
            catalog = await self._fetch_catalog(context, environment_id)
            self._catalogs[scope_key] = (catalog, self.monotonic())
            return catalog

    async def _get_catalog(
        self,
        context: ToolContext,
        environment_id: str,
    ) -> Mapping[str, _SemanticMetric]:
        now = self.monotonic()
        scope_key = self._catalog_scope_key(context, environment_id)
        cached = self._catalogs.get(scope_key)
        if cached is not None and now - cached[1] < self.catalog_ttl_seconds:
            return cached[0]
        async with self._catalog_lock:
            now = self.monotonic()
            cached = self._catalogs.get(scope_key)
            if cached is not None and now - cached[1] < self.catalog_ttl_seconds:
                return cached[0]
            catalog = await self._fetch_catalog(context, environment_id)
            self._catalogs[scope_key] = (catalog, self.monotonic())
            return catalog

    async def _fetch_catalog(
        self,
        context: ToolContext,
        environment_id: str,
    ) -> Dict[str, _SemanticMetric]:
        catalog: Dict[str, _SemanticMetric] = {}
        after: Optional[str] = None
        for _ in range(self.max_metadata_pages):
            data = await self._graphql(
                operation_name="GetSemanticCatalog",
                query=_CATALOG_QUERY,
                variables={
                    "environmentId": environment_id,
                    "first": self.metadata_page_size,
                    "after": after,
                },
                context=context,
            )
            connection = data.get("metrics")
            try:
                nodes = _connection_nodes(connection)
                has_next, cursor = _page_info(connection)
            except (TypeError, ValueError):
                raise self._error("semantic_catalog_error", context) from None

            if cursor is None or cursor == after:
                if has_next:
                    raise self._error("semantic_pagination_error", context)

            try:
                for node in nodes:
                    metric = self._parse_metric(node)
                    if metric.name in catalog:
                        raise ValueError("duplicate metric")
                    catalog[metric.name] = metric
            except (TypeError, ValueError):
                raise self._error("semantic_catalog_error", context) from None

            if not has_next:
                return catalog
            after = cursor

        raise self._error("semantic_pagination_error", context)

    @staticmethod
    def _parse_metric(value: Any) -> _SemanticMetric:
        if not isinstance(value, dict):
            raise ValueError("metric node is invalid")
        name = _safe_identifier(value.get("name"))
        aliases = {name, name.replace("_", " ")}
        for field in ("label",):
            alias = value.get(field)
            if isinstance(alias, str) and 0 < len(alias.strip()) <= 256:
                aliases.add(alias.strip())
        raw_synonyms = value.get("synonyms", [])
        if not isinstance(raw_synonyms, list) or len(raw_synonyms) > 100:
            raise ValueError("metric synonyms are invalid")
        for synonym in raw_synonyms:
            if (
                not isinstance(synonym, str)
                or not synonym.strip()
                or len(synonym.strip()) > 256
            ):
                raise ValueError("metric synonym is invalid")
            aliases.add(synonym.strip())

        raw_dimensions = value.get("dimensions", [])
        dimension_nodes = (
            _connection_nodes(raw_dimensions)
            if isinstance(raw_dimensions, dict)
            else raw_dimensions
        )
        if not isinstance(dimension_nodes, list) or len(dimension_nodes) > 100:
            raise ValueError("metric dimensions are invalid")
        dimensions: Dict[str, _SemanticDimension] = {}
        for raw_dimension in dimension_nodes:
            dimension = DbtSemanticLayerAdapter._parse_dimension(raw_dimension)
            if dimension.name in dimensions:
                raise ValueError("duplicate dimension")
            dimensions[dimension.name] = dimension
        return _SemanticMetric(
            name=name,
            aliases=frozenset(aliases),
            dimensions=dimensions,
        )

    @staticmethod
    def _parse_dimension(value: Any) -> _SemanticDimension:
        if not isinstance(value, dict):
            raise ValueError("dimension node is invalid")
        name = _safe_identifier(value.get("name"))
        aliases = {name, name.replace("_", " ")}
        label = value.get("label")
        if isinstance(label, str) and 0 < len(label.strip()) <= 256:
            aliases.add(label.strip())
        dimension_type = str(value.get("type", "categorical")).strip().lower()

        raw_grains = value.get("queryableGranularities", value.get("granularities", []))
        if not isinstance(raw_grains, list):
            raise ValueError("dimension grains are invalid")
        granularities = frozenset(
            str(grain).strip().lower()
            for grain in raw_grains
            if isinstance(grain, str) and grain.strip()
        )

        default_operators = (
            _ORDERED_OPERATORS
            if dimension_type in {"time", "numeric", "number"}
            else _CATEGORICAL_OPERATORS
        )
        raw_operators = value.get("operators")
        if raw_operators is None:
            operators = default_operators
        elif isinstance(raw_operators, list):
            operators = frozenset(
                str(operator).strip().lower()
                for operator in raw_operators
                if isinstance(operator, str)
                and str(operator).strip().lower() in _FILTER_OPERATORS
            )
            if not operators:
                raise ValueError("dimension operators are invalid")
        else:
            raise ValueError("dimension operators are invalid")

        return _SemanticDimension(
            name=name,
            aliases=frozenset(aliases),
            dimension_type=dimension_type,
            operators=operators,
            granularities=granularities,
        )

    async def plan(self, message: str, context: ToolContext) -> SemanticPlanHint:
        self._tenant_value(context)
        environment_id = await self._environment_id(context)
        catalog = await self._get_catalog(context, environment_id)
        normalized_message = _normalize_phrase(message)
        metrics = [
            metric
            for metric in catalog.values()
            if _contains_phrase(normalized_message, tuple(metric.aliases))
        ]
        if not metrics:
            return SemanticPlanHint(
                coverage="missing",
                reason="No catalogued dbt semantic metric matched the request.",
                request=None,
            )

        all_dimensions: Dict[str, _SemanticDimension] = {}
        for metric in catalog.values():
            all_dimensions.update(metric.dimensions)
        mentioned_dimensions = [
            dimension.name
            for dimension in all_dimensions.values()
            if _contains_phrase(normalized_message, tuple(dimension.aliases))
        ]
        shared_dimensions = self._shared_dimensions(metrics)
        self._require_tenant_policy(shared_dimensions, context)
        unsupported = set(mentioned_dimensions) - set(shared_dimensions)
        if unsupported:
            return SemanticPlanHint(
                coverage="partial",
                reason=(
                    f"Catalogued metric '{metrics[0].name}' does not cover all "
                    "requested dimensions."
                ),
                request=None,
            )

        grain = self._message_grain(normalized_message)
        if (
            " by " in f" {normalized_message} "
            and not mentioned_dimensions
            and grain is None
        ):
            return SemanticPlanHint(
                coverage="partial",
                reason="The requested grouping is not catalogued for this metric.",
                request=None,
            )
        selected_dimensions = list(dict.fromkeys(mentioned_dimensions))
        if grain is not None:
            candidates = [
                dimension
                for dimension in shared_dimensions.values()
                if grain in dimension.granularities
            ]
            if not candidates:
                return SemanticPlanHint(
                    coverage="partial",
                    reason="The requested time grain is not available for this metric.",
                    request=None,
                )
            selected_time_dimension = next(
                (
                    dimension
                    for dimension in candidates
                    if dimension.name in selected_dimensions
                ),
                candidates[0],
            )
            if selected_time_dimension.name not in selected_dimensions:
                selected_dimensions.append(selected_time_dimension.name)

        metric_names = [metric.name for metric in metrics]
        return SemanticPlanHint(
            coverage="full",
            reason="dbt Semantic Layer catalog coverage is complete.",
            request=SemanticQueryRequest(
                metrics=metric_names,
                dimensions=selected_dimensions,
                time_grain=grain,
            ),
        )

    @staticmethod
    def _message_grain(message: str) -> Optional[str]:
        for grain, terms in _TIME_GRAIN_TERMS.items():
            if _contains_phrase(message, terms):
                return grain
        return None

    @staticmethod
    def _shared_dimensions(
        metrics: Sequence[_SemanticMetric],
    ) -> Dict[str, _SemanticDimension]:
        names = [
            name
            for name in metrics[0].dimensions
            if all(name in metric.dimensions for metric in metrics[1:])
        ]

        shared: Dict[str, _SemanticDimension] = {}
        for name in names:
            definitions = [metric.dimensions[name] for metric in metrics]
            dimension_type = definitions[0].dimension_type
            if any(
                definition.dimension_type != dimension_type
                for definition in definitions[1:]
            ):
                continue
            operators = set(definitions[0].operators)
            granularities = set(definitions[0].granularities)
            aliases = set(definitions[0].aliases)
            for definition in definitions[1:]:
                operators &= set(definition.operators)
                granularities &= set(definition.granularities)
                aliases |= set(definition.aliases)
            shared[name] = _SemanticDimension(
                name=name,
                aliases=frozenset(aliases),
                dimension_type=dimension_type,
                operators=frozenset(operators),
                granularities=frozenset(granularities),
            )
        return shared

    async def execute(
        self,
        request: SemanticQueryRequest,
        context: ToolContext,
    ) -> SemanticQueryResult:
        tenant_value = self._tenant_value(context)
        environment_id = await self._environment_id(context)
        catalog = await self._get_catalog(context, environment_id)
        try:
            metrics = [catalog[name] for name in request.metrics]
        except KeyError:
            raise self._error("invalid_semantic_request", context) from None

        shared_dimensions = self._shared_dimensions(metrics)
        self._require_tenant_policy(shared_dimensions, context)

        dimensions = list(request.dimensions)
        if any(name not in shared_dimensions for name in dimensions):
            raise self._error("invalid_semantic_request", context)

        grain = request.time_grain.lower() if request.time_grain else None
        grain_dimension: Optional[str] = None
        if grain is not None:
            candidates = [
                dimension
                for dimension in shared_dimensions.values()
                if grain in dimension.granularities
            ]
            if not candidates:
                raise self._error("invalid_semantic_request", context)
            grain_dimension = next(
                (
                    dimension.name
                    for dimension in candidates
                    if dimension.name in dimensions
                ),
                candidates[0].name,
            )
            if grain_dimension not in dimensions:
                dimensions.append(grain_dimension)

        group_by: List[Dict[str, Any]] = []
        for name in dimensions:
            entry: Dict[str, Any] = {"name": name}
            if name == grain_dimension and grain is not None:
                entry["grain"] = grain.upper()
            group_by.append(entry)

        where = self._build_filters(
            request.filters,
            shared_dimensions,
            context,
        )
        where.append(
            {
                "dimension": {"name": self.tenant_filter_dimension},
                "operator": "EQUALS",
                "value": tenant_value,
            }
        )
        order_by = self._build_order_by(request.order_by, request, dimensions, context)
        limit = request.limit or 100
        variables = {
            "environmentId": environment_id,
            "metrics": [{"name": metric.name} for metric in metrics],
            "groupBy": group_by,
            "where": where,
            "orderBy": order_by,
            "limit": limit,
        }
        data = await self._graphql(
            operation_name="CreateSemanticQuery",
            query=_CREATE_QUERY,
            variables=variables,
            context=context,
        )
        create_query = data.get("createQuery")
        query_id = (
            create_query.get("queryId") if isinstance(create_query, dict) else None
        )
        if (
            not isinstance(query_id, str)
            or not query_id
            or len(query_id) > 256
            or any(ord(character) < 32 for character in query_id)
        ):
            raise self._error("semantic_response_error", context)

        status = await self._poll_query(query_id, context, environment_id)
        rows, pages = await self._fetch_results(
            query_id, limit, context, environment_id
        )
        return SemanticQueryResult(
            rows=rows,
            row_count=len(rows),
            metadata={
                "source": "dbt_semantic_layer",
                "semantic_metrics": [metric.name for metric in metrics],
                "semantic_dimensions": dimensions,
                "query_id": query_id,
                "status": status,
                "result_pages": pages,
                "validation_checks": [
                    "semantic_catalog_allowlist_passed",
                    "semantic_tenant_filter_passed",
                    "typed_graphql_variables_passed",
                ],
            },
        )

    def _build_filters(
        self,
        filters: Mapping[str, Any],
        dimensions: Mapping[str, _SemanticDimension],
        context: ToolContext,
    ) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for name, raw_filter in filters.items():
            if name == self.tenant_filter_dimension:
                raise self._error("semantic_policy_denied", context)
            dimension = dimensions.get(name)
            if dimension is None:
                raise self._error("invalid_semantic_request", context)

            if isinstance(raw_filter, dict):
                if set(raw_filter) != {"operator", "value"}:
                    raise self._error("invalid_semantic_request", context)
                operator = raw_filter.get("operator")
                value = raw_filter.get("value")
            else:
                operator = "equals"
                value = raw_filter
            if not isinstance(operator, str):
                raise self._error("invalid_semantic_request", context)
            normalized_operator = operator.strip().lower()
            if (
                normalized_operator not in _FILTER_OPERATORS
                or normalized_operator not in dimension.operators
            ):
                raise self._error("invalid_semantic_request", context)
            typed_value = self._filter_value(
                value,
                normalized_operator,
                context,
            )
            result.append(
                {
                    "dimension": {"name": name},
                    "operator": _FILTER_OPERATORS[normalized_operator],
                    "value": typed_value,
                }
            )
        return result

    def _require_tenant_policy(
        self,
        dimensions: Mapping[str, _SemanticDimension],
        context: ToolContext,
    ) -> None:
        tenant_dimension = dimensions.get(self.tenant_filter_dimension)
        if tenant_dimension is None or "equals" not in tenant_dimension.operators:
            raise self._error("semantic_policy_denied", context)

    def _filter_value(
        self,
        value: Any,
        operator: str,
        context: ToolContext,
    ) -> Any:
        if isinstance(value, list):
            if operator not in {"in", "not_in"} or not 1 <= len(value) <= 100:
                raise self._error("invalid_semantic_request", context)
            return [self._filter_scalar(item, context) for item in value]
        if operator in {"in", "not_in"}:
            raise self._error("invalid_semantic_request", context)
        return self._filter_scalar(value, context)

    def _filter_scalar(self, value: Any, context: ToolContext) -> Any:
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            raise self._error("invalid_semantic_request", context)
        if isinstance(value, str):
            if len(value) <= 1024 and not any(
                ord(character) < 32 for character in value
            ):
                return value
            raise self._error("invalid_semantic_request", context)
        raise self._error("invalid_semantic_request", context)

    def _build_order_by(
        self,
        value: Optional[str],
        request: SemanticQueryRequest,
        dimensions: Sequence[str],
        context: ToolContext,
    ) -> List[Dict[str, Any]]:
        if value is None:
            return []
        match = _ORDER_BY.fullmatch(value)
        if match is None:
            raise self._error("invalid_semantic_request", context)
        name = match.group("name")
        if name not in {*request.metrics, *dimensions}:
            raise self._error("invalid_semantic_request", context)
        direction = match.group("direction")
        descending = match.group("prefix") == "-" or (
            direction is not None and direction.lower() == "desc"
        )
        return [{"name": name, "descending": descending}]

    async def _poll_query(
        self,
        query_id: str,
        context: ToolContext,
        environment_id: str,
    ) -> str:
        deadline = self.monotonic() + self.query_timeout_seconds
        delay = self.poll_initial_seconds
        for attempt in range(self.max_poll_attempts):
            if self.monotonic() >= deadline:
                raise self._error("semantic_query_timeout", context)
            data = await self._graphql(
                operation_name="GetSemanticQueryStatus",
                query=_QUERY_STATUS,
                variables={
                    "environmentId": environment_id,
                    "queryId": query_id,
                },
                context=context,
            )
            query = data.get("query")
            status_value = query.get("status") if isinstance(query, dict) else None
            if not isinstance(status_value, str):
                raise self._error("semantic_response_error", context)
            status = status_value.strip().lower()
            if status in _SUCCESS_STATUSES:
                return status
            if status in _FAILURE_STATUSES:
                raise self._error("semantic_query_failed", context)
            if status not in _RUNNING_STATUSES:
                raise self._error("semantic_response_error", context)
            if attempt + 1 >= self.max_poll_attempts:
                raise self._error("semantic_query_timeout", context)

            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise self._error("semantic_query_timeout", context)
            await self.sleep(min(delay, remaining))
            delay = min(delay * 2, self.poll_max_seconds)

        raise self._error("semantic_query_timeout", context)

    async def _fetch_results(
        self,
        query_id: str,
        limit: int,
        context: ToolContext,
        environment_id: str,
    ) -> Tuple[List[Dict[str, Any]], int]:
        rows: List[Dict[str, Any]] = []
        after: Optional[str] = None
        pages = 0
        for page_index in range(self.max_result_pages):
            pages = page_index + 1
            remaining = limit - len(rows)
            if remaining <= 0:
                return rows, pages
            data = await self._graphql(
                operation_name="GetSemanticQueryResults",
                query=_QUERY_RESULTS,
                variables={
                    "environmentId": environment_id,
                    "queryId": query_id,
                    "first": min(self.result_page_size, remaining),
                    "after": after,
                },
                context=context,
            )
            connection = data.get("queryResult")
            if not isinstance(connection, dict):
                raise self._error("semantic_response_error", context)
            raw_rows = connection.get("rows")
            if not isinstance(raw_rows, list):
                raise self._error("semantic_response_error", context)
            for raw_row in raw_rows:
                rows.append(self._result_row(raw_row, context))
                if len(rows) >= limit:
                    break
            has_next, cursor = _page_info(connection)
            if not has_next or len(rows) >= limit:
                return rows, pages
            if cursor is None or cursor == after:
                raise self._error("semantic_pagination_error", context)
            after = cursor

        raise self._error("semantic_pagination_error", context)

    def _result_row(
        self,
        value: Any,
        context: ToolContext,
    ) -> Dict[str, Any]:
        if not isinstance(value, dict) or len(value) > 100:
            raise self._error("semantic_response_error", context)
        row: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 512:
                raise self._error("semantic_response_error", context)
            if item is None or isinstance(item, (str, bool, int)):
                row[key] = item
            elif isinstance(item, float) and math.isfinite(item):
                row[key] = item
            else:
                raise self._error("semantic_response_error", context)
        return row
