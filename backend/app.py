"""Flask app factory for the simulated factory test station API."""

from __future__ import annotations

from flask import Flask

from backend.api import routes


def create_app() -> Flask:
    """Build a Flask app with an empty in-memory unit store."""
    app = Flask(__name__)
    app.json.sort_keys = False  # type: ignore[attr-defined]
    routes.register(app)
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
