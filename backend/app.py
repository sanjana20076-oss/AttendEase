"""AttendEase Flask application: enrollment, explicit class selection, and attendance."""
import os
import secrets
import sqlite3
from datetime import date, timedelta
import math

import numpy as np
from flask import (
    Flask, render_template, request, redirect, url_for, session, jsonify, flash,
)
from werkzeug.exceptions import RequestEntityTooLarge

import clock
from attendance import mark_attendance
from auth import verify_password
from database import get_connection
from face_embedding_service import save_faculty_embedding
from face_recognition_service import (
    FaceModelUnavailable, generate_face_embedding, compare_embeddings,
    compare_faculty_embeddings,
)
from image_utils import decode_data_url, decode_image, MAX_IMAGE_BYTES
from session_service import ensure_today_sessions
from records_access import (
    clear_records_access, enrollment_digest, grant_records_access, records_access_expiry,
)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    APP_TIMEZONE=os.environ.get("APP_TIMEZONE", "Asia/Kolkata"),
    FACE_MATCH_THRESHOLD=float(os.environ.get("FACE_MATCH_THRESHOLD", "0.50")),
    FACE_MATCH_MARGIN=float(os.environ.get("FACE_MATCH_MARGIN", "0.05")),
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    MAX_FORM_MEMORY_SIZE=6 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    CSRF_ENABLED=True,
    AUTO_APPROVE_ATTENDANCE=os.environ.get("AUTO_APPROVE_ATTENDANCE", "1") == "1",
    FACULTY_RECORDS_VERIFICATION_TTL=int(os.environ.get("FACULTY_RECORDS_VERIFICATION_TTL", "300")),
)
if not os.environ.get("SECRET_KEY"):
    app.logger.warning("Using a temporary secret. Set SECRET_KEY in .env for stable logins across restarts/workers.")


@app.cli.command("init-db")
def init_db_command():
    from init_db import init_db
    init_db()


def csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


@app.context_processor
def template_helpers():
    return {"csrf_token": csrf_token}


@app.before_request
def protect_csrf():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE") or not app.config["CSRF_ENABLED"]:
        return None
    if request.endpoint == "recognize_face" and not (session.get("faculty_id") or session.get("admin_id")):
        return jsonify(error="Please log in again.", code="unauthorized"), 401
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("_csrf_token", "")
    if not expected or not secrets.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8")):
        if request.endpoint == "recognize_face":
            return jsonify(error="Page token expired. Reload the page and log in again if needed.", code="csrf_failed"), 403
        return "Page token expired or missing. Reload the form and try again.", 403
    return None


@app.after_request
def response_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(RequestEntityTooLarge)
def oversized_request(error):
    if request.endpoint == "recognize_face":
        return jsonify(error="Request is too large. Use a smaller camera frame.", code="image_too_large"), 413
    return "Request is too large. Capture a smaller image (maximum request: 6 MB).", 413


class AttendanceAccessError(Exception):
    def __init__(self, message, status=403, code="forbidden"):
        super().__init__(message)
        self.status = status
        self.code = code


@app.errorhandler(AttendanceAccessError)
def attendance_access_error(error):
    if request.endpoint in ("recognize_face", "active_class_session", "faculty_records_status"):
        return jsonify(error=str(error), code=error.code, active=False), error.status
    if error.status == 401:
        endpoint = "faculty_face_login" if request.path.startswith("/faculty") or request.endpoint == "review_attendance" else "login"
        return redirect(url_for(endpoint))
    flash(str(error), "error")
    return redirect(url_for("dashboard" if session.get("admin_id") else "faculty_dashboard"))


def attendance_actor(connection):
    """Return the owning faculty ID, or None for an active admin. Recheck DB state."""
    if session.get("admin_id"):
        account = connection.execute(
            "SELECT admin_id FROM admins WHERE admin_id = ? AND is_active = 1",
            (session["admin_id"],),
        ).fetchone()
        if account is not None:
            return None
    elif session.get("faculty_id"):
        account = connection.execute(
            "SELECT faculty_id FROM faculty WHERE faculty_id = ? AND is_active = 1",
            (session["faculty_id"],),
        ).fetchone()
        if account is not None:
            return account["faculty_id"]
    session.clear()
    raise AttendanceAccessError("Login expired or account inactive. Please log in again.", 401, "unauthorized")


def faculty_records_identity(connection):
    faculty_id = attendance_actor(connection)
    if faculty_id is None:
        raise AttendanceAccessError("This webcam check is for a signed-in faculty account.")
    return faculty_id


def faculty_records_access_needed(connection, faculty_id):
    if records_access_expiry(connection, faculty_id) is None:
        flash("Verify your registered faculty face before accessing attendance records.", "error")
        return redirect(url_for("faculty_records_verify"))
    return None


def selected_class(connection, session_id, *, running=False, current=False):
    faculty_id = attendance_actor(connection)
    class_session = connection.execute(
        "SELECT * FROM class_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if class_session is None:
        raise AttendanceAccessError("Class session was not found.", 404, "session_not_found")
    if faculty_id is not None and class_session["faculty_id"] != faculty_id:
        raise AttendanceAccessError("This class session does not belong to you.")
    owner = connection.execute(
        "SELECT faculty_id FROM faculty WHERE faculty_id = ? AND is_active = 1",
        (class_session["faculty_id"],),
    ).fetchone()
    if owner is None:
        raise AttendanceAccessError("The assigned faculty account is inactive.")
    if running and class_session["session_status"] != "in_progress":
        message = ("Start this class session before taking attendance."
                   if class_session["session_status"] == "scheduled"
                   else "This class session is closed and cannot accept attendance.")
        raise AttendanceAccessError(message, 409, "session_not_running")
    if current and not clock.session_is_current(class_session):
        raise AttendanceAccessError(
            "This class is outside its scheduled date/time in " + app.config["APP_TIMEZONE"] + ".",
            409, "session_outside_window",
        )
    return class_session


def positive_session_id(value):
    try:
        result = int(value)
        if result <= 0:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise AttendanceAccessError("Select a valid class session first.", 400, "invalid_session_id")


# ============================================================
# MODULE 1: ADMIN LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        connection = get_connection()

        try:
            admin = connection.execute(
                """
                SELECT admin_id, username, password_hash
                FROM admins
                WHERE username = ? AND is_active = 1
                """,
                (username,),
            ).fetchone()
        finally:
            connection.close()

        if admin and verify_password(
            password, admin["password_hash"]
        ):
            session.clear()
            session.permanent = True
            session["admin_id"] = admin["admin_id"]
            session["admin_username"] = admin["username"]

            return redirect(url_for("dashboard"))

        return "Invalid username or password", 401

    return render_template("login.html")


@app.route("/faculty/login", methods=["GET", "POST"])
def faculty_face_login():
    if request.method == "GET":
        return render_template("faculty_login.html")
    try:
        image = decode_data_url(request.form.get("face_image", ""))
        embedding = generate_face_embedding(image)
        if not isinstance(embedding, np.ndarray):
            raise ValueError(str(embedding))
        faculty_id, score = compare_faculty_embeddings(embedding)
    except ValueError as error:
        return render_template("faculty_login.html", error=str(error)), 400
    except FaceModelUnavailable as error:
        return render_template("faculty_login.html", error=str(error)), 503
    except Exception:
        app.logger.exception("Faculty recognition failed")
        return render_template("faculty_login.html", error="Recognition service failed. Check the server log."), 500
    if faculty_id is None:
        return render_template("faculty_login.html", error="Faculty face not recognized. Register the faculty face first and try again."), 401
    connection = get_connection()
    try:
        faculty = connection.execute(
            "SELECT faculty_id, full_name FROM faculty WHERE faculty_id = ? AND is_active = 1",
            (faculty_id,),
        ).fetchone()
    finally:
        connection.close()
    if faculty is None:
        return render_template("faculty_login.html", error="Faculty account is inactive."), 403
    session.clear()
    session.permanent = True
    session["faculty_id"] = faculty["faculty_id"]
    session["faculty_name"] = faculty["full_name"]
    return redirect(url_for("faculty_dashboard"))


# ============================================================
# MODULE 1: ADMIN DASHBOARD
# ============================================================

@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    if "admin_id" not in session:
        return redirect(url_for("login"))
    connection = get_connection()
    try:
        attendance_actor(connection)
        total_students = connection.execute(
            "SELECT COUNT(*) FROM students WHERE is_active = 1"
        ).fetchone()[0]
        faculty_ids = connection.execute("SELECT faculty_id FROM faculty WHERE is_active = 1").fetchall()
        for faculty in faculty_ids:
            ensure_today_sessions(connection, faculty["faculty_id"])
        today = clock.local_now().date().isoformat()
        class_sessions = [dict(row) for row in connection.execute(
            """SELECT cs.*, f.full_name AS faculty_name FROM class_sessions cs
               JOIN faculty f ON f.faculty_id = cs.faculty_id
               WHERE cs.session_date = ? AND f.is_active = 1
               ORDER BY time(cs.start_time), cs.section""", (today,)
        ).fetchall()]
        for row in class_sessions:
            row["within_window"] = clock.session_is_current(row)
    finally:
        connection.close()
    return render_template("dashboard.html", total_students=total_students,
                           class_sessions=class_sessions, today=today,
                           timezone=app.config["APP_TIMEZONE"])


# ============================================================
# MODULE 2 + MODULE 3:
# STUDENT REGISTRATION AND FACE REGISTRATION
# ============================================================

@app.route("/students/add", methods=["GET", "POST"])
def add_student():
    if "admin_id" not in session:
        return redirect(url_for("login"))
    if request.method == "GET":
        return render_template("add_student.html")
    from student_service import register_student
    roll_number = request.form.get("roll_number", "").strip()
    full_name = request.form.get("full_name", "").strip()
    department = request.form.get("department", "").strip()
    section = request.form.get("section", "").strip().upper()
    email = request.form.get("email", "").strip() or None
    if not all([roll_number, full_name, department, section]):
        return "Please fill in all required student fields.", 400
    try:
        image = decode_data_url(request.form.get("face_image", ""))
        # Infer exactly once, before opening a database write transaction.
        embedding = generate_face_embedding(image)
        if not isinstance(embedding, np.ndarray):
            raise ValueError(str(embedding))
        register_student(roll_number, full_name, department, section, email, embedding=embedding)
    except sqlite3.IntegrityError:
        return "Roll number or email already exists, or the student details are invalid.", 400
    except ValueError as error:
        return f"Face registration failed: {error}", 400
    except FaceModelUnavailable as error:
        return str(error), 503
    except Exception:
        app.logger.exception("Student registration failed")
        return "Registration failed. Check the server log.", 500
    flash("Student and face registered successfully!", "success")
    return redirect(url_for("dashboard"))


# ============================================================
# MODULE 2: VIEW ALL STUDENTS
# ============================================================

@app.route("/students")
def students():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    search_query = request.args.get("search", "").strip()

    connection = get_connection()

    try:
        if search_query:
            search_pattern = f"%{search_query}%"

            students_list = connection.execute(
                """
                SELECT
                    student_id,
                    roll_number,
                    full_name,
                    department,
                    section,
                    email,
                    is_active
                FROM students
                WHERE roll_number LIKE ?
                   OR full_name LIKE ?
                ORDER BY full_name ASC
                """,
                (search_pattern, search_pattern),
            ).fetchall()
        else:
            students_list = connection.execute(
                """
                SELECT
                    student_id,
                    roll_number,
                    full_name,
                    department,
                    section,
                    email,
                    is_active
                FROM students
                ORDER BY full_name ASC
                """
            ).fetchall()

    finally:
        connection.close()

    return render_template(
        "students.html",
        students=students_list,
        search_query=search_query,
    )

# ============================================================
# FACULTY: REGISTER FACULTY AND THEIR FACE
# ============================================================

@app.route("/faculty/add", methods=["GET", "POST"])
def add_faculty():
    if "admin_id" not in session:
        return redirect(url_for("login"))
    if request.method == "GET":
        return render_template("add_faculty.html")
    employee_id = request.form.get("employee_id", "").strip()
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip() or None
    if not employee_id or not full_name:
        return "Employee ID and full name are required.", 400
    try:
        image = decode_data_url(request.form.get("face_image", ""))
        embedding = generate_face_embedding(image)
        if not isinstance(embedding, np.ndarray):
            raise ValueError(str(embedding))
        connection = get_connection()
        try:
            with connection:
                cursor = connection.execute(
                    "INSERT INTO faculty (employee_id, full_name, email) VALUES (?, ?, ?)",
                    (employee_id, full_name, email),
                )
                save_faculty_embedding(cursor.lastrowid, embedding, connection=connection)
        finally:
            connection.close()
    except sqlite3.IntegrityError:
        return "Employee ID or email already exists, or faculty details are invalid.", 400
    except ValueError as error:
        return f"Faculty face registration failed: {error}", 400
    except FaceModelUnavailable as error:
        return str(error), 503
    except Exception:
        app.logger.exception("Faculty registration failed")
        return "Faculty registration failed. Check the server log.", 500
    flash("Faculty and face registered successfully!", "success")
    return redirect(url_for("dashboard"))


# ============================================================
# MODULE 2: EDIT STUDENT DETAILS
# ============================================================

@app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
def edit_student(student_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    connection = get_connection()

    try:
        student = connection.execute(
            """
            SELECT student_id, roll_number, full_name,
                   department, section, email, is_active
            FROM students
            WHERE student_id = ?
            """,
            (student_id,),
        ).fetchone()

        if student is None:
            flash("Student not found.", "error")
            return redirect(url_for("students"))

        if request.method == "POST":
            roll_number = request.form.get(
                "roll_number", ""
            ).strip()
            full_name = request.form.get(
                "full_name", ""
            ).strip()
            department = request.form.get(
                "department", ""
            ).strip()
            section = request.form.get(
                "section", ""
            ).strip()
            email = request.form.get("email", "").strip() or None

            if not all([
                roll_number,
                full_name,
                department,
                section,
            ]):
                flash("Please fill in all required fields.", "error")
            else:
                try:
                    connection.execute(
                        """
                        UPDATE students
                        SET roll_number = ?,
                            full_name = ?,
                            department = ?,
                            section = ?,
                            email = ?
                        WHERE student_id = ?
                        """,
                        (
                            roll_number,
                            full_name,
                            department,
                            section,
                            email,
                            student_id,
                        ),
                    )
                    connection.commit()

                    flash("Student details updated successfully.", "success")
                    return redirect(url_for("students"))

                except sqlite3.IntegrityError:
                    connection.rollback()
                    flash(
                        "That roll number or email is already in use.",
                        "error",
                    )

                # Refresh the student data after a failed update.
                student = connection.execute(
                    """
                    SELECT student_id, roll_number, full_name,
                           department, section, email, is_active
                    FROM students
                    WHERE student_id = ?
                    """,
                    (student_id,),
                ).fetchone()

        return render_template(
            "edit_students.html",
            student=student,
        )

    finally:
        connection.close()
        
# ============================================================
# MODULE 2: DEACTIVATE STUDENT
# ============================================================

@app.route(
    "/students/<int:student_id>/deactivate",
    methods=["POST"],
)
def deactivate_student(student_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE students
            SET is_active = 0
            WHERE student_id = ? AND is_active = 1
            """,
            (student_id,),
        )
        connection.commit()

        if cursor.rowcount == 0:
            flash("Student not found or already inactive.", "error")
        else:
            flash("Student deactivated successfully.", "success")

    except Exception:
        connection.rollback()
        app.logger.exception("Student deactivation failed.")
        flash("Could not deactivate the student.", "error")

    finally:
        connection.close()

    return redirect(url_for("students"))



# ============================================================
# MODULE 2: REACTIVATE STUDENT
# ============================================================

@app.route(
    "/students/<int:student_id>/reactivate",
    methods=["POST"],
)
def reactivate_student(student_id):
    if "admin_id" not in session:
        return redirect(url_for("login"))

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE students
            SET is_active = 1
            WHERE student_id = ? AND is_active = 0
            """,
            (student_id,),
        )
        connection.commit()

        if cursor.rowcount == 0:
            flash("Student not found or already active.", "error")
        else:
            flash("Student reactivated successfully.", "success")

    except Exception:
        connection.rollback()
        app.logger.exception("Student reactivation failed.")
        flash("Could not reactivate the student.", "error")

    finally:
        connection.close()

    return redirect(url_for("students"))




# ============================================================
# MODULE 4: FACE RECOGNITION AND AUTOMATIC ATTENDANCE
# ============================================================

@app.route("/recognize-face", methods=["POST"])
def recognize_face():
    connection = get_connection()
    try:
        # Authenticate before parsing the selected ID or running expensive inference.
        actor_faculty_id = attendance_actor(connection)
        session_id = positive_session_id(request.form.get("session_id"))
        selected_class(connection, session_id, running=True, current=True)
    finally:
        connection.close()
    uploaded = request.files.get("frame")
    if uploaded is None:
        return jsonify(error="No camera frame uploaded.", code="invalid_image"), 400
    try:
        image = decode_image(uploaded.read(MAX_IMAGE_BYTES + 1))
    except ValueError as error:
        return jsonify(error=str(error), code="invalid_image"), 400
    try:
        embedding = generate_face_embedding(image)
        if not isinstance(embedding, np.ndarray):
            # Empty frames/multiple faces are expected during continuous scanning.
            return jsonify(student_id=None, similarity=None, message=str(embedding), code="face_not_usable"), 200
        result = compare_embeddings(embedding)
        if isinstance(result, str):
            return jsonify(student_id=None, similarity=None, message=result, code="no_enrollments"), 200
        student_id, similarity = result
        if student_id is None:
            return jsonify(student_id=None, similarity=float(similarity),
                           message="No confident matching student found.", code="unknown_face"), 200
        recorded, message = mark_attendance(int(student_id), session_id, faculty_id=actor_faculty_id)
        connection = get_connection()
        try:
            student = connection.execute(
                "SELECT full_name, roll_number FROM students WHERE student_id = ?", (student_id,)
            ).fetchone()
            attendance = connection.execute(
                "SELECT attendance_status, review_status, auto_reviewed_at FROM student_attendance WHERE session_id = ? AND student_id = ?",
                (session_id, student_id),
            ).fetchone() if recorded else None
        finally:
            connection.close()
        duplicate = recorded and message == "Attendance already recorded."
        return jsonify(
            student_id=int(student_id), similarity=float(similarity),
            student_name=student["full_name"] if student else None,
            roll_number=student["roll_number"] if student else None,
            attendance_recorded=recorded, already_recorded=duplicate,
            attendance_status=attendance["attendance_status"] if attendance else None,
            review_status=attendance["review_status"] if attendance else None,
            review_successful=bool(attendance and attendance["review_status"] in ("auto_approved", "confirmed")),
            attendance_message=message,
            code=("already_recorded" if duplicate else "recorded") if recorded else "attendance_rejected",
        ), 200
    except FaceModelUnavailable as error:
        return jsonify(error=str(error), code="model_unavailable"), 503
    except Exception:
        app.logger.exception("Face recognition failed")
        return jsonify(error="Face recognition failed. Check the server log.", code="recognition_failed"), 500


# ============================================================
# MODULE 1: ADMIN LOGOUT
# ============================================================


@app.route("/logout", methods=["POST"])
def logout():
    is_faculty = "faculty_id" in session

    session.clear()

    if is_faculty:
        return redirect(url_for("faculty_face_login"))

    return redirect(url_for("login"))

# ============================================================
# MODULE 5: ATTENDANCE RECORDS WITH DATE FILTER
# ============================================================



def render_attendance_records(faculty_id=None):
    # Defense in depth: do not let a caller bypass the route's step-up guard.
    records_access_until = None
    if faculty_id is not None:
        guard_connection = get_connection()
        try:
            actual_id = faculty_records_identity(guard_connection)
            if actual_id != faculty_id:
                raise AttendanceAccessError("Records must belong to the verified faculty account.")
            blocked = faculty_records_access_needed(guard_connection, faculty_id)
            if blocked:
                return blocked
            records_access_until = records_access_expiry(guard_connection, faculty_id)
        finally:
            guard_connection.close()
    selected_date = request.args.get("date", "").strip()
    if selected_date:
        try:
            selected_date = date.fromisoformat(selected_date).isoformat()
        except ValueError:
            flash("Invalid date format.", "error")
            selected_date = ""
    connection = get_connection()
    try:
        query = """SELECT sa.*, s.roll_number, s.full_name, s.department,
                          s.section AS section, cs.section AS session_section,
                          cs.subject_name, cs.session_date, cs.start_time, cs.end_time
                   FROM student_attendance sa
                   JOIN students s ON s.student_id = sa.student_id
                   JOIN class_sessions cs ON cs.session_id = sa.session_id
                   WHERE 1 = 1"""
        parameters = []
        if faculty_id is not None:
            query += " AND cs.faculty_id = ?"
            parameters.append(faculty_id)
        if selected_date:
            query += " AND cs.session_date = ?"
            parameters.append(selected_date)
        query += " ORDER BY cs.session_date DESC, time(cs.start_time) DESC, sa.detected_at DESC"
        records = connection.execute(query, parameters).fetchall()
    finally:
        connection.close()
    return render_template(
        "attendance_records.html", records=records, selected_date=selected_date,
        records_endpoint="faculty_attendance_records" if faculty_id is not None else "attendance_records",
        dashboard_endpoint="faculty_dashboard" if faculty_id is not None else "dashboard",
        can_review=faculty_id is not None,
        records_access_ms=(max(0, int((records_access_until - clock.local_now().timestamp()) * 1000))
                           if records_access_until is not None else None),
    )


@app.route("/attendance-records")
def attendance_records():
    if not session.get("admin_id"):
        return redirect(url_for("login"))
    connection = get_connection()
    try:
        attendance_actor(connection)
    finally:
        connection.close()
    return render_attendance_records()


@app.route("/faculty/attendance-records")
def faculty_attendance_records():
    connection = get_connection()
    try:
        faculty_id = faculty_records_identity(connection)
        blocked = faculty_records_access_needed(connection, faculty_id)
        if blocked:
            return blocked
    finally:
        connection.close()
    return render_attendance_records(faculty_id)


@app.route("/faculty/attendance-records/verify", methods=["GET", "POST"])
def faculty_records_verify():
    connection = get_connection()
    try:
        faculty_id = faculty_records_identity(connection)
        faculty = connection.execute("SELECT full_name FROM faculty WHERE faculty_id = ?", (faculty_id,)).fetchone()
        digest_before = enrollment_digest(connection, faculty_id)
    finally:
        connection.close()
    # Deliberately require a fresh check whenever this entry page is opened.
    clear_records_access()
    if digest_before is None:
        return render_template("faculty_records_verify.html", faculty_name=faculty["full_name"],
                               error="No active faculty face enrollment exists. Ask the administrator to register your face."), 403
    if request.method == "GET":
        return render_template("faculty_records_verify.html", faculty_name=faculty["full_name"])
    try:
        image = decode_data_url(request.form.get("face_image", ""))
        embedding = generate_face_embedding(image)
        if not isinstance(embedding, np.ndarray):
            raise ValueError(str(embedding))
        matched_faculty_id, score = compare_faculty_embeddings(embedding)
        if matched_faculty_id != faculty_id:
            return render_template("faculty_records_verify.html", faculty_name=faculty["full_name"],
                                   error="Face verification failed. Use the registered face for your signed-in faculty account."), 403
        connection = get_connection()
        try:
            faculty_records_identity(connection)  # recheck account activity after inference
            digest_after = enrollment_digest(connection, faculty_id)
            if digest_before != digest_after or digest_after is None:
                return render_template("faculty_records_verify.html", faculty_name=faculty["full_name"],
                                       error="Faculty enrollment changed during verification. Please try again."), 409
            grant_records_access(faculty_id, digest_after)
        finally:
            connection.close()
    except ValueError as error:
        return render_template("faculty_records_verify.html", faculty_name=faculty["full_name"], error=str(error)), 400
    except FaceModelUnavailable as error:
        return render_template("faculty_records_verify.html", faculty_name=faculty["full_name"], error=str(error)), 503
    except AttendanceAccessError:
        raise
    except Exception:
        app.logger.exception("Faculty records webcam verification failed")
        return render_template("faculty_records_verify.html", faculty_name=faculty["full_name"],
                               error="Verification service failed. Check the server log and try again."), 500
    flash("Faculty face verified successfully. Your attendance records are unlocked temporarily.", "success")
    return redirect(url_for("faculty_attendance_records"))


@app.route("/faculty/attendance-records/access-status")
def faculty_records_status():
    connection = get_connection()
    try:
        faculty_id = faculty_records_identity(connection)
        expires = records_access_expiry(connection, faculty_id)
        remaining = max(0, math.ceil(expires - clock.local_now().timestamp())) if expires is not None else 0
        return jsonify(verified=expires is not None, remaining_seconds=remaining)
    finally:
        connection.close()


@app.route("/faculty/attendance-records/lock", methods=["POST"])
def faculty_records_lock():
    connection = get_connection()
    try:
        faculty_records_identity(connection)
    finally:
        connection.close()
    clear_records_access()
    flash("Attendance records locked. Verify your face to open them again.", "success")
    return redirect(url_for("faculty_dashboard"))


@app.route("/faculty/dashboard")
def faculty_dashboard():
    if not session.get("faculty_id"):
        return redirect(url_for("faculty_face_login"))
    connection = get_connection()
    try:
        faculty_id = attendance_actor(connection)
        faculty = connection.execute("SELECT full_name FROM faculty WHERE faculty_id = ?", (faculty_id,)).fetchone()
        today = ensure_today_sessions(connection, faculty_id)
        classes = [dict(row) for row in connection.execute(
            "SELECT * FROM class_sessions WHERE faculty_id = ? AND session_date = ? ORDER BY time(start_time)",
            (faculty_id, today),
        ).fetchall()]
        for row in classes:
            row["within_window"] = clock.session_is_current(row)
    finally:
        connection.close()
    return render_template("faculty_dashboard.html", faculty_name=faculty["full_name"],
                           classes=classes, today=today, timezone=app.config["APP_TIMEZONE"])


@app.route("/faculty/create-session", methods=["POST"])
def create_faculty_session():
    # Backward-compatible entry point for old timetable forms.
    if not session.get("faculty_id"):
        return redirect(url_for("faculty_face_login"))
    timetable_id = positive_session_id(request.form.get("timetable_id"))
    connection = get_connection()
    try:
        faculty_id = attendance_actor(connection)
        timetable = connection.execute(
            "SELECT * FROM weekly_timetable WHERE timetable_id = ? AND faculty_id = ? AND is_active = 1 AND weekday = ?",
            (timetable_id, faculty_id, clock.local_now().weekday()),
        ).fetchone()
        if timetable is None:
            raise AttendanceAccessError("This class is not assigned to you today.")
        today = ensure_today_sessions(connection, faculty_id)
        class_session = connection.execute(
            """SELECT session_id FROM class_sessions WHERE faculty_id = ? AND session_date = ?
               AND time(start_time) = time(?) AND trim(section) = trim(?) COLLATE NOCASE""",
            (faculty_id, today, timetable["start_time"], timetable["section"]),
        ).fetchone()
    finally:
        connection.close()
    return start_class_session(class_session["session_id"])


@app.route("/class-sessions/<int:session_id>/start", methods=["POST"])
def start_class_session(session_id):
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        class_session = selected_class(connection, session_id, current=True)
        if class_session["session_status"] not in ("scheduled", "in_progress"):
            raise AttendanceAccessError("Completed/cancelled sessions cannot be restarted.", 409)
        connection.execute("UPDATE class_sessions SET session_status = 'in_progress' WHERE session_id = ?", (session_id,))
        connection.commit()
    finally:
        connection.close()
    session["active_class_session_id"] = session_id  # legacy convenience, never used to choose a global class
    endpoint = "admin_attendance_camera" if session.get("admin_id") else "faculty_attendance_camera"
    return redirect(url_for(endpoint, session_id=session_id))


@app.route("/class-sessions/<int:session_id>/finish", methods=["POST"])
def finish_class_session(session_id):
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        class_session = selected_class(connection, session_id)
        if class_session["session_status"] != "in_progress":
            raise AttendanceAccessError("Only a running session can be finished.", 409)
        connection.execute("UPDATE class_sessions SET session_status = 'completed' WHERE session_id = ?", (session_id,))
        connection.commit()
    finally:
        connection.close()
    if session.get("active_class_session_id") == session_id:
        session.pop("active_class_session_id", None)
    flash("Class finished. Further scans cannot change its attendance.", "success")
    return redirect(url_for("dashboard" if session.get("admin_id") else "faculty_dashboard"))


@app.route("/attendance-camera", endpoint="admin_attendance_camera")
@app.route("/faculty/attendance-camera")
def faculty_attendance_camera():
    connection = get_connection()
    try:
        attendance_actor(connection)
        session_id = positive_session_id(request.args.get("session_id") or session.get("active_class_session_id"))
        class_session = selected_class(connection, session_id, running=True, current=True)
    finally:
        connection.close()
    return render_template(
        "faculty_attendance_camera.html", class_session=class_session,
        dashboard_endpoint="dashboard" if session.get("admin_id") else "faculty_dashboard",
        timezone=app.config["APP_TIMEZONE"],
    )


@app.route("/active-class-session")
def active_class_session():
    connection = get_connection()
    try:
        attendance_actor(connection)
        session_id = positive_session_id(request.args.get("session_id"))
        class_session = selected_class(connection, session_id, running=True, current=True)
        return jsonify(active=True, session_id=class_session["session_id"],
                       subject_name=class_session["subject_name"], section=class_session["section"],
                       end_time=class_session["end_time"], timezone=app.config["APP_TIMEZONE"])
    finally:
        connection.close()


# ============================================================
# MODULE 6: ATTENDANCE REVIEW
# ============================================================

@app.route("/attendance-records/<int:attendance_id>/review", methods=["POST"])
def review_attendance(attendance_id):
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        faculty_id = faculty_records_identity(connection)
        blocked = faculty_records_access_needed(connection, faculty_id)
        if blocked:
            return blocked
        action = request.form.get("action", "").strip().lower()
        if action not in ("confirm", "reject"):
            raise AttendanceAccessError("Invalid review action.", 400)
        now = clock.local_now().isoformat(sep=" ", timespec="seconds")
        allowed = ("pending",) if action == "confirm" else ("pending", "auto_approved")
        placeholders = ",".join("?" for _ in allowed)
        cursor = connection.execute(
            f"""UPDATE student_attendance
                SET review_status = ?, confirmed_by_faculty_id = ?, confirmed_at = ?, updated_at = ?
                WHERE attendance_id = ? AND review_status IN ({placeholders})
                  AND session_id IN (SELECT session_id FROM class_sessions WHERE faculty_id = ?)""",
            ("confirmed" if action == "confirm" else "rejected",
             faculty_id if action == "confirm" else None,
             now if action == "confirm" else None, now, attendance_id, *allowed, faculty_id),
        )
        if cursor.rowcount:
            connection.execute(
                "INSERT INTO attendance_review_events(attendance_id, action, faculty_id, occurred_at) VALUES (?, ?, ?, ?)",
                (attendance_id, "confirmed" if action == "confirm" else "rejected", faculty_id, now),
            )
            flash("Attendance confirmed." if action == "confirm" else "Attendance rejected; automatic approval overridden.", "success")
        else:
            flash("Record not found, not owned by you, or already reviewed.", "error")
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for("faculty_attendance_records"))


@app.route("/class-sessions/add", methods=["GET", "POST"])
def add_class_session():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    connection = get_connection()

    try:
        faculty_list = connection.execute(
            """
            SELECT faculty_id, employee_id, full_name
            FROM faculty
            WHERE is_active = 1
            ORDER BY full_name
            """
        ).fetchall()

        if request.method == "POST":
            subject_name = request.form.get("subject_name", "").strip()
            section = request.form.get("section", "").strip().upper()
            session_date = request.form.get("session_date", "").strip()
            start_time = request.form.get("start_time", "").strip()
            end_time = request.form.get("end_time", "").strip()
            faculty_id = request.form.get("faculty_id", "").strip()

            if not all([
                subject_name, section, session_date,
                start_time, end_time, faculty_id
            ]):
                flash("Please complete all class-session fields.", "error")
                return redirect(url_for("add_class_session"))

            from datetime import date, time

            try:
                if date.fromisoformat(session_date).isoformat() != session_date:
                    raise ValueError

                start_time = clock.normalize_time(start_time)
                end_time = clock.normalize_time(end_time)

                if time.fromisoformat(end_time) <= time.fromisoformat(start_time):
                    raise ValueError

                faculty_id = int(faculty_id)
            except ValueError:
                flash("Please enter a valid date, time, and faculty selection.", "error")
                return redirect(url_for("add_class_session"))

            faculty_exists = connection.execute(
                """
                SELECT faculty_id FROM faculty
                WHERE faculty_id = ? AND is_active = 1
                """,
                (faculty_id,),
            ).fetchone()

            if faculty_exists is None:
                flash("Please select an active faculty member.", "error")
                return redirect(url_for("add_class_session"))

            try:
                connection.execute(
                    """
                    INSERT INTO class_sessions (
                        subject_name, section, session_date,
                        start_time, end_time, faculty_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        subject_name, section, session_date,
                        start_time, end_time, faculty_id
                    ),
                )
                connection.commit()
                flash("Class session assigned successfully.", "success")
                return redirect(url_for("add_class_session"))

            except sqlite3.IntegrityError:
                connection.rollback()
                flash(
                    "This class-session assignment conflicts with an existing session.",
                    "error",
                )

        return render_template(
            "add_class_session.html",
            faculty_list=faculty_list,
        )

    finally:
        connection.close()



@app.route("/weekly-timetable/add", methods=["GET", "POST"])
def add_weekly_timetable():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    connection = get_connection()

    try:
        faculty_list = connection.execute(
            """
            SELECT faculty_id, employee_id, full_name
            FROM faculty
            WHERE is_active = 1
            ORDER BY full_name
            """
        ).fetchall()

        if request.method == "POST":
            weekday = request.form.get("weekday", "").strip()
            subject_name = request.form.get("subject_name", "").strip()
            section = request.form.get("section", "").strip().upper()
            start_time = request.form.get("start_time", "").strip()
            end_time = request.form.get("end_time", "").strip()
            faculty_id = request.form.get("faculty_id", "").strip()

            if not all([
                weekday, subject_name, section,
                start_time, end_time, faculty_id
            ]):
                flash("Please complete all timetable fields.", "error")
                return redirect(url_for("add_weekly_timetable"))

            from datetime import time

            try:
                weekday = int(weekday)
                faculty_id = int(faculty_id)
                start_time = clock.normalize_time(start_time)
                end_time = clock.normalize_time(end_time)
                start = time.fromisoformat(start_time)
                end = time.fromisoformat(end_time)

                if weekday not in range(7) or end <= start:
                    raise ValueError

            except ValueError:
                flash(
                    "Please select a valid weekday, faculty, and time range.",
                    "error",
                )
                return redirect(url_for("add_weekly_timetable"))

            faculty_exists = connection.execute(
                """
                SELECT faculty_id
                FROM faculty
                WHERE faculty_id = ? AND is_active = 1
                """,
                (faculty_id,),
            ).fetchone()

            if faculty_exists is None:
                flash("Please select an active faculty member.", "error")
                return redirect(url_for("add_weekly_timetable"))

            try:
                connection.execute(
                    """
                    INSERT INTO weekly_timetable (
                        weekday, subject_name, section,
                        start_time, end_time, faculty_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        weekday, subject_name, section,
                        start_time, end_time, faculty_id
                    ),
                )
                connection.commit()

                flash(
                    "Weekly timetable entry saved successfully.",
                    "success",
                )
                return redirect(url_for("add_weekly_timetable"))

            except sqlite3.IntegrityError:
                connection.rollback()
                flash(
                    "A timetable entry already exists for this section "
                    "and period on that weekday.",
                    "error",
                )

        # Fetch saved timetable records BEFORE closing the connection.
        timetable_list = connection.execute(
            """
            SELECT
                wt.timetable_id,
                wt.weekday,
                wt.subject_name,
                wt.section,
                wt.start_time,
                wt.end_time,
                wt.faculty_id,
                f.employee_id,
                f.full_name
            FROM weekly_timetable wt
            JOIN faculty f
                ON wt.faculty_id = f.faculty_id
            WHERE wt.is_active = 1
            ORDER BY
                wt.weekday,
                wt.start_time,
                wt.section
            """
        ).fetchall()

        return render_template(
            "add_weekly_timetable.html",
            faculty_list=faculty_list,
            timetable_list=timetable_list,
        )

    finally:
        connection.close()

# ============================================================
# MODULE: ATTENDANCE SUMMARY
# ============================================================

@app.route("/attendance-summary")
def attendance_summary():
    if "admin_id" not in session:
        return redirect(url_for("login"))

    connection = get_connection()

    try:
        summary = connection.execute(
            """
            SELECT
                COUNT(*) AS total_records,
                COALESCE(
                    SUM(
                        CASE
                            WHEN attendance_status = 'present'
                            THEN 1 ELSE 0
                        END
                    ), 0
                ) AS present_records,
                ROUND(
    100.0 * COALESCE(
        SUM(
            CASE
                WHEN attendance_status = 'present'
                THEN 1 ELSE 0
            END
        ), 0
    ) / NULLIF(COUNT(*), 0),
    2
) AS attendance_percentage,
                COALESCE(
                    SUM(
                        CASE
                            WHEN review_status = 'pending'
                            THEN 1 ELSE 0
                        END
                    ), 0
                ) AS pending_reviews,
                COALESCE(
                    SUM(
                        CASE
                            WHEN review_status = 'confirmed'
                            THEN 1 ELSE 0
                        END
                    ), 0
                ) AS confirmed_records,
                COALESCE(
                    SUM(
                        CASE
                            WHEN review_status = 'rejected'
                            THEN 1 ELSE 0
                        END
                    ), 0
                ) AS rejected_records
                , COALESCE(SUM(CASE WHEN review_status = 'auto_approved' THEN 1 ELSE 0 END), 0) AS automatic_records
                , COALESCE(SUM(CASE WHEN review_status IN ('auto_approved', 'confirmed') THEN 1 ELSE 0 END), 0) AS successful_reviews
            FROM student_attendance
            """
        ).fetchone()

    finally:
        connection.close()

    return render_template(
        "attendance_summary.html",
        summary=summary,
    )


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG", "0") == "1")
