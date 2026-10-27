"""Stage 5: asking the case questions.

The index is embeddings plus the recovered facts. The answer is generated, but
it is checked the same way an epitaph is: every sentence must cite a real
artifact, and the numbers, dates and quotations it asserts must be present in
what it cites.

The check exists because the first real answer to a real question said the
four photographs "were all created on June 20th, 2019". One of them was. The
citations were correct and the claim was false, which is the failure mode that
matters: a citation is not a check.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from . import prompts
from .llm import LLM, LLMError
from .models import Artifact
from .narrate import build_evidence

_SYSTEM = "You answer questions about recovered files using only the supplied artifacts. You return only JSON."

_CITE = re.compile(r"\[([0-9a-f]{6,})\]", re.I)
# Same shapes grounding uses for epitaphs, with non-capturing groups so findall
# returns strings rather than tuples.
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_TIMESTAMP = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_NUMBER = re.compile(r"\b\d{3,}\b")
_QUOTE = re.compile(r"[\"“]([^\"”]{12,})[\"”]")
_UNIVERSAL = re.compile(r"\b(all|every|each|both|none|neither)\b", re.I)

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_DAY = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I
)


def _facts(artifact: Artifact) -> str:
    return " ".join(e.value for e in build_evidence(artifact))


def _literals(text: str) -> list[tuple[str, str]]:
    """Return (kind, needle) for everything in the sentence that can be checked.

    A needle is a substring that has to appear in the cited facts. Dates are
    normalised to the `-MM-DD` fragment so "June 20th" can be found in
    `2019-06-20T18:28:01`.
    """
    found: list[tuple[str, str]] = []
    for stamp in _TIMESTAMP.findall(text):
        found.append(("date", stamp))
    for year in _YEAR.findall(text):
        found.append(("year", year))
    for month, day in _MONTH_DAY.findall(text):
        found.append(("date", f"-{_MONTHS[month.lower()]:02d}-{int(day):02d}"))
    for number in _NUMBER.findall(text):
        found.append(("number", number))
    for quote in _QUOTE.findall(text):
        found.append(("quote", quote.strip()))
    return found


def check_answer(answer: str, by_id: dict[str, Artifact]) -> list[dict]:
    """Split the answer into sentences and check each one against its citations.

    A universal claim ("all four were taken on...") is held to a universal
    standard: the fact must hold for every artifact the sentence cites. That is
    the only rule that catches the failure this check was written for.
    """
    facts = {aid: _facts(a) for aid, a in by_id.items()}
    verdicts: list[dict] = []
    for sentence in _SENTENCE.split(answer.strip()):
        text = sentence.strip()
        if not text:
            continue
        refs = [r for r in dict.fromkeys(_CITE.findall(text)) if r in by_id]
        verdict = {"text": text, "cited": refs, "ok": True, "reason": ""}
        if not refs:
            verdict["ok"] = False
            verdict["reason"] = "cites no artifact"
            verdicts.append(verdict)
            continue

        universal = bool(_UNIVERSAL.search(text))
        for kind, needle in _literals(text):
            holders = [r for r in refs if needle in facts[r]]
            if universal:
                if len(holders) != len(refs):
                    missing = [r for r in refs if r not in holders]
                    verdict["ok"] = False
                    verdict["reason"] = (
                        f"{kind} {needle!r} is not true of every cited file "
                        f"({', '.join(missing)})"
                    )
                    break
            elif not holders:
                verdict["ok"] = False
                verdict["reason"] = f"{kind} {needle!r} is not in any cited file"
                break
        verdicts.append(verdict)
    return verdicts


def _context(artifacts: list[Artifact]) -> str:
    lines = []
    for a in artifacts:
        descriptor = (
            a.epitaph
            or a.hypothesis
            or a.triage.get("label")
            or a.triage.get("subject")
            or a.kind
        )
        lines.append(
            f"[{a.id}] {a.display_name} | {a.kind} | deleted {a.deleted_at or 'unknown'} "
            f"| created {a.created_at or 'unknown'} | cluster {a.cluster or 'none'} "
            f"| {descriptor}"
        )
    return "\n".join(lines)


def ask(
    question: str,
    artifacts: list[Artifact],
    vectors: np.ndarray,
    ids: list[str],
    llm: LLM,
    *,
    top_k: int = 10,
    attempts: int = 2,
) -> dict:
    by_id = {a.id: a for a in artifacts}
    if vectors.size == 0:
        return {"answer": "No embeddings in this case. Run with the model enabled.", "citations": []}

    query = np.asarray(llm.embed([question])[0], dtype=np.float32)
    norm = np.linalg.norm(query) or 1.0
    scores = vectors @ (query / norm)
    order = np.argsort(-scores)[:top_k]
    chosen = [by_id[ids[i]] for i in order if ids[i] in by_id]

    prompt = (
        prompts.load("query")
        + "\n\nARTIFACTS\n"
        + _context(chosen)
        + f"\n\nQUESTION\n{question}"
    )

    best: dict = {"answer": "", "citations": [], "sentences": []}
    best_kept = -1
    for attempt in range(attempts):
        try:
            raw = llm.json_chat(_SYSTEM, prompt, num_predict=420, temperature=0.2)
        except LLMError as exc:
            if best["answer"]:
                break
            return {"answer": f"model error: {exc}", "citations": []}

        if not isinstance(raw, dict):
            break
        answer = str(raw.get("answer", "")).strip()
        verdicts = check_answer(answer, by_id)
        kept = [v for v in verdicts if v["ok"]]
        dropped = [v for v in verdicts if not v["ok"]]
        citations = [str(c) for c in raw.get("citations", []) if str(c) in by_id]

        if len(kept) > best_kept:
            best_kept = len(kept)
            # A model often cites inline and leaves the JSON list empty. The
            # inline ids are the ones the check just verified, so they win.
            inline = [r for v in kept for r in v["cited"]]
            best = {
                "answer": " ".join(v["text"] for v in kept).strip(),
                "citations": list(dict.fromkeys(inline or citations)),
                "sentences": verdicts,
                "struck": dropped,
            }
        if not dropped:
            break
        prompt = (
            prompt
            + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED\n"
            + "\n".join(f'- "{v["text"]}" -> {v["reason"]}' for v in dropped)
            + "\n\nRewrite it. Every sentence must cite the artifact ids it uses. "
            "If you are not sure a fact holds for every file, name the file it "
            "does hold for."
        )

    if not best["answer"]:
        best["answer"] = "The recovered data does not answer that."
    return best


def save_vectors(path: str | Path, vectors: np.ndarray, ids: list[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.save(p.with_suffix(".npy"), vectors)
    p.with_suffix(".ids.json").write_text(json.dumps(ids), encoding="utf-8")


def load_vectors(path: str | Path) -> tuple[np.ndarray, list[str]]:
    p = Path(path)
    npy = p.with_suffix(".npy")
    ids = p.with_suffix(".ids.json")
    if not npy.exists() or not ids.exists():
        return np.zeros((0, 0), dtype=np.float32), []
    return np.load(npy), json.loads(ids.read_text(encoding="utf-8"))
