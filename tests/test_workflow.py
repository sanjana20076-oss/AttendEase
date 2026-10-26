import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

import app as web
import clock
from attendance import mark_attendance
from conftest import post, vector
from face_recognition_service import FaceModelUnavailable


def test_admin_password_login(client):
    client.get("/login")
    response = post(client, "/login", {"username":"test-admin", "password":"test-only-password"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Today's classes" in response.data
    assert b'/attendance-records' in response.data


def test_invalid_admin_password(client):
    client.get("/login")
    assert post(client, "/login", {"username":"test-admin", "password":"wrong"}).status_code == 401


def test_student_login_does_not_exist(client):
    assert client.get("/student/login").status_code == 404
    assert b"Students do not log in here" in client.get("/login").data


def test_active_session_requires_authentication(client):
    assert client.get("/active-class-session?session_id=1").status_code == 401


def test_unauthenticated_scan_requires_login(client, jpeg):
    assert client.post("/recognize-face", data={"session_id":"1", "frame":(io.BytesIO(jpeg),"frame.jpg")}).status_code == 401


def test_explicit_session_not_global_latest(client, login_as):
    login_as()
    data = client.get("/active-class-session?session_id=1").json
    assert data["session_id"] == 1 and data["section"] == "A"
    assert client.get("/active-class-session?session_id=2").status_code == 403


@pytest.mark.parametrize("value", ["", "0", "-1", "text"])
def test_invalid_selected_session(client, login_as, value):
    login_as()
    assert client.get("/active-class-session?session_id=" + value).status_code == 400


@pytest.mark.parametrize("session_id,code", [(3,"session_not_running"),(4,"session_outside_window"),(5,"session_not_running"),(999,"session_not_found")])
def test_closed_or_wrong_date_session(client, login_as, session_id, code):
    login_as()
    response = client.get(f"/active-class-session?session_id={session_id}")
    assert response.status_code in (404,409)
    assert response.json["code"] == code


def test_resume_camera_without_cookie_pointer(client, login_as):
    login_as()
    result = client.get("/faculty/attendance-camera?session_id=1")
    assert result.status_code == 200
    assert b'data-session-id="1"' in result.data
    assert b'data-csrf-token="test-csrf-token"' in result.data


def test_inactive_faculty_cannot_scan(client, login_as, scan, fake_embedding):
    login_as(identity=3)
    assert scan().status_code == 401


def test_admin_can_open_exact_camera(client, login_as):
    login_as("admin")
    assert client.get("/attendance-camera?session_id=2").status_code == 200


def test_normal_html_times_are_saved(client, login_as, db):
    login_as("admin")
    post(client,"/class-sessions/add", {"subject_name":"Physics","section":"D","session_date":"2026-10-25",
         "start_time":"12:00", "end_time":"13:00", "faculty_id":"1"})
    row = db.execute("SELECT * FROM class_sessions WHERE subject_name='Physics'")[0]
    assert row["start_time"] == "12:00:00" and row["end_time"] == "13:00:00"
    assert row["session_status"] == "scheduled"


@pytest.mark.parametrize("start,end", [("13:00","12:00"),("09:00","09:00"),("bad","10:00"),("09:00+02:00","10:00+02:00")])
def test_invalid_time_range_not_inserted(client, login_as, db, start, end):
    login_as("admin")
    post(client,"/class-sessions/add", {"subject_name":"Invalid","section":"D","session_date":"2026-10-25",
         "start_time":start,"end_time":end,"faculty_id":"1"})
    assert not db.execute("SELECT * FROM class_sessions WHERE subject_name='Invalid'")


def test_timetable_sessions_generated_once(client, login_as, db):
    login_as("admin")
    post(client,"/weekly-timetable/add", {"weekday":"6","subject_name":"Weekly AI","section":"D",
         "start_time":"12:00","end_time":"13:00","faculty_id":"1"})
    login_as()
    for _ in range(2):
        page = client.get("/faculty/dashboard")
        assert page.status_code == 200
        assert b"Weekly AI" in page.data and b"Mathematics" in page.data
    rows = db.execute("SELECT * FROM class_sessions WHERE subject_name='Weekly AI'")
    assert len(rows) == 1 and rows[0]["session_status"] == "scheduled"


def test_legacy_time_format_does_not_duplicate_manual_session(client, login_as, db):
    db.execute("INSERT INTO weekly_timetable(weekday,subject_name,section,start_time,end_time,faculty_id) VALUES (6,'Mathematics','A','09:00:00','10:00:00',1)")
    login_as()
    client.get("/faculty/dashboard")
    assert len(db.execute("SELECT * FROM class_sessions WHERE subject_name='Mathematics'")) == 1


def test_start_scheduled_class(client, login_as, db):
    login_as()
    response = post(client,"/class-sessions/6/start")
    assert response.status_code == 302 and response.location.endswith("session_id=6")
    assert db.execute("SELECT session_status FROM class_sessions WHERE session_id=6")[0][0] == "in_progress"


def test_other_faculty_cannot_start_class(client, login_as, db):
    login_as(identity=2)
    post(client,"/class-sessions/6/start")
    assert db.execute("SELECT session_status FROM class_sessions WHERE session_id=6")[0][0] == "scheduled"


def test_cannot_start_future_or_completed_class(client, login_as, db):
    login_as()
    post(client,"/class-sessions/3/start")
    post(client,"/class-sessions/5/start")
    assert db.execute("SELECT session_status FROM class_sessions WHERE session_id=3")[0][0] == "scheduled"
    assert db.execute("SELECT session_status FROM class_sessions WHERE session_id=5")[0][0] == "completed"


def test_automatic_attendance_and_duplicate(client, login_as, scan, fake_embedding, db):
    login_as()
    first, second = scan(), scan()
    assert first.status_code == 200 and first.json["code"] == "recorded"
    assert first.json["student_name"] == "Alice"
    assert second.json["code"] == "already_recorded"
    rows = db.execute("SELECT * FROM student_attendance")
    assert len(rows) == 1 and rows[0]["attendance_status"] == "present"
    assert rows[0]["review_status"] == "auto_approved"
    assert first.json["review_successful"] is True
    assert rows[0]["auto_reviewed_at"] is not None
    assert rows[0]["confirmed_by_faculty_id"] is None
    assert len(db.execute("SELECT * FROM attendance_review_events")) == 1
    assert rows[0]["detected_at"].endswith("+05:30")


def test_wrong_section_never_marked(client, login_as, scan, monkeypatch, db):
    login_as()
    monkeypatch.setattr(web,"generate_face_embedding",lambda image: vector(1))
    result=scan()
    assert result.json["code"] == "attendance_rejected"
    assert not db.execute("SELECT * FROM student_attendance")


@pytest.mark.parametrize("index", [2,10])
def test_inactive_or_unknown_face_never_marked(client, login_as, scan, monkeypatch, db, index):
    login_as()
    monkeypatch.setattr(web,"generate_face_embedding",lambda image: vector(index))
    assert scan().json["code"] == "unknown_face"
    assert not db.execute("SELECT * FROM student_attendance")


@pytest.mark.parametrize("message", ["No face was detected.","Show only one face at a time."])
def test_unusable_frame_is_not_a_server_error(client, login_as, scan, monkeypatch, db, message):
    login_as()
    monkeypatch.setattr(web,"generate_face_embedding",lambda image: message)
    response=scan()
    assert response.status_code == 200 and response.json["message"] == message
    assert not db.execute("SELECT * FROM student_attendance")


def test_missing_model_reports_503(client, login_as, scan, monkeypatch, db):
    login_as()
    def unavailable(image):
        raise FaceModelUnavailable("Install the model first.")
    monkeypatch.setattr(web,"generate_face_embedding",unavailable)
    response=scan()
    assert response.status_code == 503 and response.json["code"] == "model_unavailable"
    assert not db.execute("SELECT * FROM student_attendance")


def test_invalid_image(client, login_as, scan):
    login_as()
    assert scan(content=b"not an image").status_code == 400


def test_missing_image(client, login_as):
    login_as()
    assert post(client,"/recognize-face",{"session_id":"1"}).status_code == 400


def test_missing_student_enrollments(client, login_as, scan, fake_embedding, db):
    login_as()
    db.execute("DELETE FROM face_embeddings")
    assert scan().json["code"] == "no_enrollments"


def test_finish_stops_further_attendance(client, login_as, scan, fake_embedding, db):
    login_as()
    post(client,"/class-sessions/1/finish")
    assert db.execute("SELECT session_status FROM class_sessions WHERE session_id=1")[0][0] == "completed"
    assert scan().status_code == 409
    assert not db.execute("SELECT * FROM student_attendance")


def test_session_rechecked_after_slow_inference(client, login_as, scan, monkeypatch, db):
    login_as()
    def finish_during_inference(image):
        db.execute("UPDATE class_sessions SET session_status='completed' WHERE session_id=1")
        return vector()
    monkeypatch.setattr(web,"generate_face_embedding",finish_during_inference)
    assert scan().json["attendance_recorded"] is False
    assert not db.execute("SELECT * FROM student_attendance")


def test_end_time_exclusive(client, login_as, monkeypatch):
    login_as()
    monkeypatch.setattr(clock,"local_now",lambda: datetime(2026,10,25,10,0,tzinfo=ZoneInfo("Asia/Kolkata")))
    assert client.get("/active-class-session?session_id=1").status_code == 409


def test_concurrent_insert_is_idempotent(app, db):
    def mark(_):
        with app.app_context():
            return mark_attendance(1,1,faculty_id=1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(mark,range(4)))
    assert all(result[0] for result in results)
    assert len(db.execute("SELECT * FROM student_attendance")) == 1
    assert sum("already recorded" not in result[1] for result in results) == 1


def test_assigned_faculty_confirms_own_record(app, client, login_as, scan, fake_embedding, db, unlock_records):
    app.config["AUTO_APPROVE_ATTENDANCE"] = False
    login_as()
    scan()
    unlock_records()
    record=db.execute("SELECT * FROM student_attendance")[0]
    response=post(client,f"/attendance-records/{record['attendance_id']}/review",{"action":"confirm"})
    assert response.status_code == 302
    reviewed=db.execute("SELECT * FROM student_attendance")[0]
    assert reviewed["review_status"] == "confirmed" and reviewed["confirmed_by_faculty_id"] == 1


def test_other_faculty_cannot_review_record(client, login_as, scan, fake_embedding, db, unlock_records):
    login_as()
    scan()
    record=db.execute("SELECT * FROM student_attendance")[0]
    login_as(identity=2)
    unlock_records(identity=2)
    post(client,f"/attendance-records/{record['attendance_id']}/review",{"action":"reject"})
    assert db.execute("SELECT review_status FROM student_attendance")[0][0] == "auto_approved"
    assert b"Alice" not in client.get("/faculty/attendance-records").data


def test_admin_does_not_impersonate_faculty_reviewer(client, login_as, scan, fake_embedding, db):
    login_as()
    scan()
    login_as("admin")
    post(client,"/attendance-records/1/review",{"action":"confirm"})
    assert db.execute("SELECT review_status FROM student_attendance")[0][0] == "auto_approved"


def test_attendance_record_and_summary_pages(client, login_as, scan, fake_embedding, unlock_records):
    login_as()
    scan()
    unlock_records()
    records=client.get("/faculty/attendance-records")
    assert records.status_code == 200 and b"Alice" in records.data and b"Successful (automatic)" in records.data
    login_as("admin")
    assert client.get("/attendance-records").status_code == 200
    assert client.get("/attendance-summary").status_code == 200


def test_student_registration_infers_once(client, login_as, monkeypatch, data_url, db):
    login_as("admin")
    calls=[]
    def infer(image):
        calls.append(1)
        return vector(11)
    monkeypatch.setattr(web,"generate_face_embedding",infer)
    response=post(client,"/students/add",{"roll_number":"N001","full_name":"New Student","department":"CSE","section":" a ","face_image":data_url})
    assert response.status_code == 302 and len(calls) == 1
    student=db.execute("SELECT * FROM students WHERE roll_number='N001'")[0]
    assert student["section"] == "A"
    assert len(db.execute("SELECT * FROM face_embeddings WHERE student_id=?",(student["student_id"],))) == 1


def test_student_registration_rolls_back_if_embedding_invalid(client, login_as, monkeypatch, data_url, db):
    login_as("admin")
    monkeypatch.setattr(web,"generate_face_embedding",lambda image: np.zeros(512,dtype=np.float32))
    assert post(client,"/students/add",{"roll_number":"BAD","full_name":"Invalid","department":"CSE","section":"A","face_image":data_url}).status_code == 400
    assert not db.execute("SELECT * FROM students WHERE roll_number='BAD'")


def test_faculty_registration_rolls_back_if_embedding_invalid(client, login_as, monkeypatch, data_url, db):
    login_as("admin")
    monkeypatch.setattr(web,"generate_face_embedding",lambda image: np.zeros(512,dtype=np.float32))
    assert post(client,"/faculty/add",{"employee_id":"BAD","full_name":"Invalid","face_image":data_url}).status_code == 400
    assert not db.execute("SELECT * FROM faculty WHERE employee_id='BAD'")


def test_faculty_face_login(client, monkeypatch, data_url):
    client.get("/faculty/login")
    monkeypatch.setattr(web,"generate_face_embedding",lambda image: vector(4))
    response=post(client,"/faculty/login",{"face_image":data_url},follow_redirects=True)
    assert response.status_code == 200 and b"Teacher One" in response.data


def test_faculty_model_error_shows_retryable_page(client, monkeypatch, data_url):
    client.get("/faculty/login")
    def unavailable(image):
        raise FaceModelUnavailable("Install the model first.")
    monkeypatch.setattr(web,"generate_face_embedding",unavailable)
    response=post(client,"/faculty/login",{"face_image":data_url})
    assert response.status_code == 503 and b"Install the model first." in response.data
    assert b"faculty-login-start" in response.data


def test_csrf_required_on_login_and_camera(client, login_as, jpeg):
    client.get("/login")
    assert client.post("/login",data={"username":"test-admin","password":"test-only-password"}).status_code == 403
    login_as()
    response=client.post("/recognize-face",data={"session_id":"1","frame":(io.BytesIO(jpeg),"frame.jpg")})
    assert response.status_code == 403 and response.json["code"] == "csrf_failed"


def test_oversized_camera_request(client, login_as):
    login_as()
    response=client.post("/recognize-face",data=b"x"*(6*1024*1024+1),
                         content_type="application/octet-stream",headers={"X-CSRF-Token":"test-csrf-token"})
    assert response.status_code == 413 and response.is_json


def test_rejected_record_cannot_be_overridden_by_rescanning(client, login_as, scan, fake_embedding, db, unlock_records):
    login_as()
    scan()
    unlock_records()
    post(client,"/attendance-records/1/review",{"action":"reject"})
    result=scan()
    assert result.json["attendance_recorded"] is False
    assert result.json["code"] == "attendance_rejected"
    assert db.execute("SELECT review_status FROM student_attendance")[0][0] == "rejected"


def test_inactive_class_owner_prevents_admin_scan(client, login_as, scan, fake_embedding, db):
    login_as("admin")
    db.execute("UPDATE faculty SET is_active=0 WHERE faculty_id=1")
    assert scan().status_code == 403
    assert not db.execute("SELECT * FROM student_attendance")


def test_database_initializer_can_run_repeatedly(app, db):
    from init_db import init_db
    with app.app_context():
        init_db()
        init_db()
    assert len(db.execute("SELECT * FROM students")) == 4
