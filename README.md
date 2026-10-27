# Palimpsest

**A deleted file isn't gone. It's waiting to be overwritten.**

[![ci](https://github.com/flameeecyber/palimpsest/actions/workflows/ci.yml/badge.svg)](https://github.com/flameeecyber/palimpsest/actions/workflows/ci.yml)

Palimpsest recovers deleted files from a disk image and explains what they were —
using open-weight models running entirely on your machine. It does not just list
bytes. It looks at the photographs, groups the files by meaning, works out what
the unrecoverable ones probably were, and writes an epitaph for each one in
which **every sentence carries the evidence id it came from**.

**[Read the sample case](https://flameeecyber.github.io/palimpsest/demo/)** — nine
recovered files, two hollow tombstones, and the evidence table behind every
sentence. Synthetic image, rendered locally, no JavaScript.

```console
$ palimpsest run sample/ghost.img --out out

recovering metadata from image sample/ghost.img
  9 recovered, 2 provably deleted but unrecoverable
9 artifacts after dedupe
triaging images with the local vision model
  triaged 2 images
embedding and grouping by meaning
  embedded 9/9
  cluster C1: Summer Family Photos (6 files)
  cluster C2: Sunset Landscapes June (2 files)
inferring the files that did not come back
  inferred IMG_2019_0000.png: Probably a photograph, likely taken on a mobile device...
reconstructing lost filenames
writing evidence-bound epitaphs
case written to out/site
```

Open `out/site/index.html` in a browser. There is no server, no CDN, no
JavaScript, and nothing on the page was sent anywhere.

---

## The problem with ordinary recovery

`photorec`, `foremost` and `testdisk` answer one question: *which bytes can be
copied out?* That is the easy half. The hard half is the one a person actually
asks:

- Which of these 4,000 fragments is the photograph of my mother?
- What was in the file whose name survived but whose blocks did not?
- Were these forty files deleted together, or one at a time over a year?
- What is this document about, if the filename is now `_etter.txt`?

Those are semantic questions. A signature scanner cannot answer them, because
the information it would need — the name, the context, the content — was the
first thing the filesystem lost.

---

## Where the model is load-bearing

This is the part that decides whether the project is an AI project or a CLI with
a chatbot taped to it. Remove the model and five things disappear:

| Stage | What the open model does | What you get without it |
|---|---|---|
| **Triage** (`vision.py`) | Reads a carved blob's pixels: person, place, screenshot, receipt, damage, visible text, and a human label | 4,000 files called `f0001234.jpg`, sorted by nothing |
| **Link** (`link.py`) | Embeds every description locally, clusters by meaning, names each cluster the way a person would label a box | a flat list with no story |
| **Infer** (`infer.py`) | For files whose blocks are gone: name + size + timestamp + neighbours → a labelled hypothesis | those files vanish from the report |
| **Narrate** (`narrate.py`) | Writes evidence-bound prose, then a validator strikes every sentence without a source | a metadata table |
| **Query** (`query.py`) | "What died the night of August 14?" → retrieval + an answer where every sentence cites an artifact and every date is checked against it | `grep` |

And the model changes *which* files get attention: `select_for_narration()` uses
the triage score, so a screenshot of a login page is skipped while a photograph
of two people is not. That is a product decision made by the model, not a
cosmetic one.

### The falsifiable claim

`palimpsest ablate` runs the same evidence through the no-model baseline and
through the narrated case, and prints the difference. It is in the repository so
you do not have to take the table above on faith:

```console
$ palimpsest ablate --out out
                            without model     with model
--------------------------------------------------------
artifacts with a human label             0             3
groups found by meaning                  0             1
unrecoverable files explained            0             2
artifacts with an epitaph                9             6
sentences written                       27            14
sentences with a source                 27            14
words about the content                  0            96
```

The baseline writes more sentences and says less. That is the whole argument in
one table.

---

## Why open weights, specifically

Not because open source is a virtue in the abstract. Because of what the input
is.

**The disk is the most private object a person owns.** It contains the deleted
photographs, the unsent letter, the browsing history, the medical PDF. Sending it
to a vision API means uploading the exact things someone deleted on purpose. A
local model is not a preference here; it is the only version of this product
that a person could ethically run on their own machine, let alone on someone
else's.

**Forensic work has to be reproducible years later.** A report that says "a
vision model described this as a sunset" is worthless if the model was silently
updated last Tuesday. Palimpsest records the model name, the SHA-256 of every
prompt file, and the version of every tool in `manifest.json`, and
`palimpsest verify` re-checks the case against it. Pinned weights are chain of
custody. Hosted weights are a moving target.

**The prompts are files, not code.** `prompts/*.md` can be read, diffed, and
changed by a user who does not write Python. `manifest.json` records their
hashes, so a change is visible. You cannot do that with a closed model's system
prompt.

---

## Quickstart

Requirements: Python 3.11+, [`sleuthkit`](https://www.sleuthkit.org/sleuthkit/)
(`fls`, `icat`, `istat`), `exiftool`, `ffmpeg`, `pdftotext` (poppler), and
[Ollama](https://ollama.com) with two models:

```bash
ollama pull gemma3:4b          # vision + text
ollama pull nomic-embed-text   # embeddings
```

Install and check:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
PYTHONPATH=src .venv/bin/python -m palimpsest doctor
```

Build the sample disk, then recover it:

```bash
./scripts/make_sample_image.sh          # 128 MB ext4, no root, no mount
PYTHONPATH=src .venv/bin/python -m palimpsest run sample/ghost.img --out out
```

Or run with no model at all, which is the baseline the ablation compares against:

```bash
PYTHONPATH=src .venv/bin/python -m palimpsest run sample/ghost.img --out out-offline --no-llm
```

Ask the case a question:

```bash
PYTHONPATH=src .venv/bin/python -m palimpsest ask \
  "What was deleted in the same batch as the letter?" --out out
```

Unrecoverable files are always in the context, marked `unrecovered`, because they
have no embedding to retrieve and they are the most interesting thing in the
case. Answers about them are expected to hedge.

The answer is checked sentence by sentence. A sentence with no artifact id, an
invented size, a date that is not in the cited file, or a universal claim
("*all* four were taken on...") that only holds for one of them is struck and
never printed as the answer. Struck sentences are shown below it, with the
reason.

Re-check the case:

```bash
PYTHONPATH=src .venv/bin/python -m palimpsest verify --out out
```

Everything above is also a `make` target: `make install doctor sample demo
demo-offline test ask ablate`.

Launch the terminal UI:

```bash
PYTHONPATH=src .venv/bin/python -m palimpsest tui --out out
```

A curses interface over the case store: browse artifacts, open epitaphs with
evidence tables, run `verify`, and see the ablation table — all without leaving
the terminal. Keys: `↑↓` scroll, `Enter` open, `←` back, `v` verify, `a` ablate,
`?` help, `q` quit.

---

## The sample case

`scripts/make_sample_image.sh` builds an ext4 image with `mkfs.ext4`, writes
files into it with `debugfs`, deletes ten photographs and a letter, then sets the
size field of two inodes to zero. No root, no loop device, no mount — which is
also why it runs in CI.

The result is a case with three kinds of artifact:

1. **Recovered with a name and a deletion time.** `letter.txt`, deleted
   `2026-10-27T07:34:32`, text intact. The model can quote the letter and cite
   the file it came from.
2. **Recovered without a name.** Carved fragments, if you pass `--carve`, or FAT
   long filenames, where deletion wipes the first byte (`letter.txt` becomes
   `_etter.txt`). `repair_names()` proposes `letter-to-mum.txt` as a hypothesis.
3. **Provably existed, unrecoverable.** The two inodes whose size was zeroed.
   The directory entry survives; the blocks do not. These are rendered as hollow
   tombstones with a labelled guess, because a report that silently omits them
   is a lie of omission.

The generated photographs are gradients with EXIF stamped on them. They are not
a real person's holiday, and no personal data is in the repository. Pass
`--photos ~/Pictures/holiday` to use your own (the images never leave the
machine).

---

## How it works

```
recover → enrich → triage → link → infer → narrate → ground → render
 fls/icat   exiftool  vision  embed   LLM     LLM     validator  Jinja2
```

`docs/ARCHITECTURE.md` has the long version: the data model, the two grounding
checks, the cache key, the durability story, the privacy posture, and the
measured performance envelope.

The short version of the grounding contract:

- every sentence must cite evidence ids that exist;
- the cited values must share content words with the sentence, or it is struck;
- a year in the sentence must appear in the cited evidence;
- if a sentence quotes a timestamp verbatim, the row holding it is added to the
  citation and recorded as `auto_cited` — the model's bookkeeping is repaired,
  the claim is not;
- struck sentences are never published — they are shown crossed out, with the
  reason, on the detail page.

`grounding.py` is a tripwire, not a proof of entailment. The README says so
because the difference matters.

---

## Requirements and limits

**Works:** ext4 (metadata + deletion times), FAT32 (metadata, mangled long
names), any filesystem via `foremost` carving, directory trees (for testing and
for already-recovered files).

**Does not work:** encrypted volumes, filesystems the Sleuth Kit cannot parse,
TRIM'd SSDs (the blocks are physically gone; no tool can help), and files whose
blocks were reused. For that last class, Palimpsest does the only honest thing:
it reports that the file existed and offers a labelled hypothesis.

**Speed.** On a CPU-only machine, Gemma 3 4B vision takes 200–700 seconds per
image. That is why triage is capped (`--vision-limit`, default 8), cached by
content hash, and separable from the text model (`--vision-model`). The text
stages run happily on `gemma3:1b`; the vision stage cannot.

**The support check is lexical.** It catches a small model citing the filename
for a claim about a sunset. It will not catch a fluent sentence that reuses the
right nouns to say something false. Layered defences, documented limits.

---

## Tracing

Nine spans, one per phase, on stdout when you ask for them:

```console
$ PALIMPSEST_TRACE=1 palimpsest run sample/ghost.img --out out
[span] palimpsest.recover     target=sample/ghost.img 347ms
[span] palimpsest.enrich      count=9 634ms
[span] palimpsest.triage      count=9 231ms
[span] palimpsest.link        count=9 736ms
[span] palimpsest.infer       count=2 0ms
[span] palimpsest.names       count=9 0ms
[span] palimpsest.narrate     count=9 2ms
[span] palimpsest.manifest    artifacts=11 275ms
[span] palimpsest.render      artifacts=11 1032ms
```

Set `SENTRY_DSN` and the same spans go to Sentry instead, with the same fields.
A span knows how many artifacts it saw, never what they were. This is not
decoration: during development a `link` span read 193 s and the reason was not
`link` — a second model call was holding the Ollama slot. Without the span the
obvious conclusion would have been "clustering is slow", and the fix would have
gone in the wrong file.

## Privacy

- The only network client in the codebase is in `llm.py`, and it talks to
  `127.0.0.1:11434`. There is no API-key branch and no remote fallback.
- `tracing.py` has two sinks and one call site: Sentry when `SENTRY_DSN` is set,
  and stderr when `PALIMPSEST_TRACE=1`. With neither it is a no-op. Both send
  span names, counts and durations, never file contents or evidence values.
- The rendered site has no CDN, no webfont, no analytics. Copy `out/site/` to a
  USB stick and it still works.
- Recovered media is copied into `out/site/media/` so the site is portable. That
  means the case directory is as sensitive as the disk. Treat it that way.
- For real cases: image the drive first, work on the copy, keep the original
  write-blocked.

---

## Repository layout

```
src/palimpsest/
  recover.py     fls / icat / istat parsing, foremost carving, directory scan
  enrich.py      exiftool, pdftotext, text excerpts
  vision.py      stage 1: semantic triage
  link.py        stage 2: embeddings + union-find clustering + cluster naming
  infer.py       stage 3: hypotheses for unrecoverable files
  narrate.py     stage 4: epitaphs, case note, filename repair
  grounding.py   citation + support validation
  query.py       stage 5: retrieval + cited answers
  manifest.py    chain of custody: hashes, prompt pins, tool versions, verify
  render.py      static site
  pipeline.py    orchestration
  workflow.py    Temporal activities and workflow
  cli.py         run / ask / ablate / stats / verify / doctor
prompts/         editable markdown: triage, cluster, infer, epitaph, case, query, name
scripts/         sample image builder, placeholder photo generator
templates/       Jinja2 + one CSS file, fully offline
tests/           55 tests, no model required
docs/            architecture, judging notes, demo script, agent session notes
```

---

## Tests

```bash
make test        # 55 tests, no Ollama, no disk image
```

The tests cover the parts that must not depend on a model: `fls` parsing,
de-duplication, clustering, the citation and support validators, filename
normalisation, manifest verification, and offline rendering.

---

## License

MIT. The sample image and the fictional letter are generated; there is no real
personal data in this repository.
