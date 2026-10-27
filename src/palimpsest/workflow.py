"""Temporal workflow: a case that survives being killed.

Carving a 64 GB image takes hours. Narration is hundreds of model calls. If the
worker dies at hour three, the case must resume, not restart.

Each activity is a phase that reads and writes the on-disk case store, so the
store is the checkpoint. Run the worker, kill it mid-carve, start it again, and
the workflow continues from the last completed phase.

    pip install temporalio
    temporal server start-dev
    python -m palimpsest.worker
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

from . import infer, link, manifest as manifest_mod, narrate, pipeline, render, timeline, vision
from .enrich import enrich
from .link import Cluster
from .llm import LLM
from .models import Claim
from .query import save_vectors
from .recover import carve, dedupe, recover_metadata, scan_directory
from .store import Store

try:  # pragma: no cover - exercised only when temporalio is installed
    from temporalio import activity, workflow
    from temporalio.common import RetryPolicy

    HAVE_TEMPORAL = True
except ImportError:  # pragma: no cover
    HAVE_TEMPORAL = False

    class _Decorator:
        def defn(self, _cls=None):
            def wrap(cls):
                return cls

            return wrap

        def run(self, fn):
            return fn

        def defn_method(self, fn):
            return fn

    activity = _Decorator()  # type: ignore[assignment]
    workflow = _Decorator()  # type: ignore[assignment]
    RetryPolicy = None  # type: ignore[assignment]


TASK_QUEUE = "palimpsest"


def _config(raw: dict[str, Any]) -> pipeline.RunConfig:
    return pipeline.RunConfig(**raw)


def _load(out: str) -> Store:
    store = Store(out)
    store.load()
    return store


def _clusters(store: Store) -> list[Cluster]:
    return [
        Cluster(
            id=str(c.get("id", "")),
            name=str(c.get("name", "")),
            summary=str(c.get("summary", "")),
            members=[str(m) for m in c.get("members", [])],
            confidence=float(c.get("confidence", 0.0) or 0.0),
        )
        for c in store.case.notes.get("clusters", [])
    ]


def _claims(store: Store) -> list[Claim]:
    return [Claim.from_dict(c) for c in store.case.notes.get("case_claims", [])]


@activity.defn
async def recover_phase(raw: dict[str, Any]) -> dict[str, Any]:
    config = _config(raw)
    store = _load(config.out)
    target = config.target

    if Path(target).is_dir():
        artifacts = await asyncio.to_thread(scan_directory, target, config.limit)
        missing = []
    else:
        result = await asyncio.to_thread(
            recover_metadata, target, str(store.root / "recovered")
        )
        artifacts, missing = result.artifacts, result.missing
        if config.carve:
            carved = await asyncio.to_thread(
                carve, target, str(store.root / "carved")
            )
            artifacts += carved

    artifacts = dedupe(artifacts)[: config.limit]
    for artifact in artifacts:
        enrich(artifact)
    case = store.replace_all(artifacts + missing, target)
    return {"artifacts": len(artifacts), "missing": len(missing), "target": target}


@activity.defn
async def triage_phase(raw: dict[str, Any]) -> dict[str, Any]:
    config = _config(raw)
    store = _load(config.out)
    if not config.use_llm:
        return {"triaged": 0, "skipped": "model disabled"}
    llm = LLM(model=config.model, embed_model=config.embed_model, cache_dir=str(store.root / "cache"))
    artifacts = [a for a in store.case.artifacts if not a.missing]
    done = await asyncio.to_thread(vision.triage_all, artifacts, llm)
    store.save()
    activity.heartbeat({"triaged": done})
    return {"triaged": done}


@activity.defn
async def link_phase(raw: dict[str, Any]) -> dict[str, Any]:
    config = _config(raw)
    store = _load(config.out)
    if not config.use_llm:
        return {"clusters": 0, "skipped": "model disabled"}
    llm = LLM(model=config.model, embed_model=config.embed_model, cache_dir=str(store.root / "cache"))
    artifacts = [a for a in store.case.artifacts if not a.missing]
    clusters, vectors = await asyncio.to_thread(
        link.link_all, artifacts, llm, threshold=config.threshold
    )
    save_vectors(store.root / "embeddings", vectors, [a.id for a in artifacts])
    store.case.notes["clusters"] = [c.to_dict() for c in clusters]
    store.save()
    activity.heartbeat({"clusters": len(clusters)})
    return {"clusters": len(clusters)}


@activity.defn
async def infer_phase(raw: dict[str, Any]) -> dict[str, Any]:
    config = _config(raw)
    store = _load(config.out)
    if not config.use_llm:
        return {"hypotheses": 0, "skipped": "model disabled"}
    llm = LLM(model=config.model, embed_model=config.embed_model, cache_dir=str(store.root / "cache"))
    recovered = [a for a in store.case.artifacts if not a.missing]
    missing = [a for a in store.case.artifacts if a.missing]
    done = await asyncio.to_thread(infer.infer_missing, missing, recovered, llm)
    store.save()
    return {"hypotheses": done}


@activity.defn
async def narrate_phase(raw: dict[str, Any]) -> dict[str, Any]:
    config = _config(raw)
    store = _load(config.out)
    artifacts = [a for a in store.case.artifacts if not a.missing]
    if not config.use_llm:
        for artifact in artifacts:
            narrate.stub_narrate(artifact)
        store.case.notes["case_claims"] = []
        store.save()
        return {"narrated": len(artifacts), "baseline": True}
    llm = LLM(model=config.model, embed_model=config.embed_model, cache_dir=str(store.root / "cache"))
    done = await asyncio.to_thread(
        narrate.narrate_all, artifacts, llm, limit=config.narrate_limit
    )
    events = timeline.build(store.case.artifacts)
    store.case.notes["case_claims"] = [
        c.to_dict() for c in narrate.narrate_case(_clusters(store), events, llm)
    ]
    store.save()
    activity.heartbeat({"narrated": done})
    return {"narrated": done}


@activity.defn
async def manifest_phase(raw: dict[str, Any]) -> dict[str, Any]:
    """Chain of custody, written by the workflow too.

    The CLI writes a manifest at the end of `run`. A case built through Temporal
    has to produce the same artifact, or `palimpsest verify` cannot check it.
    """
    config = _config(raw)
    store = _load(config.out)
    record = manifest_mod.build(
        store.case,
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
    path = store.root / "manifest.json"
    manifest_mod.write(path, record)
    activity.heartbeat({"manifest": str(path)})
    return {"manifest": str(path), "sha256": (record.get("target_sha256") or "")[:16]}


@activity.defn
async def render_phase(raw: dict[str, Any]) -> dict[str, Any]:
    config = _config(raw)
    store = _load(config.out)
    site = await asyncio.to_thread(
        render.render_case,
        store.case,
        store.root,
        clusters=_clusters(store),
        case_claims=_claims(store),
        model=config.model,
    )
    return {"site": str(site)}


if HAVE_TEMPORAL:

    @workflow.defn
    class PalimpsestCase:
        @workflow.run
        async def run(self, raw: dict[str, Any]) -> dict[str, Any]:
            retry = RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=3,
            )
            common = {
                "start_to_close_timeout": timedelta(hours=6),
                "retry_policy": retry,
            }
            await workflow.execute_activity(recover_phase, raw, **common)
            await workflow.execute_activity(
                triage_phase, raw, heartbeat_timeout=timedelta(minutes=5), **common
            )
            await workflow.execute_activity(
                link_phase, raw, heartbeat_timeout=timedelta(minutes=5), **common
            )
            await workflow.execute_activity(infer_phase, raw, **common)
            await workflow.execute_activity(
                narrate_phase, raw, heartbeat_timeout=timedelta(minutes=10), **common
            )
            await workflow.execute_activity(manifest_phase, raw, **common)
            return await workflow.execute_activity(render_phase, raw, **common)

else:  # pragma: no cover

    class PalimpsestCase:  # type: ignore[no-redef]
        """Placeholder when temporalio is not installed."""

        async def run(self, raw: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("install temporalio to run the durable workflow")
