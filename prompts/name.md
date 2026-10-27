A recovered file has lost its name.

You get everything that survived: the kind of file, its size, what it looked
like, any text inside it, and the names of files recovered beside it.

Propose the name a person would have given it. This is a hypothesis, not a
recovery: it will be shown to the user as "probably ...".

Rules:
- Lowercase, words joined by hyphens, keep a sensible extension.
- Describe the content, not the recovery ("sunset-over-the-sea.jpg", not
  "recovered-photo-1.jpg").
- Do not include a person's name. You do not know who is in the picture.
- If there is not enough to go on, return an empty name.

Return JSON:

{"name": "sunset-over-the-sea.jpg", "confidence": 0.0}
