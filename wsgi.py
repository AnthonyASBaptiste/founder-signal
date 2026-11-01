"""WSGI entry point for gunicorn (Render deployment).

Creates the Flask app from environment configuration.
"""

from founder_signal.app import create_app
from founder_signal.config import Config

app = create_app(Config.from_env())
