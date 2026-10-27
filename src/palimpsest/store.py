"""Tiny JSON-backed case store. No database, on purpose: a case is one file
you can keep, diff, and still open in ten years."""

from __future__ import annotations

from pathlib import Path

from .models import Artifact, Case, dump_json, load_json


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.case_path = self.root / "case.json"
        self.media_dir = self.root / "media"
        self.media_dir.mkdir(exist_ok=True)
        self.site_dir = self.root / "site"
        self._case: Case | None = None

    # ---- lifecycle -----------------------------------------------------
    def load(self) -> Case | None:
        if self.case_path.exists():
            self._case = Case.from_dict(load_json(self.case_path))
        return self._case

    @property
    def case(self) -> Case:
        if self._case is None:
            loaded = self.load()
            if loaded is None:
                raise FileNotFoundError(f"no case at {self.case_path}; run `palimpsest scan|recover` first")
            self._case = loaded
        return self._case

    def save(self) -> None:
        dump_json(self.case_path, self.case.to_dict())

    # ---- artifacts -----------------------------------------------------
    def add(self, artifact: Artifact) -> Artifact:
        self.case.artifacts.append(artifact)
        return artifact

    def replace_all(self, artifacts: list[Artifact], target: str) -> Case:
        self._case = Case(target=target, artifacts=artifacts)
        self.save()
        return self._case

    def get(self, artifact_id: str) -> Artifact | None:
        for a in self.case.artifacts:
            if a.id == artifact_id:
                return a
        return None

    def update(self, artifact: Artifact) -> None:
        for i, existing in enumerate(self.case.artifacts):
            if existing.id == artifact.id:
                self.case.artifacts[i] = artifact
                return
        self.case.artifacts.append(artifact)

    def __len__(self) -> int:
        return len(self.case.artifacts)
