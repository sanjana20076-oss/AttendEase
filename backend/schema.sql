
--1.ADMIN TABLE

CREATE TABLE IF NOT EXISTS admins (
    admin_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT,

    CHECK (length(trim(username)) BETWEEN 3 AND 100),
    CHECK (length(password_hash) > 0)
);


-- 2. FACULTY
-- Faculty members assigned to class sessions.

CREATE TABLE IF NOT EXISTS faculty (
    faculty_id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT COLLATE NOCASE UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (length(trim(employee_id)) > 0),
    CHECK (length(trim(full_name)) > 0)
);


-- 3. STUDENTS
-- Student records used by the dashboard and attendance system.

CREATE TABLE IF NOT EXISTS students (
    student_id INTEGER PRIMARY KEY,
    roll_number TEXT NOT NULL COLLATE NOCASE UNIQUE,
    full_name TEXT NOT NULL,
    department TEXT NOT NULL,
    section TEXT NOT NULL,
    email TEXT COLLATE NOCASE UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (length(trim(roll_number)) > 0),
    CHECK (length(trim(full_name)) > 0),
    CHECK (length(trim(department)) > 0),
    CHECK (length(trim(section)) > 0)
);


-- 4. CLASS SESSIONS
-- Each session is assigned to one faculty member.

CREATE TABLE IF NOT EXISTS class_sessions (
    session_id INTEGER PRIMARY KEY,
    subject_name TEXT NOT NULL,
    section TEXT NOT NULL,
    session_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    faculty_id INTEGER NOT NULL,
    session_status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (
            session_status IN (
                'scheduled',
                'in_progress',
                'completed',
                'cancelled'
            )
        ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (faculty_id)
        REFERENCES faculty(faculty_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CHECK (length(trim(subject_name)) > 0),
    CHECK (length(trim(section)) > 0),
    CHECK (date(session_date) IS NOT NULL),
    CHECK (time(start_time) IS NOT NULL),
    CHECK (time(end_time) IS NOT NULL),
    CHECK (time(end_time) > time(start_time)),

    UNIQUE (faculty_id, session_date, start_time, section)
);



-- 5. STUDENT ATTENDANCE
-- One attendance record per student per class session.
-- Automatic approval is explicit and never impersonates a faculty reviewer.

CREATE TABLE IF NOT EXISTS student_attendance (
    attendance_id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,

    attendance_status TEXT NOT NULL DEFAULT 'present'
        CHECK (
            attendance_status IN ('present', 'absent', 'late')
        ),

    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            review_status IN ('pending', 'confirmed', 'rejected', 'auto_approved')
        ),

    detected_at TEXT,
    auto_reviewed_at TEXT,
    confirmed_by_faculty_id INTEGER,
    confirmed_at TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (session_id)
        REFERENCES class_sessions(session_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    FOREIGN KEY (student_id)
        REFERENCES students(student_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    FOREIGN KEY (confirmed_by_faculty_id)
        REFERENCES faculty(faculty_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    -- Prevent duplicate records for the same student and session.
    UNIQUE (session_id, student_id),

    -- Automatically approved rows have a system timestamp, not a fake reviewer.
    CHECK (review_status != 'auto_approved' OR auto_reviewed_at IS NOT NULL),

    -- A manual confirmation still requires the real assigned faculty identity.
    CHECK (
        (
            review_status = 'confirmed'
            AND confirmed_by_faculty_id IS NOT NULL
            AND confirmed_at IS NOT NULL
        )
        OR
        (
            review_status != 'confirmed'
            AND confirmed_by_faculty_id IS NULL
            AND confirmed_at IS NULL
        )
    )
);


-- 6. INDEXES
-- Improve common searches and dashboard queries.

CREATE INDEX IF NOT EXISTS idx_students_active
    ON students(is_active);

CREATE INDEX IF NOT EXISTS idx_sessions_date
    ON class_sessions(session_date);

CREATE INDEX IF NOT EXISTS idx_sessions_faculty_date
    ON class_sessions(faculty_id, session_date);

CREATE INDEX IF NOT EXISTS idx_attendance_student
    ON student_attendance(student_id);

CREATE INDEX IF NOT EXISTS idx_attendance_session_review
    ON student_attendance(session_id, review_status);

CREATE INDEX IF NOT EXISTS idx_attendance_created
    ON student_attendance(created_at);
CREATE TABLE IF NOT EXISTS face_embeddings (
    embedding_id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL,
    embedding_data BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),

    FOREIGN KEY (student_id)
        REFERENCES students(student_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    CHECK (length(embedding_data) > 0)
);

CREATE INDEX IF NOT EXISTS idx_face_embeddings_student
    ON face_embeddings(student_id, is_active);

-- 7. FACULTY FACE EMBEDDINGS

CREATE TABLE IF NOT EXISTS faculty_face_embeddings (
    embedding_id INTEGER PRIMARY KEY,
    faculty_id INTEGER NOT NULL,
    embedding_data BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),

    FOREIGN KEY (faculty_id)
        REFERENCES faculty(faculty_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    CHECK (length(embedding_data) > 0)
);

CREATE INDEX IF NOT EXISTS idx_faculty_face_embeddings_faculty
    ON faculty_face_embeddings(faculty_id, is_active);

-- ============================================================
-- WEEKLY TIMETABLE TEMPLATE
-- ============================================================

CREATE TABLE IF NOT EXISTS weekly_timetable (
    timetable_id INTEGER PRIMARY KEY AUTOINCREMENT,

    weekday INTEGER NOT NULL
        CHECK (weekday BETWEEN 0 AND 6),

    subject_name TEXT NOT NULL,
    section TEXT NOT NULL,

    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,

    faculty_id INTEGER NOT NULL,

    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (faculty_id)
        REFERENCES faculty(faculty_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CHECK (length(trim(subject_name)) > 0),
    CHECK (length(trim(section)) > 0),
    CHECK (time(start_time) IS NOT NULL),
    CHECK (time(end_time) IS NOT NULL),
    CHECK (time(end_time) > time(start_time)),

    UNIQUE (weekday, section, start_time)
);

CREATE INDEX IF NOT EXISTS idx_weekly_timetable_faculty
ON weekly_timetable (faculty_id, weekday, is_active);

 


-- End of schema

-- Append-only application audit trail for automatic decisions and faculty actions.
CREATE TABLE IF NOT EXISTS attendance_review_events (
    event_id INTEGER PRIMARY KEY,
    attendance_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('auto_approved', 'confirmed', 'rejected')),
    faculty_id INTEGER,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (attendance_id) REFERENCES student_attendance(attendance_id) ON DELETE CASCADE,
    FOREIGN KEY (faculty_id) REFERENCES faculty(faculty_id) ON DELETE RESTRICT,
    CHECK (
        (action = 'auto_approved' AND faculty_id IS NULL)
        OR (action IN ('confirmed', 'rejected') AND faculty_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_review_events_attendance
    ON attendance_review_events(attendance_id, event_id);
