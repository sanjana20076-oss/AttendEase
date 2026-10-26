"""Preserve an existing database while enabling explicit automatic review.

SQLite CHECK constraints cannot be expanded with ALTER COLUMN. Rebuild only
student_attendance in a transaction, keeping IDs/data/indexes/triggers and any
external FK references. Make a SQLite backup first. No old review is reapproved.
"""
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3


def migrate_automatic_review(connection, schema):
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'student_attendance'"
    ).fetchone()
    if row is None:
        return None
    columns = {item["name"] for item in connection.execute("PRAGMA table_info(student_attendance)")}
    if "auto_reviewed_at" in columns and "'auto_approved'" in row["sql"]:
        return None
    if connection.in_transaction:
        raise RuntimeError("Commit pending writes before migrating attendance.")
    match = re.search(r"CREATE TABLE IF NOT EXISTS student_attendance\s*\(.*?\n\);", schema, re.S)
    if not match:
        raise RuntimeError("Latest attendance schema statement was not found.")
    ddl = match.group(0).replace("CREATE TABLE IF NOT EXISTS student_attendance", "CREATE TABLE student_attendance_new", 1)
    backup = None
    dbfile = connection.execute("PRAGMA database_list").fetchone()["file"]
    if dbfile:
        dbpath = Path(dbfile)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = dbpath.with_name(f"{dbpath.stem}.before-auto-review-{stamp}.db")
        destination = sqlite3.connect(backup)
        try:
            connection.backup(destination)
        finally:
            destination.close()
    # Disable FK side effects during the table swap, not data validation.
    # Otherwise DROP TABLE may cascade-delete rows in referencing tables.
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        # Another initializer may have completed while the backup was written.
        latest = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'student_attendance'").fetchone()
        latest_columns = {item["name"] for item in connection.execute("PRAGMA table_info(student_attendance)")}
        if "auto_reviewed_at" in latest_columns and "'auto_approved'" in latest["sql"]:
            connection.rollback()
            return backup
        saved_objects = connection.execute(
            """SELECT sql FROM sqlite_master WHERE tbl_name = 'student_attendance'
               AND type IN ('index', 'trigger') AND sql IS NOT NULL"""
        ).fetchall()
        connection.execute(ddl)
        new_columns = {item["name"] for item in connection.execute("PRAGMA table_info(student_attendance_new)")}
        common = [item["name"] for item in connection.execute("PRAGMA table_info(student_attendance)") if item["name"] in new_columns]
        names = ", ".join('"' + name.replace('"', '""') + '"' for name in common)
        connection.execute(f"INSERT INTO student_attendance_new ({names}) SELECT {names} FROM student_attendance")
        connection.execute("DROP TABLE student_attendance")
        connection.execute("ALTER TABLE student_attendance_new RENAME TO student_attendance")
        for item in saved_objects:
            connection.execute(item["sql"])
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed; migration rolled back. Repair the original database first.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
    return backup
