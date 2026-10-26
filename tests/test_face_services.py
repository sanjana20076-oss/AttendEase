import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

import face_recognition_service as recognition
from conftest import vector
from face_embedding_service import get_face_embedding, validate_embedding
from image_utils import decode_data_url, decode_image


def test_high_confidence_identity_matches():
    assert recognition._best_match(vector(0),[(1,vector(0)),(2,vector(1))]) == (1,1.0)


def test_unknown_identity_rejected():
    identity, score=recognition._best_match(vector(10),[(1,vector(0)),(2,vector(1))])
    assert identity is None and score == 0


def test_ambiguous_identities_rejected():
    identity, score=recognition._best_match(vector(0)+vector(1),[(1,vector(0)),(2,vector(1))])
    assert identity is None and score > 0.7


def test_two_embeddings_of_same_identity_do_not_trigger_margin_rejection():
    assert recognition._best_match(vector(0),[(1,vector(0)),(1,vector(0))])[0] == 1


@pytest.mark.parametrize("bad", [np.zeros(512),np.ones(128),np.full(512,np.nan),np.full(512,np.inf)])
def test_invalid_vectors_rejected(bad):
    with pytest.raises(ValueError):
        validate_embedding(bad)


def test_corrupted_embedding_skipped(app, db):
    db.execute("INSERT INTO face_embeddings(student_id,embedding_data) VALUES (1,?)",(b"broken",))
    with app.app_context():
        assert len(get_face_embedding()) == 3  # active students only, not corrupt record


@pytest.mark.parametrize("count", [0,1,2])
def test_face_generation_requires_exactly_one_face(monkeypatch, count):
    class FakeModel:
        def get(self, image):
            return [SimpleNamespace(embedding=vector()) for _ in range(count)]
    monkeypatch.setattr(recognition,"get_face_model",lambda: FakeModel())
    result=recognition.generate_face_embedding(np.zeros((64,64,3),dtype=np.uint8))
    assert isinstance(result,np.ndarray) if count == 1 else isinstance(result,str)


def test_model_is_initialized_only_once_and_uses_cpu(monkeypatch):
    calls=[]
    class FakeModel:
        def __init__(self,**kwargs):
            calls.append(kwargs)
        def prepare(self,**kwargs):
            calls.append(kwargs)
    module=ModuleType("insightface.app")
    module.FaceAnalysis=FakeModel
    monkeypatch.setitem(sys.modules,"insightface",ModuleType("insightface"))
    monkeypatch.setitem(sys.modules,"insightface.app",module)
    monkeypatch.setattr(recognition,"_model",None)
    monkeypatch.setattr(recognition,"_model_failure",None)
    first,second=recognition.get_face_model(),recognition.get_face_model()
    assert first is second and len(calls) == 2
    assert calls[0]["providers"] == ["CPUExecutionProvider"]
    assert calls[1]["ctx_id"] == -1


def test_unavailable_model_never_returns_fake_identity(monkeypatch):
    module=ModuleType("insightface.app")
    def fail(**kwargs):
        raise RuntimeError("Missing ONNX files")
    module.FaceAnalysis=fail
    monkeypatch.setitem(sys.modules,"insightface",ModuleType("insightface"))
    monkeypatch.setitem(sys.modules,"insightface.app",module)
    monkeypatch.setattr(recognition,"_model",None)
    monkeypatch.setattr(recognition,"_model_failure",None)
    monkeypatch.setattr(recognition,"_retry_after",0)
    with pytest.raises(recognition.FaceModelUnavailable):
        recognition.get_face_model()
    # Avoid repeated downloads/reinitialization for every incoming frame.
    with pytest.raises(recognition.FaceModelUnavailable):
        recognition.get_face_model()


def test_data_url_and_image_decode(data_url, jpeg):
    assert decode_data_url(data_url).shape == (64,64,3)
    assert decode_image(jpeg).shape == (64,64,3)


@pytest.mark.parametrize("value", ["", "data:image/gif;base64,aGVsbG8=", "data:image/jpeg;base64,%%%%", "data:image/png;base64,aGVsbG8="])
def test_invalid_data_url_rejected(value):
    with pytest.raises(ValueError):
        decode_data_url(value)
