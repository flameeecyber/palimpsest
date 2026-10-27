"""The query stage is checked the same way an epitaph is.

These tests encode a real answer the model gave: four photographs from one
cluster, described as "all created on June 20th, 2019". One of them was.
"""

from palimpsest.models import Artifact
from palimpsest.query import check_answer


def _case() -> dict[str, Artifact]:
    artifacts = [
        Artifact(
            id="2f3dfa31df",
            recovered_path="x",
            original_name="IMG_2019_0006.png",
            kind="photo",
            size=90933,
            created_at="2019-06-20T18:28:01",
            cluster="Summer Family Photos",
        ),
        Artifact(
            id="59125a46a8",
            recovered_path="x",
            original_name="IMG_2019_0009.png",
            kind="photo",
            size=105094,
            created_at="2019-06-23T18:31:01",
            cluster="Summer Family Photos",
        ),
    ]
    return {a.id: a for a in artifacts}


def test_universal_date_claim_over_several_files_is_struck():
    verdicts = check_answer(
        "The files [2f3dfa31df] and [59125a46a8] were all created on June 20th, 2019.",
        _case(),
    )
    assert len(verdicts) == 1
    assert not verdicts[0]["ok"]
    assert "every cited file" in verdicts[0]["reason"]


def test_the_same_claim_about_one_file_passes():
    verdicts = check_answer(
        "The file [2f3dfa31df] was created on June 20th, 2019.",
        _case(),
    )
    assert verdicts[0]["ok"]


def test_a_sentence_without_a_citation_is_struck():
    verdicts = check_answer("These photographs were taken in the summer.", _case())
    assert not verdicts[0]["ok"]
    assert verdicts[0]["reason"] == "cites no artifact"


def test_an_invented_size_is_struck():
    verdicts = check_answer("The file [2f3dfa31df] was 204800 bytes.", _case())
    assert not verdicts[0]["ok"]
    assert "number" in verdicts[0]["reason"]


def test_a_correct_size_passes():
    verdicts = check_answer("The file [2f3dfa31df] was 90933 bytes.", _case())
    assert verdicts[0]["ok"]


def test_an_unknown_id_does_not_count_as_a_citation():
    verdicts = check_answer("The file [deadbeef01] was 90933 bytes.", _case())
    assert not verdicts[0]["ok"]
    assert verdicts[0]["reason"] == "cites no artifact"


def test_sentences_are_judged_separately():
    verdicts = check_answer(
        "The file [2f3dfa31df] was 90933 bytes. "
        "Both [2f3dfa31df] and [59125a46a8] were created in 2019.",
        _case(),
    )
    assert [v["ok"] for v in verdicts] == [True, True]


def test_a_second_sentence_still_needs_its_own_citation():
    verdicts = check_answer(
        "The file [2f3dfa31df] was 90933 bytes. Both files were created in 2019.",
        _case(),
    )
    assert [v["ok"] for v in verdicts] == [True, False]


def test_citations_fall_back_to_the_ids_that_survived_the_check():
    """A model can cite inline and leave the JSON list empty.

    The ids inside the sentences are the ones the checker verified, so they are
    the ids the summary has to show.
    """
    verdicts = check_answer(
        "The file [2f3dfa31df] was 90933 bytes. The file [59125a46a8] was 105094 bytes.",
        _case(),
    )
    kept = [v for v in verdicts if v["ok"]]
    inline = [r for v in kept for r in v["cited"]]
    assert list(dict.fromkeys(inline)) == ["2f3dfa31df", "59125a46a8"]
