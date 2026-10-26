import base64
import io
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import app as web
import clock
from auth import hash_password
from database import get_connection


def vector(index=0):
    result = np.zeros(512, dtype=np.float32)
    result[index] = 1
    return result


@pytest.fixture
def app(tmp_path, monkeypatch):
    web.app.config.update(TESTING=True, SECRET_KEY="unit-test-key-only",
                          DATABASE_PATH=tmp_path / "test.db", CSRF_ENABLED=True,
                          APP_TIMEZONE="Asia/Kolkata", FACE_MATCH_THRESHOLD=0.5, FACE_MATCH_MARGIN=0.05,
                          AUTO_APPROVE_ATTENDANCE=True, FACULTY_RECORDS_VERIFICATION_TTL=300)
    monkeypatch.setattr(clock, "local_now", lambda: datetime(2026, 10, 25, 9, 30, tzinfo=ZoneInfo("Asia/Kolkata")))
    with web.app.app_context():
        c = get_connection()
        c.executescript(Path(web.__file__).with_name("schema.sql").read_text())
        c.execute("INSERT INTO admins(username,password_hash) VALUES (?,?)", ("test-admin", hash_password("test-only-password")))
        c.executemany("INSERT INTO faculty(faculty_id,employee_id,full_name,is_active) VALUES (?,?,?,?)",
                      [(1,"F1","Teacher One",1),(2,"F2","Teacher Two",1),(3,"F3","Inactive Teacher",0)])
        c.executemany("INSERT INTO students(student_id,roll_number,full_name,department,section,is_active) VALUES (?,?,?,?,?,?)",
                      [(1,"A001","Alice","CSE","A",1),(2,"B001","Bob","CSE","B",1),
                       (3,"A003","Inactive Student","CSE","A",0),(4,"A004","Charlie","CSE","A",1)])
        c.executemany("INSERT INTO face_embeddings(student_id,embedding_data) VALUES (?,?)",
                      [(1,vector(0).tobytes()),(2,vector(1).tobytes()),(3,vector(2).tobytes()),(4,vector(3).tobytes())])
        c.executemany("INSERT INTO faculty_face_embeddings(faculty_id,embedding_data) VALUES (?,?)",
                      [(1,vector(4).tobytes()),(2,vector(5).tobytes())])
        c.executemany("""INSERT INTO class_sessions
                      (session_id,subject_name,section,session_date,start_time,end_time,faculty_id,session_status)
                      VALUES (?,?,?,?,?,?,?,?)""", [
            (1,"Mathematics","A","2026-10-25","09:00","10:00",1,"in_progress"),
            (2,"Science","B","2026-10-25","09:00","10:00",2,"in_progress"),
            (3,"English","A","2026-10-25","10:00","11:00",1,"scheduled"),
            (4,"Tomorrow","A","2026-10-26","09:00","10:00",1,"in_progress"),
            (5,"Closed","A","2026-10-25","08:00","10:00",1,"completed"),
            (6,"Scheduled Now","C","2026-10-25","09:00","10:00",1,"scheduled"),
        ])
        c.commit()
        c.close()
    yield web.app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login_as(client):
    def login(role="faculty", identity=1):
        with client.session_transaction() as s:
            s.clear()
            s[f"{role}_id"] = identity
            s["faculty_name" if role == "faculty" else "admin_username"] = "Test account"
            s["_csrf_token"] = "test-csrf-token"
        return client
    return login


def post(client, path, data=None, **kwargs):
    with client.session_transaction() as s:
        token = s.get("_csrf_token", "")
    payload = dict(data or {})
    payload["csrf_token"] = token
    return client.post(path, data=payload, **kwargs)


@pytest.fixture
def jpeg():
    ok, encoded = cv2.imencode(".jpg", np.zeros((64,64,3), dtype=np.uint8))
    assert ok
    return encoded.tobytes()


@pytest.fixture
def data_url(jpeg):
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


@pytest.fixture
def scan(client, jpeg):
    def send(session_id=1, content=None):
        return post(client, "/recognize-face", {"session_id": str(session_id),
                    "frame": (io.BytesIO(jpeg if content is None else content), "camera.jpg")})
    return send


@pytest.fixture
def fake_embedding(monkeypatch):
    # Only inference is stubbed. Real matching, auth, validation and SQLite writes run.
    monkeypatch.setattr(web, "generate_face_embedding", lambda image: vector(0))


@pytest.fixture
def db(app):
    class DB:
        def execute(self, sql, params=()):
            with app.app_context():
                c = get_connection()
                try:
                    cursor = c.execute(sql, params)
                    rows = cursor.fetchall()
                    c.commit()
                    return rows
                finally:
                    c.close()
    return DB()


@pytest.fixture
def unlock_records(client, data_url, monkeypatch):
    def unlock(identity=1):
        previous = web.generate_face_embedding
        monkeypatch.setattr(web, "generate_face_embedding", lambda image: vector(identity + 3))
        try:
            response = post(client, "/faculty/attendance-records/verify", {"face_image": data_url})
            assert response.status_code == 302 and response.location.endswith("/faculty/attendance-records")
        finally:
            monkeypatch.setattr(web, "generate_face_embedding", previous)
        return response
    return unlock
