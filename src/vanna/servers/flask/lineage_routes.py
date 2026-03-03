"""
Flask routes for lineage evidence retrieval.
"""

from __future__ import annotations

from typing import Any, Dict

try:
    from flask import Blueprint, Flask, jsonify
except ImportError:
    raise ImportError(
        "Flask is required for lineage routes. "
        "Install with: pip install 'vanna[flask]'"
    )

from ..base import ChatHandler


def register_lineage_routes(
    app: Flask,
    chat_handler: ChatHandler,
) -> None:
    """Register lineage retrieval routes on a Flask app."""

    bp = Blueprint("lineage", __name__, url_prefix="/api/v1/lineage")

    @bp.route("/latest", methods=["GET"])
    def get_latest_lineage():  # type: ignore[no-untyped-def]
        evidence = getattr(chat_handler, "_latest_lineage", None)
        if evidence is None:
            return jsonify(
                {"lineage": None, "message": "No lineage evidence available yet"}
            )
        return jsonify({"lineage": evidence})

    @bp.route("/latest/markdown", methods=["GET"])
    def get_latest_lineage_markdown():  # type: ignore[no-untyped-def]
        markdown = getattr(chat_handler, "_latest_lineage_markdown", None)
        if markdown is None:
            return jsonify(
                {"markdown": "", "message": "No lineage evidence available yet"}
            )
        return jsonify({"markdown": markdown})

    app.register_blueprint(bp)
