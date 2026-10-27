"""Temporal worker for Palimpsest.

    pip install -e '.[temporal]'
    temporal server start-dev          # separate terminal
    python -m palimpsest.worker        # separate terminal
    python -m palimpsest.worker --start sample/ghost.img out

Kill the worker mid-run and restart it: the workflow resumes at the last
completed phase, because every phase checkpoints to the case store on disk.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from .workflow import (
    HAVE_TEMPORAL,
    TASK_QUEUE,
    PalimpsestCase,
    infer_phase,
    link_phase,
    manifest_phase,
    narrate_phase,
    recover_phase,
    render_phase,
    triage_phase,
)

ACTIVITIES = [
    recover_phase,
    triage_phase,
    link_phase,
    infer_phase,
    narrate_phase,
    manifest_phase,
    render_phase,
]


async def serve() -> None:
    from dataclasses import replace

    from temporalio.client import Client
    from temporalio.worker import Worker
    from temporalio.worker.workflow_sandbox import (
        SandboxedWorkflowRunner,
        SandboxRestrictions,
    )

    client = await Client.connect("localhost:7233")
    # The workflow module shares a package with the activities, which read files
    # and call a model. Those imports are never executed inside the workflow
    # body — the body only schedules activities — so the package passes through
    # the sandbox unchanged instead of being re-imported under restrictions.
    restrictions = replace(
        SandboxRestrictions.default,
        passthrough_modules=SandboxRestrictions.default.passthrough_modules | {"palimpsest"},
    )
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[PalimpsestCase],
        activities=ACTIVITIES,
        workflow_runner=SandboxedWorkflowRunner(restrictions=restrictions),
    )
    print(f"worker listening on {TASK_QUEUE}")
    await worker.run()


async def start(target: str, out: str, model: str, *, use_llm: bool, limit: int, narrate_limit: int) -> None:
    from temporalio.client import Client

    client = await Client.connect("localhost:7233")
    handle = await client.start_workflow(
        PalimpsestCase.run,
        {
            "target": target,
            "out": out,
            "model": model,
            "use_llm": use_llm,
            "limit": limit,
            "carve": False,
            "threshold": 0.72,
            "narrate_limit": narrate_limit,
        },
        id=f"palimpsest-{target.replace('/', '-')}",
        task_queue=TASK_QUEUE,
    )
    print(f"started {handle.id}")
    print(json.dumps(await handle.result(), indent=2))


def main() -> None:
    if not HAVE_TEMPORAL:
        raise SystemExit("temporalio is not installed: pip install -e '.[temporal]'")
    parser = argparse.ArgumentParser(prog="palimpsest.worker")
    parser.add_argument("--start", nargs=2, metavar=("TARGET", "OUT"), help="start a case and wait")
    parser.add_argument("--model", default="gemma3:4b")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="run the phases without the model, to test resumption quickly",
    )
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--narrate-limit", type=int, default=40)
    args = parser.parse_args()
    if args.start:
        target, out = args.start
        asyncio.run(
            start(
                target,
                out,
                args.model,
                use_llm=not args.no_llm,
                limit=args.limit,
                narrate_limit=args.narrate_limit,
            )
        )
    else:
        asyncio.run(serve())


if __name__ == "__main__":
    main()
