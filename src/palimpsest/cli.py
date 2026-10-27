"""Palimpsest command line."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import ablate as ablate_mod
from . import manifest as manifest_mod
from . import pipeline, query, tracing
from .llm import LLM, LLMError
from .store import Store


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def cmd_run(args: argparse.Namespace) -> int:
    config = pipeline.RunConfig(
        target=args.target,
        out=args.out,
        model=args.model,
        embed_model=args.embed_model,
        vision_model=args.vision_model,
        use_llm=not args.no_llm,
        limit=args.limit,
        carve=args.carve,
        threshold=args.threshold,
        narrate_limit=args.narrate_limit,
        vision_limit=args.vision_limit,
        name_repair=not args.no_name_repair,
    )
    report = pipeline.run(config, log=_log)
    print(json.dumps(report.as_dict(), indent=2))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    store = Store(args.out)
    case = store.case
    artifacts = [a for a in case.artifacts if not a.missing]
    vectors, ids = query.load_vectors(store.root / "embeddings")
    if vectors.size == 0:
        print("no embeddings in this case; run without --no-llm first", file=sys.stderr)
        return 2
    llm = LLM(model=args.model, embed_model=args.embed_model)
    try:
        result = query.ask(args.question, artifacts, vectors, ids, llm, top_k=args.top_k)
    except LLMError as exc:
        print(f"model error: {exc}", file=sys.stderr)
        return 2
    print(result["answer"])
    if result["citations"]:
        by_id = {a.id: a for a in artifacts}
        print("\ncited:")
        for cid in result["citations"]:
            artifact = by_id.get(cid)
            if artifact:
                print(f"  [{cid}] {artifact.display_name} — {artifact.cluster or 'unlinked'}")
    return 0


def cmd_ablate(args: argparse.Namespace) -> int:
    result = ablate_mod.compare(args.out)
    print(ablate_mod.format_table(result))
    if args.json:
        print(json.dumps(result, indent=2))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    """Re-render the site from the case on disk.

    No model calls: useful after a template or stylesheet change, and it keeps
    the site a pure function of `case.json`.
    """
    from . import render
    from .link import Cluster
    from .models import Claim

    store = Store(args.out)
    if not store.case.artifacts:
        print(f"no case at {args.out}; run `palimpsest run` first", file=sys.stderr)
        return 2
    clusters = [Cluster.from_dict(c) for c in store.case.notes.get("clusters", [])]
    case_claims = [Claim.from_dict(c) for c in store.case.notes.get("case_claims", [])]
    site = render.render_case(
        store.case,
        store.root,
        clusters=clusters,
        case_claims=case_claims,
        model=args.model,
    )
    print(str(site))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    case = Store(args.out).case
    print(json.dumps(case.stats(), indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    store = Store(args.out)
    path = store.root / "manifest.json"
    if not path.exists():
        print(f"no manifest at {path}; run `palimpsest run` first", file=sys.stderr)
        return 2
    record = manifest_mod.load(path)
    checks = manifest_mod.verify(store.case, record, check_target=not args.no_target)
    print(manifest_mod.format_checks(checks))
    if args.json:
        print(json.dumps(checks, indent=2))
    return 0 if all(c["ok"] for c in checks) else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    tools = ["photorec", "foremost", "fls", "icat", "istat", "exiftool", "ffmpeg", "pdftotext"]
    print("tools")
    missing = []
    for tool in tools:
        path = shutil.which(tool)
        print(f"  {'ok ' if path else '-- '} {tool:<10} {path or 'not found'}")
        if not path:
            missing.append(tool)

    print("\nmodel")
    llm = LLM(model=args.model, embed_model=args.embed_model)
    try:
        models = llm.models()
        print(f"  ok  ollama     {llm.host}")
        for name in models:
            print(f"      - {name}")
        for required in (args.model, args.embed_model):
            present = llm.has_model(required)
            print(f"  {'ok ' if present else '-- '} {required:<20} {'pulled' if present else 'missing'}")
    except Exception as exc:
        print(f"  --  ollama     unreachable: {exc}")

    print("\noptional")
    for module in ("sentry_sdk", "temporalio", "numpy", "jinja2"):
        try:
            __import__(module)
            print(f"  ok  {module}")
        except ImportError:
            print(f"  --  {module} not installed")

    return 1 if missing else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="palimpsest",
        description="Recover deleted files and tell their story, offline.",
    )
    parser.add_argument("--version", action="version", version="palimpsest 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="recover a directory or disk image and build the case site")
    run.add_argument("target", help="directory of files, or a disk image")
    run.add_argument("--out", default="out", help="case directory (default: out)")
    run.add_argument("--model", default="gemma3:4b")
    run.add_argument("--embed-model", default="nomic-embed-text")
    run.add_argument("--vision-model", default=None, help="separate vision model (default: --model)")
    run.add_argument("--vision-limit", type=int, default=8, help="triage only the N most promising images")
    run.add_argument("--no-name-repair", action="store_true", help="skip filename reconstruction")
    run.add_argument("--no-llm", action="store_true", help="factual baseline only (ablation)")
    run.add_argument("--limit", type=int, default=400)
    run.add_argument("--narrate-limit", type=int, default=40)
    run.add_argument("--threshold", type=float, default=0.72)
    run.add_argument("--carve", action="store_true", help="also carve free space with foremost")
    run.set_defaults(func=cmd_run)

    ask = sub.add_parser("ask", help="ask the recovered case a question")
    ask.add_argument("question")
    ask.add_argument("--out", default="out")
    ask.add_argument("--model", default="gemma3:4b")
    ask.add_argument("--embed-model", default="nomic-embed-text")
    ask.add_argument("--top-k", type=int, default=10)
    ask.set_defaults(func=cmd_ask)

    ablate = sub.add_parser("ablate", help="compare the model against the factual baseline")
    ablate.add_argument("--out", default="out")
    ablate.add_argument("--json", action="store_true")
    ablate.set_defaults(func=cmd_ablate)

    render = sub.add_parser("render", help="re-render the site from the case on disk")
    render.add_argument("--out", default="out")
    render.add_argument("--model", default=None, help="label to show in the footer")
    render.set_defaults(func=cmd_render)

    stats = sub.add_parser("stats", help="print case statistics")
    stats.add_argument("--out", default="out")
    stats.set_defaults(func=cmd_stats)

    verify = sub.add_parser("verify", help="re-check hashes, citations and prompt drift")
    verify.add_argument("--out", default="out")
    verify.add_argument("--no-target", action="store_true", help="skip the source image hash")
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(func=cmd_verify)

    doctor = sub.add_parser("doctor", help="check tools and models")
    doctor.add_argument("--model", default="gemma3:4b")
    doctor.add_argument("--embed-model", default="nomic-embed-text")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    tracing.init()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
