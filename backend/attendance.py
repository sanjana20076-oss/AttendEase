"""Idempotent Present attendance with explicit, auditable automatic approval."""
from flask import current_app, has_app_context

import clock
from database import get_connection


def mark_attendance(student_id, session_id, *, faculty_id=None):
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        class_session = connection.execute(
            """SELECT cs.* FROM class_sessions cs JOIN faculty f ON f.faculty_id = cs.faculty_id
               WHERE cs.session_id = ? AND f.is_active = 1""", (session_id,)
        ).fetchone()
        now = clock.local_now()
        if (class_session is None or class_session["session_status"] != "in_progress"
                or not clock.session_is_current(class_session, now)):
            return False, "No active class session is available."
        if faculty_id is not None and class_session["faculty_id"] != faculty_id:
            return False, "This class session does not belong to you."
        student = connection.execute(
            """SELECT student_id FROM students WHERE student_id = ? AND is_active = 1
               AND trim(section) = trim(?) COLLATE NOCASE""",
            (student_id, class_session["section"]),
        ).fetchone()
        if student is None:
            return False, "Student is inactive or belongs to another section."
        auto_approve = current_app.config.get("AUTO_APPROVE_ATTENDANCE", True) if has_app_context() else True
        status = "auto_approved" if auto_approve else "pending"
        timestamp = now.isoformat(sep=" ", timespec="seconds")
        cursor = connection.execute(
            """INSERT INTO student_attendance
               (session_id, student_id, attendance_status, review_status, detected_at, auto_reviewed_at)
               VALUES (?, ?, 'present', ?, ?, ?)
               ON CONFLICT(session_id, student_id) DO NOTHING""",
            (session_id, student_id, status, timestamp, timestamp if auto_approve else None),
        )
        if cursor.rowcount == 0:
            existing = connection.execute(
                "SELECT review_status FROM student_attendance WHERE session_id = ? AND student_id = ?",
                (session_id, student_id),
            ).fetchone()
            if existing["review_status"] == "rejected":
                return False, "Attendance was rejected by faculty. A rescan cannot override that review."
            return True, "Attendance already recorded."
        if auto_approve:
            connection.execute(
                """INSERT INTO attendance_review_events(attendance_id, action, faculty_id, occurred_at)
                   VALUES (?, 'auto_approved', NULL, ?)""", (cursor.lastrowid, timestamp),
            )
        connection.commit()
        return True, ("Present saved successfully. Review successful — automatically approved."
                      if auto_approve else "Attendance recorded successfully (pending faculty review).")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
