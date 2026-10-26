from pathlib import Path
import sqlite3

import pytest

from migrations import migrate_automatic_review

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (ROOT/'backend/schema.sql').read_text()
LEGACY = (ROOT/'tests/fixtures/legacy_schema.sql').read_text()


def legacy_db(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.executescript(LEGACY)
    c.execute("INSERT INTO faculty(faculty_id,employee_id,full_name) VALUES(1,'F1','Original Faculty')")
    c.executemany('INSERT INTO students(student_id,roll_number,full_name,department,section) VALUES(?,?,?,?,?)',
                  [(i,f'A{i}',f'Student {i}','CSE','A') for i in range(1,4)])
    c.execute("INSERT INTO class_sessions(session_id,subject_name,section,session_date,start_time,end_time,faculty_id) VALUES(1,'Original Class','A','2026-10-25','09:00','10:00',1)")
    c.execute("INSERT INTO student_attendance(attendance_id,session_id,student_id,review_status,detected_at) VALUES(11,1,1,'pending','original pending time')")
    c.execute("INSERT INTO student_attendance(attendance_id,session_id,student_id,review_status,detected_at,confirmed_by_faculty_id,confirmed_at) VALUES(12,1,2,'confirmed','original detected',1,'original reviewed time')")
    c.execute("INSERT INTO student_attendance(attendance_id,session_id,student_id,review_status) VALUES(13,1,3,'rejected')")
    c.commit()
    return c


def test_migration_preserves_data_and_writes_real_backup(tmp_path):
    path = tmp_path/'attendance.db'
    c = legacy_db(path)
    before = [dict(r) for r in c.execute('SELECT * FROM student_attendance ORDER BY attendance_id')]
    backup = migrate_automatic_review(c,SCHEMA)
    assert backup and backup.is_file()
    after = [dict(r) for r in c.execute('SELECT * FROM student_attendance ORDER BY attendance_id')]
    assert [{k:v for k,v in row.items() if k!='auto_reviewed_at'} for row in after] == before
    assert all(row['auto_reviewed_at'] is None for row in after)
    assert c.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert not c.execute('PRAGMA foreign_key_check').fetchall()
    with sqlite3.connect(backup) as original:
        assert len(original.execute('SELECT * FROM student_attendance').fetchall()) == 3
        assert 'auto_reviewed_at' not in {r[1] for r in original.execute('PRAGMA table_info(student_attendance)')}
    c.close()


def test_migration_preserves_indexes_triggers_and_foreign_key_children(tmp_path):
    c = legacy_db(tmp_path/'attendance.db')
    c.execute('CREATE INDEX custom_attendance_index ON student_attendance(detected_at)')
    c.execute('CREATE TABLE notes(note_id INTEGER PRIMARY KEY,attendance_id INTEGER REFERENCES student_attendance(attendance_id) ON DELETE CASCADE)')
    c.execute('INSERT INTO notes VALUES(1,11)')
    c.execute('CREATE TABLE edit_log(attendance_id INTEGER)')
    c.execute('CREATE TRIGGER custom_attendance_trigger AFTER UPDATE ON student_attendance BEGIN INSERT INTO edit_log VALUES(new.attendance_id); END')
    c.commit()
    migrate_automatic_review(c,SCHEMA)
    assert c.execute('SELECT COUNT(*) FROM notes').fetchone()[0] == 1
    assert c.execute("SELECT name FROM sqlite_master WHERE name='custom_attendance_index'").fetchone()
    c.execute("UPDATE student_attendance SET detected_at='changed' WHERE attendance_id=11")
    assert c.execute('SELECT attendance_id FROM edit_log').fetchone()[0] == 11
    c.close()


def test_failed_migration_rolls_back_and_restores_foreign_keys(tmp_path):
    c = legacy_db(tmp_path/'attendance.db')
    impossible_schema = SCHEMA.replace('session_id INTEGER NOT NULL,','session_id INTEGER NOT NULL CHECK (session_id < 0),',1)
    with pytest.raises(sqlite3.IntegrityError):
        migrate_automatic_review(c,impossible_schema)
    assert c.execute('SELECT COUNT(*) FROM student_attendance').fetchone()[0] == 3
    assert 'auto_reviewed_at' not in {r['name'] for r in c.execute('PRAGMA table_info(student_attendance)')}
    assert c.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert not c.execute("SELECT name FROM sqlite_master WHERE name='student_attendance_new'").fetchone()
    c.close()


def test_repeated_initialization_migrates_only_once(app, tmp_path):
    from init_db import init_db
    path = tmp_path/'old.db'
    c = legacy_db(path)
    c.close()
    app.config['DATABASE_PATH'] = path
    with app.app_context():
        init_db()
        init_db()
    assert len(list(tmp_path.glob('old.before-auto-review-*.db'))) == 1
    c = sqlite3.connect(path)
    assert c.execute('PRAGMA user_version').fetchone()[0] == 2
    assert c.execute('SELECT COUNT(*) FROM attendance_review_events').fetchone()[0] == 0
    assert c.execute("SELECT review_status FROM student_attendance WHERE attendance_id=11").fetchone()[0] == 'pending'
    assert c.execute("SELECT review_status FROM student_attendance WHERE attendance_id=12").fetchone()[0] == 'confirmed'
    c.close()


def test_new_schema_is_already_up_to_date(tmp_path):
    c = sqlite3.connect(tmp_path/'new.db')
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    assert migrate_automatic_review(c,SCHEMA) is None
    assert not list(tmp_path.glob('*.before-auto-review-*.db'))
    c.close()


def test_initializer_works_with_a_new_database(app, tmp_path):
    from init_db import init_db
    path = tmp_path/'fresh.db'
    app.config['DATABASE_PATH'] = path
    with app.app_context():
        init_db()
    c = sqlite3.connect(path)
    assert 'auto_reviewed_at' in {r[1] for r in c.execute('PRAGMA table_info(student_attendance)')}
    assert c.execute('SELECT COUNT(*) FROM attendance_review_events').fetchone()[0] == 0
    c.close()
