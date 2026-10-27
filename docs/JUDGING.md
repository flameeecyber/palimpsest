# Judging notes

The challenge page lists five criteria. This file maps the project to them
honestly, including where it is weak.

> Writing Quality (weighted most heavily) · Relevance to the Prompt and Theme ·
> Creativity · Technical Execution · Use of Partner Technology (optional)

The post is the deliverable that carries the writing score. This file is the
evidence the post points at.

---

## 1. Writing quality

The post is not a changelog. It is built around one sentence:

> A deleted file isn't gone. It's waiting to be overwritten.

and one tension:

> Classical recovery finds the bones. It cannot tell you who they were.

The post uses that tension to introduce each stage, shows real output (including
a struck sentence, which is more convincing than a success story), and ends with
the argument for open weights that only this project can make: the disk is the
most private object a person owns, and a forensic report has to be reproducible
years later.

Writing decisions:

- No "in this article we will explore". Start with the letter.
- Every technical claim has a number, a command, or a file path behind it.
- The failure is included: a 1B model cited a filename for a claim about a
  sunset, and the validator struck it. That is the most credible paragraph in
  the post.
- The limits section is not buried. Encrypted disks, TRIM'd SSDs and lexical
  support checking are stated plainly.

## 2. Relevance to the prompt and theme

The prompt asks for **open-source AI at the core**, and the theme is **Ghost in
the Machine** / Día de los Muertos.

**Open at the core.** The project runs Gemma 3 4B and `nomic-embed-text` through
a local Ollama. There is no remote API branch in the code. The five model stages
are the product; `--no-llm` produces a visibly poorer case, and `ablate` measures
the difference.

**Ghost in the Machine, literally.** A disk is a palimpsest: written over, never
quite erased. Deleted files are the ghosts — the directory entry survives, the
blocks are reused, the name is all that is left. The tool's job is to find the
shape of what was there and say only what the evidence supports.

**Día de los Muertos, without kitsch.** The case site is an ofrenda: marigold and
deep violet, one tombstone per artifact, hollow stones for the files that did not
come back, a timeline of the day they died, and an epitaph for each. The
aesthetic is a frame for the evidence, not a substitute for it. There are no
skeletons, no "the ghost remembers", no haunted voice. The restraint is the
point: the dead are honored by accuracy, not by decoration.

The sample case is a fictional letter to a mother and ten photographs from a
summer. It is generated, and the post says so. The emotion is real because the
situation is real: everyone has deleted something they wish they had not.

## 3. Creativity

The idea is not "chat with your files". It is a specific, defensible inversion:

- Ordinary recovery asks *what can be copied out?* Palimpsest asks *what was
  this, and how do you know?*
- The most interesting artifacts are the ones that **cannot** be recovered. They
  get a labelled hypothesis instead of being silently dropped.
- The model's output is treated as a **witness statement**, not as text: every
  sentence is bound to evidence ids and can be struck.
- `ablate` turns the "is the AI load-bearing?" objection into a reproducible
  table.
- The chain-of-custody manifest pins prompt hashes and tool versions, so the
  case can be re-verified after the model is gone.

The demo moment is not a chatbot reply. It is a deleted letter coming back with
its text intact, next to a hollow tombstone for a file that no longer exists.

## 4. Technical execution

What is actually implemented:

| Area | Evidence |
|---|---|
| Real forensic recovery | `fls`/`icat`/`istat` on ext4, `foremost` carving, FAT32, directory scan |
| Deletion timestamps | ext4 `dtime` parsed from `istat`, not file mtime |
| Unrecoverable-file accounting | `missing` artifacts with name, size, parent and deletion time |
| Five model stages | triage, link, infer, narrate, query — each with a no-model fallback |
| Grounding | citation existence, lexical support, year check, struck-claim UI |
| Validator-in-the-loop | rejected sentences are fed back once; the best attempt wins |
| Reproducibility | content-addressed cache, prompt hashes, tool versions, `verify` |
| Durability | seven Temporal activities, heartbeats, a manifest written by the workflow |
| Tests | 35 tests, no model or disk image required |
| CI | compile, tests, offline end-to-end run on a generated image |
| Offline UI | static HTML/CSS, no JS, no CDN, media copied locally |

The honest weak points:

- **Vision latency.** Gemma 3 4B on a CPU is 200–700 s per cold image. The
  mitigation is architectural (cap, cache, hero ranking), not a benchmark win.
- **Lexical support.** It is a tripwire, not entailment. The docs say so.
- **The sample image is small.** 128 MB, 11 deleted entries. It proves the
  pipeline, not scale.
- **No encrypted volumes, no TRIM'd SSDs.** Stated in the README.

Judges reward shipped, working software over ambition. This runs end to end
today, and the failure modes are documented rather than hidden.

## 5. Use of partner technology

Only claim what is real.

### Gemma — the core claim

- `gemma3:4b` does vision triage and evidence-bound narration.
- `gemma3:1b` is used in the ablation to show the grounding check catching a
  weaker model. That is a real, measured comparison, not a logo.
- Both run through local Ollama. No Google Cloud, no API key, no data egress.
- Why it fits the category: the model is not a feature bolted on; removing it
  removes five stages. The post's central table is a Gemma capability table.

**Strength: strongest category.** The project is a genuine local-Gemma
application with a measured failure case.

### Temporal — the durability claim

- `workflow.py` defines six activities: recover, triage, link, infer, narrate,
  render.
- Each activity reads and writes `out/case.json`, so the store is the checkpoint.
- Heartbeats on the long stages; retry policy with backoff; `start_to_close` of
  six hours.
- The README documents the kill-and-resume test: start a case, kill the worker
  mid-triage, restart, and the workflow continues.

**Strength: real but optional.** `temporalio` is an optional extra; the CLI path
works without a Temporal server. The post should say that plainly. The category
asks for durability, and the design genuinely provides it.

### Sentry Agent Tracing — the observability claim

- `tracing.py` wraps every stage in a span with counts (artifacts, clusters,
  hypotheses, narrated).
- It is a **no-op** unless `SENTRY_DSN` is set, because the tool must run with
  the network off. When enabled it sends span names and counts, never file
  contents or evidence values.
- The manifest records model, prompt hashes and tool versions; Sentry records
  latency and stage failures. Together they answer "what happened in this run?"

**Strength: real but thin.** Spans exist and are wired into the pipeline. The
post should show a trace screenshot if one is captured, and not pretend it is
more than stage-level instrumentation.

### Categories deliberately not entered

- **Render / DigitalOcean / .tech** — no deployment. The product is local-first;
  putting the case site online would contradict the privacy argument. A static
  demo could be hosted, but it is not the product.
- **ElevenLabs** — a voiceover for the demo video is not a use of the technology
  in the project. Entering would be padding.
- **TabPFN, Tinker, Arduino, Browserbase, MongoDB, Mastra, Auth0, Backboard,
  SerpApi, Tiger Data, Ultramarine, Entire, Copilot** — not used.

Entering fewer categories with true claims is better than entering many with
thin ones. The post can say: "I am entering Gemma, Temporal and Sentry because
those are the three I actually use."

## 6. Submission checklist

- [ ] Repository is public and contains only work started inside the challenge
      window (Oct 26–31).
- [ ] `README.md` states requirements, quickstart, limitations and privacy.
- [ ] `LICENSE` present (MIT).
- [ ] Demo: 3-minute video (see `docs/DEMO_SCRIPT.md`) or a hosted static case.
- [ ] Post follows the official template: What I Built / Demo / Code / How I
      Built It / Why Does Open Innovation Matter? / The Spirit of It / Prize
      Categories.
- [ ] Tags: `devchallenge`, `hf26challenge`.
- [ ] Post links the repo and the video.
- [ ] Any commits after submission are noted in the README.
- [ ] Prize categories listed explicitly: Best Use of Gemma, Best Use of
      Temporal, Best Use of Sentry Agent Tracing.
- [ ] Read the post once for the opening line and once for the closing line.
      Those are what judges remember.
