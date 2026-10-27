"""Two small behaviours that cost real time when they are wrong."""

from pathlib import Path

from palimpsest.models import Artifact
from palimpsest.query import _context
from palimpsest.vision import triage_all


class _ExplodingLLM:
    """Any model call is a test failure."""

    model = "none"
    calls = 0

    def __getattr__(self, name):  # pragma: no cover - only called on failure
        raise AssertionError(f"model was called: {name}")


def test_vision_limit_zero_skips_triage(tmp_path: Path):
    photo = tmp_path / "IMG_0001.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n")
    artifact = Artifact(id="a1", recovered_path=str(photo), original_name="IMG_0001.png")

    assert triage_all([artifact], _ExplodingLLM(), limit=0) == 0
    assert artifact.triage == {}


def test_context_marks_unrecovered_files_and_keeps_the_hypothesis():
    missing = Artifact(
        id="deadbeef01",
        recovered_path="x",
        original_name="IMG_2019_0000.png",
        kind="photo",
        size=4096,
        deleted_at="2026-10-27T07:34:32",
        missing=True,
        hypothesis="Probably a photograph taken on a mobile device.",
    )
    line = _context([missing])
    assert "unrecovered" in line
    assert "Probably a photograph" in line
    assert "IMG_2019_0000.png" in line


def test_context_marks_recovered_files():
    artifact = Artifact(
        id="a1", recovered_path="x", original_name="letter.txt", kind="document"
    )
    assert "recovered" in _context([artifact])
