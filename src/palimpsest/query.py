"""Stage 5: asking the case questions.

The index is embeddings plus the recovered facts. The answer is generated, but
it must cite artifact ids, and ids that do not exist are dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import prompts
from .llm import LLM, LLMError
from .models import Artifact

_SYSTEM = "You answer questions about recovered files using only the supplied artifacts. You return only JSON."


def _context(artifacts: list[Artifact]) -> str:
    lines = []
    for a in artifacts:
        descriptor = (
            a.epitaph
            or a.hypothesis
            or a.triage.get("label")
            or a.triage.get("subject")
            or a.kind
        )
        lines.append(
            f"[{a.id}] {a.display_name} | {a.kind} | deleted {a.deleted_at or 'unknown'} "
            f"| cluster {a.cluster or 'none'} | {descriptor}"
        )
    return "\n".join(lines)


def ask(
    question: str,
    artifacts: list[Artifact],
    vectors: np.ndarray,
    ids: list[str],
    llm: LLM,
    *,
    top_k: int = 10,
) -> dict:
    by_id = {a.id: a for a in artifacts}
    if vectors.size == 0:
        return {"answer": "No embeddings in this case. Run with the model enabled.", "citations": []}

    query = np.asarray(llm.embed([question])[0], dtype=np.float32)
    norm = np.linalg.norm(query) or 1.0
    scores = vectors @ (query / norm)
    order = np.argsort(-scores)[:top_k]
    chosen = [by_id[ids[i]] for i in order if ids[i] in by_id]

    try:
        raw = llm.json_chat(
            _SYSTEM,
            prompts.load("query") + "\n\nARTIFACTS\n" + _context(chosen) + f"\n\nQUESTION\n{question}",
            num_predict=420,
            temperature=0.2,
        )
    except LLMError as exc:
        return {"answer": f"model error: {exc}", "citations": []}

    if not isinstance(raw, dict):
        return {"answer": "The model returned no usable answer.", "citations": []}
    citations = [str(c) for c in raw.get("citations", []) if str(c) in by_id]
    return {"answer": str(raw.get("answer", "")).strip(), "citations": citations}


def save_vectors(path: str | Path, vectors: np.ndarray, ids: list[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.save(p.with_suffix(".npy"), vectors)
    p.with_suffix(".ids.json").write_text(json.dumps(ids), encoding="utf-8")


def load_vectors(path: str | Path) -> tuple[np.ndarray, list[str]]:
    p = Path(path)
    npy = p.with_suffix(".npy")
    ids = p.with_suffix(".ids.json")
    if not npy.exists() or not ids.exists():
        return np.zeros((0, 0), dtype=np.float32), []
    return np.load(npy), json.loads(ids.read_text(encoding="utf-8"))
