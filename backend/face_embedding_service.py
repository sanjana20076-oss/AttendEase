"""Store and read float32 InsightFace vectors, never raw enrollment photographs."""
import logging

import numpy as np

from database import get_connection

logger = logging.getLogger(__name__)
EMBEDDING_SIZE = 512


def validate_embedding(embedding):
    vector = np.asarray(embedding, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if (vector.shape != (EMBEDDING_SIZE,) or not np.isfinite(vector).all()
            or not np.isfinite(norm) or norm == 0):
        raise ValueError("Expected a finite, non-zero 512-dimensional face embedding.")
    return vector


def _save(table, key, identity, embedding, connection=None):
    # table/key are internal constants, not user input.
    blob = validate_embedding(embedding).tobytes()
    owned = connection is None
    connection = connection if connection is not None else get_connection()
    try:
        connection.execute(
            f"INSERT INTO {table} ({key}, embedding_data) VALUES (?, ?)",
            (identity, blob),
        )
        if owned:
            connection.commit()
    finally:
        if owned:
            connection.close()


def save_embedding(student_id, embedding, *, connection=None):
    _save("face_embeddings", "student_id", student_id, embedding, connection)


def save_faculty_embedding(faculty_id, embedding, *, connection=None):
    _save("faculty_face_embeddings", "faculty_id", faculty_id, embedding, connection)


def _load(table, people, key):
    connection = get_connection()
    try:
        rows = connection.execute(
            f"""SELECT fe.{key}, fe.embedding_data FROM {table} fe
                JOIN {people} p ON p.{key} = fe.{key}
                WHERE fe.is_active = 1 AND p.is_active = 1"""
        ).fetchall()
        vectors = []
        for row in rows:
            try:
                vector = validate_embedding(np.frombuffer(row["embedding_data"], dtype=np.float32))
            except (ValueError, TypeError):
                logger.warning("Skipping invalid embedding in %s for ID %s", table, row[key])
                continue
            vectors.append((row[key], vector))
        return vectors
    finally:
        connection.close()


def get_face_embedding():
    return _load("face_embeddings", "students", "student_id")


def get_faculty_embeddings():
    return _load("faculty_face_embeddings", "faculty", "faculty_id")
