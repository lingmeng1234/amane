#!/usr/bin/env python3
"""Download and verify pinned ONNX models for face-guided poster cropping."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "src" / "amane" / "media"
REFERENCE_COMMIT = "657b70dc36047a875eb1431dca342abc7a07a346"
MODELS = (
    ("face_detect_scrfd.onnx", 16_923_827, "bbfebbab00217df73af23fca160236208bb69616"),
    ("face_detect_genderage.onnx", 1_322_532, "c1a68b8db319d8d5c78f27136822ef1313c51a77"),
)


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _download(name: str, expected_size: int, expected_sha: str) -> None:
    destination = MODEL_DIR / name
    if destination.is_file():
        current = destination.read_bytes()
        if len(current) == expected_size and _git_blob_sha1(current) == expected_sha:
            LOGGER.info("Verified existing model: %s", destination)
            return

    url = f"https://raw.githubusercontent.com/BiancaVeritas/amane-promax/{REFERENCE_COMMIT}/src/amane/media/{name}"
    request = Request(url, headers={"User-Agent": "Amane-face-model-fetcher"})
    LOGGER.info("Downloading %s ...", name)
    with urlopen(request, timeout=120) as response:
        data = response.read()

    actual_sha = _git_blob_sha1(data)
    if len(data) != expected_size or actual_sha != expected_sha:
        raise RuntimeError(
            f"Model integrity check failed for {name}: size={len(data)} "
            f"(expected {expected_size}), git_blob_sha1={actual_sha} "
            f"(expected {expected_sha})"
        )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(destination)
    LOGGER.info("Installed %s (%d bytes)", destination, len(data))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for model in MODELS:
        _download(*model)


if __name__ == "__main__":
    main()
