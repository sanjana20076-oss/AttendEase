from datetime import timedelta
import sqlite3

import pytest

import app as web
import clock
from conftest import post, vector
from face_recognition_service import FaceModelUnavailable


def test_records_direct_url_requires_login(client):
    response = client.get('/faculty/attendance-records')
    assert response.status_code == 302 and response.location.endswith('/faculty/login')


def test_logged_in_faculty_still_needs_webcam(client, login_as, scan, fake_embedding):
    login_as()
    scan()
    response = client.get('/faculty/attendance-records')
    assert response.status_code == 302 and response.location.endswith('/verify')
    assert b'Alice' not in response.data


def test_correct_face_unlocks_own_records_only(client, login_as, unlock_records, scan, fake_embedding, db):
    login_as()
    scan()
    db.execute("INSERT INTO student_attendance(session_id,student_id,detected_at) VALUES(2,2,'test')")
    unlock_records()
    page = client.get('/faculty/attendance-records?faculty_id=2')
    assert page.status_code == 200 and b'Alice' in page.data and b'Bob' not in page.data
    assert b'Successful (automatic)' in page.data
    assert page.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('face_index', [5,9])
def test_other_registered_faculty_or_unknown_face_does_not_unlock(client, login_as, monkeypatch, data_url, face_index):
    login_as()
    monkeypatch.setattr(web,'generate_face_embedding',lambda image: vector(face_index))
    response = post(client,'/faculty/attendance-records/verify',{'face_image':data_url})
    assert response.status_code == 403
    assert b'Face verification failed' in response.data
    assert client.get('/faculty/attendance-records/access-status').json['verified'] is False
    assert client.get('/faculty/attendance-records').status_code == 302


@pytest.mark.parametrize('message', ['No face was detected.','Show only one face at a time.'])
def test_unusable_face_never_unlocks(client, login_as, monkeypatch, data_url, message):
    login_as()
    monkeypatch.setattr(web,'generate_face_embedding',lambda image: message)
    assert post(client,'/faculty/attendance-records/verify',{'face_image':data_url}).status_code == 400
    assert client.get('/faculty/attendance-records/access-status').json['verified'] is False


def test_model_error_fails_closed(client, login_as, monkeypatch, data_url):
    login_as()
    def unavailable(image):
        raise FaceModelUnavailable('Install real model first.')
    monkeypatch.setattr(web,'generate_face_embedding',unavailable)
    response = post(client,'/faculty/attendance-records/verify',{'face_image':data_url})
    assert response.status_code == 503 and b'Install real model first.' in response.data
    assert client.get('/faculty/attendance-records/access-status').json['verified'] is False


def test_bad_image_and_csrf_do_not_unlock(client, login_as):
    login_as()
    assert post(client,'/faculty/attendance-records/verify',{'face_image':'invalid'}).status_code == 400
    assert client.post('/faculty/attendance-records/verify',data={'face_image':'invalid'}).status_code == 403


def test_non_ascii_csrf_token_is_rejected_without_server_error(client, login_as):
    login_as()
    assert client.post('/faculty/attendance-records/verify',data={'csrf_token':'invalid-\u0c85'}).status_code == 403


def test_enrollment_required_even_with_valid_login(client, login_as, db):
    login_as()
    db.execute('UPDATE faculty_face_embeddings SET is_active=0 WHERE faculty_id=1')
    response = client.get('/faculty/attendance-records/verify')
    assert response.status_code == 403 and b'No active faculty face enrollment' in response.data


def test_inactive_faculty_loses_access(client, login_as, unlock_records, db):
    login_as()
    unlock_records()
    db.execute('UPDATE faculty SET is_active=0 WHERE faculty_id=1')
    assert client.get('/faculty/attendance-records/access-status').status_code == 401
    assert client.get('/faculty/attendance-records').status_code == 302


def test_access_expires_and_filters_cannot_bypass(client, login_as, unlock_records, monkeypatch):
    login_as()
    unlock_records()
    assert client.get('/faculty/attendance-records/access-status').json == {'verified':True,'remaining_seconds':300}
    later = clock.local_now() + timedelta(seconds=301)
    monkeypatch.setattr(clock,'local_now',lambda: later)
    assert client.get('/faculty/attendance-records/access-status').json['verified'] is False
    response = client.get('/faculty/attendance-records?date=2026-10-25')
    assert response.status_code == 302 and response.location.endswith('/verify')


def test_access_is_bound_to_faculty_account(client, login_as, unlock_records):
    login_as()
    unlock_records()
    with client.session_transaction() as s:
        s['faculty_id'] = 2  # mimic an account switch without deleting old grant
    assert client.get('/faculty/attendance-records/access-status').json['verified'] is False


@pytest.mark.parametrize('change', ['re_enroll','deactivate'])
def test_changing_face_enrollment_revokes_access(client, login_as, unlock_records, db, change):
    login_as()
    unlock_records()
    if change == 're_enroll':
        db.execute('UPDATE faculty_face_embeddings SET embedding_data=? WHERE faculty_id=1',(vector(12).tobytes(),))
    else:
        db.execute('UPDATE faculty_face_embeddings SET is_active=0 WHERE faculty_id=1')
    assert client.get('/faculty/attendance-records/access-status').json['verified'] is False


def test_gate_page_reopening_requires_a_fresh_face(client, login_as, unlock_records):
    login_as()
    unlock_records()
    page = client.get('/faculty/attendance-records/verify')
    assert page.status_code == 200 and b'Verify your faculty face' in page.data
    assert client.get('/faculty/attendance-records/access-status').json['verified'] is False


def test_lock_and_logout_revoke_access(client, login_as, unlock_records):
    login_as()
    unlock_records()
    assert post(client,'/faculty/attendance-records/lock').status_code == 302
    assert client.get('/faculty/attendance-records/access-status').json['verified'] is False
    unlock_records()
    post(client,'/logout')
    assert client.get('/faculty/attendance-records/access-status').status_code == 401


def test_review_post_requires_verification_too(client, login_as, scan, fake_embedding, db):
    login_as()
    scan()
    response = post(client,'/attendance-records/1/review',{'action':'reject'})
    assert response.status_code == 302 and response.location.endswith('/verify')
    assert db.execute('SELECT review_status FROM student_attendance')[0][0] == 'auto_approved'


def test_automatic_approval_is_truthfully_audited(client, login_as, scan, fake_embedding, db):
    login_as()
    response = scan()
    assert response.json['attendance_status'] == 'present'
    assert response.json['review_status'] == 'auto_approved' and response.json['review_successful'] is True
    row = db.execute('SELECT * FROM student_attendance')[0]
    assert row['confirmed_by_faculty_id'] is None and row['confirmed_at'] is None
    assert row['auto_reviewed_at'] == row['detected_at']
    event = db.execute('SELECT * FROM attendance_review_events')[0]
    assert event['action'] == 'auto_approved' and event['faculty_id'] is None
    scan()
    assert len(db.execute('SELECT * FROM attendance_review_events')) == 1


def test_faculty_can_reject_auto_approval_without_erasing_history(client, login_as, scan, fake_embedding, db, unlock_records):
    login_as()
    scan()
    unlock_records()
    post(client,'/attendance-records/1/review',{'action':'reject'})
    row = db.execute('SELECT * FROM student_attendance')[0]
    assert row['review_status'] == 'rejected' and row['auto_reviewed_at'] is not None
    events = db.execute('SELECT * FROM attendance_review_events ORDER BY event_id')
    assert [(r['action'],r['faculty_id']) for r in events] == [('auto_approved',None),('rejected',1)]
    assert scan().json['attendance_recorded'] is False
    assert len(db.execute('SELECT * FROM attendance_review_events')) == 2


def test_previous_pending_mode_remains_available(app, client, login_as, scan, fake_embedding, db):
    app.config['AUTO_APPROVE_ATTENDANCE'] = False
    login_as()
    result = scan().json
    assert result['review_status'] == 'pending' and result['review_successful'] is False
    row = db.execute('SELECT * FROM student_attendance')[0]
    assert row['auto_reviewed_at'] is None
    assert not db.execute('SELECT * FROM attendance_review_events')


def test_schema_rejects_automatic_approval_without_timestamp(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO student_attendance(session_id,student_id,review_status) VALUES(1,1,'auto_approved')")


def test_schema_still_rejects_fake_manual_confirmation(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO student_attendance(session_id,student_id,review_status,confirmed_at) VALUES(1,1,'confirmed','test')")


def test_admin_flow_unchanged_and_cannot_claim_faculty_grant(client, login_as):
    login_as('admin')
    assert client.get('/attendance-records').status_code == 200
    assert client.get('/faculty/attendance-records/access-status').status_code == 403
    assert client.get('/faculty/attendance-records/verify').status_code == 302


def test_gate_does_not_take_untrusted_return_url(client, login_as, unlock_records, data_url, monkeypatch):
    login_as()
    monkeypatch.setattr(web,'generate_face_embedding',lambda image: vector(4))
    result = post(client,'/faculty/attendance-records/verify?next=https://example.com',{'face_image':data_url})
    assert result.status_code == 302 and result.location == '/faculty/attendance-records'
