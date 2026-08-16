"""Flask server factory for Vanna Agents."""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, Optional, Tuple

from flask import Flask, Response, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from ...core import Agent
from ..base import ChatHandler
from ..base.authorization import RequestBoundUserResolver
from ..base.errors import (
    InternalServerError,
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


class VannaFlaskServer:
    """Flask server factory for Vanna Agents."""

    def __init__(self, agent: Agent, config: Optional[Dict[str, Any]] = None):
        """Initialize a Flask server with explicit security configuration."""

        self.agent = agent
        self.config = dict(config or {})
        self.security_mode = security_mode(self.config)
        self.agent.user_resolver = RequestBoundUserResolver.wrap(
            self.agent.user_resolver
        )
        self.chat_handler = ChatHandler(agent)

    def create_app(self) -> Flask:
        """Create the configured Flask application."""

        validate_conversation_store(self.agent, mode=self.security_mode)
        validate_agent_memory(self.agent, mode=self.security_mode)
        validate_tool_capabilities(self.agent, mode=self.security_mode)

        ui_enabled = bool(self.config.get("enable_default_ui_route", False))
        static_folder = None
        if ui_enabled:
            configured_static = self.config.get("static_folder", "static")
            if isinstance(configured_static, str) and os.path.isdir(configured_static):
                static_folder = configured_static

        app = Flask(__name__, static_folder=static_folder, static_url_path="/static")
        app.config.update(self.config.get("flask", {}))
        self._install_error_handlers(app)

        cors_config = dict(self.config.get("cors", {}))
        validate_cors_configuration(
            cors_config,
            origins_key="origins",
            credentials_key="supports_credentials",
        )
        if cors_config.get("enabled", False):
            cors_params = {
                key: value for key, value in cors_config.items() if key != "enabled"
            }
            cors_params.setdefault(
                "origins",
                [
                    "http://localhost",
                    "http://127.0.0.1",
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                ],
            )
            cors_params.setdefault("supports_credentials", False)
            cors_params.setdefault("methods", ["GET", "POST", "OPTIONS"])
            cors_params.setdefault(
                "allow_headers",
                ["Authorization", "Content-Type", "Accept", "X-Requested-With"],
            )
            CORS(app, **cors_params)

        for middleware_hook in self.config.get("middleware_hooks", []):
            middleware_hook(app)

        register_chat_routes(app, self.chat_handler, self.config)

        @app.route("/health")
        def health_check() -> Dict[str, str]:
            return {"status": "healthy", "service": "vanna"}

        return app

    @staticmethod
    def _install_error_handlers(app: Flask) -> None:
        @app.errorhandler(PublicServerError)
        def public_error_handler(error: PublicServerError) -> Tuple[Response, int]:
            response = jsonify(public_error_payload(error))
            if error.retry_after is not None:
                response.headers["Retry-After"] = str(error.retry_after)
            return response, error.status_code

        @app.errorhandler(HTTPException)
        def http_error_handler(error: HTTPException) -> Tuple[Response, int]:
            status_code = error.code or 500
            public_error = public_error_for_status(status_code)
            return jsonify(public_error_payload(public_error)), status_code

        @app.errorhandler(Exception)
        def unhandled_error_handler(error: Exception) -> Tuple[Response, int]:
            del error
            public_error = InternalServerError()
            logger.error(
                "Unhandled Flask request error correlation_id=%s",
                public_error.correlation_id,
            )
            return jsonify(public_error_payload(public_error)), public_error.status_code

    def run(self, **kwargs: Any) -> None:
        """Run the Flask development server."""

        default_host = "127.0.0.1" if self.security_mode == DEVELOPMENT else "0.0.0.0"
        run_kwargs = {"host": default_host, "port": 5000, "debug": False, **kwargs}
        host = str(run_kwargs.get("host", default_host))
        if self.security_mode == DEVELOPMENT:
            validate_development_host(host)

        app = self.create_app()
        port = int(run_kwargs.get("port", 5000))

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

        app.run(**run_kwargs)
