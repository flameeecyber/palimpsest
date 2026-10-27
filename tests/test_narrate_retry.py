"""The retry loop: a rejected sentence is fed back, and the best attempt wins.

No model is involved. The fake client returns a bad answer once and a good
answer the second time, which is exactly the behaviour measured with gemma3:1b.
"""

from palimpsest import narrate
from palimpsest.models import Artifact, Evidence


class FakeLLM:
    model = "fake:1b"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def json_chat(self, system, prompt, **kwargs):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _artifact():
    return Artifact(
        id="a1",
        recovered_path="/tmp/letter.txt",
        kind="document",
        original_name="letter.txt",
        size=216,
        recovery_method="metadata",
        text_excerpt="Mum, I found the box of photographs in the hall cupboard.",
    )


def test_second_attempt_is_used_when_the_first_is_struck():
    artifact = _artifact()
    llm = FakeLLM(
        [
            {
                "sentences": [
                    {
                        "text": "The sea was calm at dusk.",
                        "evidence": ["E1"],
                        "confidence": "certain",
                    }
                ]
            },
            {
                "sentences": [
                    {
                        "text": "letter.txt contains the line Mum, I found the box of photographs.",
                        "evidence": ["E1", "E4"],
                        "confidence": "certain",
                    }
                ]
            },
        ]
    )

    narrate.narrate(artifact, llm)

    assert len(llm.prompts) == 2
    assert "YOUR PREVIOUS ATTEMPT WAS REJECTED" in llm.prompts[1]
    assert "support" in llm.prompts[1]
    assert artifact.claims and not artifact.claims[0].struck
    assert artifact.narration_model == "fake:1b"


def test_best_attempt_wins_when_both_are_flawed():
    artifact = _artifact()
    llm = FakeLLM(
        [
            {
                "sentences": [
                    {"text": "The sea was calm at dusk.", "evidence": ["E1"], "confidence": "certain"}
                ]
            },
            {
                "sentences": [
                    {
                        "text": "letter.txt contains the line Mum, I found the box of photographs.",
                        "evidence": ["E1", "E4"],
                        "confidence": "certain",
                    },
                    {"text": "It was written by her mother.", "evidence": ["E1"], "confidence": "certain"},
                ]
            },
        ]
    )

    narrate.narrate(artifact, llm)

    supported = [c for c in artifact.claims if not c.struck]
    assert len(supported) == 1
    assert "Mum" in supported[0].text


def test_a_single_good_attempt_does_not_call_the_model_twice():
    artifact = _artifact()
    llm = FakeLLM(
        [
            {
                "sentences": [
                    {
                        "text": "letter.txt contains the line Mum, I found the box of photographs.",
                        "evidence": ["E1", "E4"],
                        "confidence": "certain",
                    }
                ]
            }
        ]
    )

    narrate.narrate(artifact, llm)
    assert len(llm.prompts) == 1


def test_evidence_table_has_ids_a_model_can_cite():
    artifact = _artifact()
    evidence = narrate.build_evidence(artifact)
    assert all(isinstance(e, Evidence) and e.id.startswith("E") for e in evidence)
    assert any(e.source == "content" for e in evidence)
