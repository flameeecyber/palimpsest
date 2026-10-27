"""Recovery.

Two paths, because deleted files die in two different ways:

* metadata path  - the directory entry still exists, so we get the original
                   name, size and (on ext) the deletion time. `fls` + `icat`.
* carving path   - the entry is gone, so we scan free space for file signatures.
                   `foremost`.

The metadata path is the one that produces the gasp: a filename and a deletion
timestamp are worth more than a thousand unnamed fragments.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import Artifact, sha256_file

PHOTO = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".tif", ".tiff", ".bmp", ".avif", ".raw", ".cr2", ".nef"}
DOCUMENT = {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".json", ".xml", ".html", ".eml", ".msg"}
AUDIO = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma", ".opus"}
VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v", ".3gp"}
ARCHIVE = {".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz", ".iso"}

_MAGIC = (
    (b"\xff\xd8\xff", "photo"),
    (b"\x89PNG\r\n\x1a\n", "photo"),
    (b"GIF8", "photo"),
    (b"RIFF", "other"),
    (b"%PDF-", "document"),
    (b"PK\x03\x04", "archive"),
    (b"\x1f\x8b", "archive"),
    (b"ID3", "audio"),
    (b"OggS", "audio"),
    (b"\x00\x00\x00\x18ftyp", "video"),
)


def kind_of(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in PHOTO:
        return "photo"
    if suffix in DOCUMENT:
        return "document"
    if suffix in AUDIO:
        return "audio"
    if suffix in VIDEO:
        return "video"
    if suffix in ARCHIVE:
        return "archive"
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return "other"
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    return "other"


def artifact_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()[:10]


def _iso(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    for fmt in (
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%a %b %d %H:%M:%S %Y",
        "%a %b  %d %H:%M:%S %Y",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return value


@dataclass
class FlsEntry:
    inode: str
    name: str
    path: str
    is_dir: bool
    deleted: bool
    size: int | None = None


@dataclass
class Recovery:
    artifacts: list[Artifact] = field(default_factory=list)
    missing: list[Artifact] = field(default_factory=list)
    notes: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# metadata path
# ---------------------------------------------------------------------------
def parse_fls(output: str) -> list[FlsEntry]:
    entries: list[FlsEntry] = []
    for line in output.splitlines():
        if ":\t" not in line:
            continue
        left, path = line.split(":\t", 1)
        tokens = left.split()
        if not tokens:
            continue
        deleted = "*" in tokens
        inode = None
        for token in reversed(tokens):
            if re.fullmatch(r"\d+(?:-\d+)*", token):
                inode = token
                break
        if inode is None:
            continue
        type_token = tokens[0]
        is_dir = type_token.startswith("d")
        entries.append(
            FlsEntry(
                inode=inode,
                name=Path(path).name,
                path=path,
                is_dir=is_dir,
                deleted=deleted,
            )
        )
    return entries


def deletion_time(image: str | Path, inode: str) -> str | None:
    try:
        out = subprocess.run(
            ["istat", str(image), inode],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("dtime:") or low.startswith("deleted:"):
            raw = stripped.split(":", 1)[1].strip()
            raw = raw.split(" -- ")[-1]
            raw = re.sub(r"\.\d+", "", raw)
            raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw)
            return _iso(raw)
    return None


def recover_metadata(image: str | Path, outdir: str | Path) -> Recovery:
    image = Path(image)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    result = Recovery()

    try:
        listing = subprocess.run(
            ["fls", "-r", "-d", "-p", str(image)],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result.notes["metadata_error"] = str(exc)
        return result

    if listing.returncode != 0:
        result.notes["metadata_error"] = listing.stderr.strip()[:400]
        return result

    entries = [e for e in parse_fls(listing.stdout) if not e.is_dir]
    result.notes["deleted_entries"] = len(entries)

    for entry in entries:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", entry.path)[-120:] or f"inode_{entry.inode}"
        dest = outdir / f"{entry.inode}_{safe}"
        proc = None
        try:
            with open(dest, "wb") as fh:
                proc = subprocess.run(
                    ["icat", str(image), entry.inode],
                    stdout=fh,
                    stderr=subprocess.DEVNULL,
                    timeout=120,
                )
            size = dest.stat().st_size if dest.exists() else 0
        except (OSError, subprocess.SubprocessError):
            size = 0

        if proc is None or proc.returncode != 0 or size == 0:
            dest.unlink(missing_ok=True)
            result.missing.append(
                Artifact(
                    id=artifact_id(f"missing:{image}:{entry.inode}:{entry.path}"),
                    recovered_path="",
                    kind=kind_of(entry.path),
                    original_name=entry.name,
                    inode=entry.inode,
                    deleted_at=deletion_time(image, entry.inode),
                    recovery_method="metadata-missing",
                    missing=True,
                    exif={"parent": str(Path(entry.path).parent)},
                )
            )
            continue

        result.artifacts.append(
            Artifact(
                id=artifact_id(f"{image}:{entry.inode}:{entry.path}"),
                recovered_path=str(dest),
                kind=kind_of(dest),
                original_name=entry.name,
                inode=entry.inode,
                size=size,
                sha256=sha256_file(dest),
                deleted_at=deletion_time(image, entry.inode),
                recovery_method="metadata",
                exif={"parent": str(Path(entry.path).parent)},
            )
        )

    return result


# ---------------------------------------------------------------------------
# carving path
# ---------------------------------------------------------------------------
def carve(image: str | Path, outdir: str | Path, timeout: int = 1800) -> list[Artifact]:
    image = Path(image)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="palimpsest-carve-", dir=str(outdir.parent)))
    artifacts: list[Artifact] = []
    try:
        subprocess.run(
            ["foremost", "-Q", "-i", str(image), "-o", str(work)],
            timeout=timeout,
            check=False,
            capture_output=True,
        )
        for path in sorted(work.rglob("*")):
            if not path.is_file() or path.name == "audit.txt":
                continue
            artifacts.append(
                Artifact(
                    id=artifact_id(f"carved:{image}:{path.name}:{path.stat().st_size}"),
                    recovered_path=str(path),
                    kind=kind_of(path),
                    original_name=None,
                    size=path.stat().st_size,
                    sha256=sha256_file(path),
                    recovery_method="carved",
                )
            )
    except (OSError, subprocess.SubprocessError):
        pass
    return artifacts


# ---------------------------------------------------------------------------
# directory path (already-recovered files, used by the demo and by tests)
# ---------------------------------------------------------------------------
def scan_directory(root: str | Path, limit: int | None = None) -> list[Artifact]:
    root = Path(root)
    artifacts: list[Artifact] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        stat = path.stat()
        artifacts.append(
            Artifact(
                id=artifact_id(str(path.relative_to(root))),
                recovered_path=str(path),
                kind=kind_of(path),
                original_name=path.name,
                size=stat.st_size,
                sha256=sha256_file(path),
                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                created_at=datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds"),
                recovery_method="directory",
                exif={"parent": str(path.parent.relative_to(root))},
            )
        )
        if limit and len(artifacts) >= limit:
            break
    return artifacts


def dedupe(artifacts: Iterable[Artifact]) -> list[Artifact]:
    seen: dict[str, Artifact] = {}
    for artifact in artifacts:
        key = artifact.sha256 or artifact.id
        if key not in seen:
            seen[key] = artifact
        elif artifact.recovery_method == "metadata" and seen[key].recovery_method != "metadata":
            seen[key] = artifact
    return list(seen.values())
