You are naming a group of files recovered from the same disk.

The group was formed because the files are semantically similar: same place,
same people, same subject, same period, or the same kind of document. You get
short descriptions, not the files themselves.

Name it the way a person would label a box of belongings, not the way a
database would. Four words maximum. No quotes, no trailing punctuation.

Return JSON:

{
  "name": "The House on Cedar Street",
  "summary": "one sentence describing what holds the group together",
  "confidence": 0.0
}

If the members have nothing meaningful in common, return
{"name": "", "summary": "", "confidence": 0.0}.
