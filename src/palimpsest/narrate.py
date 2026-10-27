"""Stage 4: the epitaph.

Evidence goes in, prose comes out, and a validator deletes every sentence that
cannot point at the fact it came from. The model is allowed to be quiet.
"""

from __future__ import annotations

import re
from typing import Callable

from . import prompts
from .grounding import quotes_content, validate_sentences
from .llm import LLM, LLMError
from .models import Artifact, Claim, Evidence
from .vision import triage_rank

_SYSTEM = (
    "You write short, restrained, evidence-bound epitaphs for recovered files. "
    "You never invent people, places, or events. You return only JSON."
)

_NAME_SYSTEM = "You reconstruct lost filenames from forensic evidence. You return only JSON."

_EXT = {"photo": ".jpg", "document": ".txt", "audio": ".mp3", "video": ".mp4", "archive": ".zip"}

_EXIF_KEYS = (
    # Only what a person would recognise. Width, height, MIME type and the
    # duplicate date fields cost prompt tokens and invite the model to write
    # "exhibits an ImageWidth of 640 pixels" instead of an epitaph.
    "Model",
    "GPSLatitude",
    "GPSLongitude",
)

# The evidence table is read by the model and by the person reading the report.
# "exif:GPSLatitude" is neither English nor useful; "latitude" is both. Renaming
# the source also removes the word "triage" from the model's vocabulary, which
# is the word it kept reaching for.
_PLAIN_SOURCE = {
    "Model": "camera",
    "GPSLatitude": "latitude",
    "GPSLongitude": "longitude",
}


def build_evidence(artifact: Artifact) -> list[Evidence]:
    evidence: list[Evidence] = []

    def add(source: str, value: object, note: str = "") -> None:
        evidence.append(
            Evidence(id=f"E{len(evidence) + 1}", source=source, value=str(value), note=note)
        )

    add("filename", artifact.display_name)
    add("kind", artifact.kind)
    add("size", f"{artifact.size} bytes")
    if artifact.created_at:
        add("created", artifact.created_at)
    if artifact.modified_at:
        add("modified", artifact.modified_at)
    if artifact.deleted_at:
        add("deleted", artifact.deleted_at)

    for key in _EXIF_KEYS:
        if key in artifact.exif and artifact.exif[key] not in (None, ""):
            add(_PLAIN_SOURCE.get(key, key), artifact.exif[key])

    t = artifact.triage
    if t:
        if t.get("label"):
            add("description", t["label"])
        if t.get("subject"):
            add("subject", t["subject"])
        if t.get("text"):
            add("visible text", t["text"])

    if artifact.text_excerpt:
        add("content", artifact.text_excerpt[:300])

    return evidence


def _table(evidence: list[Evidence]) -> str:
    width = max((len(e.source) for e in evidence), default=8)
    return "\n".join(f"{e.id}  {e.source.ljust(width)}  {e.value}" for e in evidence)


def narrate(artifact: Artifact, llm: LLM, *, attempts: int = 2) -> None:
    """Write an epitaph, then let the validator reject it once.

    A small model often gets it wrong on the first pass and gets it right when
    shown the exact reason it was struck. Feeding the rejection back is worth
    one extra call; the alternative is publishing nothing.
    """
    evidence = build_evidence(artifact)
    artifact.evidence = evidence
    # The rules and the worked examples are the system message: they are the
    # same for every artifact, so a local runtime can reuse the cached prompt
    # prefix instead of reprocessing ~700 tokens per call. On a CPU that is the
    # difference between a four-hour case and a one-hour case.
    system = prompts.load("epitaph")
    prompt = prompts.render(
        "epitaph_input",
        EVIDENCE=_table(evidence),
        KIND=artifact.kind,
        NAME=artifact.display_name,
        METHOD=artifact.recovery_method,
    )

    best: list[Claim] = []
    best_score = -1
    for attempt in range(attempts):
        try:
            raw = llm.json_chat(system, prompt, num_predict=320, temperature=0.3)
        except LLMError:
            break
        sentences = raw.get("sentences", []) if isinstance(raw, dict) else []
        if not isinstance(sentences, list):
            break
        claims = validate_sentences(sentences, evidence)
        score = sum(1 for c in claims if not c.struck)
        quoted = quotes_content(claims, evidence)
        if quoted:
            score += 1  # a document that quotes itself beats one that does not
        if score > best_score:
            best, best_score = claims, score
        if claims and all(not c.struck for c in claims) and quoted:
            break
        struck = [c for c in claims if c.struck]
        if not struck and quoted:
            break
        reasons = [f'- "{c.text}" -> {c.reason}' for c in struck]
        if not quoted:
            reasons.append(
                "- no sentence quotes six consecutive words from the content row"
            )
        prompt = (
            prompt
            + "\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED\n"
            + "\n".join(reasons)
            + "\n\nRewrite it. Quote the cited evidence values directly. "
            "Do not mention anything that is not in EVIDENCE."
        )

    artifact.claims = best
    artifact.narration_model = llm.model


def _id_for(evidence: list[Evidence], source: str) -> str | None:
    for e in evidence:
        if e.source == source:
            return e.id
    return None


def stub_narrate(artifact: Artifact) -> None:
    """The no-model baseline.

    Same evidence, no semantics. This is what `palimpsest ablate` compares
    against: the model has to earn its place over this.
    """
    evidence = build_evidence(artifact)
    artifact.evidence = evidence
    claims: list[Claim] = []

    name_id = _id_for(evidence, "filename")
    kind_id = _id_for(evidence, "kind")
    size_id = _id_for(evidence, "size")
    if name_id and kind_id and size_id:
        claims.append(
            Claim(
                text=f"{artifact.display_name} is a {artifact.kind} of {artifact.size} bytes.",
                evidence=[name_id, kind_id, size_id],
                confidence="certain",
            )
        )

    modified_id = _id_for(evidence, "modified")
    deleted_id = _id_for(evidence, "deleted")
    if modified_id:
        claims.append(
            Claim(
                text=f"Its last recorded modification is {artifact.modified_at or artifact.exif.get('DateTimeOriginal')}.",
                evidence=[modified_id],
                confidence="certain",
            )
        )
    if deleted_id:
        claims.append(
            Claim(
                text=f"It was deleted at {artifact.deleted_at}.",
                evidence=[deleted_id],
                confidence="certain",
            )
        )
    artifact.claims = claims


def select_for_narration(artifacts: list[Artifact], limit: int) -> list[Artifact]:
    """Triage decides who gets a eulogy.

    Without this filter a large case produces thousands of near-identical
    sentences about cache files. The model's own triage output is the filter,
    which is another place where removing it changes the product, not just the
    prose.
    """
    candidates = [a for a in artifacts if not a.missing]
    ranked = sorted(candidates, key=triage_rank, reverse=True)
    chosen: list[Artifact] = []
    for artifact in ranked:
        if artifact.triage and not artifact.triage.get("is_personal_memory"):
            if artifact.kind == "photo":
                continue
        chosen.append(artifact)
        if len(chosen) >= limit:
            break
    return chosen


def clean_name(raw: str, kind: str) -> str | None:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw.strip().lower()).strip("-.")
    if not name:
        return None
    if "." not in name:
        name += _EXT.get(kind, "")
    return name[:80]


def repair_names(
    artifacts: list[Artifact],
    llm: LLM,
    *,
    limit: int = 8,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Give a name back to files that lost one.

    Carved files are called f0001234.jpg. FAT deletes the first byte of every
    long filename, so a letter becomes _etter.txt. The model proposes the name a
    person would have used, and the UI shows it as a hypothesis, never as fact.
    """
    candidates = [
        a
        for a in artifacts
        if not a.missing
        and (
            not a.original_name
            or a.original_name.startswith("_")
            or re.match(r"^f\d{3,}", a.original_name)
        )
    ][:limit]

    done = 0
    for artifact in candidates:
        facts = [
            f"kind: {artifact.kind}",
            f"size: {artifact.size} bytes",
        ]
        if artifact.triage:
            facts.append(f"looks like: {artifact.triage.get('label') or artifact.triage.get('subject')}")
        if artifact.text_excerpt:
            facts.append(f"text inside: {artifact.text_excerpt[:200]}")
        if artifact.cluster:
            facts.append(f"recovered near: {artifact.cluster}")
        siblings = [
            a.display_name
            for a in artifacts
            if a is not artifact and a.exif.get("parent") == artifact.exif.get("parent")
        ][:5]
        if siblings:
            facts.append("other files nearby: " + ", ".join(siblings))

        try:
            raw = llm.json_chat(
                _NAME_SYSTEM,
                prompts.load("name") + "\n\nFACTS\n" + "\n".join(facts),
                num_predict=160,
                temperature=0.3,
            )
        except LLMError:
            continue
        if not isinstance(raw, dict):
            continue
        name = clean_name(str(raw.get("name", "")), artifact.kind)
        if name:
            artifact.suggested_name = name
            done += 1
            if progress:
                progress(f"  name repaired: {artifact.display_name} -> {name}")
    return done


def narrate_all(
    artifacts: list[Artifact],
    llm: LLM,
    *,
    limit: int = 60,
    progress: Callable[[str], None] | None = None,
) -> int:
    chosen = select_for_narration(artifacts, limit)
    for i, artifact in enumerate(chosen, start=1):
        narrate(artifact, llm)
        if progress and i % 5 == 0:
            progress(f"  narrated {i}/{len(chosen)}")
    return len(chosen)


def narrate_case(clusters: list, timeline: list[dict], llm: LLM, *, attempts: int = 2) -> list[Claim]:
    """One case note, cited against cluster ids."""
    evidence: list[Evidence] = []
    lines: list[str] = []
    for cluster in clusters:
        evidence.append(
            Evidence(
                id=cluster.id,
                source="cluster",
                value=f"{cluster.name} ({len(cluster.members)} files)",
            )
        )
        lines.append(f"{cluster.id}: {cluster.name} — {cluster.summary or 'no summary'}")
    for event in timeline[:12]:
        eid = f"T{len(evidence) + 1}"
        evidence.append(
            Evidence(id=eid, source="timeline", value=f"{event['date']}: {event['count']} deletions")
        )
        lines.append(f"{eid}: {event['date']} — {event['count']} files deleted")

    if not evidence:
        return []

    prompt = prompts.load("case") + "\n\nFACTS\n" + "\n".join(lines)
    best: list[Claim] = []
    best_score = -1
    for _ in range(attempts):
        try:
            raw = llm.json_chat(_SYSTEM, prompt, num_predict=420, temperature=0.3)
        except LLMError:
            break
        sentences = raw.get("sentences", []) if isinstance(raw, dict) else []
        if not isinstance(sentences, list):
            break
        claims = validate_sentences(
            sentences, evidence, max_sentences=5, style_guard=False
        )
        score = sum(1 for c in claims if not c.struck)
        if score > best_score:
            best, best_score = claims, score
        struck = [c for c in claims if c.struck]
        if not struck or score == len(claims):
            break
        prompt = (
            prompt
            + "\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED\n"
            + "\n".join(f'- "{c.text}" -> {c.reason}' for c in struck)
            + "\n\nRewrite it using only the facts above, quoting their values."
        )
    return best
