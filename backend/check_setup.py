"""Run from the project root: python backend/check_setup.py [--model]."""
import argparse
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="Check dependencies, database schema and optional face-model readiness.")
    parser.add_argument("--model", action="store_true", help="Load/download buffalo_l and verify detector/recognizer initialization (internet needed on first run).")
    args = parser.parse_args()
    print("Python:", sys.version.split()[0])
    if sys.version_info[:2] not in ((3,10),(3,11)):
        print("NOTE: Python 3.10/3.11 is recommended for InsightFace 0.7.3; this Python version was not validated for a full install.")
    ok = True
    for name in ("Flask", "python-dotenv", "numpy", "opencv-python-headless", "insightface", "onnxruntime"):
        try:
            print(f"{name}: {version(name)}")
        except PackageNotFoundError:
            # Some developer environments use opencv-python instead of the headless build.
            if name == "opencv-python-headless":
                try:
                    print("OpenCV:", version("opencv-python"), "(desktop build; install only ONE OpenCV distribution)")
                    continue
                except PackageNotFoundError:
                    pass
            print(name + ": NOT INSTALLED")
            ok = False
    try:
        from database import get_connection, DATABASE_PATH, PROJECT_ROOT
        path = Path(DATABASE_PATH)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        print("Database:", path)
        if not path.exists():
            raise RuntimeError("Database is missing. Run python backend/init_db.py and python backend/create_admin.py.")
        c = get_connection()
        try:
            expected = {"admins","students","faculty","face_embeddings","faculty_face_embeddings",
                        "class_sessions","student_attendance","weekly_timetable","attendance_review_events"}
            actual = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = expected - actual
            if missing:
                raise RuntimeError("Missing tables: " + ", ".join(sorted(missing)) + ". Initialize/migrate your database first.")
            attendance_columns = {row["name"] for row in c.execute("PRAGMA table_info(student_attendance)")}
            if "auto_reviewed_at" not in attendance_columns:
                raise RuntimeError("Attendance schema is outdated. Run python backend/init_db.py to back up and migrate it.")
            for table in ("admins","students","faculty","face_embeddings","faculty_face_embeddings"):
                print(f"Active {table}: {c.execute('SELECT COUNT(*) FROM ' + table + ' WHERE is_active = 1').fetchone()[0]}")
            if c.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Foreign-key violations found. Back up and repair the database.")
        finally:
            c.close()
        from clock import local_now
        now = local_now()
        print("Campus clock:", now.isoformat(), "weekday:", now.weekday(), "(Monday=0)")
    except Exception as error:
        print("Database/clock check FAILED:", error)
        ok = False
    if args.model:
        print("Loading the real buffalo_l model. First run may download model files; do not interrupt.")
        try:
            from face_recognition_service import get_face_model
            model = get_face_model()
            print("Model initialized. Loaded modules:", ", ".join(sorted(model.models)))
            if not {"detection","recognition"}.issubset(model.models):
                raise RuntimeError("Both detection and recognition models must be available.")
        except Exception as error:
            print("Model check FAILED:", error)
            ok = False
    print("Check complete. A device-camera and real enrolled/unknown-face test is still required.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
