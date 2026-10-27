# Architecture

Palimpsest is a five-stage pipeline over one disk image. Every stage produces
something the next stage needs, and every stage checkpoints to disk so the case
survives a crash.

```
                 ┌──────────────────────────────────────────────┐
   disk image ──▶│ 1. recover   fls / icat / istat / foremost   │
                 └───────────────┬──────────────────────────────┘
                                 │  Artifact(bytes, name, inode, dtime)
                                 ▼
                 ┌──────────────────────────────────────────────┐
                 │ 2. enrich    exiftool / pdftotext / reads    │
                 └───────────────┬──────────────────────────────┘
                                 │  Evidence (provable facts only)
                                 ▼
      ┌──────────────────────────┴───────────────────────────┐
      │                                                      │
      ▼                                                      ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ 3. triage     │──▶│ 4. link       │──▶│ 5. infer      │──▶│ 6. narrate    │
│ vision model  │   │ embeddings    │   │ missing files │   │ cited prose   │
└───────────────┘   └───────────────┘   └───────────────┘   └───────┬───────┘
                                                                    │
                                          ┌─────────────────────────┘
                                          ▼
                              ┌───────────────────────┐
                              │ 7. ground + verify    │
                              │ citations, hashes     │
                              └───────────┬───────────┘
                                          ▼
                              static site + case.json + manifest.json
```

The numbers below refer to the stages as they appear in `pipeline.py`.

---

## 1. Design constraints

Four constraints shaped every decision. They are not aspirations; each one
removes a class of implementation.

| Constraint | Consequence |
|---|---|
| **The disk never leaves the machine.** | No HTTP client anywhere except `llm.py`, which only talks to `127.0.0.1:11434`. No telemetry by default. The rendered site has no CDN, no webfont, no analytics. |
| **A claim must be checkable later.** | Sentences are stored with evidence ids, and `palimpsest verify` re-runs the checks. The manifest pins prompt hashes, tool versions and the source image hash. |
| **A case must survive interruption.** | Every phase writes to `out/case.json`. The Temporal workflow treats the store as its checkpoint. Model calls are cached by content hash. |
| **A small model must be usable.** | The pipeline never asks a 4B model to do something a `stat` call can do. The model is confined to semantic work: seeing, grouping, inferring, phrasing. |

---

## 2. Data model

`models.py` is deliberately small. The important part is the direction of
dependency: prose depends on evidence, never the other way round.

```
Evidence   id, source, value            e.g. E4, deleted, 2021-08-14T22:41:03
   ▲
   │ cited by
Claim      text, evidence[], confidence, struck, reason, support
   ▲
   │ belongs to
Artifact   bytes + name + inode + timestamps + triage + cluster + claims
   ▲
   │ belongs to
Case       target, artifacts[], notes{}
```

`Evidence.source` is a closed vocabulary in practice: `filename`, `kind`,
`size`, `created`, `modified`, `deleted`, `exif:*`, `triage:*`,
`content`, `cluster`. The narrator is shown the whole table and must cite ids
from it.

`Claim.struck` is not a warning. A struck claim is **not rendered** in the
epitaph; it appears only in the detail page, crossed out, with the reason. The
published text is therefore always a subset of the validated text.

---

## 3. Recovery: two ways a file dies

### 3.1 Metadata path (ext4, NTFS, HFS+)

The directory entry survives deletion, so the filesystem still knows the name,
size, inode and — on ext4 — the deletion timestamp. `recover.py` runs:

```
fls -r -d -p image          # every deleted entry, recursively
istat image <inode>         # "Deleted:" / "dtime:" line
icat image <inode>          # the bytes, if the blocks are still free
```

If `icat` returns zero bytes, the file is recorded as **missing**, not dropped:
the case keeps a hollow tombstone with its name, size and deletion time. That
distinction is the emotional centre of the tool. A report that lists only what
it recovered is lying by omission.

### 3.2 Carving path (any filesystem)

When the entry is gone, `foremost` scans free space for signatures. Carved files
have no name, no timestamp, and no directory. They are the hardest case for
narration and the best case for triage: a filename cannot bias the model,
because there is no filename.

### 3.3 Sample image

`scripts/make_sample_image.sh` builds a 128 MB ext4 image with `mkfs.ext4` and
writes into it with `debugfs`. No root, no loop device, no mount. It deletes ten
photographs and a letter, then sets the size field of two inodes to zero to
simulate blocks that were reused. That is how the demo gets both classes of
artifact without shipping a real person's disk.

```
debugfs -w -R "write photo.png /DCIM/photo.png" ghost.img
debugfs -w -R "rm /DCIM/photo.png"             ghost.img
debugfs -w -R "set_inode_field <18> size 0"    ghost.img
```

---

## 4. Triage: the model sees what the filesystem cannot

Input: a recovered image file. Output: a JSON object with subject, setting,
people count, visible text, a personal-memory flag, a human label, damage and
confidence.

Three design choices matter:

1. **The image is downscaled to 768 px before inference.** A 12 MP photo costs
   roughly ten times the vision tokens for no extra signal in triage.
2. **Triage is capped (`--vision-limit`).** On a CPU, a 4B vision model can take
   minutes per image. The cap is not a compromise; it is a ranking decision:
   the images most likely to be memories are triaged first (photos with EXIF
   before screenshots), and the rest still appear in the case with their
   filesystem facts.
3. **Triage output is cached and stored.** Re-running a case with the same
   prompts costs zero model calls. This is what makes iteration on a slow
   machine possible.

Triage also drives `select_for_narration()`: artifacts flagged as screenshots or
non-memories are skipped when the narration budget is small. Removing the model
therefore changes *which files get a eulogy*, not just the wording.

---

## 5. Link: grouping by meaning

`link.py` embeds a text rendering of each artifact:

```
name | kind | triage label | triage subject | setting | visible text |
text excerpt | modified date | cluster
```

Vectors are L2-normalised and clustered with union-find over a cosine-similarity
graph at a fixed threshold (default 0.72). This is intentionally inspectable:
two artifacts are in the same group if their descriptions are similar enough,
and a group is a connected component. No density estimation, no random seeds,
no hidden parameters.

Each group of two or more is then named by the model, with a prompt that asks
for "the way a person would label a box of belongings". A group of one is not
named, because a cluster of one is not a cluster.

The embeddings are persisted to `out/embeddings.npy` with an id index, which is
what `palimpsest ask` uses.

---

## 6. Infer: the files that did not come back

For each missing artifact, the model receives only facts:

```
name: tax_2021.pdf
size: 184320 bytes
deleted_at: 2021-08-14T22:41:03
directory: /Documents/2021
recovered in the same directory:
- letter.txt (a scanned letter about a move)
- notes.md (a list of things to do before moving)
```

It returns a one-sentence hypothesis, a coarse kind, a confidence, and a short
reasoning string. The UI renders it as a dashed tombstone labelled `hypothesis ·
low`, never as a recovered file. `infer.py` refuses empty hypotheses and
whitelists the kind.

This is the stage that has no classical equivalent. `photorec` reports a file it
could not recover as a failure. Palimpsest reports the shape of the hole.

---

## 7. Narrate: prose under arrest

`narrate.py` builds the evidence table, renders `prompts/epitaph.md`, and parses
JSON. `grounding.py` then applies two checks to every sentence:

**Check 1 — citation exists.** Every id must be in the artifact's evidence table.
Unknown ids are dropped, and a sentence with no surviving ids is struck.

**Check 2 — citation supports the sentence.** `support_score()` computes the
fraction of the sentence's content words that appear in the cited values, after
removing a stoplist of function words and generic visual nouns (`image`,
`photo`, `depicts`, `metadata`, …). Below `SUPPORT_THRESHOLD = 0.2`, the
sentence is struck. Years get a stricter check: a year in the text must appear
verbatim in a cited value.

The support check exists because of a measured failure. `gemma3:1b` wrote:

> "The image depicts a sunset over the sea." — citing `E1: IMG_2019_0006.png`

Every word of that sentence is plausible and none of it came from the evidence.
A citation-existence check alone would have published it. The support score
strikes it.

**Citation completion.** A 4B model repeatedly wrote *"IMG_2021_0002.png was
created on 2019-06-16T18:24:01 with an iPhone 8"* and cited the filename and the
camera, skipping the `created` row that actually holds the timestamp. The
sentence is true, and the timestamp appears character for character in exactly
one row — so `complete_citations()` adds that row before the checks run, and
records it on the claim as `auto_cited`. The report never claims the model cited
it. A year that appears nowhere in the evidence is still struck, and the ids
added this way are re-checked against the same support threshold. Completion
fixes a bookkeeping mistake; it cannot manufacture support.

**Prompt shape.** Rules alone were not enough. With rules only, `gemma3:4b`
wrote sentences like *"The file, identified as E1, contained the word 'Mum'"*:
true, cited, and unreadable. The prompt now carries two worked examples — one
photograph, one document — and a bad/good pair:

```
BAD:  "The description indicated a sunset."     (about the tool)
GOOD: "It showed a sunset."                     (about the file)
```

A 4B model imitates an example far more reliably than it follows an
instruction. The examples cost ~400 prompt tokens and changed the output more
than any rule in the file. The content rule — quote six consecutive words from
a `content` row — is what turns the recovered letter from a metadata record
into a sentence in its own voice.

**What this cannot do.** Lexical overlap is a tripwire, not entailment. A
sentence can share vocabulary with its evidence and still be wrong
("the sunset was photographed by her mother" cites the label `sunset`). The
tool's defence is layered: the prompt forbids invented relations, the support
score catches the crude cases, `verify` re-checks later, and the UI labels
`speculation` differently. It is not a proof. It is a documented, reproducible
filter, which is more than most generated text gets.

---

## 8. Case note and timeline

`timeline.py` groups deletions by date and flags days with five or more as
`mass`. The case note is generated from cluster ids and timeline ids, and goes
through the same validator with a five-sentence cap. If the evidence supports
only "a large deletion happened on this date", that is all it can say.

---

## 9. Verify: chain of custody

`manifest.py` writes `out/manifest.json`:

- source image size and SHA-256
- SHA-256 of every recovered artifact
- model and embedding model names
- SHA-256 (truncated) of every prompt file
- SHA-256 (truncated) of every source module
- versions of `fls`, `icat`, `istat`, `foremost`, `exiftool`, `ffmpeg`,
  `pdftotext`, `debugfs`
- Python version and platform
- the run configuration

`palimpsest verify` re-reads the case and checks:

1. the artifact set matches the manifest
2. every recovered file still hashes to its recorded digest
3. every citation points at evidence that exists
4. every *published* sentence still passes the support check
5. the prompt files have not changed since the run
6. the source modules have not changed since the run
7. the source image still hashes to the recorded digest

Exit code 1 on any failure, so it drops straight into CI or a court exhibit
list. This is the concrete form of the open-weights argument: a report produced
by a hosted model that was silently updated cannot be reproduced; a report
produced by a pinned digest can.

---

## 10. Durability

Carving a large image takes hours; narration is hundreds of sequential model
calls. A crash at hour three must not restart the case.

`workflow.py` defines seven activities — recover, triage, link, infer, narrate,
manifest, render — each of which reads and writes `out/case.json`. The Temporal
workflow runs them in order with retries and heartbeats. Killing the worker
mid-triage and restarting resumes at the last completed activity. The store is
the checkpoint; Temporal is the conductor.

A workflow that skipped the manifest would produce a case `verify` cannot check,
so `manifest_phase` is an activity like any other. Running the workflow on the
sample image produces a case that passes `verify` with 39 checks — the same
chain of custody the CLI writes, just scheduled durably.

The CLI path (`pipeline.run`) is the same sequence without the conductor, for
machines where running a Temporal server is overkill.

---

## 11. Privacy posture

- The only network call in the codebase is `urllib.request` inside `llm.py`,
  and its host defaults to `http://127.0.0.1:11434`. There is no API-key
  branch, no fallback to a hosted provider, no "if Ollama is down, use…".
- `tracing.py` is a no-op unless `SENTRY_DSN` is set. When set, it sends span
  metadata (operation names, counts), never file contents or evidence values.
- The rendered site copies media into `out/site/media/` so it works from a USB
  stick. That means recovered photos are duplicated on disk. The README says so.
- The sample image contains generated gradients and a fictional letter. No real
  personal data is in the repository.
- Recommended practice for real cases: work on a copy, keep the original
  write-blocked, and treat `out/` as sensitive as the disk.

---

## 12. Performance envelope

Measured on this machine (15 GB RAM, CPU-only Ollama in Docker, Gemma 3 4B):

| Operation | Time |
|---|---|
| `fls` + `icat` + `istat` for 11 deleted entries | ~4 s |
| `nomic-embed-text` for 11 artifacts | < 2 s |
| Gemma 3 4B text call (~180 tokens out) | 60–65 s |
| Gemma 3 4B vision call, cold | 200–700 s |
| Gemma 3 4B vision call, warm + cached | 0 s (cache hit) |
| Gemma 3 1B text call | ~24 s |

The variance in vision is memory pressure, not image size: the model is 3.3 GB
and the machine is usually swapping. The mitigation is structural, not a
micro-optimisation: cap triage, cache by content hash, keep the model resident
(`keep_alive=30m`), and run the text stages on a smaller model when the case is
large. `--vision-model` and `--model` are separate flags for exactly this.

---

## 13. Extension points

- **Prompts** are markdown files in `prompts/`. Editing one changes behaviour
  without touching Python, and `manifest.json` records that it changed.
- **A new stage** is a module with a function over `list[Artifact]` plus a span
  in `pipeline.py`. The Temporal activity is five lines.
- **A new recovery backend** returns `Artifact` objects; nothing downstream
  cares whether they came from `icat`, `foremost`, or a directory scan.
- **A new renderer** consumes `case.json`; the static site is one consumer, and
  `index.json` is the stable interface for others.
