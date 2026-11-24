"""SCRFD + gender-age subject selection tests without loading real ONNX assets."""

from PIL import Image

from amane.media import face_detect


class _Detector:
    def __init__(self, faces):
        self.faces = faces

    def detect(self, image, *, conf, max_side):
        return list(self.faces)


class _GenderAge:
    def __init__(self, values):
        self.values = values

    def predict(self, rgb, bbox):
        return self.values[bbox[0]]


def test_main_subject_prefers_female_face(monkeypatch):
    male = (20.0, 30.0, 140.0, 180.0, 0.99)
    female = (420.0, 40.0, 510.0, 160.0, 0.85)
    monkeypatch.setattr(face_detect, "_detector", lambda: _Detector([male, female]))
    monkeypatch.setattr(
        face_detect,
        "_gender_model",
        lambda: _GenderAge({20.0: (False, 34.0), 420.0: (True, 27.0)}),
    )

    result = face_detect.main_subject_face(Image.new("RGB", (800, 600)))

    assert result == female[:4]


def test_main_subject_uses_top_scored_face_when_no_female(monkeypatch):
    first = (20.0, 30.0, 140.0, 180.0, 0.99)
    second = (420.0, 40.0, 510.0, 160.0, 0.85)
    monkeypatch.setattr(face_detect, "_detector", lambda: _Detector([first, second]))
    monkeypatch.setattr(
        face_detect,
        "_gender_model",
        lambda: _GenderAge({20.0: (False, 34.0), 420.0: (False, 27.0)}),
    )

    result = face_detect.main_subject_face(Image.new("RGB", (800, 600)))

    assert result == first[:4]


def test_main_subject_returns_none_when_gender_age_model_unavailable(monkeypatch):
    face = (20.0, 30.0, 140.0, 180.0, 0.99)
    monkeypatch.setattr(face_detect, "_detector", lambda: _Detector([face]))
    monkeypatch.setattr(face_detect, "_gender_model", lambda: None)

    assert face_detect.main_subject_face(Image.new("RGB", (800, 600))) is None


def test_main_subject_returns_none_when_gender_age_inference_fails(monkeypatch):
    class BrokenGenderAge:
        def predict(self, rgb, bbox):
            raise RuntimeError("broken model")

    face = (20.0, 30.0, 140.0, 180.0, 0.99)
    monkeypatch.setattr(face_detect, "_detector", lambda: _Detector([face]))
    monkeypatch.setattr(face_detect, "_gender_model", lambda: BrokenGenderAge())

    assert face_detect.main_subject_face(Image.new("RGB", (800, 600))) is None


def test_missing_onnxruntime_does_not_download_model(monkeypatch):
    called = False

    def unexpected_download(filename):
        nonlocal called
        called = True
        raise AssertionError("model download must not run without ONNX Runtime")

    monkeypatch.setattr(face_detect, "_onnxruntime_available", lambda: False)
    monkeypatch.setattr(face_detect, "_ensure_model", unexpected_download)
    face_detect._detector.cache_clear()
    face_detect._gender_model.cache_clear()
    try:
        assert face_detect._detector() is None
        assert face_detect._gender_model() is None
        assert called is False
    finally:
        face_detect._detector.cache_clear()
        face_detect._gender_model.cache_clear()
