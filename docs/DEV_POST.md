---
title: A deleted file isn't gone. It's waiting to be overwritten.
published: false
tags: devchallenge, hf26challenge
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 4: Ghost in the Machine](https://dev.to/challenges/hacktoberfest-week4-2026-10-26)*

## What I Built

The letter is 208 bytes, and it is fictional. I built a 128 MB ext4 image, wrote the letter into it, and deleted it at 07:34 on a Tuesday morning. It begins:

> Mum,
>
> I found the box of photographs in the hall cupboard, the ones from the summer we drove to the coast. I am keeping the one of you by the blue door.

The filesystem still knows the letter existed. The directory entry survived, the inode survived, the deletion timestamp survived. `icat` can still copy the bytes out. So a classical recovery tool will hand it to you, correctly, and then stop — because the next question is not a filesystem question.

*What else went with it? Which of these eight photographs was in the box? What was the file whose name survived but whose blocks did not?*

That is the gap **Palimpsest** fills. It recovers deleted files from a disk image and then explains what they were, using open-weight models running entirely on your own machine. It reads the photographs, groups the files by meaning, writes a labelled hypothesis for the ones that cannot be recovered, and composes an epitaph for each artifact in which **every sentence carries the id of the evidence it came from**.

It is not a chatbot for your files. It is a witness statement with a chain of custody.

A disk is a palimpsest: parchment scraped down and written over, with the older text still faintly there under the new. Deletion is the scrape. The blocks are reused, the name is overwritten, and what is left is a shape — a directory entry pointing at nothing, a filename that no longer matches its contents. The ghost in the machine is not a spirit. It is the residue of a write that did not quite erase.

I built the tool to report that residue honestly, including the parts it cannot bring back.

## Demo

**[The sample case, rendered](https://flameeecyber.github.io/palimpsest/demo/)** — nine recovered files, two hollow tombstones, and the evidence table behind every sentence. Everything on that page was generated on this laptop from a synthetic disk image, and the four commands below reproduce it.

The whole demo is four commands, and none of them touch the network:

```bash
./scripts/make_sample_image.sh          # builds a 128 MB ext4 image, no root, no mount
palimpsest run sample/ghost.img --out out
palimpsest ablate --out out
palimpsest verify --out out
```

`out/site/index.html` is a static site: no server, no JavaScript, no CDN, no webfont. Copy it to a USB stick and it still opens.

The case looks like this. Nine artifacts came back. Two are hollow.

```
recovering metadata from image sample/ghost.img
  9 recovered, 2 provably deleted but unrecoverable
triaging images with the local vision model
  triaged 2 images
embedding and grouping by meaning
  cluster C1: Summer Family Photos (6 files)
  cluster C2: Sunset Landscapes June (2 files)
inferring the files that did not come back
  inferred IMG_2019_0000.png: Probably a photograph, likely taken on a mobile device...
writing evidence-bound epitaphs
case written to out/site
```

![The rendered case: nine tombstones, two of them hollow](https://raw.githubusercontent.com/flameeecyber/palimpsest/main/docs/screenshots/case.png)

*The rendered case. The two dashed stones at the bottom are files that provably existed and did not come back.*

## Code

**[github.com/flameeecyber/palimpsest](https://github.com/flameeecyber/palimpsest)** — MIT, Python 3.11+, 40 tests that need no model and no disk image.

```
src/palimpsest/
  recover.py     fls / icat / istat parsing, foremost carving, directory scan
  vision.py      stage 1: semantic triage with Gemma 3
  link.py        stage 2: local embeddings + union-find clustering
  infer.py       stage 3: hypotheses for unrecoverable files
  narrate.py     stage 4: evidence-bound epitaphs
  grounding.py   citation + support validation
  query.py       stage 5: retrieval with artifact citations
  manifest.py    hashes, prompt pins, tool versions, verify
```

## How I Built It

### The rule I started with

The theme invites a haunted chatbot. The problem with a haunted chatbot is that the model is a costume: replace it with a regex and the product is unchanged. So I wrote one constraint down before any code:

> The model must be the only way to answer the user's question, and removing it must be a measurable regression.

Deleted-file recovery fits because the classical tools stop exactly where semantics begin. `photorec` can hand you four thousand unnamed fragments. It cannot tell you which one is the photograph of your mother.

### Recovery first, because the story depends on it

No root, no loop device, no mount. The sample image is built with `mkfs.ext4` and `debugfs`, which means it is reproducible in CI and cannot damage the machine it runs on:

```bash
mkfs.ext4 -q -F ghost.img
debugfs -w -R "write photo.png /DCIM/photo.png" ghost.img
debugfs -w -R "rm /DCIM/photo.png" ghost.img
```

Recovery runs the Sleuth Kit:

```bash
fls -r -d -p image      # every deleted entry, recursively
istat image <inode>     # the ext4 "Deleted:" line — when the file died
icat image <inode>      # the bytes, if the blocks are still free
```

Two details make the case worth reading. First, `istat` gives the **deletion time**, not the modification time — the difference between *when this was last written* and *when someone got rid of it*. Second, when `icat` returns zero bytes, the artifact is kept as **missing**, with its name, size, parent directory and deletion time. It is not dropped from the report.

That second decision is the emotional centre of the tool. A recovery report that lists only what it recovered is lying by omission.

### Five stages, five different jobs for the model

Everything runs through a local Ollama: `gemma3:4b` for vision and prose, `nomic-embed-text` for embeddings. The only network client in the codebase talks to `127.0.0.1:11434`. There is no API-key branch, no hosted fallback, no "if Ollama is down, use…".

**1. Triage.** The vision model looks at a recovered image and returns subject, setting, people count, visible text, a personal-memory flag, and a human label. A carved file has no name and no EXIF, so the pixels are the only evidence — which makes this the purest model stage in the pipeline. On a CPU this is also the most expensive call: 200–700 seconds per cold image. So triage is capped and ranked (photos with EXIF before screenshots), and every artifact still keeps its filesystem facts. The cap is a scheduling decision, not a filter that hides failure.

**2. Link.** Every artifact is rendered as a line of text (name, kind, triage label, setting, visible text, excerpt, date) and embedded locally. Vectors are L2-normalised and clustered with union-find over a cosine graph at a fixed threshold. Two files are in the same group if their descriptions are similar enough; a group is a connected component. No random seeds, no hidden parameters. The model then names each group the way a person labels a box of belongings — `C1: Summer Family Photos`.

**3. Infer.** For a file whose blocks are gone, the model gets only facts: name, size, deletion time, directory, and the files recovered beside it. It returns a one-sentence hypothesis, a coarse kind, a confidence, and its reasoning. The UI renders it as a dashed tombstone labelled `hypothesis`, never as a recovered file.

This is the stage with no classical equivalent. `photorec` reports an unrecoverable file as a failure. Palimpsest reports the shape of the hole.

**4. Narrate.** Two to four sentences per artifact, each citing evidence ids. Then the validator runs.

**5. Query.** Embed the question, take the cosine top-k over the case, answer with artifact citations.

The model also decides *which* files get attention: `select_for_narration()` uses the triage score, so a screenshot of a login page is skipped while a photograph of two people is not. Remove the model and the case does not just get quieter — it gets a different set of eulogies.

### The part that changed the project: a citation is not support

The first version of the validator checked that every cited evidence id existed. That is the obvious check, and it is not enough.

`gemma3:1b` wrote:

> "The image depicts a sunset over the sea." — citing `E1: IMG_2019_0006.png`

Every word is plausible. None of it came from the evidence. A citation-existence check published it.

So the second check computes a **support score**: the fraction of the sentence's content words that actually appear in the cited values, after removing function words and generic visual nouns (`image`, `photo`, `depicts`, `metadata`). Below `0.2`, the sentence is struck. Years get a stricter rule: a year in the sentence must appear verbatim in a cited value.

Struck sentences are never published. They appear on the detail page crossed out, with the reason — because the failure is evidence too.

```python
claims = validate_sentences(raw["sentences"], evidence)
struck = [c for c in claims if c.struck]
# "- 'The image depicts a sunset over the sea.' -> cited evidence does not
#    support this sentence (support 0.00)"
```

Then the loop feeds the rejection back to the model, once, with the exact strike reason. The second attempt usually quotes the evidence instead of inventing around it. The best attempt wins. That retry loop is the difference between a demo and something that holds up when the model is having a bad day.

One repair sits before the checks, because the model kept making the same bookkeeping mistake: it would write *"IMG_2021_0002.png was created on 2019-06-16T18:24:01 with an iPhone 8"* and cite the filename and the camera, skipping the row that held the timestamp. The year check struck it — correctly, since the cited rows did not contain the date — and the retry frequently repeated it. `complete_citations()` now runs first: if a sentence quotes a timestamp character for character, the row containing it is added to the citation and recorded on the claim as `auto_cited`, so the report never pretends the model cited it. An invented year still dies, because no row contains it. The repair fixes bookkeeping; it cannot manufacture support.

![The letter's page: each sentence with the evidence ids behind it](https://raw.githubusercontent.com/flameeecyber/palimpsest/main/docs/screenshots/letter.png)

*The letter's page. Two sentences, five evidence rows, and the percentage is the support score — how much of each sentence is actually in what it cites.*

I want to be precise about what this is: **lexical overlap is a tripwire, not entailment.** A fluent sentence can reuse the right nouns and still be wrong. The defence is layered — the prompt forbids invented relations, the support score catches the crude cases, `verify` re-checks later, and the UI labels speculation differently. It is not a proof. It is a documented, reproducible filter, which is more than most generated text gets.

### The ablation

The claim "the AI is load-bearing" is easy to make and hard to check, so it is a command:

```bash
$ palimpsest ablate --out out
                            without model     with model
--------------------------------------------------------
artifacts with a human label             0             2
groups found by meaning                  0             2
unrecoverable files explained            0             2
artifacts with an epitaph                9             9
sentences written                       26            18
sentences with a source                 26            18
words about the content                  0            17
```

The baseline is not a strawman. `stub_narrate()` was written before the model path and emits only what a `stat` call can prove: *"letter.txt is a document of 208 bytes."* It writes more sentences and says less. That is the whole argument in one table.

### Chain of custody

A forensic report is only worth something if someone else can check it later. `palimpsest run` writes `manifest.json` with the source image hash, the SHA-256 of every recovered artifact, the model names, the SHA-256 of every prompt file, and the version of every tool that touched the evidence.

`palimpsest verify` re-reads the case and checks seven things: the artifact set, every file hash, every citation target, every published sentence's support score, prompt drift, code drift, and the source image hash. Exit code 1 on any failure, so it drops straight into CI.

This is the concrete form of the reproducibility argument. A report produced by a hosted model that was silently updated last Tuesday cannot be reproduced. A report produced by a pinned digest can.

### What it does not do

- **No write-back.** It reports; it does not restore to the original filesystem. That is a different, riskier product.
- **No live-disk mode.** An image or a directory, never a mounted filesystem. Mounting read-write while recovering is how evidence gets destroyed.
- **No encrypted volumes.** LUKS, BitLocker and FileVault need a passphrase and a different toolchain.
- **No face recognition, no identity inference.** The prompt forbids it and there is no code for it. A tool that recovers deleted photographs of people must not also name them.
- **No TRIM'd SSD recovery.** The blocks are physically gone. Claiming otherwise would be a lie.

## Why Does Open Innovation Matter?

Three reasons, and none of them are ideological.

**The input is the most private object a person owns.** A disk holds the deleted photographs, the unsent letter, the medical PDF, the browsing history. Uploading it to a vision API means sending the exact things someone deleted on purpose. A local model is not a preference here; it is the only version of this product a person could ethically run on their own machine, let alone on someone else's. That is why there is no remote path in the code at all — not a flag, not an opt-in, not a fallback.

**A forensic report has to outlive the model that wrote it.** The manifest pins the model name, the prompt hashes, the source hashes and the tool versions. Six months from now, `palimpsest verify` can tell you whether the case still stands, and `prompts/epitaph.md` can be diffed to see exactly what the model was told. You cannot do that with a closed model's system prompt, and you cannot do it at all if the model behind an API changes without a version number.

**The behaviour is editable by the person using it.** The prompts are markdown files, not code. A researcher who wants the narrator to stop using the word "probably" can change one line and re-run; the manifest records that the prompt changed. A model small enough to run on a laptop is also a model you can swap, quantise, fine-tune, or replace with a better one next year without asking anyone's permission.

And the practical one: **it costs nothing to run and works with the network off.** No tokens, no rate limit, no account. On a train, in a basement, on a machine that will never see a patch, the tool behaves the same.

## My Agent Session

This project was built in a single long session with an AI coding agent running locally — the same machine, the same offline constraint, the same 15 GB of RAM that made Gemma 3 4B vision take anywhere from 200 to 700 seconds per cold image.

The session notes are in the repository: **[docs/AGENT_SESSION.md](https://github.com/flameeecyber/palimpsest/blob/main/docs/AGENT_SESSION.md)**. The short version of what it was like:

- The first grounding check was too weak, and the agent's own benchmark caught it. That is where the support score came from.
- The vision model repeatedly exhausted swap. The fix was architectural, not a prompt tweak: cap triage, cache by content hash, keep the model resident, and separate `--vision-model` from `--model`.
- The `gemma3:1b` comparison was run specifically to see whether a smaller model could narrate. It could not: it cited filenames for claims about sunsets and leaked few-shot examples into output. That failure is now part of the documentation, because it is the best evidence that the validator does something.
- The prompt that finally worked carries two worked examples and tells the model to *reuse the cited evidence's own words*. Both exist because the validator struck everything that did not, and because a 4B model imitates an example far more reliably than it follows a rule.

Using an agent did not remove the engineering. It compressed the loop between "try a prompt" and "measure whether the prompt lied".

## The Spirit of It

The sample letter is fictional. The situation is not.

Everyone has deleted something they wish they had not — a voicemail, a photograph, a message from someone who is no longer around. The filesystem does not mourn. It marks the blocks free and moves on. The palimpsest is scraped and written over.

What I wanted from this project was not a horror trick. It was the opposite: a tool that treats the dead honestly. That is why the unrecoverable files are still on the page, as hollow tombstones with their names and the day they died. That is why a sentence the evidence cannot support is struck instead of smoothed over. That is why the tool says "hypothesis" when it is guessing.

Día de los Muertos is not about scaring people. It is about naming the dead and leaving something out for them. An ofrenda is an evidence table with flowers on it. Palimpsest is a small, literal version of that: one tombstone per file, the date it was deleted, and an epitaph that can only say what the record supports.

The most affecting moment in testing was not a photograph. It was the letter's text coming back intact — *"I am keeping the one of you by the blue door"* — and the epitaph quoting that line without ever telling me who "you" was, because the evidence does not say. The tool knew the limit of its knowledge and stopped there. That restraint is the whole design.

## Prize Categories

I am entering three categories, because these are the three I actually use:

- **Best Use of Gemma** — `gemma3:4b` performs vision triage and evidence-bound narration through local Ollama. During development, `gemma3:1b` was the measured failure case: it cited a filename for a claim about a sunset, and the validator struck it. No Google Cloud, no API key, no data egress.
- **Best Use of Temporal** — `workflow.py` defines seven activities (recover, triage, link, infer, narrate, manifest, render) with heartbeats, retry policies and a six-hour ceiling on each. The case store is the checkpoint, so a worker that dies mid-case resumes at the last completed phase instead of starting over. I ran the workflow end to end on the sample image; the case it produced passes `palimpsest verify` with 39 checks.
- **Best Use of Sentry Agent Tracing** — `tracing.py` wraps every stage in a span with counts. It is a no-op unless `SENTRY_DSN` is set, because the tool must run offline; when enabled it sends span names and counts, never file contents or evidence values.

I am not entering Render, DigitalOcean or .tech: the product is local-first, and putting a real case online would contradict the reason it exists. A demo site could be hosted; the tool should not be.

---

*Repository: [github.com/flameeecyber/palimpsest](https://github.com/flameeecyber/palimpsest) · MIT · Python 3.11+ · Gemma 3 4B + `nomic-embed-text` via Ollama · no network required.*
