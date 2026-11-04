# The Genuine-Handoff Experiment — NOVA Intelligence Assistance

**Status: DESIGN + BUILD COMPLETE (2026-10-27). $0 spent. No live calls
made. Paid testing NOT authorized — this document is the plan the user
authorizes against. Full design + costed plan; the build is mock-tested
only.**

## 0. Why this experiment exists

The Phase 1 audit (§17) proved the 600/600 is real — and proved the
model contributes **zero** of the NOVA arm's answers. The advisor gets
the same prompt as the alone arm, its output is never used, and the
pipeline **replaces** the model rather than assisting it. That is a
real result about the deterministic pipeline, but it is not evidence
that attaching NOVA improves a language model's own ability to answer
questions.

The user's research note (Oct 27, 2026) restates the original vision
and governs this experiment: *NOVA provides definitions, synonyms,
antonyms, simplified concepts, alternative interpretations, reasoning
steps, and verified answers. The language model receives that
information and generates the final response.* The objective is to
determine whether NOVA helps a language model answer questions it
previously could not answer.

## 1. Permanent architecture decision (user, Oct 27, 2026)

1. **Preserve BOTH capabilities.** NOVA's independent reasoning
   (symbolic reasoner, concept engine, knowledge retrieval,
   calculator, specialized modules solving supported problems on its
   own) is RETAINED in full. The handoff is a SECOND capability, not
   a replacement.
2. **NOVA Intelligence Assistance:** NOVA also functions as an
   intelligence adapter for existing language models — simplified
   concepts, definitions, synonyms, antonyms, alternative
   interpretations, reasoning steps, verified answers — and the LM
   generates the final natural-language response.
3. **Combined operation:** both capabilities work together. NOVA can
   independently solve supported problems, assist a LM with unfamiliar
   concepts, or verify the model's reasoning.
4. **PERMANENT DEVELOPMENT RULE:** never remove, replace, or weaken
   NOVA's independent reasoning capability merely to implement
   language-model integration. The handoff work is purely additive.
   The deterministic pipeline's behavior stays exactly as it is.
5. **Next milestone:** one verified execution trace demonstrating
   Spark receives NOVA's reasoning and produces the final response.
   No broader paid benchmarks until that handoff is verified.
6. **Long-term objective:** a modular intelligence system capable of
   both independent reasoning AND improving compatible LMs without
   weight changes.

Compliance in this build: no file in the deterministic pipeline was
modified (`nova/semantic/pipeline.py`, `reason.py`, `interpret.py`,
`extract.py`, `router.py` untouched). New code is additive only:
`nova/semantic/handoff.py` (new), `eval/run_handoff.py` (new),
`eval/gen_reserved.py` (new), `tests/test_handoff.py` (new), and
additive functions in `eval/harness.py` (`run_arm_handoff`,
`summarize_handoff`). One eval-harness scoring fix was made in
`eval/normalize.py` (digit-vs-word, §7) — it changes future scoring
of model arms only, not the pipeline. Verified: deterministic frozen
250/250 and fresh 250/250 still reproduce exactly; full test suite
OVERALL PASS; frozen baseline ZIP md5 unchanged
(`b8c7b5cb8a078a787cd85366779c9c5b`).

The third combined mode — **verification** (NOVA checking the
model's reasoning) — is NOT built in this task. The hook exists:
`nova.semantic.confidence.model_agreement_factor` already compares
an advisor's direct answer against the adjudicated answer. Wiring
it into a verification arm is named follow-up work, not part of
this experiment.

## 2. The handoff path (what is built)

### 2.1 The explanation package

`nova.semantic.handoff.build_explanation_package(text, knowledge,
rules, nova_request, ground_truth)` — deterministic, **zero model
calls**. It runs the SAME pipeline the independent NOVA arm runs
(text path, with the same structured-oracle fallback the harness
uses — `eval/harness._nova_answer` routing, including the rule that
an item whose ground truth is "unknown" abstains and never falls
through to the oracle) plus the Req 4 multi-interpretation pass
(deterministic simplifications only). The package contains:

| Section | Source |
|---|---|
| Definitions (dictionary/encyclopedia, term + meaning + source) | router per sentence over the fixture store; oracle dictionary/encyclopedia answers included with source named |
| Synonyms / antonyms (+ WSD sense) per term, max 3 terms | licensed production lexicon (`Lexicon.synonyms/antonyms/disambiguate`); absent lexicon yields empty lists, never an exception |
| 2–3 simplified interpretations (text, method, verdict, answer, proof) + agreement rate + contradiction flag | `interpret()` deterministic simplifications |
| Concept graph (actors, actions, objects, edges, max 12) | `ConceptGraph.from_frames` |
| Reasoning steps (the proof trace) | pipeline envelope `proof` |
| Verified answer + confidence + certified flag + provenance + input mode + missing reasons | pipeline envelope + `interpret()` confidence |

**Leakage rule (enforced, tested):** the package NEVER contains the
item's ground truth. The verified answer comes from the pipeline
envelope, never from the item. `ground_truth` is read ONLY for the
oracle-fallback routing decision. Test
`test_ground_truth_does_not_leak_into_content` proves it: rebuilding
a package with a deliberately wrong ground truth produces a
byte-identical package.

### 2.2 The prompt (exact, fixed order)

`build_variant_prompt(package, variant)` — five variants from the
same package, so arms differ only in which sections the model sees.
The full (H) prompt is:

```
You are answering a question. NOVA, a concept-reasoning system, has
already analysed it. Read NOVA's analysis, then give your own final
answer. If NOVA's analysis contradicts itself, or says the answer
cannot be determined, answer "I don't know" rather than guessing.

NOVA's understanding of the words:
- <term> (<kind>): <meaning>
- <term> — synonyms: ...
- <term> — antonyms: ...

How NOVA reads the question:
- Reading 1 (<method>): <verdict> — <answer>
- Reading 2 (<method>): <verdict> — <answer>
Agreement across readings: <rate>.   (or: These readings DISAGREE.)

The concepts and their relationships:
- Actors: ...
- Actions: ...
- Objects: ...
- <actor> --<rel>--> <target> ...

NOVA's reasoning:
- <proof step>
- ...

NOVA's verified answer: <answer> (confidence <c> against a bar of
0.85, <certified/not certified>; provenance: <sources>)

Question: <text>
Put your final answer alone on the first line: a number, yes, no, a
short definition, or "I don't know". You may add at most one short
sentence after it explaining your reasoning in your own words.
```

**Scoring rule (fixed with the prompt):** the answer instruction puts
the final answer alone on the FIRST line, so the first line is
normalized and scored; the rest of the response feeds the coherence
rubric only. This is deliberate: a free-form explanation may quote
story numbers ("Marcus gave John $20"), and scoring the whole text
would mine the wrong number out of it.

### 2.3 The arms

| Arm | Variant | What the model sees | What it isolates |
|---|---|---|---|
| A | — (template v2, as before) | question only | baseline |
| H | `full` | full package incl. verified answer | the vision as stated: does the LM follow correct reasoning to a correct final response? |
| H′ | `no_answer` | full package WITHOUT the stated answer (reasoning steps kept) | does the LM complete the reasoning from NOVA's steps? (the steps may implicitly reveal the answer — documented, not hidden) |
| B | `context` | lexical block + the question's sentences as a plain fact list | "more context" control: same facts, no NOVA computation (no interpretations, graph, proof, or answer) |
| C | retrieval only (existing) | template v2 + "Relevant knowledge" block | lookup alone |
| D | `translation` | interpretations only | restatement alone |
| E | `reasoning` | graph + proof steps, no stated answer | structured representation + reasoning steps, model does the last step |
| F | full NOVA deterministic (existing) | — | reference only, NOT re-run (250/250 frozen + fresh recorded) |
| G | deterministic without LM (existing) | — | reference only, NOT re-run |

H′ is a sub-arm of H, not in the original A–G list: H (with the
stated answer) measures copy-fidelity and override behavior; H′ is
the arm that tests the deeper question — whether the LM can answer
from NOVA's reasoning rather than from NOVA's answer. It costs
~$0.71 (mean) and may be dropped at authorization time.

## 3. Question sets

- **Development set: FRESH (250 items, seed 20261029).** The handoff
  arm has never run on it. The 50-item smoke subset is stratified by
  category, evenly spaced within each category (money 12, symbolic 6,
  calculator/synonym/negation/multi_step/dictionary 4,
  antonym/hard_negative 3, ambiguous/encyclopedia/knowledge_combo 2),
  fixed and reproducible (`eval/run_handoff.py: dev_subset`).
  Alone-arm answers for the dev-50 are extracted from the EXISTING
  v2 fresh alone run file — no re-run, no new calls.
- **Reserved evaluation set: RESERVED (250 items, seed 20261030).**
  `data/eval_uplift_reserved.jsonl` + `data/eval_reserved_manifest.json`
  (sha256 `693b426c9699dfe4…`). Same categories/counts as frozen/fresh.
  Verified disjoint: 0 text overlaps with frozen (242 texts), fresh
  (250), holdout (100), and money probes (100); 0 dropped items;
  knowledge routing 30/30. Third phrasings for dictionary
  (unquoted "Define X.", double-quoted 'What does "X" mean?') and
  third rewordings for encyclopedia; 4 new syllogisms (mammal/fur,
  vehicle/wheels, chef/cooks food, bird/feathers). **Do not run live
  until the single-trace milestone is verified and the paid run is
  authorized.** The CLI refuses `--set holdout` outright (argparse +
  explicit guard) — the holdout stays spent.
- **The fixture-echo caveat carries forward** (§17): the 30 knowledge
  items are graded against the same fixture definitions the store
  holds. Genuinely new terms from the licensed store are a named
  follow-up (after the production store is wired into the harness),
  NOT part of this set — keeping the reserved set comparable with
  frozen/fresh was the design choice.

## 4. Scoring

Per item, per handoff arm (recorded in each run record's `trace`):

- **Accuracy** — first-line normalized answer vs ground truth, same
  `check_correct` as all arms (incl. the honest-abstention rule for
  "unknown" ground truths). Reported with Wilson 95% CI and a paired
  bootstrap CI vs alone.
- **Coherence — deterministic 0–3 rubric** (`coherence_scores`):
  - **C1 answer present (0/1):** the first line normalizes to an
    answer.
  - **C2 grounded explanation (0/1):** there is an explanation line
    after the first AND it shares ≥1 content token with the NOVA
    package (definition term/meaning word, synonym/antonym, proof
    number, graph word, interpretation word). Answer-only responses
    score 0 here.
  - **C3 answer restated/supported (0/1):** no explanation
    (answer-only, scored 1 vacuously) OR the explanation contains
    the first-line answer's value (number: value or word form;
    yes/no: the word; text: a word from the first-line answer).
    An explanation that never mentions the stated answer scores 0
    by design.
  - Plus a **human-read sample: 20 items per arm**, hand-read by the
    run operator for fluency/naturalness (0–2), recorded in the run
    summary — not computed.
- **Corrected mistakes** — wrong→correct vs alone (same
  `classify()` buckets as before).
- **New errors / regressions** — correct→wrong vs alone, with
  regression rate.
- **Overrides** — NOVA's verified answer was correct AND the model's
  final answer is wrong (`trace.override`). Reported as a count, a
  rate, and a rate among NOVA-correct items.
- **Ignores** — comparison-time: the model's handoff answer equals
  its alone-arm answer while NOVA was right and the model wrong
  (the model behaved as if the package wasn't there).
- **Abstentions** — normalized None / "unknown" rates, handoff vs
  alone.
- **Token usage, latency, cost** — per item from the live API usage
  (same accounting as the alone arm); NOVA package-build time
  recorded separately as `nova_ms` (mean 5.8 ms/item, max 48 ms —
  negligible against ~2.8 s model latency).
- **Dictionary secondary score** — the audit found the keyword rule
  understates the alone arm's knowledge (13/15 fresh + 14/16 frozen
  alone dictionary "misses" are definitions a human grader would
  accept). The paid run hand-grades the reserved set's 20 dictionary
  items per arm against "would a human accept this definition"
  and reports it alongside the keyword score.

## 5. Failure modes to watch (and how each is detected per item)

| Failure mode | Detection (per item) |
|---|---|
| LM ignores NOVA content | `ignore` flag (handoff answer == alone answer, NOVA right, model wrong); also `matches_nova == False` while `nova_correct == True` |
| LM overrides correct NOVA reasoning | `override` flag (NOVA right, model wrong); override rate among NOVA-correct items |
| LM copies without reasoning | `copied_without_reasoning` flag (no explanation lines); C2 == 0 |
| LM contradicts itself | C3 == 0 (explanation never restates the stated answer); C1 == 0 with non-empty response |
| Truncation | `trace.truncated` (finish_reason "length"); max_tokens=2048 as in all v2 runs |
| Prompt sensitivity | H vs H′ gap (sensitivity to the stated answer line); B vs H gap (sensitivity to reasoning vs context); dev-50 vs reserved-250 stability for H |
| Package failure (no NOVA answer to hand off) | `nova_correct == False` with `input_mode`/`missing` recorded; items where the package says "cannot be determined" are analyzed as a subgroup (the model must abstain, not guess) |
| NOVA wrong, model right (model rescues NOVA) | `nova_correct == False` AND handoff correct — counted separately; a high rate here would mean the model is doing the work, not NOVA |

## 6. The staged paid plan (authorization gates)

**Stage 0 — Single verified execution trace (milestone 1). 1 live
call, ~$0.003.** Command:
`python3 -m eval.run_handoff --set fresh --variant full --live --trace fresh-003`
(`--trace` prints the full prompt, the package JSON, the raw
response, and the scoring.) Recommended item **fresh-003** — "Zoe
received $120 from Amir. Zoe gave Ivy $90. Noor gave $55 to Amir.
How much money does Zoe have left from the $120?" — verified answer
$30, confidence 0.950, certified, 4 proof steps, agreement 1.0.
Backup: fresh-004 ($58, same profile). **Acceptance criteria for
the trace:** (a) the prompt printed contains the full NOVA package
(definitions/readings/graph/steps/verified answer); (b) Spark's raw
response has the correct answer on its first line; (c) the response
contains at least one explanatory sentence in its own words (not a
bare copy); (d) the record is written with `mock: false` and the
cost recorded. If (b) fails, the trace is a finding, not a pass —
record the override and do NOT proceed to Stage 1 on the same prompt
without a design change.

**Stage 1 — Dev smoke. 100 live calls (H + B × dev-50), mean $0.28,
cap $0.38.** Commands: `python3 -m eval.run_handoff --set fresh
--variant full --live --dev-subset --with-alone` and the same for
`context`. Purpose: verify the prompts work live (no truncation
storm, no systematic first-line failures), measure real token
usage, and confirm the alone-arm reuse matches. Gate: proceed only
if no prompt-format defect appears (truncation ≤ 2/50 per arm,
C1 ≥ 0.9).

**Stage 2 — Main run. 1,750 live calls (7 arms × reserved-250),
mean $4.71, cap $6.48.** One command per arm (workers 4, ~20 min
total):
`python3 -m eval.run_handoff --set reserved --variant <v> --live --with-alone --workers 4`
for variants full, no_answer, context, translation, reasoning; plus
A and C via the existing `run_eval.py live3` path on the reserved
set (or `--with-alone` already covers A per invocation — the paired
summary is written per handoff run; A and C need one dedicated run
each for their own run files). F and G are NOT re-run (reference
values from §13/§16).

## 7. Normalizer fix (digit-vs-word artifact) — fixed, quantified

The audit found the model arms lose ~2 items per 250-set because the
keyword rule requires "six" where the model answers "6" (NOVA is
immune — it produces numbers). Fixed in `eval/normalize.py`:
`normalize_number` now parses number-word phrases ("six" → 6,
"twenty-one" → 21, "one hundred" → 100; whole-phrase only — mining
a number word out of a sentence is refused as ambiguous), and
`is_correct` for text items now expands digits↔words in both
directions before keyword containment. **Measured effect on the
recorded v2 live runs (re-scored offline, run files untouched):**
frozen alone 132→134, frozen retrieval 149→151, fresh alone
135→137, fresh retrieval 149→151, holdout alone 57→58, holdout
retrieval 57→58 — exactly the audit's predicted items (eval-004,
eval-240, fresh-012, fresh-145, holdout-092). **Past recorded
numbers stand as recorded under the old rule; the fixed rule applies
to the handoff experiment onward.** NOVA deterministic scores are
unaffected.

## 8. Cost of the paid run (measured, not estimated from guesses)

Basis: Muse Spark pricing $1.25/M input, $4.25/M output (Meta
Billing is the authority). Measured alone-arm (v2, fresh 250):
mean_in 63 tokens, mean_out 578 tokens, $0.00254/call, mean latency
2.7 s. Prompt lengths measured from the mock handoff runs (chars/4
token estimate, calibrated against the alone arm's 63 tokens ≈
250 chars): H mean 1303 chars (~326 tok, p95 1548, max 1633); H′
mean 1251 (~313); B mean 624 (~156); D mean 639 (~160); E mean 974
(~244). Mean estimate uses mean tokens_in + mean_out 578; cap uses
max tokens_in + 800 output tokens.

| Stage | Calls | Mean cost | Cap cost |
|---|---|---|---|
| 0 — single trace (H, 1 call) | 1 | $0.003 | $0.01 |
| 1 — dev smoke (H + B × 50) | 100 | $0.28 | $0.38 |
| 2 — main, A alone (250) | 250 | $0.63 | $0.88 |
| 2 — main, C retrieval (250) | 250 | $0.64 | $0.88 |
| 2 — main, H full (250) | 250 | $0.72 | $0.98 |
| 2 — main, H′ no-answer (250) | 250 | $0.71 | $0.97 |
| 2 — main, B context (250) | 250 | $0.66 | $0.93 |
| 2 — main, D translation (250) | 250 | $0.66 | $0.90 |
| 2 — main, E reasoning (250) | 250 | $0.69 | $0.95 |
| **Total (all stages)** | **1,851** | **$4.99** | **$6.87** |
| Total without H′ | 1,601 | $4.28 | $5.90 |

**Budget check:** master-program budget is $10 additional. Total
cap $6.87 leaves $3.13 headroom — enough for one full re-run of a
failed arm or a later Baseten comparison. No stage may proceed past
its gate without the user's go-ahead at that gate.

## 9. Go / no-go checklist (for the user to authorize paid testing)

- [ ] Design read (this document) — the handoff is understood as a
  SECOND capability; the independent pipeline is untouched.
- [ ] Mock verification accepted: full suite OVERALL PASS (13 suites
  + test_phase2 36 + test_concept_graph 27 + test_handoff 22);
  deterministic frozen 250/250 + fresh 250/250 reproduce; ZIP md5
  unchanged; mock handoff runs for all 5 variants complete ($0.00).
- [ ] Reserved set accepted: seed 20261030, 250 items, 0 overlaps,
  routing 30/30, manifest sha256 on file.
- [ ] **STAGE 0 authorized: run the single live trace**
  (`--trace fresh-003`, ~$0.003). The trace is the next milestone.
- [ ] Trace verified against the 4 acceptance criteria in §6
  (prompt contains the package; correct first-line answer; own-words
  explanation; record + cost written).
- [ ] **STAGE 1 authorized: dev smoke (H + B × dev-50, ~$0.28).**
- [ ] Smoke gate passed (truncation ≤ 2/50 per arm, C1 ≥ 0.9, no
  prompt-format defect).
- [ ] **STAGE 2 authorized: main run (7 arms × reserved-250,
  ~$4.71 mean / $6.48 cap).** H′ in or out? (Dropping it saves
  ~$0.71 mean / $0.97 cap.)
- [ ] Meta credits confirmed sufficient (session total so far ~$9.02
  of $150; the $10 master-program budget is the binding limit).

## 10. What this design does NOT claim

- It does not claim the handoff will improve the model — that is
  the experiment's question, and H′ exists precisely because H
  alone could show only copy-fidelity.
- It does not claim the reserved set escapes the fixture-echo
  caveat (§3) or the synthetic-template scope caveat (§17) — both
  are disclosed and carried.
- It does not claim coherence C2/C3 are human judgments — they are
  deterministic proxies; the human-read 20-item sample is the
  judgment, and it is small by design.
- The verification mode (NOVA checking the model's reasoning) is
  future work, not part of this experiment.

## 11. Files

- `nova/semantic/handoff.py` — package builder, 5 prompt variants,
  coherence rubric (new, additive only)
- `eval/harness.py` — `run_arm_handoff`, `summarize_handoff`
  (additive functions; RunConfig arm list extended)
- `eval/run_handoff.py` — CLI: mock (default) / `--live`, `--set`,
  `--variant`, `--dev-subset`, `--with-alone`, `--trace`
- `eval/gen_reserved.py` — reserved-set generator (seed 20261030)
- `data/eval_uplift_reserved.jsonl` (250 items) +
  `data/eval_reserved_manifest.json`
- `tests/test_handoff.py` — 22 tests (package, variants, coherence,
  runner, normalizer fix, dev subset)
- `eval/normalize.py` — digit-vs-word fix (§7)
- Mock run files: `eval/runs/20261027-06381*-handoff-fresh-*.jsonl`
  (all 5 variants, $0.00) + summaries
- This design doc: `EXPERIMENT_HANDOFF_DESIGN.md`
- Results record: `EVAL_RESULTS.md` §19
