"""Evidence-bound generation.

The model may write prose. It may not write facts.

Two checks run on every sentence:

1. Citation exists - the evidence ids it names must be real.
2. Citation supports it - the cited values must actually share vocabulary with
   the sentence. A model that cites E1 for a claim E1 says nothing about gets
   struck, which is the failure mode small models produce most often.

This is the difference between an epitaph you can put in a forensic report and
a hallucination with good lighting.
"""

from __future__ import annotations

import re
from typing import Any

from .models import CONFIDENCE, Claim, Evidence

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_TIMESTAMP = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")
_TOKEN = re.compile(r"[a-z0-9']+")
# Evidence, cluster and timeline ids look like E12, C1, T3. The prompt tells the
# model to cite them in the "evidence" field, never in the prose. This catches a
# model that writes "Evidence E12 indicates..." and cites something else.
_ID_IN_TEXT = re.compile(r"\b([CET]\d{1,3})\b")

# Words that carry no evidential weight. Generic visual nouns are included on
# purpose: "the image shows a photo" must not count as support for anything.
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "from",
    "with", "by", "is", "was", "were", "are", "be", "been", "being", "it", "its",
    "this", "that", "these", "those", "as", "but", "not", "no", "he", "she",
    "they", "them", "his", "her", "their", "you", "we", "i", "had", "has",
    "have", "would", "could", "may", "might", "perhaps", "probably", "appears",
    "seems", "image", "photo", "photograph", "picture", "file", "artifact",
    "depicts", "shows", "showing", "taken", "recovered", "recovery", "data",
    "device", "metadata", "recorded", "indicates", "indicating", "exhibiting",
    "over", "under", "near", "into", "onto", "about", "after", "before", "during",
    "between", "through", "across", "behind", "above", "below", "off", "out", "up",
    "down", "than", "then", "when", "where", "which", "who", "what", "how", "why",
    "all", "any", "some", "more", "most", "other", "such", "only", "also", "very",
    "just", "still", "even", "well", "back", "around",
}

# Words that describe the machinery rather than the file. A 4B model reaches for
# them constantly ("The description indicated a sunset"), so they are checked
# rather than merely forbidden in the prompt.
_META = (
    "metadata",
    "triage",
    "cluster",
    "description",
    "label",
    "evidence",
    "categorized",
    "recovered",
    "artifact",
)


def meta_words(text: str) -> list[str]:
    lowered = text.lower()
    return [word for word in _META if word in lowered]


SUPPORT_THRESHOLD = 0.2


def _tokens(text: str) -> list[str]:
    return [
        t
        for t in _TOKEN.findall(text.lower())
        if (len(t) >= 3 or t.isdigit()) and t not in _STOP
    ]


def _match(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5:
        return a[:5] == b[:5]
    return False


def uncited_ids(text: str, refs: list[str]) -> list[str]:
    """Ids written in the prose that are not in the citation list."""
    return sorted(set(_ID_IN_TEXT.findall(text.upper())) - set(refs))


# Preference order when a bare year is quoted and several rows contain it.
_DATE_SOURCES = ("created", "modified", "deleted")


def complete_citations(text: str, refs: list[str], evidence: list[Evidence]) -> list[str]:
    """Add rows that a sentence quotes verbatim but did not cite.

    A 4B model writes "was created on 2019-06-16T18:24:01 with an iPhone 8" and
    cites the filename and the camera model, skipping the row that actually
    holds the timestamp. The sentence is still true and still checkable: the
    timestamp appears character for character in exactly one row. Adding that
    row is citation completion, not forgiveness — the sentence is re-validated
    against the widened citation immediately afterwards, and every id added here
    is recorded on the claim as `auto_cited` so the report never pretends the
    model cited it.
    """
    added: list[str] = []

    def add(entry: Evidence) -> None:
        if entry.id not in refs:
            refs.append(entry.id)
            added.append(entry.id)

    for stamp in _TIMESTAMP.findall(text):
        holders = [e for e in evidence if stamp in e.value]
        if len(holders) == 1:
            add(holders[0])

    for match in _YEAR.finditer(text):
        year = match.group(0)
        if any(year in e.value for e in evidence if e.id in refs):
            continue
        holders = [e for e in evidence if year in e.value]
        if not holders:
            continue
        holders.sort(
            key=lambda e: _DATE_SOURCES.index(e.source) if e.source in _DATE_SOURCES else 99
        )
        add(holders[0])

    return added


def support_score(text: str, cited_values: list[str]) -> float:
    """Fraction of the sentence's content words that appear in what it cites.

    Crude, deterministic, and enough to catch a 1B model citing the filename for
    a claim about a sunset. Not a semantic entailment check: it is a tripwire,
    and the UI says so.
    """
    tokens = _tokens(text)
    if not tokens:
        return 1.0
    evidence_tokens = _tokens(" ".join(cited_values))
    if not evidence_tokens:
        return 0.0
    hits = sum(1 for token in tokens if any(_match(token, e) for e in evidence_tokens))
    return hits / len(tokens)


def validate_sentences(
    raw_sentences: list[dict[str, Any]],
    evidence: list[Evidence],
    *,
    max_sentences: int = 4,
    style_guard: bool = True,
) -> list[Claim]:
    index = {e.id: e for e in evidence}
    claims: list[Claim] = []

    for raw in raw_sentences[:max_sentences]:
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        refs = [str(r).strip().upper() for r in raw.get("evidence", [])]
        refs = [r for r in refs if r in index]
        confidence = str(raw.get("confidence", "probable")).strip().lower()
        if confidence not in CONFIDENCE:
            confidence = "probable"

        support = 0.0
        struck = False
        reason = ""
        auto_cited: list[str] = []

        if not refs:
            struck = True
            reason = "no evidence cited"
        else:
            # Complete the citation before judging it: a sentence that quotes a
            # timestamp verbatim has already told us which row it came from.
            auto_cited = complete_citations(text, refs, evidence)
            support = support_score(text, [index[r].value for r in refs])

        if not struck:
            jargon = meta_words(text) if style_guard else []
            if leaked := uncited_ids(text, refs):
                struck = True
                reason = "mentions ids it does not cite: " + ", ".join(leaked)
            elif jargon:
                struck = True
                reason = "talks about the tool, not the file: " + ", ".join(jargon)
            elif confidence != "speculation":
                cited = " ".join(index[r].value for r in refs)
                for match in _YEAR.finditer(text):
                    if match.group(0) not in cited:
                        struck = True
                        reason = f"year {match.group(0)} not present in cited evidence"
                        break
                if not struck and support < SUPPORT_THRESHOLD:
                    struck = True
                    reason = f"cited evidence does not support this sentence (support {support:.2f})"

        claims.append(
            Claim(
                text=text,
                evidence=refs,
                confidence=confidence,
                struck=struck,
                reason=reason,
                support=round(support, 3),
                auto_cited=auto_cited,
            )
        )
    return claims


def grounded_ratio(claims: list[Claim]) -> float:
    if not claims:
        return 0.0
    return sum(1 for c in claims if not c.struck) / len(claims)


def quotes_content(claims: list[Claim], evidence: list[Evidence], *, n: int = 6) -> bool:
    """Does any published sentence quote n consecutive words from a content row?

    Rule 8 of the prompt asks for it; this checks it. Without the check the model
    satisfied the rule by quoting the single word "Mum," — true, cited, and not
    the sentence the file actually wrote.
    """
    content = [e.value for e in evidence if e.source == "content"]
    if not content:
        return True
    words = _TOKEN.findall(" ".join(c.text for c in claims if not c.struck).lower())
    for value in content:
        source = _TOKEN.findall(value.lower())
        for i in range(len(source) - n + 1):
            gram = source[i : i + n]
            for j in range(len(words) - n + 1):
                if words[j : j + n] == gram:
                    return True
    return False
