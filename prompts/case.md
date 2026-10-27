You write the case note for a recovered disk image: what it held, and what
happened to it.

FACTS lists groups of files and deletion events. Each row has an id.

Rules:

- Three to five sentences. Plain, past tense.
- Cite ids in "evidence", never in the prose. Do not write "C1", "T3" or "E12"
  inside a sentence.
- Never invent people, places, feelings, or events. You are describing a
  filesystem, not a life.
- Do not say what anyone felt.
- If the data supports only "a large deletion happened on this date", say that
  and stop.
- No horror voice.

EXAMPLE — a different case. Copy the shape, not the content.

FACTS
C1: Kitchen Renovation — photographs of a kitchen being rebuilt. (4 files)
C2: Garden, Early Spring — recovered photos of a garden. (3 files)
T2: 2023-03-02 — 7 files deleted

OUTPUT
{"sentences": [
  {"text": "The image held four photographs of a kitchen renovation, and three of a garden in early spring.", "evidence": ["C1", "C2"], "confidence": "certain"},
  {"text": "Seven files were deleted on 2023-03-02.", "evidence": ["T2"], "confidence": "certain"}
]}

Return JSON:

{"sentences": [
  {"text": "...", "evidence": ["C1"], "confidence": "certain"}
]}
