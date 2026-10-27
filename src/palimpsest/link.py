"""Stage 2: semantic linking.

Embeddings of the triage descriptions group files by meaning, not by filename
or extension. That is what turns a list into a case: "the house", "the tax
year", "the last summer".

A keyword search cannot do this. The filenames were the first thing the disk
lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from . import prompts
from .llm import LLM, LLMError
from .models import Artifact


@dataclass
class Cluster:
    id: str
    name: str = ""
    summary: str = ""
    members: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "members": list(self.members),
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Cluster":
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            summary=str(d.get("summary", "")),
            members=[str(m) for m in d.get("members", [])],
            confidence=float(d.get("confidence", 0.0) or 0.0),
        )


def artifact_text(artifact: Artifact) -> str:
    t = artifact.triage
    parts = [
        artifact.display_name,
        artifact.kind,
        t.get("label", ""),
        t.get("subject", ""),
        t.get("setting", ""),
        t.get("text", ""),
        (artifact.text_excerpt or "")[:400],
        artifact.modified_at or "",
        artifact.cluster or "",
    ]
    return " | ".join(str(p) for p in parts if p)


def embed_artifacts(
    artifacts: list[Artifact],
    llm: LLM,
    batch_size: int = 8,
    progress: Callable[[str], None] | None = None,
) -> np.ndarray:
    vectors: list[list[float]] = []
    total = len(artifacts)
    for start in range(0, total, batch_size):
        batch = artifacts[start : start + batch_size]
        vectors.extend(llm.embed([artifact_text(a) for a in batch]))
        if progress:
            progress(f"  embedded {min(start + batch_size, total)}/{total}")
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def cluster_vectors(vectors: np.ndarray, threshold: float = 0.72) -> list[list[int]]:
    """Union-find over a cosine-similarity graph.

    Deliberately simple and inspectable: two artifacts are in the same cluster
    when their descriptions are similar enough, and clusters are the connected
    components. No black box.
    """
    n = len(vectors)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    if n:
        sim = vectors @ vectors.T
        for i in range(n):
            for j in range(i + 1, n):
                if sim[i, j] >= threshold:
                    union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=len, reverse=True)


def _cluster_prompt(artifacts: list[Artifact], members: list[int]) -> str:
    lines = []
    for idx in members[:24]:
        a = artifacts[idx]
        t = a.triage
        descriptor = t.get("label") or t.get("subject") or a.display_name
        lines.append(f"- {a.kind}: {descriptor} ({a.modified_at or 'date unknown'})")
    return "FILES\n" + "\n".join(lines)


def link_all(
    artifacts: list[Artifact],
    llm: LLM,
    *,
    threshold: float = 0.72,
    progress: Callable[[str], None] | None = None,
) -> tuple[list[Cluster], np.ndarray]:
    if not artifacts:
        return [], np.zeros((0, 0), dtype=np.float32)

    vectors = embed_artifacts(artifacts, llm, progress=progress)
    groups = cluster_vectors(vectors, threshold=threshold)

    clusters: list[Cluster] = []
    for number, members in enumerate(groups, start=1):
        if len(members) < 2:
            continue
        cluster = Cluster(id=f"C{number}", members=[artifacts[i].id for i in members])
        try:
            raw = llm.json_chat(
                "You name groups of recovered files. You return only JSON.",
                prompts.load("cluster") + "\n\n" + _cluster_prompt(artifacts, members),
                num_predict=220,
                temperature=0.2,
            )
            if isinstance(raw, dict):
                cluster.name = str(raw.get("name", "")).strip()[:60]
                cluster.summary = str(raw.get("summary", "")).strip()[:200]
                cluster.confidence = float(raw.get("confidence", 0.0) or 0.0)
        except (LLMError, ValueError, TypeError):
            pass

        if not cluster.name:
            cluster.name = f"Unnamed group {number}"
        for idx in members:
            artifacts[idx].cluster_id = cluster.id
            artifacts[idx].cluster = cluster.name
        clusters.append(cluster)
        if progress:
            progress(f"  cluster {cluster.id}: {cluster.name} ({len(members)} files)")

    return clusters, vectors
