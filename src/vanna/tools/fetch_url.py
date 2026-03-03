"""Fetch URL tool for retrieving data from web pages and REST APIs."""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Type

import httpx
import pandas as pd
from pydantic import BaseModel, Field

from vanna.capabilities.file_system import FileSystem
from vanna.components import (
    CardComponent,
    ComponentType,
    DataFrameComponent,
    NotificationComponent,
    SimpleLinkComponent,
    SimpleTextComponent,
    UiComponent,
)
from vanna.core.tool import Tool, ToolContext, ToolResult
from vanna.integrations.local import LocalFileSystem

logger = logging.getLogger(__name__)

# Hard ceiling to avoid downloading huge payloads.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB


class FetchUrlToolArgs(BaseModel):
    """Arguments for the fetch_url tool."""

    url: str = Field(
        ...,
        description="The fully-qualified URL to fetch (must start with http:// or https://).",
    )
    method: str = Field(
        default="GET",
        description="HTTP method. Use GET for reading data, POST for sending data to an API.",
    )
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional HTTP headers (e.g. {\"Authorization\": \"Bearer <token>\"}).",
    )
    body: Optional[str] = Field(
        default=None,
        description="Optional request body for POST requests (JSON string or form data).",
    )
    timeout_seconds: float = Field(
        default=30.0,
        description="Request timeout in seconds.",
    )


class FetchUrlTool(Tool[FetchUrlToolArgs]):
    """Fetches data from a URL and returns it for analysis.

    JSON responses containing tabular data (arrays of objects) are
    automatically converted to CSV and saved so that downstream tools
    like ``visualize_data`` can consume them directly.
    """

    def __init__(self, file_system: Optional[FileSystem] = None):
        self.file_system = file_system or LocalFileSystem()

    @property
    def name(self) -> str:
        return "fetch_url"

    @property
    def description(self) -> str:
        return (
            "Fetch data from a URL (web page, REST API, JSON endpoint). "
            "Supports GET and POST with custom headers. "
            "JSON array responses are auto-saved as CSV for visualization."
        )

    def get_args_schema(self) -> Type[FetchUrlToolArgs]:
        return FetchUrlToolArgs

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------
    async def execute(
        self, context: ToolContext, args: FetchUrlToolArgs
    ) -> ToolResult:
        # --- Validate URL scheme ---
        if not args.url.startswith(("http://", "https://")):
            msg = "URL must start with http:// or https://."
            return self._error_result(msg)

        method = args.method.upper()
        if method not in ("GET", "POST"):
            msg = "Only GET and POST methods are supported."
            return self._error_result(msg)

        # --- Make the HTTP request ---
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=args.timeout_seconds,
                max_redirects=5,
            ) as client:
                request_kwargs: Dict[str, Any] = {
                    "url": args.url,
                    "headers": args.headers or {},
                }
                if method == "POST" and args.body is not None:
                    content_type = (request_kwargs["headers"].get("Content-Type") or "").lower()
                    if "json" in content_type or args.body.lstrip().startswith(("{", "[")):
                        request_kwargs["content"] = args.body.encode()
                        request_kwargs["headers"].setdefault("Content-Type", "application/json")
                    else:
                        request_kwargs["content"] = args.body.encode()

                response = await getattr(client, method.lower())(**request_kwargs)

        except httpx.TimeoutException:
            return self._error_result(
                f"Request to {args.url} timed out after {args.timeout_seconds}s."
            )
        except httpx.TooManyRedirects:
            return self._error_result(
                f"Too many redirects following {args.url}."
            )
        except httpx.RequestError as exc:
            return self._error_result(f"Connection error: {exc}")

        # --- Enforce size limit ---
        raw_bytes = response.content
        if len(raw_bytes) > MAX_RESPONSE_BYTES:
            return self._error_result(
                f"Response too large ({len(raw_bytes):,} bytes). "
                f"Maximum allowed is {MAX_RESPONSE_BYTES:,} bytes."
            )

        status_code = response.status_code
        content_type = response.headers.get("content-type", "")
        body_text = response.text

        if status_code >= 400:
            preview = body_text[:2000] if body_text else "(empty body)"
            return self._error_result(
                f"HTTP {status_code} from {args.url}:\n{preview}",
                metadata={"status_code": status_code, "url": str(response.url)},
            )

        # --- Detect and handle JSON with tabular data ---
        if "json" in content_type or self._looks_like_json(body_text):
            try:
                data = json.loads(body_text)
                rows = self._extract_tabular_rows(data)
                if rows:
                    return await self._handle_tabular_json(
                        context, args, rows, status_code, response
                    )
                # Non-tabular JSON — return formatted
                return self._handle_generic_json(
                    args, data, status_code, response
                )
            except json.JSONDecodeError:
                pass  # fall through to plain-text handling

        # --- Plain text / HTML fallback ---
        return self._handle_text(args, body_text, status_code, response)

    # ------------------------------------------------------------------
    # JSON helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _looks_like_json(text: str) -> bool:
        stripped = text.lstrip()
        return stripped.startswith(("{", "["))

    @staticmethod
    def _extract_tabular_rows(data: Any) -> Optional[List[Dict[str, Any]]]:
        """Return a list-of-dicts if *data* looks tabular, else ``None``."""
        # Direct list of objects
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data

        # Object with a key whose value is a list of objects
        # (covers {"rows": [...]}, {"data": [...]}, {"results": [...]}, etc.)
        if isinstance(data, dict):
            for value in data.values():
                if (
                    isinstance(value, list)
                    and value
                    and isinstance(value[0], dict)
                ):
                    return value

        return None

    # ------------------------------------------------------------------
    # Response handlers
    # ------------------------------------------------------------------
    async def _handle_tabular_json(
        self,
        context: ToolContext,
        args: FetchUrlToolArgs,
        rows: List[Dict[str, Any]],
        status_code: int,
        response: httpx.Response,
    ) -> ToolResult:
        df = pd.DataFrame(rows)

        # Save as CSV for downstream tools
        file_id = str(uuid.uuid4())[:8]
        filename = f"fetched_data_{file_id}.csv"
        csv_content = df.to_csv(index=False)
        await self.file_system.write_file(filename, csv_content, context, overwrite=True)

        # Build preview for LLM
        preview = csv_content
        if len(preview) > 1000:
            preview = (
                preview[:1000]
                + "\n(Results truncated. Use visualize_data for full analysis.)"
            )

        result_text = (
            f"Fetched {len(df)} rows with {len(df.columns)} columns from {args.url}\n\n"
            f"{preview}\n\n"
            f"Results saved to file: {filename}\n\n"
            f"**IMPORTANT: FOR VISUALIZE_DATA USE FILENAME: {filename}**"
        )

        dataframe_component = DataFrameComponent.from_records(
            records=rows[:100],
            title=f"Data from {args.url}",
            description=f"HTTP {status_code} — {len(df)} rows, {len(df.columns)} columns",
        )

        return ToolResult(
            success=True,
            result_for_llm=result_text,
            ui_component=UiComponent(
                rich_component=dataframe_component,
                simple_component=SimpleLinkComponent(url=args.url, text=args.url),
            ),
            metadata={
                "status_code": status_code,
                "url": str(response.url),
                "content_type": response.headers.get("content-type", ""),
                "row_count": len(df),
                "columns": df.columns.tolist(),
                "output_file": filename,
            },
        )

    @staticmethod
    def _handle_generic_json(
        args: FetchUrlToolArgs,
        data: Any,
        status_code: int,
        response: httpx.Response,
    ) -> ToolResult:
        formatted = json.dumps(data, indent=2, default=str)
        if len(formatted) > 50_000:
            formatted = formatted[:50_000] + "\n... (truncated)"

        result_text = f"HTTP {status_code} from {args.url}:\n\n```json\n{formatted}\n```"

        return ToolResult(
            success=True,
            result_for_llm=result_text,
            ui_component=UiComponent(
                rich_component=CardComponent(
                    type=ComponentType.CARD,
                    title=f"API Response — {args.url}",
                    subtitle=f"HTTP {status_code}",
                    content=formatted[:3000],
                    status="success",
                    markdown=False,
                ),
                simple_component=SimpleLinkComponent(url=args.url, text=args.url),
            ),
            metadata={
                "status_code": status_code,
                "url": str(response.url),
                "content_type": response.headers.get("content-type", ""),
            },
        )

    @staticmethod
    def _handle_text(
        args: FetchUrlToolArgs,
        body_text: str,
        status_code: int,
        response: httpx.Response,
    ) -> ToolResult:
        truncated = len(body_text) > 50_000
        content = body_text[:50_000] if truncated else body_text
        suffix = " (truncated)" if truncated else ""

        result_text = f"HTTP {status_code} from {args.url}{suffix}:\n\n{content}"

        return ToolResult(
            success=True,
            result_for_llm=result_text,
            ui_component=UiComponent(
                rich_component=CardComponent(
                    type=ComponentType.CARD,
                    title=f"Fetched: {args.url}",
                    subtitle=f"HTTP {status_code}{suffix}",
                    content=content[:3000],
                    status="success",
                    markdown=False,
                ),
                simple_component=SimpleLinkComponent(url=args.url, text=args.url),
            ),
            metadata={
                "status_code": status_code,
                "url": str(response.url),
                "content_type": response.headers.get("content-type", ""),
                "truncated": truncated,
            },
        )

    # ------------------------------------------------------------------
    # Shared error helper
    # ------------------------------------------------------------------
    @staticmethod
    def _error_result(
        message: str, metadata: Optional[Dict[str, Any]] = None
    ) -> ToolResult:
        return ToolResult(
            success=False,
            result_for_llm=message,
            ui_component=UiComponent(
                rich_component=NotificationComponent(
                    type=ComponentType.NOTIFICATION,
                    level="error",
                    message=message,
                ),
                simple_component=SimpleTextComponent(text=message),
            ),
            error=message,
            metadata=metadata or {},
        )
