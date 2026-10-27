"""Core data model for Palimpsest.

An Artifact is a recovered file plus everything we can prove about it.
Nothing in `claims` is allowed to exist without an Evidence entry behind it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIDENCE = ("certain", "probable", "speculation")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


@dataclass
class Evidence:
    """A single verifiable fact pulled from the artifact or the filesystem."""

    id: str
    source: str
    value: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "source": self.source, "value": self.value, "note": self.note}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Evidence":
        return cls(
            id=str(d.get("id", "")),
            source=str(d.get("source", "")),
            value=str(d.get("value", "")),
            note=str(d.get("note", "")),
        )


@dataclass
class Claim:
    """One sentence of the epitaph, bound to the evidence that supports it."""

    text: str
    evidence: list[str] = field(default_factory=list)
    confidence: str = "probable"
    struck: bool = False
    reason: str = ""
    support: float = 1.0
    # ids added by citation completion, not by the model
    auto_cited: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "struck": self.struck,
            "reason": self.reason,
            "support": self.support,
            "auto_cited": list(self.auto_cited),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Claim":
        return cls(
            text=str(d.get("text", "")),
            evidence=[str(x) for x in d.get("evidence", [])],
            confidence=str(d.get("confidence", "probable")),
            struck=bool(d.get("struck", False)),
            reason=str(d.get("reason", "")),
            support=float(d.get("support", 1.0) or 1.0),
            auto_cited=[str(x) for x in d.get("auto_cited", [])],
        )


@dataclass
class Artifact:
    id: str
    recovered_path: str
    kind: str = "other"
    original_name: str | None = None
    inode: str | None = None
    size: int = 0
    sha256: str = ""
    deleted_at: str | None = None
    modified_at: str | None = None
    created_at: str | None = None
    exif: dict[str, Any] = field(default_factory=dict)
    text_excerpt: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    recovery_method: str = "directory"  # directory | metadata | carved
    narration_model: str | None = None
    # --- model-derived, load-bearing ---
    triage: dict[str, Any] = field(default_factory=dict)
    cluster: str | None = None
    cluster_id: str | None = None
    missing: bool = False              # provably existed, blocks gone
    hypothesis: str | None = None      # model's labelled guess for a missing file
    hypothesis_confidence: str | None = None
    suggested_name: str | None = None  # model's reconstruction of a lost name

    # ---- derived -------------------------------------------------------
    @property
    def epitaph(self) -> str:
        return " ".join(c.text for c in self.claims if not c.struck)

    @property
    def grounded_ratio(self) -> float:
        if not self.claims:
            return 0.0
        return sum(1 for c in self.claims if not c.struck) / len(self.claims)

    @property
    def display_name(self) -> str:
        return self.original_name or Path(self.recovered_path).name

    def evidence_map(self) -> dict[str, Evidence]:
        return {e.id: e for e in self.evidence}

    # ---- serialisation -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "recovered_path": self.recovered_path,
            "kind": self.kind,
            "original_name": self.original_name,
            "inode": self.inode,
            "size": self.size,
            "sha256": self.sha256,
            "deleted_at": self.deleted_at,
            "modified_at": self.modified_at,
            "created_at": self.created_at,
            "exif": self.exif,
            "text_excerpt": self.text_excerpt,
            "evidence": [e.to_dict() for e in self.evidence],
            "claims": [c.to_dict() for c in self.claims],
            "recovery_method": self.recovery_method,
            "narration_model": self.narration_model,
            "triage": self.triage,
            "cluster": self.cluster,
            "cluster_id": self.cluster_id,
            "missing": self.missing,
            "hypothesis": self.hypothesis,
            "hypothesis_confidence": self.hypothesis_confidence,
            "suggested_name": self.suggested_name,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Artifact":
        return cls(
            id=str(d["id"]),
            recovered_path=str(d.get("recovered_path", "")),
            kind=str(d.get("kind", "other")),
            original_name=d.get("original_name"),
            inode=d.get("inode"),
            size=int(d.get("size", 0) or 0),
            sha256=str(d.get("sha256", "")),
            deleted_at=d.get("deleted_at"),
            modified_at=d.get("modified_at"),
            created_at=d.get("created_at"),
            exif=dict(d.get("exif", {})),
            text_excerpt=d.get("text_excerpt"),
            evidence=[Evidence.from_dict(x) for x in d.get("evidence", [])],
            claims=[Claim.from_dict(x) for x in d.get("claims", [])],
            recovery_method=str(d.get("recovery_method", "directory")),
            narration_model=d.get("narration_model"),
            triage=dict(d.get("triage", {})),
            cluster=d.get("cluster"),
            cluster_id=d.get("cluster_id"),
            missing=bool(d.get("missing", False)),
            hypothesis=d.get("hypothesis"),
            hypothesis_confidence=d.get("hypothesis_confidence"),
            suggested_name=d.get("suggested_name"),
        )


@dataclass
class Case:
    """The whole recovery: one image, one story."""

    target: str
    created_at: str = field(default_factory=utcnow)
    artifacts: list[Artifact] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "created_at": self.created_at,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Case":
        return cls(
            target=str(d.get("target", "")),
            created_at=str(d.get("created_at", utcnow())),
            artifacts=[Artifact.from_dict(x) for x in d.get("artifacts", [])],
            notes=dict(d.get("notes", {})),
        )

    def stats(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for a in self.artifacts:
            kinds[a.kind] = kinds.get(a.kind, 0) + 1
        claims = [c for a in self.artifacts for c in a.claims]
        grounded = [c for c in claims if not c.struck]
        struck = [c for c in claims if c.struck]
        return {
            "artifacts": len(self.artifacts),
            "kinds": kinds,
            "claims": len(claims),
            "grounded": len(grounded),
            "struck": len(struck),
            "grounded_ratio": round(len(grounded) / len(claims), 3) if claims else 0.0,
            "narrated": sum(1 for a in self.artifacts if a.claims),
        }


def dump_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
