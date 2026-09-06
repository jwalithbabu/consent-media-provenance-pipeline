"""Local face detection and consent-based face signature generation."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class FaceProcessingError(RuntimeError):
    """Raised when the input image cannot be processed safely."""


@dataclass(frozen=True)
class FaceObservation:
    """The local, non-identifying output of the face stage."""

    detector: str
    image_sha256: str
    image_size: dict[str, int]
    face_count: int
    selected_face: dict[str, int]
    signature_dimensions: int
    signature: list[float]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _encode_face(face: np.ndarray) -> list[float]:
    """Create a stable local signature from a normalized face crop.

    This is intentionally a similarity signature for consent-based matching,
    not an identity-grade biometric embedding.
    """

    grayscale = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
    normalized = cv2.resize(grayscale, (32, 32), interpolation=cv2.INTER_AREA)
    normalized = cv2.equalizeHist(normalized).astype(np.float32) / 255.0
    centered = normalized - float(normalized.mean())
    scale = float(centered.std())
    if scale > 1e-8:
        centered /= scale
    return [round(float(value), 6) for value in centered.flatten()]


def detect_and_encode(image_path: str | Path) -> FaceObservation:
    """Detect the largest face and encode it locally."""

    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise FaceProcessingError(f"Input image does not exist: {path}")

    image = cv2.imread(str(path))
    if image is None:
        raise FaceProcessingError(f"OpenCV could not read the input image: {path}")

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        raise FaceProcessingError("OpenCV's bundled Haar face detector could not load")

    faces = detector.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(48, 48),
    )
    if len(faces) == 0:
        raise FaceProcessingError("No face was detected in the input image")

    x, y, face_width, face_height = max(
        faces,
        key=lambda box: int(box[2]) * int(box[3]),
    )
    face_crop = image[y : y + face_height, x : x + face_width]
    signature = _encode_face(face_crop)

    return FaceObservation(
        detector="opencv-haar-frontalface-default",
        image_sha256=_sha256_file(path),
        image_size={"width": width, "height": height},
        face_count=len(faces),
        selected_face={
            "x": int(x),
            "y": int(y),
            "width": int(face_width),
            "height": int(face_height),
        },
        signature_dimensions=len(signature),
        signature=signature,
    )