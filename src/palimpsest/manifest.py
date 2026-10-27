"""Chain of custody.

A forensic report is only worth something if someone else can check it later.
That means the report has to say which bytes it came from, which prompts the
model was given, and which version of every tool touched the evidence.

`palimpsest run` writes a manifest next to the case. `palimpsest verify` re-reads
it and re-checks the case: hashes, citations, prompt drift. If a sentence no
longer rests on evidence, verify says so.

This is the practical form of the argument for pinned open weights. A report
produced by a hosted model that was silently updated is not reproducible. A
report produced by `gemma3:4b` at a known digest is.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__, prompts
from .grounding import SUPPORT_THRESHOLD, support_score, uncited_ids
from .models import Case, sha256_file

VERSION_COMMANDS: dict[str, list[str]] = {
    "fls": ["fls", "-V"],
    "icat": ["icat", "-V"],
    "istat": ["istat", "-V"],
    "foremost": ["foremost", "-V"],
    "exiftool": ["exiftool", "-ver"],
    "ffmpeg": ["ffmpeg", "-version"],
    "pdftotext": ["pdftotext", "-v"],
    "debugfs": ["debugfs", "-V"],
}


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


def tool_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, command in VERSION_COMMANDS.items():
        if not shutil.which(command[0]):
            out[name] = "not installed"
            continue
        try:
            proc = subprocess.run(
                command, capture_output=True, text=True, timeout=20
            )
            text = (proc.stdout or "") + (proc.stderr or "")
            out[name] = _first_line(text) or f"exit {proc.returncode}"
        except (OSError, subprocess.SubprocessError) as exc:
            out[name] = f"error: {type(exc).__name__}"
    return out


def prompt_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(prompts.PROMPT_DIR.glob("*.md")):
        hashes[path.stem] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return hashes


def code_hashes() -> dict[str, str]:
    """sha256 of every source module.

    The prompts are pinned because they change behaviour. The code does too.
    Recording both means `verify` can say "this case was written by a different
    build" instead of quietly re-checking it with new rules.
    """
    base = Path(__file__).resolve().parent
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        for path in sorted(base.glob("*.py"))
    }


def build(
    case: Case,
    *,
    model: str | None,
    embed_model: str | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = Path(case.target)
    artifacts = []
    for artifact in case.artifacts:
        entry: dict[str, Any] = {
            "id": artifact.id,
            "name": artifact.display_name,
            "kind": artifact.kind,
            "missing": artifact.missing,
            "size": artifact.size,
            "sha256": artifact.sha256,
            "recovered_path": artifact.recovered_path,
            "claims": len(artifact.claims),
        }
        artifacts.append(entry)

    return {
        "tool": f"palimpsest {__version__}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": str(case.target),
        "target_size": target.stat().st_size if target.is_file() else None,
        "target_sha256": sha256_file(target) if target.is_file() else None,
        "model": model,
        "embed_model": embed_model,
        "prompts": prompt_hashes(),
        "code": code_hashes(),
        "tools": tool_versions(),
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "hostname": os.uname().nodename if hasattr(os, "uname") else "",
        },
        "config": config or {},
        "artifacts": artifacts,
        "counts": case.stats(),
    }


def write(path: str | Path, manifest: dict[str, Any]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------
def _check(ok: bool, label: str, detail: str = "") -> dict[str, Any]:
    return {"ok": ok, "label": label, "detail": detail}


def verify(case: Case, manifest: dict[str, Any], *, check_target: bool = True) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    recorded = {a.get("id"): a for a in manifest.get("artifacts", [])}
    live = {a.id: a for a in case.artifacts}

    checks.append(
        _check(
            set(recorded) == set(live),
            "artifact set matches the manifest",
            f"{len(recorded)} recorded, {len(live)} present",
        )
    )

    # 1. every recovered file still hashes to what the manifest recorded
    for artifact in case.artifacts:
        if artifact.missing or not artifact.recovered_path:
            continue
        path = Path(artifact.recovered_path)
        if not path.is_file():
            checks.append(_check(False, f"{artifact.display_name}: file present", str(path)))
            continue
        actual = sha256_file(path)
        checks.append(
            _check(
                actual == artifact.sha256,
                f"{artifact.display_name}: sha256",
                actual[:16] if actual else "missing",
            )
        )

    # 2. every citation points at evidence that exists
    for artifact in case.artifacts:
        known = {e.id for e in artifact.evidence}
        for claim in artifact.claims:
            missing = [ref for ref in claim.evidence if ref not in known]
            if missing:
                checks.append(
                    _check(
                        False,
                        f"{artifact.display_name}: citation exists",
                        f"unknown ids {missing}",
                    )
                )

    # 3. every published sentence still passes the support check
    for artifact in case.artifacts:
        index = {e.id: e for e in artifact.evidence}
        for claim in artifact.claims:
            if claim.struck:
                continue
            leaked = uncited_ids(claim.text, claim.evidence)
            if leaked:
                checks.append(
                    _check(
                        False,
                        f"{artifact.display_name}: no uncited ids",
                        ", ".join(leaked),
                    )
                )
            values = [index[r].value for r in claim.evidence if r in index]
            score = support_score(claim.text, values)
            ok = claim.confidence == "speculation" or score >= SUPPORT_THRESHOLD
            checks.append(
                _check(
                    ok,
                    f"{artifact.display_name}: sentence supported",
                    f"support {score:.2f}",
                )
            )

    # 4. prompts have not drifted since the case was written
    current = prompt_hashes()
    recorded_prompts = manifest.get("prompts", {})
    if recorded_prompts:
        drift = [
            name
            for name, digest in recorded_prompts.items()
            if current.get(name) != digest
        ]
        checks.append(
            _check(
                not drift,
                "prompts unchanged",
                ", ".join(drift) if drift else f"{len(recorded_prompts)} pinned",
            )
        )

    # 5. the code has not drifted either
    recorded_code = manifest.get("code", {})
    if recorded_code:
        current_code = code_hashes()
        drift = [
            name
            for name, digest in recorded_code.items()
            if current_code.get(name) != digest
        ]
        checks.append(
            _check(
                not drift,
                "code unchanged",
                ", ".join(drift) if drift else f"{len(recorded_code)} modules pinned",
            )
        )

    # 6. the source image is unchanged
    if check_target and manifest.get("target_sha256"):
        target = Path(case.target)
        if not target.is_file():
            checks.append(_check(False, "source image available", str(target)))
        else:
            checks.append(
                _check(
                    sha256_file(target) == manifest["target_sha256"],
                    "source image sha256",
                    manifest["target_sha256"][:16],
                )
            )

    return checks


def format_checks(checks: list[dict[str, Any]]) -> str:
    lines = []
    for check in checks:
        mark = "ok  " if check["ok"] else "FAIL"
        detail = f"  {check['detail']}" if check["detail"] else ""
        lines.append(f"{mark} {check['label']}{detail}")
    failed = sum(1 for c in checks if not c["ok"])
    lines.append("")
    lines.append(f"{len(checks) - failed} passed, {failed} failed")
    return "\n".join(lines)
