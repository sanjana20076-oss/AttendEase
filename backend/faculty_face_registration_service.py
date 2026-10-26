
import numpy as np

from face_recognition_service import generate_face_embedding
from face_embedding_service import save_faculty_embedding
from database import get_connection


def register_faculty_face(faculty_id, image_input):
    connection = get_connection()

    try:
        faculty = connection.execute(
            """
            SELECT faculty_id
            FROM faculty
            WHERE faculty_id = ? AND is_active = 1
            """,
            (faculty_id,),
        ).fetchone()
    finally:
        connection.close()

    if faculty is None:
        raise ValueError(
            "Faculty member does not exist or is inactive."
        )

    # Generate an embedding from the captured image.
    embedding = generate_face_embedding(image_input)

    if not isinstance(embedding, np.ndarray):
        raise ValueError(str(embedding))

    # Store the embedding as float32 in SQLite.
    save_faculty_embedding(
        faculty_id,
        embedding.astype(np.float32)
    )

    return "Faculty face registered successfully."
