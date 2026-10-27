import json
from pathlib import Path

from palimpsest import manifest
from palimpsest.models import Artifact, Case, Claim, Evidence
from palimpsest.narrate import clean_name


def _case(tmp_path):
    recovered = tmp_path / "recovered"
    recovered.mkdir()
    file = recovered / "letter.txt"
    file.write_text("Mum, I found the photographs.", encoding="utf-8")
    artifact = Artifact(
        id="abc123",
        recovered_path=str(file),
        kind="document",
        original_name="letter.txt",
        size=file.stat().st_size,
        sha256=manifest.sha256_file(file),
        recovery_method="metadata",
    )
    artifact.evidence = [
        Evidence(id="E1", source="filename", value="letter.txt"),
        Evidence(id="E2", source="content", value="Mum, I found the photographs."),
    ]
    artifact.claims = [
        Claim(
            text="letter.txt contains the line Mum, I found the photographs.",
            evidence=["E1", "E2"],
            confidence="certain",
        )
    ]
    return Case(target=str(tmp_path / "ghost.img"), artifacts=[artifact])


def test_manifest_verifies_clean_case(tmp_path):
    case = _case(tmp_path)
    record = manifest.build(case, model="gemma3:4b", embed_model="nomic-embed-text")
    manifest.write(tmp_path / "manifest.json", record)
    loaded = manifest.load(tmp_path / "manifest.json")
    checks = manifest.verify(case, loaded, check_target=False)
    assert all(c["ok"] for c in checks), manifest.format_checks(checks)


def test_manifest_detects_changed_file(tmp_path):
    case = _case(tmp_path)
    record = manifest.build(case, model=None, embed_model=None)
    Path(case.artifacts[0].recovered_path).write_text("tampered", encoding="utf-8")
    checks = manifest.verify(case, record, check_target=False)
    sha_checks = [c for c in checks if "sha256" in c["label"]]
    assert sha_checks and not sha_checks[0]["ok"]


def test_manifest_detects_prompt_drift(tmp_path):
    case = _case(tmp_path)
    record = manifest.build(case, model=None, embed_model=None)
    record["prompts"] = {"triage": "deadbeefdeadbeef"}
    checks = manifest.verify(case, record, check_target=False)
    drift = [c for c in checks if c["label"] == "prompts unchanged"]
    assert drift and not drift[0]["ok"]


def test_manifest_flags_unsupported_published_sentence(tmp_path):
    case = _case(tmp_path)
    case.artifacts[0].claims[0].evidence = ["E1"]
    case.artifacts[0].claims[0].text = "The sea was calm at dusk."
    record = manifest.build(case, model=None, embed_model=None)
    checks = manifest.verify(case, record, check_target=False)
    support = [c for c in checks if "sentence supported" in c["label"]]
    assert support and not support[0]["ok"]


def test_manifest_flags_uncited_id_written_in_prose(tmp_path):
    case = _case(tmp_path)
    case.artifacts[0].claims[0].text = "Evidence E9 shows a letter."
    case.artifacts[0].claims[0].evidence = ["E1", "E2"]
    record = manifest.build(case, model=None, embed_model=None)
    checks = manifest.verify(case, record, check_target=False)
    leaked = [c for c in checks if "uncited ids" in c["label"]]
    assert leaked and not leaked[0]["ok"]


def test_manifest_records_counts_and_hashes(tmp_path):
    case = _case(tmp_path)
    record = manifest.build(case, model="gemma3:4b", embed_model="nomic-embed-text")
    assert record["counts"]["artifacts"] == 1
    assert record["artifacts"][0]["sha256"] == case.artifacts[0].sha256
    assert record["prompts"]
    assert record["code"]["grounding.py"]
    assert "fls" in record["tools"]


def test_clean_name_normalises_model_output():
    assert clean_name("Sunset Over The Sea.jpg", "photo") == "sunset-over-the-sea.jpg"
    assert clean_name("sunset", "photo") == "sunset.jpg"
    assert clean_name("letter to mum", "document") == "letter-to-mum.txt"
    assert clean_name("  ", "photo") is None
    assert clean_name("!!!", "photo") is None
