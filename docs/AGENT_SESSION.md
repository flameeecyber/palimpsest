# Agent session notes

This project was built in one long session with an AI coding agent (OpenCode)
driving a local shell, with Ollama running in Docker on the same 15 GB machine.
No cloud model was used for the build, and none is used by the product.

These notes are the honest version of "how I built it": the order things
happened, the dead ends, and the measurements that changed the design. They are
also the answer to the question a judge should ask — *did the agent do the
engineering, or did it generate plausible text?* The tests and the benchmark
numbers are the evidence either way.

---

## 0. Choosing the wrong idea first

The first proposal was a haunted honeypot: a fake SSH server whose "ghost"
taunts intruders with a locally generated voice. It was rejected before any code
was written, for three reasons that are worth recording:

1. The interesting data (who attacks, how) only exists after days of exposure,
   and the challenge window is five days.
2. Bots do not converse. The model would be decorative almost all the time.
3. A honeypot needs a public IP, which means a cloud host, which means the
   "runs on your laptop with the network off" argument evaporates.

The lesson: the theme invites atmosphere, and atmosphere is the easiest place to
hide a weak AI story.

## 1. The constraint that survived

The project that replaced it started from a single sentence:

> The model must be the only way to answer the user's question, and removing it
> must be a measurable regression.

Everything else was negotiable. That sentence is why there is an `ablate`
command, and why the no-model baseline was written before the model path.

## 2. Proving recovery without root

The riskiest assumption was that a deleted-file demo could be built without
root, a loop device, or a mount. The first experiment was `mkfs.ext4` +
`debugfs` on a file:

```bash
dd if=/dev/zero of=ghost.img bs=1M count=128
mkfs.ext4 -q -F ghost.img
debugfs -w -R "write photo.png /DCIM/photo.png" ghost.img
debugfs -w -R "rm /DCIM/photo.png" ghost.img
fls -r -d -p ghost.img
```

`fls` listed the deleted entry with its inode. `icat` returned the bytes.
`istat` returned the `Deleted:` timestamp. The demo was possible.

The second experiment was the one the story depends on:

```bash
debugfs -w -R "set_inode_field <18> size 0" ghost.img
```

The directory entry survives, the name survives, the deletion time survives, and
`icat` returns nothing. That is the "provably existed, unrecoverable" class. If
this had not worked, the project would have had no emotional payload and no
reason to exist.

## 3. Writing the baseline first

`stub_narrate()` emits only what `stat` can prove: name, kind, size, timestamps.
It was written before any prompt, on purpose. An ablation against a strawman is
not an ablation.

The baseline also set the tone for the model's output: short, plain, past tense,
no adjectives that are not in the evidence.

## 4. The benchmark that changed the grounding design

Three local models were compared on the same evidence table, same prompt, same
validator. The results, measured on this machine:

| Model | Latency (one epitaph) | Result |
|---|---|---|
| `gemma3:1b` | 21–24 s | cited the filename for a claim about a sunset; leaked few-shot example text into output |
| `qwen2.5:3b` | 13–75 s | fluent, but wrote "recovered from the deleted cluster" citing a deletion timestamp; support 0.00 |
| `gemma3:4b` | 63–75 s | 2/2 and 1/1 sentences supported on the same evidence |

The first validator only checked that cited ids existed. It published the 1B
model's sunset sentence. That is the moment the project changed: a citation is
not support.

`support_score()` was added — the fraction of the sentence's content words that
appear in the cited values, after a stoplist for function words and generic
visual nouns. `SUPPORT_THRESHOLD = 0.2`. Then the year check, because the 1B
model also invented a year that was not in the evidence.

The validator was still one-shot at this point: it struck bad sentences and the
artifact was left with nothing. The retry loop came next — feed the exact strike
reason back, once, and keep the best attempt. That is why `narrate()` takes
`attempts=2`.

## 5. The machine as a design constraint

Gemma 3 4B vision on this CPU takes 200–700 seconds per cold image. One run was
killed by the kernel after swap hit 8/8 GB and RAM hit 14 GB; the model had to
be stopped with `ollama stop` before the machine recovered.

This is not a footnote. It produced four design decisions:

- **`--vision-limit`**: triage the images most likely to be memories first, and
  leave the rest with their filesystem facts.
- **Content-addressed cache**: every model call keyed by model + system + prompt
  + image bytes. A re-run costs zero calls, which is what makes prompt
  iteration possible at all.
- **`keep_alive=30m`**: stop paying the load cost between calls.
- **`--vision-model` separate from `--model`**: a slow 4B vision model can
  coexist with a fast 1B text model.

A benchmark on a fast machine would have produced a worse product.

## 6. Where the agent was wrong

Recording this matters more than recording what worked.

- The first grounding check was too weak, and the agent's own benchmark caught
  it. The fix was a new check, not a better prompt.
- The first epitaph prompt produced sentences like *"The file, identified as
  E1, contained the word 'Mum'"*. Grammatical, cited, and unreadable. The fix
  was an explicit rule: cite ids in the `evidence` field, never in the prose.
- The first sample image was FAT32, which mangles the first byte of a deleted
  long filename (`letter.txt` → `_etter.txt`). That is a good story but a bad
  default, so ext4 became the default and FAT32 the option.
- An early README claimed "every phase writes to `case.json`" before the CLI
  actually did. The pipeline was changed to checkpoint after every phase rather
  than weakening the claim.
- The epitaph prompt was rewritten four times against the same two artifacts,
  and each version was worse in a new way. Rules alone produced
  *"The file, identified as E1, contained the word 'Mum'"*. Rules plus one
  worked example produced *"The triage label indicated a sunset landscape"* —
  the model had learned the shape and kept the tool's vocabulary. The version
  that worked carries two worked examples and renamed the evidence sources:
  `triage:label` became `description`, `exif:Model` became `camera`,
  `cluster` became `group`. The word "triage" disappeared from the output
  because it disappeared from the input. Renaming a column is not a prompt
  trick, but it changed the prose more than any rule did.
- The year check kept striking true sentences. The model wrote
  *"IMG_2021_0002.png was created on 2019-06-16T18:24:01 with an iPhone 8"* and
  cited the filename and the camera, skipping the `created` row. The agent's
  first instinct was to loosen the check. The better fix was to keep the check
  and complete the citation: a timestamp quoted character for character can
  only have come from one row, so that row is added and recorded as
  `auto_cited`. An invented year still dies.
- The content-quote rule was satisfied by quoting the single word "Mum,". The
  prompt asked for four consecutive words; nothing checked. It now asks for six,
  `quotes_content()` checks, and a missing quote triggers the retry instead of a
  strike.

## 7. What was measured, not assumed

- `fls` + `icat` + `istat` over 11 deleted entries: ~4 s.
- `nomic-embed-text` over 9 artifacts: < 2 s.
- Gemma 3 4B text call: 63–75 s warm, 165–1000 s when the prompt cache misses.
- Gemma 3 4B vision call, cold: 202 s, 529 s, 712 s on three attempts.
- Prompt processing on this CPU: 3.7 tokens/second. A 1,260-token prompt is
  342 seconds of pure prefill before the first output token exists.
- Cache hit: 0 s.
- Test suite: 37 tests, ~1.3 s, no model, no disk image.

## 8. What the agent did not do

It did not decide the product. The constraint, the rejection of the honeypot,
the decision to keep unrecoverable files in the report, the refusal to add face
recognition, and the choice to enter only three partner categories were human
decisions made against the agent's suggestions at least once each.

The agent wrote most of the code, ran the benchmarks, and found several of its
own failures. That is the honest division of labour, and it is the same division
the tool itself proposes: the model does the semantic work, the human decides
what is allowed to be published.
