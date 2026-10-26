# Setup and upgrade guide — faculty webcam gate + automatic review

## 1. Extract and create a Python environment

Extract `AttendEase-faculty-webcam-review.zip` and open a terminal inside the extracted `AttendEase-faculty-webcam-review` folder.

Use Python **3.10 or 3.11** for the full InsightFace stack.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If activation is blocked, run `.\.venv\Scripts\python.exe` directly rather than changing system-wide security policy.

Linux/macOS:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

## 2. Install full recognition dependencies

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install "numpy>=1.26,<2" "Cython>=3,<4"
python -m pip install --no-build-isolation -r backend/requirements.txt
```

InsightFace 0.7.3 may need a C/C++ compiler (Microsoft C++ Build Tools on Windows; appropriate compiler/Python development tools on Linux). Use only one OpenCV distribution; these requirements use `opencv-python-headless` because the camera is in the browser, not an OpenCV desktop window.

The full InsightFace/ONNX stack and real model were not installed/validated in this workspace. The supplied deterministic tests do not require them.

## 3. Configure `.env`

Copy `.env.example` to `.env` in the project root (`Copy-Item .env.example .env` on PowerShell, or `cp .env.example .env` on Linux/macOS).

Generate a private secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Replace the example `SECRET_KEY` with that value. Keep `.env` private. Check:

```dotenv
APP_TIMEZONE=Asia/Kolkata
DATABASE_PATH=database/attendance.db
AUTO_APPROVE_ATTENDANCE=1
FACULTY_RECORDS_VERIFICATION_TTL=300
SESSION_COOKIE_SECURE=0
PORT=5000
FLASK_DEBUG=0
```

- A stable `SECRET_KEY` is required across restarts/workers.
- Set secure cookies to `1` only under HTTPS, not local HTTP.
- `AUTO_APPROVE_ATTENDANCE=1` saves new eligible matches as Present / Successful (automatic). Use `0` to keep new matches Present/Pending.
- Records-verification access lasts five minutes by default; enforced range is 30–900 seconds.
- Match threshold/margin are configurable starting points, not calibrated accuracy guarantees.

## 4A. Fresh installation

```bash
python backend/init_db.py
python backend/create_admin.py
```

Create your own strong admin credentials at the prompts. There are no built-in application accounts or enrolled faces in the ZIP.

## 4B. Upgrade your existing installation

1. **Stop the old application.** Make an independent backup of its database.
2. Work with a **copy** of your old `database/attendance.db` inside the new extracted project's `database` folder. Create the folder if needed. Do not copy an active SQLite database without a proper SQLite backup.
3. If reusing an existing `.env`, confirm `DATABASE_PATH` points to this copied database, not an absolute path to your old production database. Do not run the old app and this new app against the same database.
4. Run:

```bash
python backend/init_db.py
```

For the previous schema, initialization writes a backup named similar to `attendance.before-auto-review-20261025T...Z.db`, then migrates the attendance table. Existing students, faculty, embeddings, attendance IDs, and pending/confirmed/rejected states are preserved. Do **not** run a destructive database reset or clear-students script.

Initialization can be repeated. If migration fails, its table swap is rolled back; keep the printed backup and inspect the error. Protect backups because they contain sensitive account and biometric data.

Do not recreate an admin if your existing database already has one. Historical pending rows remain pending; they are not retrospectively auto-approved. Assigned faculty can review them after the new face check.

## 5. Check and load the real model

```bash
python backend/check_setup.py
python backend/check_setup.py --model
```

First-time model loading may download `buffalo_l` and needs internet plus writable model storage, normally `~/.insightface`. Optionally configure `FACE_MODEL_ROOT`. Both detection and recognition modules must load. The running app initializes its own singleton on its first recognition request; a separate check process does not warm another process's memory.

If initialization fails, fix dependencies/model files and restart the server or allow its 60-second retry cooldown. The app returns 503 instead of inventing identities.

## 6. Start the application

```bash
python backend/app.py
```

Open:

- Admin: `http://127.0.0.1:5000/login`
- Faculty: `http://127.0.0.1:5000/faculty/login`

`0.0.0.0` is a bind address, not the browser destination. This Flask development server is not a production deployment.

Camera access requires localhost or HTTPS, browser/OS permission, and an available camera. Plain HTTP LAN addresses generally cannot access `getUserMedia`. `localhost` on a phone means the phone, not your laptop. An embedded preview may block cameras: open the app in a separate tab. The Flask server does not need a physical webcam; the browser supplies frames.

## 7. Verify automatic attendance

1. Admin registers active faculty and students with one clear face each.
2. Assign a dated class or weekly timetable with the same student section, today's campus-local date, and a time range including now.
3. Faculty signs in using the registered face, starts the selected class, and opens its camera (admin can also operate the class scanner).
4. Click Start Attendance once. Show one student at a time.
5. A successful eligible match displays **Present · Review successful (automatic)** and inserts one row with `review_status=auto_approved`, an automatic timestamp, and an audit event.
6. Keep the same face visible: no duplicate attendance or review event should appear.
7. Unknown/no/multiple faces, wrong section, inactive accounts, or an ended/wrong class must not create attendance.

## 8. Verify faculty record access

1. On the faculty dashboard choose **Verify face & view attendance records** (or the camera page's records link).
2. Start Camera and choose **Verify & open records**.
3. The face must match the registered face for the **signed-in faculty account**. Another registered faculty member is refused.
4. On success, only that faculty member's classes are shown; new records display **Present / Successful (automatic)**.
5. Test Lock records: opening the records URL again must require verification.
6. Test access expiry: after five minutes, the viewer returns to verification and direct/filter/review requests are also blocked until a fresh check.
7. If an automatic result is wrong, the verified assigned faculty can Reject it. The decision history is retained; a later scan cannot reverse the rejection.

The admin records page still uses admin authentication and is not subject to this faculty-only step-up gate. Faculty checking verifies identity, not physical liveness or an independent second factor.

## 9. Tests and troubleshooting

```bash
python -m pip install -r backend/requirements-dev.txt
pytest -q
```

The 106 supplied tests use temporary databases and synthetic embeddings. Browser checks used a simulated camera. Neither proves real biometric accuracy or camera permission on your device.

- **401:** expired login or inactive account; sign in again.
- **403 on verification:** wrong/unknown faculty face, inactive/missing enrollment, or stale CSRF token. Use the signed-in faculty's registered face; reload the form if needed.
- **409:** class outside its date/time/status, or enrollment changed during verification.
- **503:** model unavailable; check full dependencies, model cache, and server log.
- **500 after updating code only:** run the new `init_db.py` against a backed-up/correctly copied database; the automatic status requires the schema migration.
- **No camera prompt:** use localhost/HTTPS, select/start a valid class, check OS/browser permissions, and avoid restrictive iframes.

Do not share passwords, cookies, face images, Base64 frames, embeddings, or database backups in public debugging reports.

Before real use, calibrate thresholds on consented genuine/unknown data, add liveness/anti-spoofing and rate limits, secure biometric storage/backups, review model licensing, and deploy with HTTPS and production secrets. Room-wide multi-face capture, automatic absence generation, and a student self-service login are not implemented.
