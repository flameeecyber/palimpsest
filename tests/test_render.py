from pathlib import Path

from palimpsest.models import Artifact, Case, Claim, Evidence
from palimpsest.render import render_case


def test_render_produces_offline_site(tmp_path):
    artifact = Artifact(
        id="abc123",
        recovered_path=str(tmp_path / "missing.jpg"),
        kind="photo",
        original_name="IMG_0042.JPG",
        size=4032000,
        deleted_at="2021-08-14T22:41:03",
        recovery_method="metadata",
    )
    artifact.evidence = [
        Evidence(id="E1", source="filename", value="IMG_0042.JPG"),
        Evidence(id="E2", source="deleted", value="2021-08-14T22:41:03"),
    ]
    artifact.claims = [
        Claim(text="IMG_0042.JPG was deleted in 2021.", evidence=["E1", "E2"], confidence="certain")
    ]
    case = Case(target="ghost.img", artifacts=[artifact])

    site = render_case(case, tmp_path, clusters=[], case_claims=[], model="gemma3:4b")

    index = (site / "index.html").read_text(encoding="utf-8")
    assert "Palimpsest" in index
    assert "IMG_0042.JPG" in index
    assert "assets/style.css" in index
    assert (site / "assets" / "style.css").exists()
    assert (site / "abc123.html").exists()
    assert (site / "index.json").exists()


def test_missing_artifact_renders_hypothesis(tmp_path):
    artifact = Artifact(
        id="gone1",
        recovered_path="",
        kind="document",
        original_name="tax_2021.pdf",
        missing=True,
        hypothesis="Probably a scanned tax document.",
        hypothesis_confidence="medium",
    )
    case = Case(target="ghost.img", artifacts=[artifact])
    site = render_case(case, tmp_path, clusters=[], case_claims=[], model=None)
    page = (site / "index.html").read_text(encoding="utf-8")
    assert "Probably a scanned tax document." in page
