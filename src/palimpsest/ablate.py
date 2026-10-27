"""Ablation: what the model is actually for.

Runs the same evidence through the no-model baseline and through the narrated
case, and prints the difference. This is the honest answer to "isn't the AI just
decoration?" — a table you can reproduce.
"""

from __future__ import annotations

import copy
from typing import Any

from .narrate import stub_narrate
from .store import Store


def _count_words(artifacts: list) -> int:
    return sum(len(c.text.split()) for a in artifacts for c in a.claims if not c.struck)


def compare(out: str) -> dict[str, Any]:
    store = Store(out)
    case = store.case
    artifacts = [a for a in case.artifacts if not a.missing]

    baseline = copy.deepcopy(artifacts)
    for artifact in baseline:
        stub_narrate(artifact)

    with_model = {
        "labelled": sum(1 for a in artifacts if a.triage.get("label")),
        "groups": len({a.cluster_id for a in artifacts if a.cluster_id}),
        "hypotheses": sum(1 for a in case.artifacts if a.hypothesis),
        "narrated": sum(1 for a in artifacts if a.claims),
        "sentences": sum(len(a.claims) for a in artifacts),
        "grounded": sum(1 for a in artifacts for c in a.claims if not c.struck),
        "words": _count_words(artifacts),
        "semantic_words": sum(
            len((a.triage.get("label", "") + " " + a.triage.get("subject", "")).split())
            for a in artifacts
        ),
    }
    without_model = {
        "labelled": 0,
        "groups": 0,
        "hypotheses": 0,
        "narrated": sum(1 for a in baseline if a.claims),
        "sentences": sum(len(a.claims) for a in baseline),
        "grounded": sum(1 for a in baseline for c in a.claims if not c.struck),
        "words": _count_words(baseline),
        "semantic_words": 0,
    }
    return {"without_model": without_model, "with_model": with_model}


def format_table(result: dict[str, Any]) -> str:
    rows = [
        ("artifacts with a human label", "labelled"),
        ("groups found by meaning", "groups"),
        ("unrecoverable files explained", "hypotheses"),
        ("artifacts with an epitaph", "narrated"),
        ("sentences written", "sentences"),
        ("sentences with a source", "grounded"),
        ("words about the content", "semantic_words"),
    ]
    left = result["without_model"]
    right = result["with_model"]
    width = max(len(label) for label, _ in rows) + 2
    lines = [
        f"{'':<{width}}{'without model':>16}{'with model':>14}",
        "-" * (width + 30),
    ]
    for label, key in rows:
        lines.append(f"{label:<{width}}{left[key]:>16}{right[key]:>14}")
    return "\n".join(lines)
