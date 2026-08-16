"""FastAPI server factory for Vanna Agents."""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ...core import Agent
from ..base import ChatHandler
from ..base.authorization import RequestBoundUserResolver
from ..base.errors import (
    InternalServerError,
    InvalidRequestError,
    PublicServerError,
    public_error_for_status,
    public_error_payload,
)
from ..base.security import (
    DEVELOPMENT,
    security_mode,
    validate_agent_memory,
    validate_conversation_store,
    validate_tool_capabilities,
    validate_cors_configuration,
    validate_development_host,
)
from .routes import register_chat_routes

logger = logging.getLogger(__name__)


class VannaFastAPIServer:
    """FastAPI server factory for Vanna Agents."""

    def __init__(self, agent: Agent, config: Optional[Dict[str, Any]] = None):
        """Initialize a FastAPI server with explicit security configuration."""

        self.agent = agent
        self.config = dict(config or {})
        self.security_mode = security_mode(self.config)
        self.agent.user_resolver = RequestBoundUserResolver.wrap(
            self.agent.user_resolver
        )
        self.chat_handler = ChatHandler(agent)

    def create_app(self) -> FastAPI:
        """Create the configured FastAPI application."""

        validate_conversation_store(self.agent, mode=self.security_mode)
        validate_agent_memory(self.agent, mode=self.security_mode)
        validate_tool_capabilities(self.agent, mode=self.security_mode)

        app_config = self.config.get("fastapi", {})
        app = FastAPI(
            title="Vanna Agents API",
            description="API server for Vanna Agents framework",
            version="0.1.0",
            **app_config,
        )
        self._install_error_handlers(app)

        cors_config = dict(self.config.get("cors", {}))
        validate_cors_configuration(
            cors_config,
            origins_key="allow_origins",
            credentials_key="allow_credentials",
        )
        if cors_config.get("enabled", False):
            cors_params = {
                key: value for key, value in cors_config.items() if key != "enabled"
            }
            cors_params.setdefault(
                "allow_origins",
                [
                    "http://localhost",
                    "http://127.0.0.1",
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                ],
            )
            cors_params.setdefault("allow_credentials", False)
            cors_params.setdefault("allow_methods", ["GET", "POST", "OPTIONS"])
            cors_params.setdefault(
                "allow_headers",
                ["Authorization", "Content-Type", "Accept", "X-Requested-With"],
            )
            app.add_middleware(CORSMiddleware, **cors_params)

        for middleware_hook in self.config.get("middleware_hooks", []):
            middleware_hook(app)

        ui_enabled = bool(self.config.get("enable_default_ui_route", False))
        if ui_enabled:
            static_folder = self.config.get("static_folder", "static")
            if isinstance(static_folder, str) and os.path.isdir(static_folder):
                app.mount(
                    "/static", StaticFiles(directory=static_folder), name="static"
                )

        register_chat_routes(app, self.chat_handler, self.config)

        @app.get("/health")
        async def health_check() -> Dict[str, str]:
            return {"status": "healthy", "service": "vanna"}

        return app

    @staticmethod
    def _install_error_handlers(app: FastAPI) -> None:
        @app.exception_handler(PublicServerError)
        async def public_error_handler(
            request: Request, error: PublicServerError
        ) -> JSONResponse:
            del request
            headers = _retry_headers(error)
            return JSONResponse(
                status_code=error.status_code,
                content=public_error_payload(error),
                headers=headers,
            )

        @app.exception_handler(RequestValidationError)
        async def validation_error_handler(
            request: Request, error: RequestValidationError
        ) -> JSONResponse:
            del request, error
            public_error = InvalidRequestError()
            return JSONResponse(
                status_code=public_error.status_code,
                content=public_error_payload(public_error),
            )

        @app.exception_handler(StarletteHTTPException)
        async def http_error_handler(
            request: Request, error: StarletteHTTPException
        ) -> JSONResponse:
            del request
            public_error = public_error_for_status(error.status_code)
            return JSONResponse(
                status_code=error.status_code,
                content=public_error_payload(public_error),
                headers=error.headers,
            )

        @app.exception_handler(Exception)
        async def unhandled_error_handler(
            request: Request, error: Exception
        ) -> JSONResponse:
            del request, error
            public_error = InternalServerError()
            logger.error(
                "Unhandled FastAPI request error correlation_id=%s",
                public_error.correlation_id,
            )
            return JSONResponse(
                status_code=public_error.status_code,
                content=public_error_payload(public_error),
            )

    def run(self, **kwargs: Any) -> None:
        """Run the FastAPI server through uvicorn."""

        import uvicorn

        default_host = "127.0.0.1" if self.security_mode == DEVELOPMENT else "0.0.0.0"
        run_kwargs = {
            "host": default_host,
            "port": 8000,
            "log_level": "info",
            **kwargs,
        }
        host = str(run_kwargs.get("host", default_host))
        if self.security_mode == DEVELOPMENT:
            validate_development_host(host)

        in_async_env = False
        try:
            asyncio.get_running_loop()
            in_async_env = True
        except RuntimeError:
            pass

        if in_async_env:
            try:
                import nest_asyncio  # type: ignore[import-not-found]

                nest_asyncio.apply()
            except ImportError as exc:
                raise RuntimeError(
                    "Running inside an active event loop requires nest_asyncio; "
                    "install it explicitly before starting the server"
                ) from exc

        app = self.create_app()
        port = int(run_kwargs.get("port", 8000))
        log_level = str(run_kwargs.get("log_level", "info"))

        if "google.colab" in sys.modules:
            try:
                from google.colab import output  # type: ignore[import-not-found]
                from google.colab.output import eval_js  # type: ignore[import-not-found]

                output.serve_kernel_port_as_window(port)
                print("Your app is running at:")
                print(eval_js(f"google.colab.kernel.proxyPort({port})"))
            except Exception:
                print(f"Your app is running at: http://localhost:{port}")
        else:
            print("Your app is running at:")
            print(f"http://{host}:{port}")

        if in_async_env:
            uvicorn_config = uvicorn.Config(
                app, host=host, port=port, log_level=log_level, loop="asyncio"
            )
            server = uvicorn.Server(uvicorn_config)
            asyncio.run(server.serve())
        else:
            uvicorn.run(app, **run_kwargs)


def _retry_headers(error: PublicServerError) -> Optional[Dict[str, str]]:
    if error.retry_after is None:
        return None
    return {"Retry-After": str(error.retry_after)}
