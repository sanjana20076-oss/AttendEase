"""Student details and an optional enrollment embedding commit together."""
from database import get_connection
from face_embedding_service import save_embedding


def register_student(roll_number, full_name, department, section, email=None, *, embedding=None):
    connection = get_connection()
    try:
        with connection:
            cursor = connection.execute(
                """INSERT INTO students
                   (roll_number, full_name, department, section, email)
                   VALUES (?, ?, ?, ?, ?)""",
                (roll_number, full_name, department, section.strip().upper(), email),
            )
            student_id = cursor.lastrowid
            if embedding is not None:
                save_embedding(student_id, embedding, connection=connection)
        return student_id
    finally:
        connection.close()
