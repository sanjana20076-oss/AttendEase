"""One explicit campus clock; do not depend on the server's OS timezone."""
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

from flask import current_app, has_app_context


def local_now():
    timezone = (
        current_app.config["APP_TIMEZONE"]
        if has_app_context()
        else os.environ.get("APP_TIMEZONE", "Asia/Kolkata")
    )
    return datetime.now(ZoneInfo(timezone))


def normalize_time(value):
    """Accept HTML's HH:MM and legacy HH:MM:SS, store HH:MM:SS."""
    parsed = time.fromisoformat(value)
    if parsed.tzinfo is not None or parsed.microsecond:
        raise ValueError("Use a local time without an offset or fractions.")
    return parsed.isoformat(timespec="seconds")


def session_is_current(class_session, now=None):
    now = now or local_now()
    return (
        class_session["session_date"] == now.date().isoformat()
        and time.fromisoformat(class_session["start_time"])
        <= now.time().replace(tzinfo=None)
        < time.fromisoformat(class_session["end_time"])
    )
