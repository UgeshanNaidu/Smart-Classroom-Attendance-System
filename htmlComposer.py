"""HTML rendering now uses Flask/Jinja templates instead of custom comment tags.
Retained as a small compatibility entrypoint for the original project module.
"""

from flask import render_template


def compose():
    """Render the application shell inside a Flask request context."""
    return render_template("index.html")
