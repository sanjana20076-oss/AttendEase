# AttendEase — faculty webcam verification + automatic attendance review

Updated workspace copy of the Face Recognition Attendance Management System. Original author: **Sanjana**. This version keeps the earlier camera/session fixes and adds the two requested changes. The previous project folder and ZIPs were left unchanged; nothing was pushed to GitHub.

## 1. Webcam verification before faculty attendance records

```text
Faculty face login -> dashboard -> Verify face & view attendance records
    -> webcam must match the active registered face of the SAME faculty account
    -> only that faculty member's assigned-class records open
```

A login alone no longer unlocks the records page. A direct URL, date filter, or review POST cannot bypass the server-side check. Access expires after five minutes by default, can be locked manually, and is invalidated if the faculty face enrollment changes/deactivates or the account becomes inactive. Opening the verification entry page starts a fresh check. The admin records workflow is unchanged.

## 2. Automatic Present and successful review

A confident active-student match in the selected active class automatically saves:

```text
attendance_status = present
review_status = auto_approved
```

The UI shows **Present / Successful (automatic)**. No extra Confirm click is needed for new matches. Automatic approval has its own timestamp and audit event; it does not falsely record a faculty member as having manually reviewed the record. Duplicate scans do not add duplicate attendance or review events. Verified assigned faculty can reject an automatic result; rescanning cannot override that rejection.

## Start here

**[Installation, database upgrade, and real-camera checklist](SETUP_AND_TESTING.md)**  
**[Feature details and changed files](CHANGES_FACULTY_WEBCAM_REVIEW.md)**  
**[Verification results and limitations](TEST_RESULTS.md)**

Recommended full-recognition runtime: a fresh **Python 3.10 or 3.11** virtual environment.

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install "numpy>=1.26,<2" "Cython>=3,<4"
python -m pip install --no-build-isolation -r backend/requirements.txt
```

Then copy `.env.example` to `.env`, replace the secret with a private random value, and run:

```bash
python backend/init_db.py
python backend/create_admin.py
python backend/check_setup.py --model
python backend/app.py
```

Create an admin only for a fresh installation; an existing migrated database preserves its accounts. If updating an earlier installation, stop the old app, use a **copy** of its database in this project, and read the migration instructions before running initialization. The initializer backs up and migrates the previous attendance table without reapproving historical rows.

Open `http://127.0.0.1:5000/login` for admin or `/faculty/login` for faculty. Use localhost or HTTPS and grant browser/OS webcam permission. Register faculty/student faces and assign a class inside the current campus-local time range before scanning.

## Configuration

```dotenv
AUTO_APPROVE_ATTENDANCE=1
FACULTY_RECORDS_VERIFICATION_TTL=300
APP_TIMEZONE=Asia/Kolkata
```

Set `AUTO_APPROVE_ATTENDANCE=0` to retain the earlier Present/Pending workflow. Records access still requires the webcam gate. Verification TTL is constrained to 30–900 seconds. Keep a stable private `SECRET_KEY`; use secure cookies only when serving HTTPS.

## Tests

```bash
python -m pip install -r backend/requirements-dev.txt
pytest -q
```

**106 tests passed**, covering the earlier workflow plus faculty step-up verification, expiry, account/enrollment binding, automatic approval/audit, manual rejection, and safe database migration/rollback. Chromium checks also verified the new flow with a simulated camera and synthetic inference.

**Real hardware camera access, full InsightFace/ONNX installation, real model inference/accuracy, and production deployment were not verified here.** No real credentials, enrolled database, model weights, or biometric photos are included. Tests use temporary synthetic data; the running application has no fake-recognition fallback.

This remains an educational project. A fresh face check is not liveness detection or a second authentication factor. Before real-world use, add anti-spoofing, rate limits, audit/access policies, privacy controls, validated recognition thresholds, and a secure production deployment. Student scanning is one face at a time; automatic absence generation and a student self-service login are not implemented.
