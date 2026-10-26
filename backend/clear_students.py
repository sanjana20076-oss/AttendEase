
import sqlite3
from database import get_connection


def clear_student_data():
    confirmation = input(
        "This will delete ALL student records, face embeddings, "
        "and student attendance. Type DELETE to continue: "
    )

    if confirmation != "DELETE":
        print("Cancelled. No data was deleted.")
        return

    connection = get_connection()

    try:
        connection.execute("PRAGMA foreign_keys = ON")

        # Check foreign-key relationships before deleting anything.
        connection.execute("BEGIN")

        # Attendance must be removed before its referenced students.
        connection.execute("DELETE FROM student_attendance")
        connection.execute("DELETE FROM face_embeddings")
        connection.execute("DELETE FROM students")

        connection.commit()

        print("Student records cleared successfully.")
        print("Face embeddings cleared successfully.")
        print("Student attendance records cleared successfully.")
        print("Admin accounts and faculty records were preserved.")

    except sqlite3.Error as error:
        connection.rollback()
        print("Database error. Changes were rolled back:", error)

    finally:
        connection.close()


if __name__ == "__main__":
    clear_student_data()
