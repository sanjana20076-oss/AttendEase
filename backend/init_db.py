"""Initialize fresh tables or safely migrate the previous attendance schema."""
from pathlib import Path

from database import get_connection
from migrations import migrate_automatic_review

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def init_db():
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = get_connection()
    try:
        backup = migrate_automatic_review(connection, schema)
        connection.executescript(schema)
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    finally:
        connection.close()
    if backup:
        print("Previous database backed up to:", backup)
    print("Database initialized successfully (automatic-review schema v2).")


if __name__ == "__main__":
    init_db()
