"""Stage 3: inference for the files that did not come back.

The filesystem still knows these files existed: name, size, timestamps, the
directory they lived in. Their blocks are gone. Classical recovery reports them
as failures and moves on.

The model is allowed to make one labelled guess about what each one was, using
only the surrounding facts. In the UI they are hollow tombstones: the shape of
something that was there.
"""

from __future__ import annotations

from typing import Callable

from . import prompts
from .llm import LLM, LLMError
from .models import Artifact

_SYSTEM = "You infer what a deleted, unrecoverable file probably was. You return only JSON."


def _context(missing: Artifact, artifacts: list[Artifact], limit: int = 8) -> str:
    parent = str(missing.exif.get("parent", ""))
    siblings = [
        a
        for a in artifacts
        if str(a.exif.get("parent", "")) == parent and a.id != missing.id
    ][:limit]
    lines = [
        f"name: {missing.display_name}",
        f"size: {missing.size} bytes",
        f"deleted_at: {missing.deleted_at or 'unknown'}",
        f"directory: {parent or 'unknown'}",
    ]
    if missing.cluster:
        lines.append(f"nearby cluster: {missing.cluster}")
    if siblings:
        lines.append("recovered in the same directory:")
        for s in siblings:
            descriptor = s.triage.get("label") or s.triage.get("subject") or s.kind
            lines.append(f"- {s.display_name} ({descriptor})")
    return "\n".join(lines)


def infer_missing(
    missing: list[Artifact],
    artifacts: list[Artifact],
    llm: LLM,
    progress: Callable[[str], None] | None = None,
) -> int:
    done = 0
    for item in missing:
        try:
            raw = llm.json_chat(
                _SYSTEM,
                prompts.load("infer") + "\n\nFACTS\n" + _context(item, artifacts),
                num_predict=260,
                temperature=0.2,
            )
        except LLMError:
            continue
        if not isinstance(raw, dict):
            continue
        hypothesis = str(raw.get("hypothesis", "")).strip()
        if not hypothesis:
            continue
        item.hypothesis = hypothesis[:300]
        item.hypothesis_confidence = str(raw.get("confidence", "low")).strip().lower()
        kind = str(raw.get("kind", "")).strip().lower()
        if kind in {"photo", "document", "audio", "video", "archive", "other"}:
            item.kind = kind
        done += 1
        if progress:
            progress(f"  inferred {item.display_name}: {hypothesis[:80]}")
    return done
