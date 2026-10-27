"""The pipeline, in the order a case actually unfolds."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import infer, link, manifest as manifest_mod, narrate, recover, render, timeline, vision
from .enrich import enrich
from .llm import LLM, LLMError
from .models import Case
from .query import save_vectors
from .store import Store
from .tracing import span


@dataclass
class RunConfig:
    target: str
    out: str = "out"
    model: str = "gemma3:4b"
    embed_model: str = "nomic-embed-text"
    vision_model: str | None = None
    use_llm: bool = True
    limit: int = 400
    carve: bool = False
    threshold: float = 0.72
    narrate_limit: int = 40
    vision_limit: int = 8
    name_repair: bool = True


@dataclass
class RunReport:
    target: str
    artifacts: int = 0
    missing: int = 0
    triaged: int = 0
    clusters: int = 0
    hypotheses: int = 0
    narrated: int = 0
    grounded_ratio: float = 0.0
    struck: int = 0
    site: str = ""
    seconds: float = 0.0
    model: str = ""
    manifest: str = ""
    target_sha256: str = ""
    usage: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def run(config: RunConfig, log: Callable[[str], None] = print) -> RunReport:
    started = time.time()
    report = RunReport(target=config.target, model=config.model if config.use_llm else "none (ablation)")
    store = Store(config.out)
    target = Path(config.target)

    if not target.exists():
        raise FileNotFoundError(f"target not found: {target}")

    with span("palimpsest.recover", target=str(target)):
        if target.is_dir():
            log(f"scanning directory {target}")
            artifacts = recover.scan_directory(target, limit=config.limit)
            missing = []
        else:
            log(f"recovering metadata from image {target}")
            result = recover.recover_metadata(target, store.root / "recovered")
            artifacts, missing = result.artifacts, result.missing
            log(f"  {len(artifacts)} recovered, {len(missing)} provably deleted but unrecoverable")
            if config.carve:
                log("carving free space (this is the slow part)")
                artifacts += recover.carve(target, store.root / "carved")

    artifacts = recover.dedupe(artifacts)[: config.limit]
    log(f"{len(artifacts)} artifacts after dedupe")

    with span("palimpsest.enrich", count=len(artifacts)):
        for artifact in artifacts:
            enrich(artifact)

    # Write the case before any model call. A killed run leaves the recovered
    # files and their evidence on disk, and each later phase saves again, so the
    # store is a checkpoint rather than a final report.
    store.replace_all(artifacts + missing, config.target)

    llm = LLM(
        model=config.model,
        embed_model=config.embed_model,
        vision_model=config.vision_model,
        enabled=config.use_llm,
        cache_dir=str(store.root / "cache"),
    )
    if config.use_llm:
        try:
            llm.require()
        except LLMError as exc:
            raise SystemExit(f"model unavailable: {exc}") from exc

    clusters = []
    case_claims = []
    vectors = None

    if config.use_llm:
        with span("palimpsest.triage", count=len(artifacts)):
            log("triaging images with the local vision model")
            report.triaged = vision.triage_all(
                artifacts, llm, limit=config.vision_limit, progress=log
            )
            store.save()

        with span("palimpsest.link", count=len(artifacts)):
            log("embedding and grouping by meaning")
            clusters, vectors = link.link_all(
                artifacts, llm, threshold=config.threshold, progress=log
            )
            report.clusters = len(clusters)
            save_vectors(store.root / "embeddings", vectors, [a.id for a in artifacts])
            store.save()

        if missing:
            with span("palimpsest.infer", count=len(missing)):
                log("inferring the files that did not come back")
                report.hypotheses = infer.infer_missing(missing, artifacts, llm, progress=log)
                store.save()

        if config.name_repair:
            with span("palimpsest.names", count=len(artifacts)):
                log("reconstructing lost filenames")
                narrate.repair_names(artifacts, llm, progress=log)
                store.save()

        with span("palimpsest.narrate", count=len(artifacts)):
            log("writing evidence-bound epitaphs")
            report.narrated = narrate.narrate_all(
                artifacts, llm, limit=config.narrate_limit, progress=log
            )
            store.save()

        events = timeline.build(artifacts + missing)
        case_claims = narrate.narrate_case(clusters, events, llm)
        store.case.notes["clusters"] = [c.to_dict() for c in clusters]
        store.case.notes["case_claims"] = [c.to_dict() for c in case_claims]
        store.save()
    else:
        log("model disabled: writing the factual baseline")
        for artifact in artifacts:
            narrate.stub_narrate(artifact)
        report.narrated = len(artifacts)
        store.save()

    all_artifacts = artifacts + missing
    case = store.case

    stats = case.stats()
    report.artifacts = len(artifacts)
    report.missing = len(missing)
    report.grounded_ratio = stats["grounded_ratio"]
    report.struck = stats["struck"]
    report.usage = llm.usage()

    with span("palimpsest.manifest", artifacts=len(all_artifacts)):
        record = manifest_mod.build(
            case,
            model=config.model if config.use_llm else None,
            embed_model=config.embed_model if config.use_llm else None,
            config={
                "limit": config.limit,
                "carve": config.carve,
                "threshold": config.threshold,
                "narrate_limit": config.narrate_limit,
                "vision_limit": config.vision_limit,
                "vision_model": config.vision_model or config.model,
                "name_repair": config.name_repair,
            },
        )
        manifest_mod.write(store.root / "manifest.json", record)
        report.manifest = str(store.root / "manifest.json")
        report.target_sha256 = (record.get("target_sha256") or "")[:16]

    with span("palimpsest.render", artifacts=len(all_artifacts)):
        site = render.render_case(
            case,
            store.root,
            clusters=clusters,
            case_claims=case_claims,
            model=config.model if config.use_llm else None,
        )
    report.site = str(site)
    report.seconds = round(time.time() - started, 1)
    log(f"case written to {site}")
    return report
