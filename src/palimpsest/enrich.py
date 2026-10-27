"""Enrichment: pull every fact we can prove out of a recovered file.

exiftool for image metadata, pdftotext for documents, plain reads for text.
Nothing here uses a model; this is the evidence layer the model is forced to
cite.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .models import Artifact

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".sh", ".yml", ".yaml", ".ini", ".cfg", ".eml"}

_EXIF_KEEP = {
    "DateTimeOriginal": "DateTimeOriginal",
    "CreateDate": "CreateDate",
    "ModifyDate": "ModifyDate",
    "Make": "Make",
    "Model": "Model",
    "GPSLatitude": "GPSLatitude",
    "GPSLongitude": "GPSLongitude",
    "ImageWidth": "ImageWidth",
    "ImageHeight": "ImageHeight",
    "MIMEType": "MIMEType",
    "Duration": "Duration",
    "PageCount": "PageCount",
    "FileType": "FileType",
    "Software": "Software",
}


def _iso(value: str) -> str:
    value = str(value).strip()
    m = re.match(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", value)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}:{m.group(6)}"
    return value


def exiftool(path: str | Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["exiftool", "-j", "-n", "-q", "-q", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        data = json.loads(proc.stdout)[0]
    except (json.JSONDecodeError, IndexError, TypeError):
        return {}
    out: dict[str, Any] = {}
    for source, target in _EXIF_KEEP.items():
        if source in data and data[source] not in ("", None):
            value = data[source]
            if isinstance(value, str) and re.match(r"^\d{4}:\d{2}:\d{2}", value):
                value = _iso(value)
            out[target] = value
    return out


def text_excerpt(path: str | Path, limit: int = 1200) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        try:
            proc = subprocess.run(
                ["pdftotext", "-l", "1", "-q", "--", str(path), "-"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return _clean(proc.stdout)[:limit]
        except (OSError, subprocess.SubprocessError):
            pass
        return None
    if suffix in TEXT_SUFFIXES:
        try:
            raw = Path(path).read_bytes()[: limit * 2]
        except OSError:
            return None
        return _clean(raw.decode("utf-8", "replace"))[:limit]
    return None


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def enrich(artifact: Artifact) -> Artifact:
    if artifact.missing or not artifact.recovered_path:
        return artifact
    path = Path(artifact.recovered_path)
    if artifact.kind in {"photo", "video"}:
        artifact.exif.update(exiftool(path))
    elif artifact.kind == "document":
        artifact.exif.update(exiftool(path))

    if not artifact.modified_at:
        artifact.modified_at = artifact.exif.get("ModifyDate") or artifact.exif.get("DateTimeOriginal")
    if not artifact.created_at:
        artifact.created_at = artifact.exif.get("CreateDate")

    if artifact.kind == "document" and artifact.size < 8 * 1024 * 1024:
        artifact.text_excerpt = text_excerpt(path)

    return artifact
