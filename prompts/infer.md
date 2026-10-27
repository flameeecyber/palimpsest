A file existed. We know its name, its size, and when it was deleted, but its
blocks have been overwritten, so it cannot be recovered.

Infer what it most likely was, using the directory it lived in and the files
recovered around it. You are producing a labelled hypothesis, not a fact.

Be conservative. "Unknown" is an acceptable answer and is better than a
confident guess. Never invent a person or an event.

Return JSON:

{
  "hypothesis": "one sentence, e.g. 'Probably a scanned tax document, deleted with fourteen others.'",
  "kind": "photo" | "document" | "audio" | "video" | "archive" | "other",
  "confidence": "low" | "medium" | "high",
  "reasoning": "max 40 words, referring only to the supplied facts"
}
