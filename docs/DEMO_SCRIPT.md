# Demo script

Three minutes, screen recording, no talking head. The point of the video is to
show one thing a viewer will remember: a deleted letter coming back with its
text intact, next to a tombstone for a file that did not come back.

Record at 1080p, terminal font at 16–18 px, browser zoom at 110%. Have the case
already built before recording, so no shot waits on a model.

---

## Before recording

```bash
cd palimpsest
make sample                       # ~2 s, builds sample/ghost.img
PYTHONPATH=src .venv/bin/python -m palimpsest run sample/ghost.img --out out
PYTHONPATH=src .venv/bin/python -m palimpsest verify --out out
```

Two things must be on screen and ready:

- `out/site/index.html` open in a browser tab, scrolled to the top.
- A second terminal tab with the repo open, for the code shots.

Turn off notifications. Set the terminal prompt to something short (`$`) so the
commands read cleanly.

**If the model is slow on the day:** the run above is already cached by content
hash, so re-running is instant. If you must record a cold run, record the first
20 seconds of `triaging images with the local vision model` and cut — the
voiceover explains the wait honestly.

---

## 0:00–0:20 — the hook

**Screen:** the letter's detail page, scrolled so the recovered text is visible.

**Voiceover:**

> This is a letter that was deleted from a disk. The filesystem still had the
> directory entry, so the name survived: `letter.txt`. The text survived too.
>
> What did not survive was any answer to the question a person actually asks:
> *what was this, and what else went with it?*

**Action:** click the "evidence" chips under the first sentence; the evidence
table highlights the row it came from.

---

## 0:20–0:50 — the problem

**Screen:** terminal. Run the baseline.

```bash
PYTHONPATH=src .venv/bin/python -m palimpsest run sample/ghost.img \
  --out out-offline --no-llm
```

**Voiceover:**

> This is the same case with no model at all. Nine files recovered, two
> accounted for but gone. Every sentence true, every sentence useless:
> *"letter.txt is a document of 208 bytes."*
>
> Classical recovery answers *which bytes can be copied out*. It cannot answer
> *which of these is the photograph of my mother*.

**Action:** open `out-offline/site/index.html`, scroll the flat grid. Then cut
to `palimpsest ablate` output.

```bash
PYTHONPATH=src .venv/bin/python -m palimpsest ablate --out out
```

Hold on the table for three seconds. The right column is the argument.

---

## 0:50–1:40 — the five stages, one shot each

**Voiceover over terminal, commands already run:**

> Five stages, five different jobs for the model.

```bash
PYTHONPATH=src .venv/bin/python -m palimpsest stats --out out
```

**1. Triage.** Open one photo's detail page. Point at the triage line:
`sunset sky with a sun`, and the confidence label.

> The model looked at the pixels. No filename, no EXIF — the description is
> what it saw.

**2. Link.** Back to the index. Point at cluster `C1: Summer Family Photos`.

> Every artifact was embedded locally with `nomic-embed-text` and grouped by
> meaning. The model named the group the way a person labels a box.

**3. Infer.** Scroll to the hollow tombstone for `IMG_2019_0000.png`.

> This file's blocks were reused. It cannot be recovered by any tool. So the
> model reads the name, the size, the deletion time, and the files recovered
> beside it, and writes a hypothesis — labelled as a hypothesis, never as a
> fact. `photorec` reports this as a failure. Palimpsest reports the shape of
> the hole.

**4. Narrate.** Open `letter.txt` again.

> Every sentence in this epitaph carries the id of the evidence it came from.
> `E5` is the recovered text. The support score under the sentence is the
> fraction of its content words that actually appear in that evidence.

**5. Query.**

```bash
PYTHONPATH=src .venv/bin/python -m palimpsest ask \
  "What was deleted in the same batch as the letter?" --out out
```

> Retrieval over the local embeddings, answered with artifact citations. No
> network. Ollama is on `127.0.0.1`.

---

## 1:40–2:20 — the failure that makes it credible

**Screen:** the detail page of an artifact whose epitaph has a struck sentence.
If the current case has none, open `docs/ARCHITECTURE.md` at the `gemma3:1b`
example instead.

**Voiceover:**

> Here is the part most demos cut. A smaller model wrote: *"The image depicts a
> sunset over the sea,"* citing the filename. Every word plausible, none of it
> in the evidence. A citation-existence check would have published it.
>
> The support check struck it. Struck sentences are never published; they are
> shown crossed out, with the reason, so you can see what the filter caught.
>
> Then the validator feeds the rejection back to the model, once. The second
> attempt quotes the evidence. That is the retry loop.

**Action:** run verify.

```bash
PYTHONPATH=src .venv/bin/python -m palimpsest verify --out out
```

> And this re-checks the whole case later: file hashes, citation targets,
> support scores, prompt drift, code drift, the source image hash. Exit code 1 if anything
> moved.

---

## 2:20–3:00 — why open weights

**Screen:** `manifest.json`, scrolled to `model`, `prompts`, `tools`.

**Voiceover:**

> Three reasons this had to be open, and none of them are ideological.
>
> One: the input is the most private object a person owns. The deleted
> photographs, the unsent letter. There is no API-key branch in this codebase.
> The only network client talks to localhost.
>
> Two: a forensic report has to be reproducible years later. This manifest pins
> the model, the prompt hashes, and the version of every tool that touched the
> evidence. A hosted model that was silently updated last Tuesday cannot give
> you that.
>
> Three: the prompts are markdown files. You can read them, diff them, change
> how the agent behaves without writing Python — and the manifest records that
> you did.
>
> A deleted file isn't gone. It's waiting to be overwritten. The least we can do
> is ask what it was, and show our work.

**End card:** repo URL, `#hf26challenge`, "runs on a laptop with the network
off".

---

## Shot list

| Time | Shot | Source |
|---|---|---|
| 0:00 | letter detail, evidence chips | `out/site/artifact-*.html` |
| 0:20 | no-model run + flat grid | `out-offline/site/index.html` |
| 0:40 | ablation table | `palimpsest ablate` |
| 0:50 | triage line on a photo | detail page |
| 1:05 | cluster card C1 | `out/site/index.html` |
| 1:20 | hollow tombstone + hypothesis | index, `IMG_2019_0000.png` |
| 1:35 | support percentage | letter detail page |
| 1:50 | `ask` answer | terminal |
| 2:00 | struck sentence + reason | detail page / architecture doc |
| 2:15 | `verify` output | terminal |
| 2:25 | manifest | `out/manifest.json` |
| 2:45 | end card | title slide |

## What not to do

- Do not show a cold vision call in real time. It is 200–700 seconds and it
  makes the project look broken rather than honest.
- Do not narrate the architecture diagram. The viewer came for the letter.
- Do not claim the support check is entailment. Say "tripwire" if you say
  anything.
- Do not put music under the evidence table. Silence reads as confidence.
