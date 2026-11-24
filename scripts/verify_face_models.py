#!/usr/bin/env python3
"""Verify the two ONNX models bundled with the Amane source tree."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parents[1] / "src" / "amane" / "media"
MODELS = {
    "face_detect_scrfd.onnx": (16_923_827, "bbfebbab00217df73af23fca160236208bb69616"),
    "face_detect_genderage.onnx": (1_322_532, "c1a68b8db319d8d5c78f27136822ef1313c51a77"),
}


def git_blob_sha1(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    failed = False
    for name, (expected_size, expected_sha) in MODELS.items():
        path = MODEL_DIR / name
        if not path.is_file():
            print(f"MISSING: {path}", file=sys.stderr)  # noqa: T201
            failed = True
            continue
        size = path.stat().st_size
        sha = git_blob_sha1(path)
        if size != expected_size or sha != expected_sha:
            print(
                f"INVALID: {name}: size={size} (expected {expected_size}), "
                f"git_blob_sha1={sha} (expected {expected_sha})",
                file=sys.stderr,
            )  # noqa: T201
            failed = True
            continue
        print(f"OK: {name} ({size} bytes, {sha})")  # noqa: T201
    if failed:
        return 1
    print("Both bundled face models passed integrity verification.")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
