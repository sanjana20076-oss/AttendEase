"""Lazy, process-local InsightFace model and conservative cosine matching.

No mock recognition or fallback identity is used in the running application.
A missing/unloadable model fails explicitly instead of marking attendance.
"""
import logging
import os
import threading
import time

import cv2
import numpy as np
from flask import current_app, has_app_context

from face_embedding_service import get_face_embedding, get_faculty_embeddings, validate_embedding

logger = logging.getLogger(__name__)
_model = None
_model_lock = threading.Lock()
_inference_lock = threading.Lock()
_model_failure = None
_retry_after = 0.0


class FaceModelUnavailable(RuntimeError):
    pass


def get_face_model():
    global _model, _model_failure, _retry_after
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        if _model_failure is not None and time.monotonic() < _retry_after:
            raise FaceModelUnavailable(_model_failure)
        try:
            # Keep this import lazy: admin pages and tests do not need ONNX.
            from insightface.app import FaceAnalysis
            model = FaceAnalysis(
                name="buffalo_l",
                root=os.path.expanduser(os.environ.get("FACE_MODEL_ROOT", "~/.insightface")),
                allowed_modules=["detection", "recognition"],
                providers=["CPUExecutionProvider"],
            )
            model.prepare(ctx_id=-1, det_size=(640, 640))
            _model = model
            _model_failure = None
        except Exception as error:
            logger.exception("InsightFace initialization failed")
            _model_failure = (
                "Face model unavailable. Install backend/requirements.txt using Python 3.10/3.11, "
                "then run python backend/check_setup.py --model. Check model downloads and the server log."
            )
            _retry_after = time.monotonic() + 60
            raise FaceModelUnavailable(_model_failure) from error
    return _model


def generate_face_embedding(image_input):
    image = cv2.imread(image_input) if isinstance(image_input, str) else image_input
    if not isinstance(image, np.ndarray) or image.size == 0:
        return "Image loading failed."
    model = get_face_model()
    # Avoid concurrent access to the same native inference sessions.
    with _inference_lock:
        faces = model.get(image)
    if not faces:
        return "No face was detected. Face the camera in good lighting."
    if len(faces) != 1:
        return "Show only one face at a time."
    try:
        return validate_embedding(faces[0].embedding)
    except ValueError:
        return "The face embedding was invalid. Capture the face again."


def _setting(name, default):
    if has_app_context():
        return float(current_app.config.get(name, default))
    return float(os.environ.get(name, default))


def _best_match(embedding, saved_embeddings):
    try:
        vector = validate_embedding(embedding)
    except ValueError:
        return None, -1.0
    vector = vector / np.linalg.norm(vector)
    # Compare runners-up by identity, not by enrollment photo of the same person.
    scores = {}
    for identity, saved in saved_embeddings:
        try:
            saved = validate_embedding(saved)
        except ValueError:
            continue
        score = float(np.clip(np.dot(vector, saved / np.linalg.norm(saved)), -1.0, 1.0))
        scores[identity] = max(scores.get(identity, -1.0), score)
    if not scores:
        return None, -1.0
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    identity, best = ranked[0]
    threshold = _setting("FACE_MATCH_THRESHOLD", 0.50)
    margin = _setting("FACE_MATCH_MARGIN", 0.05)
    if best < threshold or (len(ranked) > 1 and best - ranked[1][1] < margin):
        return None, best
    return identity, best


def compare_embeddings(embedding):
    saved = get_face_embedding()
    if not saved:
        return "No registered student embeddings are available. Register a student's face first."
    return _best_match(embedding, saved)


def compare_faculty_embeddings(embedding):
    return _best_match(embedding, get_faculty_embeddings())
