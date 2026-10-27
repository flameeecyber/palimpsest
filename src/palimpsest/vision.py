"""Stage 1: semantic triage.

Carving hands you bytes with no name. Magic-byte detection can tell a JPEG from
a ZIP; it cannot tell a photograph of a person from a screenshot of a receipt.
That distinction is the whole difference between a folder of 4,000 files and a
case with 40 memories in it.

This stage is why the model is not decoration. Remove it and the ranking, the
labels, and the decision about what deserves an epitaph all disappear.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import prompts
from .llm import LLM, LLMError
from .models import Artifact

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".avif"}

_SYSTEM = (
    "You are a forensic image triage assistant. You describe what is visible and "
    "nothing else. You never identify people. You return only JSON."
)


def can_see(artifact: Artifact) -> bool:
    return Path(artifact.recovered_path).suffix.lower() in IMAGE_SUFFIXES and Path(
        artifact.recovered_path
    ).is_file()


def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    return {
        "subject": str(raw.get("subject", "")).strip()[:160],
        "setting": str(raw.get("setting", "unknown")).strip().lower()[:24],
        "people": max(0, int(raw.get("people", 0) or 0)),
        "has_text": bool(raw.get("has_text", False)),
        "text": str(raw.get("text", "")).strip()[:240],
        "is_personal_memory": bool(raw.get("is_personal_memory", False)),
        "label": str(raw.get("label", "")).strip()[:60],
        "damage": str(raw.get("damage", "unknown")).strip().lower()[:16],
        "confidence": _float(raw.get("confidence", 0.0)),
    }


def triage(artifact: Artifact, llm: LLM) -> dict[str, Any]:
    if not can_see(artifact):
        return {}
    try:
        raw = llm.vision_json(
            artifact.recovered_path,
            _SYSTEM,
            prompts.load("triage"),
            num_predict=320,
            temperature=0.1,
        )
    except LLMError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return _normalise(raw)


def _hero_key(artifact: Artifact) -> tuple[int, int, int]:
    name = (artifact.original_name or "").lower()
    return (
        0 if "screenshot" in name else 1,
        1 if artifact.exif.get("DateTimeOriginal") else 0,
        artifact.size,
    )


def triage_all(
    artifacts: list[Artifact],
    llm: LLM,
    *,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Triage images, optionally only the most promising ones.

    A 4B vision model on a CPU is slow. Triaging the 40 artifacts most likely to
    be memories, instead of 4,000 fragments, is a design decision: the ranking
    is part of the product, and the case store caches every result.
    """
    candidates = [a for a in artifacts if can_see(a)]
    if limit is not None and limit > 0:
        candidates = sorted(candidates, key=_hero_key, reverse=True)[:limit]

    done = 0
    for artifact in candidates:
        result = triage(artifact, llm)
        if result:
            artifact.triage = result
            done += 1
            if progress and done % 5 == 0:
                progress(f"  triaged {done} images")
    if progress:
        progress(f"  triaged {done} images")
    return done


def triage_rank(artifact: Artifact) -> float:
    """How much does this artifact look like something a person kept?

    Used to decide what gets narrated first when a case is too large to narrate
    end to end. Not a truth score: a ranking heuristic over model output.
    """
    t = artifact.triage
    if not t:
        return 0.0
    score = 0.0
    if t.get("is_personal_memory"):
        score += 2.0
    if t.get("people", 0) > 0:
        score += 1.5
    if t.get("has_text"):
        score += 0.5
    setting = t.get("setting")
    if setting in {"indoor", "outdoor"}:
        score += 0.5
    if t.get("damage") == "severe":
        score -= 0.5
    return score + float(t.get("confidence", 0.0))
