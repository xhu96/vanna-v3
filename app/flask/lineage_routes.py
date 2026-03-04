"""
Flask routes for lineage evidence retrieval.
"""

from __future__ import annotations


try:
    from flask import Blueprint, Flask, jsonify, request
except ImportError:
    raise ImportError(
        "Flask is required for lineage routes. "
        "Install with: pip install 'vanna[flask]'"
    )

from app.base import ChatHandler


def register_lineage_routes(
    app: Flask,
    chat_handler: ChatHandler,
) -> None:
    """Register lineage retrieval routes on a Flask app."""

    bp = Blueprint("lineage", __name__, url_prefix="/api/v1/lineage")

    @bp.route("/latest", methods=["GET"])
    def get_latest_lineage():  # type: ignore[no-untyped-def]
        conversation_id = request.args.get("conversation_id")
        if not conversation_id:
            return jsonify({"error": "conversation_id query parameter is required"}), 400

        evidence = chat_handler.get_lineage(conversation_id)
        if evidence is None:
            return jsonify(
                {
                    "lineage": None,
                    "conversation_id": conversation_id,
                    "message": "No lineage evidence available for this conversation",
                }
            )
        return jsonify({"lineage": evidence, "conversation_id": conversation_id})

    @bp.route("/latest/markdown", methods=["GET"])
    def get_latest_lineage_markdown():  # type: ignore[no-untyped-def]
        conversation_id = request.args.get("conversation_id")
        if not conversation_id:
            return jsonify({"error": "conversation_id query parameter is required"}), 400

        markdown = chat_handler.get_lineage_markdown(conversation_id)
        if markdown is None:
            return jsonify(
                {
                    "markdown": "",
                    "conversation_id": conversation_id,
                    "message": "No lineage evidence available for this conversation",
                }
            )
        return jsonify({"markdown": markdown, "conversation_id": conversation_id})

    app.register_blueprint(bp)
