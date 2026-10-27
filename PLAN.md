# Plan

This file is the engineering plan behind the submission: what had to be true,
what was built in which order, what was cut, and what happens next.

## 1. The constraint that shaped everything

The challenge is "Ghost in the Machine" and the deadline is four days. The
temptation is a haunted chatbot. The problem with a haunted chatbot is that the
model is a costume: you can replace it with a script and the product is
unchanged.

So the design brief was narrower and harder:

> Build something where the model is the only way to answer the user's question,
> and where removing it is a measurable regression.

Deleted-file recovery fits because the classical tools stop exactly where
semantics begin. `photorec` can hand you 4,000 unnamed fragments. It cannot tell
you which one is the photograph of your mother. That gap is the product.

## 2. Success criteria

Written before the code, used to decide what to cut.

| # | Criterion | How it is demonstrated |
|---|---|---|
| 1 | The model does work no classical tool can do | triage, clustering, inference, narration, query — five stages, each with a no-model fallback |
| 2 | The model's contribution is measurable | `palimpsest ablate` prints the delta on the same evidence |
| 3 | The output is trustworthy | every sentence cites evidence ids; two automated checks; struck sentences are never published |
| 4 | The output is reproducible | `manifest.json` pins hashes, prompts and tool versions; `palimpsest verify` re-checks |
| 5 | It runs with the network off | localhost-only model client; no CDN in the rendered site; `--no-llm` path works |
| 6 | It is honest about failure | unrecoverable files are reported as hollow tombstones, not omitted; limitations are documented |
| 7 | A stranger can run it | one script builds the sample image; `make demo` runs end to end |

## 3. Build order

The order was chosen so that the riskiest thing was proven first.

### Phase 0 — prove recovery without root (half a day)

- `mkfs.ext4` + `debugfs` to build a disk image with no mount and no loop device.
- `fls -r -d`, `icat`, `istat` to recover deleted entries and read the ext4
  deletion timestamp.
- Confirm that `set_inode_field <ino> size 0` produces a file that still has a
  directory entry and no recoverable bytes. This is the "provably existed, gone"
  class the whole story depends on.

**Why first:** if deletion timestamps or the missing-file class did not work, the
project had no emotional payload and no reason to exist.

### Phase 1 — the evidence layer (half a day)

- `Artifact`, `Evidence`, `Claim`, `Case` dataclasses.
- `enrich.py`: exiftool, pdftotext, text excerpts.
- JSON case store, one file, no database.
- `stub_narrate()`: the factual baseline, written before the model path so the
  ablation would be a fair comparison rather than a strawman.

**Why before the model:** the baseline defines the floor. Writing it first
prevents the model path from quietly becoming the only path.

### Phase 2 — the five model stages (one day)

Built in dependency order, each with a disk cache:

1. `vision.py` — triage, with downscaling and a hero-image cap.
2. `link.py` — embeddings, union-find clustering, cluster naming.
3. `infer.py` — hypotheses for unrecoverable files.
4. `narrate.py` — epitaphs, case note, filename repair.
5. `query.py` — retrieval and cited answers.

### Phase 3 — grounding (half a day)

This was the part that changed the most, because the first version was too weak.

- v1 checked only that cited ids existed. `gemma3:1b` immediately produced
  "the image depicts a sunset over the sea" citing a filename, and v1 published
  it.
- v2 added `support_score()`: the fraction of the sentence's content words that
  appear in the cited values, with a stoplist for function words and generic
  visual nouns. That struck the sentence.
- v3 added the year check and the struck-claim UI, so the failure is visible
  rather than silently deleted.

The lesson is in the repo: a citation is not support. Both checks are needed.

### Phase 4 — the case site (half a day)

- Jinja2 templates, one CSS file, no external assets.
- Tombstone grid, hollow tombstones for missing files, deletion timeline,
  cluster cards, detail pages with evidence chips and support percentages.
- `index.json` as the stable machine-readable interface.

### Phase 5 — operations and proof (half a day)

- `manifest.py` + `palimpsest verify` for chain of custody.
- Content-addressed LLM cache (this is what makes a slow machine usable).
- Temporal workflow with six resumable activities.
- `doctor`, CI, Makefile.

## 4. Risk register

| Risk | Likelihood | Impact | Mitigation | Outcome |
|---|---|---|---|---|
| Vision model too slow on CPU | certain | high | cap triage, cache by content hash, separate vision/text models, hero ranking | mitigated; 200–700 s cold, 0 s cached |
| Small model hallucinates citations | high | high | support check + year check + struck-claim UI | mitigated; measured on 1B and 4B |
| Evidence destroyed by mounting | medium | fatal | never mount; image + `debugfs`/Sleuth Kit only | avoided by design |
| Sample image not reproducible | medium | high | pure `mkfs`/`debugfs`, no root, no loop device | works in CI |
| "AI is decoration" critique | certain | fatal | ablation table + five-stage dependency map | addressed |
| Scope creep into a web app | high | medium | static site only; no server; no upload | avoided |
| Partner integrations become dead code | medium | low | all optional imports guarded; Sentry no-op without DSN; Temporal optional extra | contained |

## 5. What was cut

- **Live-disk mode.** Too dangerous; an image is the correct unit of work.
- **A web upload service.** The disk must not leave the machine. A local static
  site is the honest interface.
- **Face recognition / identity inference.** Technically possible, ethically
  wrong, and it would poison the story.
- **A second full case study (FAT32).** The mode works and is documented, but the
  submission uses one polished ext4 case rather than two thin ones.
- **Audio narration inside the product.** The demo video can have a voiceover;
  the tool does not need a speech API to do its job.

## 6. What ships

- A working CLI: `run`, `ask`, `ablate`, `stats`, `verify`, `doctor`.
- 35 tests that do not need a model.
- A reproducible sample case with recovered, carved and unrecoverable artifacts.
- A static case site that works offline.
- A manifest and a verifier.
- An optional Temporal workflow that resumes after a kill.
- Documentation: architecture, features, judging notes, demo script, this plan.

## 7. Roadmap (v0.2 and beyond)

Ordered by what a real user would need next, not by what is fun to build.

1. **Streaming progress in the site.** The CLI prints progress; the site is
   written at the end. A `status.json` polled by a local page would make long
   cases less opaque.
2. **Redaction pass.** A model-assisted pass that flags likely-PII in recovered
   documents so a case can be shared without leaking the person it belongs to.
3. **Better support checking.** Lexical overlap is a tripwire. A small local
   entailment model, or a claim-to-evidence NLI check, would raise the ceiling.
4. **NTFS and APFS metadata paths.** `fls` already supports them; the deletion
   time parsing is ext-specific.
5. **Case diffing.** Two images of the same disk, before and after a wipe: what
   disappeared between them.
6. **Prompt regression suite.** A frozen set of evidence tables with expected
   accept/strike outcomes, run against every model upgrade. The manifest already
   records the prompt hashes; this would test them.
7. **A write-blocked ingestion helper.** Detect whether the target is a block
   device and refuse to touch it, pointing at `dd`/`dcfldd` instead.

## 8. Timeline as it actually happened

| Day | Work |
|---|---|
| Oct 27, morning | sample image, recovery path, data model, baseline narration |
| Oct 27, midday | five model stages, prompts as files, static site |
| Oct 27, afternoon | grounding v2/v3, cache, vision cap, name repair, manifest, verify |
| Oct 27, evening | docs, CI, final case run |
| Oct 28–30 | buffer: final run, screenshots, video, post revision |
| Oct 31 | submit early |
