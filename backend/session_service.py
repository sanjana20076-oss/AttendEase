"""Materialize today's recurring classes without starting cameras or classes."""
import clock


def ensure_today_sessions(connection, faculty_id):
    now = clock.local_now()
    today = now.date().isoformat()
    connection.execute("BEGIN IMMEDIATE")
    try:
        timetables = connection.execute(
            """SELECT wt.* FROM weekly_timetable wt
               JOIN faculty f ON f.faculty_id = wt.faculty_id
               WHERE wt.faculty_id = ? AND wt.weekday = ?
                 AND wt.is_active = 1 AND f.is_active = 1""",
            (faculty_id, now.weekday()),
        ).fetchall()
        for timetable in timetables:
            # time() prevents duplicates from legacy '09:00' vs '09:00:00'.
            connection.execute(
                """INSERT INTO class_sessions
                   (subject_name, section, session_date, start_time, end_time,
                    faculty_id, session_status)
                   SELECT ?, ?, ?, ?, ?, ?, 'scheduled'
                   WHERE NOT EXISTS (
                       SELECT 1 FROM class_sessions
                       WHERE faculty_id = ? AND session_date = ?
                         AND time(start_time) = time(?)
                         AND trim(section) = trim(?) COLLATE NOCASE
                   )
                   ON CONFLICT DO NOTHING""",
                (timetable["subject_name"], timetable["section"], today,
                 clock.normalize_time(timetable["start_time"]),
                 clock.normalize_time(timetable["end_time"]), faculty_id,
                 faculty_id, today, timetable["start_time"], timetable["section"]),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return today
