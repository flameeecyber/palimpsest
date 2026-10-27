from palimpsest.grounding import validate_sentences
from palimpsest.models import Evidence


def _evidence():
    return [
        Evidence(id="E1", source="filename", value="IMG_0042.JPG"),
        Evidence(id="E2", source="deleted", value="2021-08-14T22:41:03"),
        Evidence(id="E3", source="size", value="4032000 bytes"),
    ]


def test_keeps_supported_sentence():
    claims = validate_sentences(
        [{"text": "It was deleted in 2021.", "evidence": ["E2"], "confidence": "certain"}],
        _evidence(),
    )
    assert len(claims) == 1
    assert not claims[0].struck


def test_strikes_sentence_without_evidence():
    claims = validate_sentences(
        [{"text": "Someone loved this photograph.", "evidence": [], "confidence": "certain"}],
        _evidence(),
    )
    assert claims[0].struck
    assert "no evidence" in claims[0].reason


def test_strikes_invented_year():
    claims = validate_sentences(
        [{"text": "It was taken in 1998.", "evidence": ["E2"], "confidence": "certain"}],
        _evidence(),
    )
    assert claims[0].struck
    assert "1998" in claims[0].reason


def test_drops_unknown_evidence_ids():
    claims = validate_sentences(
        [{"text": "A photograph.", "evidence": ["E99"], "confidence": "certain"}],
        _evidence(),
    )
    assert claims[0].struck


def test_speculation_is_kept_but_labelled():
    claims = validate_sentences(
        [{"text": "Perhaps it was a birthday.", "evidence": ["E1"], "confidence": "speculation"}],
        _evidence(),
    )
    assert not claims[0].struck
    assert claims[0].confidence == "speculation"


def test_unknown_confidence_is_normalised():
    claims = validate_sentences(
        [{"text": "A photograph.", "evidence": ["E1"], "confidence": "very sure"}],
        _evidence(),
    )
    assert claims[0].confidence == "probable"
