from palimpsest.grounding import (
    SUPPORT_THRESHOLD,
    meta_words,
    quotes_content,
    support_score,
    validate_sentences,
)
from palimpsest.models import Evidence


def _evidence():
    return [
        Evidence(id="E1", source="filename", value="IMG_2019_0006.png"),
        Evidence(id="E2", source="triage:label", value="sunset sky with a sun"),
        Evidence(id="E3", source="deleted", value="2021-08-14T22:41:03"),
    ]


def test_support_is_zero_when_citation_is_unrelated():
    assert support_score("The sea was calm at dusk.", ["IMG_2019_0006.png"]) == 0.0


def test_support_is_high_when_citation_contains_the_content():
    assert support_score("A sunset over the sky.", ["sunset sky with a sun"]) > 0.6


def test_unsupported_citation_is_struck():
    claims = validate_sentences(
        [{"text": "The sea was calm at dusk.", "evidence": ["E1"], "confidence": "certain"}],
        _evidence(),
    )
    assert claims[0].struck
    assert "support" in claims[0].reason
    assert claims[0].support == 0.0


def test_supported_citation_survives():
    claims = validate_sentences(
        [{"text": "A sunset sky with a sun.", "evidence": ["E2"], "confidence": "certain"}],
        _evidence(),
    )
    assert not claims[0].struck
    assert claims[0].support >= SUPPORT_THRESHOLD


def test_speculation_is_not_support_checked():
    claims = validate_sentences(
        [{"text": "Perhaps the sea was calm.", "evidence": ["E1"], "confidence": "speculation"}],
        _evidence(),
    )
    assert not claims[0].struck


def test_id_named_in_prose_must_also_be_cited():
    claims = validate_sentences(
        [
            {
                "text": "Evidence E9 indicates a deletion.",
                "evidence": ["E3"],
                "confidence": "certain",
            }
        ],
        _evidence(),
    )
    assert claims[0].struck
    assert "mentions ids" in claims[0].reason


def test_sentence_without_ids_in_prose_survives():
    claims = validate_sentences(
        [
            {
                "text": "The file was deleted in 2021.",
                "evidence": ["E3"],
                "confidence": "certain",
            }
        ],
        _evidence(),
    )
    assert not claims[0].struck


def _photo_evidence():
    return [
        Evidence(id="E1", source="filename", value="IMG_2021_0002.png"),
        Evidence(id="E2", source="created", value="2019-06-16T18:24:01"),
        Evidence(id="E3", source="camera", value="iPhone 8"),
        Evidence(id="E4", source="deleted", value="2026-10-27T07:34:32"),
    ]


def test_timestamp_quoted_verbatim_completes_the_citation():
    # The model cites the filename and the camera, and forgets the row that
    # holds the timestamp. The sentence is still checkable, so the row is added
    # and recorded rather than the sentence thrown away.
    claims = validate_sentences(
        [
            {
                "text": "IMG_2021_0002.png was created on 2019-06-16T18:24:01 with an iPhone 8.",
                "evidence": ["E1", "E3"],
                "confidence": "certain",
            }
        ],
        _photo_evidence(),
    )
    claim = claims[0]
    assert not claim.struck
    assert "E2" in claim.evidence
    assert claim.auto_cited == ["E2"]


def test_bare_year_is_completed_from_the_date_row():
    claims = validate_sentences(
        [
            {
                "text": "The photo was made in 2019 with an iPhone 8.",
                "evidence": ["E1", "E3"],
                "confidence": "certain",
            }
        ],
        _photo_evidence(),
    )
    assert not claims[0].struck
    assert "E2" in claims[0].auto_cited


def test_invented_year_is_still_struck():
    claims = validate_sentences(
        [
            {
                "text": "The photo was made in 2017 with an iPhone 8.",
                "evidence": ["E1", "E3"],
                "confidence": "certain",
            }
        ],
        _photo_evidence(),
    )
    assert claims[0].struck
    assert "2017" in claims[0].reason


def test_content_quote_requires_four_consecutive_words():
    evidence = [
        Evidence(
            id="E1",
            source="content",
            value="I found the box of photographs in the hall cupboard.",
        )
    ]
    short = validate_sentences(
        [{"text": "The content read, \"the box\".", "evidence": ["E1"], "confidence": "certain"}],
        evidence,
    )
    long = validate_sentences(
        [
            {
                "text": 'It began, "I found the box of photographs".',
                "evidence": ["E1"],
                "confidence": "certain",
            }
        ],
        evidence,
    )
    assert not quotes_content(short, evidence)
    assert quotes_content(long, evidence)


def test_no_content_row_means_no_quote_requirement():
    evidence = [Evidence(id="E1", source="filename", value="IMG_0001.png")]
    claims = validate_sentences(
        [{"text": "IMG_0001.png existed.", "evidence": ["E1"], "confidence": "certain"}],
        evidence,
    )
    assert quotes_content(claims, evidence)


def test_sentence_about_the_tool_is_struck():
    claims = validate_sentences(
        [
            {
                "text": "The description indicated a sunset sky with a sun.",
                "evidence": ["E2"],
                "confidence": "certain",
            }
        ],
        _evidence(),
    )
    assert claims[0].struck
    assert "tool" in claims[0].reason


def test_style_guard_can_be_disabled_for_case_notes():
    claims = validate_sentences(
        [
            {
                "text": "The description indicated a sunset sky with a sun.",
                "evidence": ["E2"],
                "confidence": "certain",
            }
        ],
        _evidence(),
        style_guard=False,
    )
    assert not claims[0].struck


def test_meta_words_finds_jargon():
    assert sorted(meta_words("The triage label was metadata.")) == ["label", "metadata", "triage"]
