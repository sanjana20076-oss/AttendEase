"""SQLite connections shared by the application, CLI commands, and tests."""
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from flask import current_app, has_app_context

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", PROJECT_ROOT / "database" / "attendance.db"))


def get_connection():
    path = current_app.config.get("DATABASE_PATH", DATABASE_PATH) if has_app_context() else DATABASE_PATH
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection
