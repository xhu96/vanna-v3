"""
FastAPI server factory for Vanna Agents.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ...core import Agent
from ..base import ChatHandler
from .routes import register_chat_routes
from .lineage_routes import register_lineage_routes

logger = logging.getLogger(__name__)


class VannaFastAPIServer:
    """FastAPI server factory for Vanna Agents."""

    def __init__(self, agent: Agent, config: Optional[Dict[str, Any]] = None):
        """Initialize FastAPI server.

        Args:
            agent: The agent to serve (must have user_resolver configured)
            config: Optional server configuration
        """
        self.agent = agent
        self.config = config or {}
        self.chat_handler = ChatHandler(agent)

    def create_app(self) -> FastAPI:
        """Create configured FastAPI app.

        Returns:
            Configured FastAPI application
        """
        # Create FastAPI app
        app_config = self.config.get("fastapi", {})
        app = FastAPI(
            title="Vanna Agents API",
            description="API server for Vanna Agents framework",
            version="0.1.0",
            **app_config,
        )

        # Configure CORS if enabled
        cors_config = self.config.get("cors", {})
        if cors_config.get("enabled", True):
            cors_params = {k: v for k, v in cors_config.items() if k != "enabled"}

            # Secure-by-default CORS policy (explicit localhost defaults).
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

        # Optional hook for auth and rate-limit middleware registration.
        for middleware_hook in self.config.get("middleware_hooks", []):
            middleware_hook(app)

        # Add static file serving in dev mode
        dev_mode = self.config.get("dev_mode", False)
        if dev_mode:
            static_folder = self.config.get("static_folder", "static")
            try:
                import os

                if os.path.exists(static_folder):
                    app.mount(
                        "/static", StaticFiles(directory=static_folder), name="static"
                    )
            except Exception:
                pass  # Static files not available

        # Register routes
        register_chat_routes(app, self.chat_handler, self.config)
        register_lineage_routes(app, self.chat_handler)

        # --- Personalization (opt-in) ---
        personalization_config = self.config.get("personalization")
        if personalization_config is not None:
            self._register_personalization_routes(app, personalization_config)

        # --- Skills (opt-in) ---
        skills_config = self.config.get("skills")
        if skills_config is not None:
            self._register_skill_routes(app, skills_config)

        # Add health check
        @app.get("/health")
        async def health_check() -> Dict[str, str]:
            return {"status": "healthy", "service": "vanna"}

        return app

    def _register_personalization_routes(
        self, app: FastAPI, personalization_config: Dict[str, Any]
    ) -> None:
        """Wire personalization routes with config-driven service init."""
        from vanna.personalization.services import (
            ConsentManager,
            GlossaryService,
            ProfileService,
        )
        from vanna.personalization.stores import (
            InMemoryGlossaryStore,
            InMemoryProfileStore,
        )

        from .personalization_routes import register_personalization_routes

        profile_store = personalization_config.get(
            "profile_store", InMemoryProfileStore()
        )
        glossary_store = personalization_config.get(
            "glossary_store", InMemoryGlossaryStore()
        )
        admin_roles = personalization_config.get("admin_roles")

        profile_service = personalization_config.get(
            "profile_service"
        ) or ProfileService(profile_store, admin_roles=admin_roles)
        glossary_service = personalization_config.get(
            "glossary_service"
        ) or GlossaryService(glossary_store, admin_roles=admin_roles)
        consent_manager = personalization_config.get(
            "consent_manager"
        ) or ConsentManager(profile_store)

        register_personalization_routes(
            app,
            profile_service,
            glossary_service,
            consent_manager,
            user_resolver=self.agent.user_resolver,
        )
        logger.info("Personalization routes registered at /api/v1/")

    def _register_skill_routes(
        self, app: FastAPI, skills_config: Dict[str, Any]
    ) -> None:
        """Wire skill routes with config-driven service init."""
        from vanna.skills.approval import ApprovalWorkflow
        from vanna.skills.compiler import SkillCompiler
        from vanna.skills.generator import SkillGenerator
        from vanna.skills.registry import SkillRegistry
        from vanna.skills.stores import InMemorySkillRegistryStore

        from .skill_routes import register_skill_routes

        skill_store = skills_config.get("store", InMemorySkillRegistryStore())
        publish_roles = skills_config.get("publish_roles")

        registry = skills_config.get("registry") or SkillRegistry(
            skill_store, publish_roles=publish_roles
        )
        compiler = skills_config.get("compiler") or SkillCompiler()
        approval_workflow = skills_config.get(
            "approval_workflow"
        ) or ApprovalWorkflow(registry, compiler)
        generator = skills_config.get("generator") or SkillGenerator(
            compiler=compiler
        )

        register_skill_routes(
            app,
            registry,
            compiler,
            approval_workflow,
            generator,
            user_resolver=self.agent.user_resolver,
        )
        logger.info("Skill routes registered at /api/v1/skills/")

    def run(self, **kwargs: Any) -> None:
        """Run the FastAPI server.

        This method automatically detects if running in an async environment
        (Jupyter, Colab, IPython, etc.) and:
        - Uses appropriate async handling for existing event loops
        - Sets up port forwarding if in Google Colab
        - Displays the correct URL for accessing the app

        Args:
            **kwargs: Arguments passed to uvicorn configuration
        """
        import sys
        import asyncio
        import uvicorn

        # Check if we're in an environment with a running event loop FIRST
        in_async_env = False
        try:
            asyncio.get_running_loop()
            in_async_env = True
        except RuntimeError:
            in_async_env = False

        # If in async environment, apply nest_asyncio BEFORE creating the app
        if in_async_env:
            try:
                import nest_asyncio

                nest_asyncio.apply()
            except ImportError:
                raise ImportError(
                    "Required package 'nest_asyncio' is not installed. "
                    "Please install it manually: pip install nest_asyncio"
                )

        # Now create the app after nest_asyncio is applied
        app = self.create_app()

        # Set defaults
        run_kwargs = {"host": "0.0.0.0", "port": 8000, "log_level": "info", **kwargs}

        # Get the port and other config from run_kwargs
        port = run_kwargs.get("port", 8000)
        host = run_kwargs.get("host", "0.0.0.0")
        log_level = run_kwargs.get("log_level", "info")

        # Check if we're specifically in Google Colab for port forwarding
        in_colab = "google.colab" in sys.modules

        if in_colab:
            try:
                from google.colab import output

                output.serve_kernel_port_as_window(port)
                from google.colab.output import eval_js

                print("Your app is running at:")
                print(eval_js(f"google.colab.kernel.proxyPort({port})"))
            except Exception as e:
                print(f"Warning: Could not set up Colab port forwarding: {e}")
                print(f"Your app is running at: http://localhost:{port}")
        else:
            print("Your app is running at:")
            print(f"http://localhost:{port}")

        if in_async_env:
            # In Jupyter/Colab, create config with loop="asyncio" and use asyncio.run()
            # This matches the working pattern from Colab
            config = uvicorn.Config(
                app, host=host, port=port, log_level=log_level, loop="asyncio"
            )
            server = uvicorn.Server(config)
            asyncio.run(server.serve())
        else:
            # Normal execution outside of Jupyter/Colab
            uvicorn.run(app, **run_kwargs)
