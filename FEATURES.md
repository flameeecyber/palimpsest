# Features

Everything below is implemented and exercised by the sample case unless marked
otherwise. The column that matters is the last one: **what disappears if the
model is removed**. A feature that survives `--no-llm` unchanged is filesystem
engineering, not AI, and the README says which is which.

## Recovery

| Feature | Detail | Model-dependent? |
|---|---|---|
| ext4 metadata recovery | `fls -r -d` for deleted entries, `icat` for bytes, `istat` for the `Deleted:` timestamp | no |
| Deletion timestamps | ext4 `dtime`, parsed from `istat`; the only timestamp that tells you *when* a file died rather than when it was last written | no |
| Unrecoverable-file accounting | entries whose blocks are gone are kept as `missing`, with name, size, parent directory and deletion time | no |
| FAT32 recovery | `fls`/`icat`; long filenames lose their first byte on delete (`letter.txt` → `_etter.txt`) | no |
| Carving | `foremost` over free space for artifacts with no directory entry | no |
| Deduplication | SHA-256 keyed; metadata recovery wins over a carved copy of the same bytes | no |
| Directory scan | recover a folder of already-extracted files, for testing and for triage-only runs | no |
| Reproducible sample image | `mkfs.ext4` + `debugfs`, no root, no mount, no loop device; optional simulated block loss | no |

## Model stages

| Feature | Detail | Model-dependent? |
|---|---|---|
| Semantic triage | Gemma 3 vision reads a recovered image: subject, setting, people count, visible text, personal-memory flag, human label, damage, confidence | **yes** |
| Triage ranking | photos with EXIF before screenshots; used to pick which images to triage and which artifacts get narrated | **yes** |
| Semantic clustering | `nomic-embed-text` vectors, L2-normalised, union-find over a cosine graph at a fixed threshold | **yes** |
| Cluster naming | the model names a group the way a person labels a box ("The Last Summer"), with a one-sentence summary | **yes** |
| Missing-file inference | for unrecoverable files: a one-sentence hypothesis, coarse kind, confidence, reasoning, from name/size/date/neighbours | **yes** |
| Evidence-bound epitaphs | 2–4 sentences per artifact, each citing evidence ids | **yes** |
| Validator-in-the-loop retry | a struck sentence is fed back with its exact reason; the best of two attempts is kept | **yes** |
| Citation completion | a sentence that quotes a timestamp verbatim has the row holding it added to its citation, recorded as `auto_cited` | **yes** |
| Case note | 3–5 sentences over cluster ids and deletion-timeline ids | **yes** |
| Filename repair | reconstructs a lost name (`_etter.txt` → `letter-to-mum.txt`) as a labelled hypothesis | **yes** |
| Retrieval Q&A | embed the question, cosine top-k over the case, answer with artifact citations | **yes** |
| Ablation | runs the baseline and the narrated case over the same evidence and prints the delta | no (measures the model) |

## Evidence and integrity

| Feature | Detail |
|---|---|
| Evidence table | every artifact carries `E1…En` with source and value: filename, kind, size, created/modified/deleted, `exif:*`, `triage:*`, content excerpt, cluster |
| Citation existence check | unknown ids are dropped; a sentence left with no ids is struck |
| Support check | fraction of the sentence's content words present in the cited values; below 0.2 the sentence is struck |
| Year check | a year in the sentence must appear verbatim in cited evidence |
| Struck-claim rendering | struck sentences are never published; the detail page shows them crossed out with the reason |
| Confidence labels | `certain` / `probable` / `speculation`, normalised and rendered differently |
| Manifest | source image hash, per-artifact hashes, model names, prompt hashes, tool versions, runtime, config |
| `palimpsest verify` | re-checks artifact set, file hashes, citations, support, prompt drift, code drift and source hash; exit code 1 on failure |
| Content-addressed cache | every model call keyed by model + system + prompt + image bytes; a re-run costs zero calls |
| JSON case store | one `case.json`, no database, diffable, readable in ten years |
| Offline static site | Jinja2 + one CSS file, no CDN, no JS, no analytics, media copied locally |

## Operations

| Feature | Detail |
|---|---|
| `doctor` | checks `fls`, `icat`, `istat`, `foremost`, `exiftool`, `ffmpeg`, `pdftotext`, Ollama reachability, required models, optional Python packages |
| Temporal workflow | six activities (recover, triage, link, infer, narrate, render), retries, heartbeats, resumable after a worker kill |
| Sentry tracing | opt-in spans around every stage; no-op and offline when `SENTRY_DSN` is unset; never sends file contents |
| Separate vision model | `--vision-model` lets a slow 4B vision model coexist with a fast 1B text model |
| Triage cap | `--vision-limit N` bounds the expensive stage without dropping artifacts from the case |
| Name-repair toggle | `--no-name-repair` |
| CLI | `run`, `ask`, `ablate`, `stats`, `verify`, `doctor` |
| Make targets | `install`, `doctor`, `sample`, `demo`, `demo-offline`, `test`, `ask`, `ablate`, `clean` |
| CI | GitHub Actions: compile, 40 tests, offline end-to-end run on a generated image |

## Interface

| Feature | Detail |
|---|---|
| Tombstone grid | each artifact as a headstone; hollow/dashed for unrecoverable files |
| Deletion timeline | per-day counts, bars, mass-deletion days highlighted |
| Cluster cards | model-named groups with summaries and member counts |
| Artifact detail page | epitaph with evidence chips and support percentages, struck sentences with reasons, full evidence table, provenance (SHA-256, inode, path, cluster, model), recovered text, media preview |
| Suggested names | "probably `letter-to-mum.txt`" with an explicit hypothesis label |
| `index.json` | stable machine-readable export of the whole case |

## Deliberately not built

Honesty about scope is part of the submission.

- **No write-back / undelete.** Palimpsest reports; it does not restore to the
  original filesystem. That is a different, riskier product.
- **No live-disk mode.** Everything works on an image or a directory. Mounting a
  live filesystem read-write while recovering is how evidence gets destroyed.
- **No encrypted-volume support.** LUKS/BitLocker/FileVault need a passphrase and
  a different toolchain.
- **No OCR engine.** Visible text comes from the vision model, which is worse
  than Tesseract for dense documents and better for "is there text here at all".
- **No face recognition, no identity inference.** The prompt forbids it, and
  there is no code for it. A tool that recovers deleted photographs of people
  must not also name them.
- **No SSD TRIM recovery.** The blocks are physically gone. Claiming otherwise
  would be a lie.
- **No web upload.** There is no server component on purpose.
