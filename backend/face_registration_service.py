
import numpy as np

from face_recognition_service import generate_face_embedding
from face_embedding_service import save_embedding
from database import get_connection


def register_student_face(student_id, image_input):
    connection = get_connection()

    try:
        student = connection.execute(
            """
            SELECT student_id
            FROM students
            WHERE student_id = ? AND is_active = 1
            """,
            (student_id,),
        ).fetchone()
    finally:
        connection.close()

    if student is None:
        raise ValueError("Student does not exist or is inactive.")

    # Generate an embedding from the uploaded image.
    embedding = generate_face_embedding(image_input)

    if not isinstance(embedding, np.ndarray):
        raise ValueError(str(embedding))

    # Store the embedding as float32 in the database.
    save_embedding(student_id, embedding.astype(np.float32))

    return "Face registered successfully."
