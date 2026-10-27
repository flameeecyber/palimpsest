"""Render a case as a static, offline site.

No CDN, no fonts fetched, no analytics. You can copy `out/site` to a USB stick
and open it in ten years, which is the whole argument for doing this locally.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Artifact, Case
from .timeline import build as build_timeline
from .timeline import range_label

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"


def human_size(num: int | float) -> str:
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["human_size"] = human_size
    env.filters["short_date"] = lambda value: (value or "")[:10]
    return env


def _thumbnail(source: str, dest: Path, edge: int = 520) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "ffmpeg", "-loglevel", "error", "-y", "-i", source,
                "-vf", f"scale='min({edge},iw)':-2",
                "-q:v", "5", str(dest),
            ],
            check=True,
            timeout=90,
        )
        return dest.exists() and dest.stat().st_size > 0
    except (OSError, subprocess.SubprocessError):
        return False


def _media(artifact: Artifact, site: Path) -> dict[str, str | None]:
    out: dict[str, str | None] = {"thumb": None, "file": None}
    if artifact.missing or not artifact.recovered_path:
        return out
    source = Path(artifact.recovered_path)
    if not source.exists():
        return out
    media_dir = site / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    if artifact.kind == "photo":
        thumb = media_dir / f"{artifact.id}.jpg"
        if _thumbnail(str(source), thumb):
            out["thumb"] = f"media/{thumb.name}"
    elif artifact.kind == "document" and source.suffix.lower() == ".pdf" and source.stat().st_size < 20_000_000:
        dest = media_dir / f"{artifact.id}.pdf"
        shutil.copy2(source, dest)
        out["file"] = f"media/{dest.name}"
    elif artifact.kind in {"audio", "video"} and source.stat().st_size < 40_000_000:
        dest = media_dir / f"{artifact.id}{source.suffix.lower()}"
        shutil.copy2(source, dest)
        out["file"] = f"media/{dest.name}"
    return out


def _claim_view(artifact: Artifact) -> list[dict[str, Any]]:
    index = artifact.evidence_map()
    view = []
    for claim in artifact.claims:
        chips = []
        for ref in claim.evidence:
            item = index.get(ref)
            if item:
                chips.append({"id": ref, "source": item.source, "value": item.value})
        view.append(
            {
                "text": claim.text,
                "confidence": claim.confidence,
                "struck": claim.struck,
                "reason": claim.reason,
                "support": claim.support,
                "chips": chips,
            }
        )
    return view


def render_case(
    case: Case,
    out_root: str | Path,
    clusters: list[Any] | None = None,
    case_claims: list[Any] | None = None,
    model: str | None = None,
) -> Path:
    out_root = Path(out_root)
    site = out_root / "site"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)

    env = _environment()
    timeline = build_timeline(case.artifacts)
    stats = case.stats()

    # enrich stats with the model-derived counts, so the ablation is visible
    stats["clusters"] = len(clusters or [])
    stats["hypotheses"] = sum(1 for a in case.artifacts if a.hypothesis)
    stats["triaged"] = sum(1 for a in case.artifacts if a.triage)
    stats["missing"] = sum(1 for a in case.artifacts if a.missing)
    stats["date_range"] = range_label(timeline)
    stats["model"] = model or "none"
    stats["recovered"] = sum(1 for a in case.artifacts if not a.missing)

    cluster_index = {c.id: c for c in (clusters or [])}
    cards = []
    for artifact in sorted(
        case.artifacts,
        key=lambda a: (a.missing, -(len(a.epitaph) + (2 if a.triage.get("is_personal_memory") else 0))),
    ):
        cluster = cluster_index.get(artifact.cluster_id or "")
        cards.append(
            {
                "artifact": artifact,
                "media": _media(artifact, site),
                "claims": _claim_view(artifact),
                "cluster": cluster,
                "label": artifact.triage.get("label") or artifact.triage.get("subject") or artifact.kind,
            }
        )

    index_html = env.get_template("index.html.j2").render(
        case=case,
        stats=stats,
        cards=cards,
        clusters=clusters or [],
        timeline=timeline,
        case_claims=[
            {"text": c.text, "confidence": c.confidence, "struck": c.struck, "evidence": c.evidence}
            for c in (case_claims or [])
        ],
        model=model,
    )
    (site / "index.html").write_text(index_html, encoding="utf-8")

    artifact_tpl = env.get_template("artifact.html.j2")
    for card in cards:
        artifact = card["artifact"]
        page = artifact_tpl.render(
            case=case,
            artifact=artifact,
            media=card["media"],
            claims=card["claims"],
            cluster=card["cluster"],
            label=card["label"],
            stats=stats,
        )
        (site / f"{artifact.id}.html").write_text(page, encoding="utf-8")

    (site / "assets").mkdir(exist_ok=True)
    shutil.copy2(TEMPLATE_DIR / "style.css", site / "assets" / "style.css")

    payload = {
        "target": case.target,
        "stats": stats,
        "clusters": [c.to_dict() for c in (clusters or [])],
        "timeline": timeline,
        "artifacts": [a.to_dict() for a in case.artifacts],
    }
    (site / "index.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return site
