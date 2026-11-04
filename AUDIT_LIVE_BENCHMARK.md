# Audit of the Live 250/250 Benchmark Claim

**Auditor:** independent-evaluation agent (not the Phase 1 team)
**Date:** 2026-10-27 (UTC; Oct 26 ~11 PM EDT local)
**Claim under audit:** "Muse Spark 1.3 alone 126/250 = 0.504 vs + NOVA 250/250 = 1.000,
net +0.496, regression 0.000" (EVAL_RESULTS.md §9, run
`20261027-025343-live-eval-comparison`)
**Method:** re-read the run files and re-computed every number from the
records; sampled and read raw model responses by hand; checked the
harness code paths that produce each arm. No run file was modified.
Analysis scripts: `/tmp/audit_analysis.py`, `/tmp/advisor_sample.txt`
(sample seed 20261029), `/tmp/audit_analysis.json`.

## Verdict

**The 250/250 NOVA score is real as a pipeline measurement, and it
reproduces exactly. The headline gap (+0.496) is NOT sound as a pure
capability claim, because the two arms were given different prompts
and the prompt difference — not NOVA's machinery — explains most of
the gap.**

The precise honest claim (see §7) is: *under template v1 (terse
answers only), Muse Spark 1.3 alone scored 0.504 while the NOVA
pipeline scored 1.000. When the same model is given the raw question
with room to reason, it answers roughly 70–95% of the alone arm's
misses correctly (sampled estimate), so the prompt asymmetry accounts
for the majority of the measured gap. NOVA's verified unique
contribution is the remaining items, plus a proof for every answer.*

What must change before the claim is finalized (§8): measure the model
alone under a fair prompt (raw text, room to reason — an "alone-raw"
arm with conclusion-based scoring), fix the template's answer schema
so text answers are permitted, and re-test knowledge items on
genuinely new terms from the licensed store. None of this changes the
NOVA score (250/250); it changes what the gap means.

## 1. Reproduction — the §9 numbers check out

Recomputed from `eval/runs/20261027-025343-live-eval-comparison-*.jsonl`
(250 records per arm, aligned by item id):

| Check | §9 says | Audit recomputation |
|---|---|---|
| Alone correct | 126/250 | 126/250 ✓ |
| NOVA correct | 250/250 | 250/250 ✓ |
| Classification wrong→correct / correct→wrong / correct→correct / wrong→wrong | 124 / 0 / 126 / 0 | 124 / 0 / 126 / 0 ✓ |
| Alone "I don't know" (verbatim, all 250) | 139 | 139 ✓ (24 of them correct — ground truth was unknown) |
| Alone misses that were abstentions | 117/124 (94%) | 115 verbatim "I don't know" + 2 empty = 117 ✓ |
| Alone confident-wrong | 7 | 7 ✓ (listed in §2) |
| Truncated at 2048 tokens | alone 2, nova 3 | alone eval-029, eval-123; nova eval-001, eval-097, eval-107 ✓ |
| Tokens in/out, cost $1.4935 | as recorded | totals match the summary file ✓ |
| NOVA input modes | text 248, structured_oracle 2 | text 248, structured_oracle 2 ✓ |

No errors, no fabricated usage, no overwritten files. The comparison
guard (identical model config in both arms) held: `muse-spark-1.3`,
temperature 0, max_tokens 2048, recorded in every record.

## 2. (a) The alone arm's 124 misses: abstention, not error

| Raw response class (alone arm, the 124 misses) | Count |
|---|---|
| Verbatim "I don't know" | 115 |
| Empty (truncated at the 2048-token cap) | 2 (eval-029, eval-123) |
| Concrete wrong answer | 7 |

The 7 confident-wrong answers, in full:

| Item | Category | Ground truth | Model answered |
|---|---|---|---|
| eval-032, eval-052, eval-132, eval-168, eval-178 | antonym | "unknown" | "yes" (5 items: give ⇒ take) |
| eval-004 | encyclopedia | keywords ["six"] | "6" (digit vs word) |
| eval-240 | encyclopedia | keywords ["eight"] | "8" (digit vs word) |

So 117/124 misses (94%) are abstentions or empty answers, and 5 of
the 7 confident-wrong answers are a single benchmark-convention case
(see §5): the benchmark's ground truth for "gave ⇒ took" is
"unknown", while the model (and any ordinary reader) says "yes".
The alone arm is not mostly *wrong* — it mostly *refuses to answer*.

## 3. (b) How NOVA fixed the 124 — and what the model itself could do

### NOVA's module contributions (from the NOVA-arm traces)

For the 124 wrong→correct items, the modules recorded in the trace
(items can carry more than one module, so the counts sum past 124):

| Module | Items |
|---|---|
| money_engine (ledger + frames) | 96 |
| concept_translation (5W1H / synonyms / negation) | 38 |
| dictionary (store retrieval) | 27 |
| reasoner (propositional yes/no) | 11 |

Structured-oracle use: 2 items in the NOVA arm (eval-018, eval-056 —
rule syllogisms whose text path yielded frames but an unknown
verdict). Both were already correct in the alone arm, so the oracle
path contributed **0** of the 124 fixes. The oracle is a real
methodological footnote (those 2 answers came from pre-structured
input, not from the question text), but it does not inflate the
uplift.

### The advisor test: same model, different prompt

The NOVA arm calls the same model as an *advisor* on the raw item
text, with no template and no instruction to be terse. Its output is
recorded (`model_output`) and never substituted for the proven
answer — which makes it a clean, built-in control for the prompt
difference: same model, same items, raw text instead of template v1.

Scored with the **same normalizer** the alone arm is scored with,
the advisor got 155/250 = 0.620 (vs alone 0.504), and 70/124 of the
wrong→correct items. But the normalizer is a bad instrument for
free-form text: `normalize_number` takes the **first** dollar amount
in the text, while a reasoning trace states the story amounts first
and the concluded answer last. Example (eval-009, ground truth 17):
the advisor writes "$35 - $18 she gave to Rosa = **$17**", and the
normalizer reads 35. Six of the eight number items I sampled first
were scored wrong this way despite correct conclusions in the text.

So I read a stratified random sample of 30 advisor texts by hand
(seed 20261029; 15 number, 10 yes/no, 5 text) and classified each
advisor's **stated conclusion** against the ground truth:

| Kind | Sample | Advisor conclusion correct |
|---|---|---|
| number | 15 | 15 |
| yes/no | 10 | 6 |
| text (definitions) | 5 | 5 |
| **Total** | **30** | **26 (0.867)** |

Wilson 95% CI for 26/30: **0.703–0.947**. Stratified by the
wrong→correct mix (78 number, 19 yes/no, 27 text), the point
estimate is ~116/124 (0.94); the pooled CI is the safer range:
**the advisor likely answers 70–95% of the alone arm's misses
correctly — roughly 87–117 of the 124.**

The 4 sample misses are all benchmark-convention cases, not
reasoning failures: 3 antonym give/take items (ground truth
"unknown", advisor says "yes" — the commonsense answer) and 1
closed-world hard negative (eval-080: ground truth "no" via the
completeness assumption, advisor abstains).

**Interpretation.** The model itself, given the raw question and
room to reason, answers most of the items the alone arm missed. The
prompt asymmetry — not NOVA's deterministic machinery — explains the
majority of the +0.496 gap. NOVA's verified unique contribution is:
(a) the remaining ~7–37 items the advisor gets wrong or cannot
answer (concentrated in the benchmark's closed-world and
give/take conventions), and (b) verification — a proof for every
answer, where the advisor's free-form reasoning is unverified prose.
The dictionary items make the point sharply: the advisor answered
all 5 sampled definitions correctly from its own parametric
knowledge, while the alone arm scored 0/20 — because the template
would not let it answer at all (see §4).

## 4. (c) The prompt difference — exact texts and a schema flaw

**Alone arm** — template v1, identical on all 250 items (exactly 1
distinct template in the run file):

> Answer the following question. Give only the answer: a number,
> yes, no, or "I don't know" if it cannot be determined.
>
> Question: {text}
> Answer:

**NOVA-arm advisor** — the raw item text, no template, no
instruction. The NOVA arm's `prompt` field is null on all 250
records; the advisor input is the question itself.

| | Alone arm | NOVA advisor |
|---|---|---|
| Mean input tokens | 58.5 | 26.2 |
| Mean output tokens | 617.1 | 763.7 |
| Mean prompt characters | 199.6 | 62.6 |

The advisor reasons more (764 vs 617 output tokens) because nothing
tells it to be terse.

**The template-schema flaw (the sharpest single finding).**
Template v1's permitted answers are "a number, yes, no, or 'I don't
know'". A *definition is none of those*. For the 20 dictionary
items, the correct answer type is excluded by the instruction itself
— the model cannot comply and answer correctly at the same time, so
it abstains on all 20 (every dictionary raw response is exactly
"I don't know"). The encyclopedia items confirm the mechanism: the
alone arm's only 3 correct answers there are the numeric ones (60,
366, 100), and its 2 numeric misses are digit-vs-word form ("6" vs
keyword "six", "8" vs "eight"). The dictionary +1.000 net is
therefore largely a **template artifact**, not evidence that NOVA
adds knowledge the model lacks — the advisor demonstrates the model
already knows these definitions.

Note what the asymmetry does *not* do: it cannot change the NOVA
score. The pipeline's answer never comes from the advisor, so the
250/250 stands regardless of the advisor's prompt. The asymmetry
changes what the *gap* means, not the NOVA measurement.

## 5. (d) Leakage checks — no contamination, one structural caveat

Checked directly, not assumed:

- **Eval ↔ holdout text overlap: 0 items.** Eval ↔ money-probes
  overlap: 0. Holdout ↔ money-probes: 0. (Set comparison on item
  texts; the generator's own guards agree.)
- **Model context:** the live adapter sends exactly one message —
  `messages: [{role: "user", content: prompt}]` — with no system
  prompt, no retrieved context, and no eval data. The advisor sees
  only the item text. The alone arm sees only the templated item.
- **Eval text in system code:** no eval item text appears in
  `nova/` or `eval/*.py` except three docstring/generator examples:
  `nova/semantic/router.py` docstring quotes "What does 'purchase'
  mean?", "How many legs does a spider have?", and "Prove Socrates
  is mortal." verbatim (eval-022, eval-240, eval-059), and
  `eval/gen_adversarial.py` reuses the Socrates syllogism as a
  generator template. These are documentation strings and a
  generator — the router's regexes do not depend on those specific
  strings — so this is co-development evidence, not leakage. It
  should still be cleaned up (reword the docstring examples) so the
  claim cannot be misread.
- **Fixture-derived knowledge items (the structural caveat).** All
  30 frozen dictionary/encyclopedia ground truths (12/12 holdout)
  have their keywords present in the stored fixture meaning, matched
  via each item's `nova_request.term`. The eval's knowledge questions
  were generated *from* the store's authored entries: the store is
  the knowledge being tested, and the items test retrieval of it.
  That is the harness working as designed — but it means the
  dictionary/encyclopedia categories measure **retrieval of the
  test's own fixtures**, not discovery of new knowledge. Combined
  with §3 (the model knows these definitions parametrically), the
  knowledge categories as run cannot distinguish "NOVA retrieved a
  definition" from "the model already knew it". The remedy is the
  fresh-set evaluation on new terms from the licensed store (§8).

**Leakage verdict:** no test data in training, no overlap between
sets, no eval text in the system under test. The limitation is
structural (fixture-derived knowledge items + prompt asymmetry),
not contamination.

## 6. Additional observations

- **Closed-world convention vs commonsense.** Several ground truths
  rest on conventions a careful reader would dispute: "gave ⇒ took"
  is "unknown" (5 alone-arm "yes" answers scored wrong; the advisor
  agrees with the model, not the benchmark), and unmentioned
  transfers are assumed not to have happened (eval-027, eval-030:
  the advisor abstains where the benchmark expects 0). NOVA scores
  these correctly *because it shares the benchmark's conventions*,
  not because it out-reasons the model. The conventions are
  documented in the generator and defensible — but the submission
  should state them, because on these items the "improvement" is
  convention alignment, not reasoning.
- **The NOVA arm equals the deterministic 250/250 (§8).** The live
  model adds nothing to the NOVA score — the advisor's output is
  discarded. That is the architecture working as designed, and it
  means the live run's new information is entirely about the alone
  arm, not about NOVA.
- **No version control.** The repo has no git history; the frozen
  baseline is protected by convention and manifest hashes only
  (`gen_eval --check` passes; eval sha256 `84c8bf249690f6df…`,
  holdout `41fd77a8fdd1c799…`). A frozen baseline that can be edited
  in place is a risk to the claim; the holdout guard and the
  manifest are the only backstops.
- **Cost.** The live run cost $1.4935 for 500 calls; the audit used
  no live calls (all analysis is on the recorded run files).

## 7. The precise honest claim

**Sound as stated:** "On the frozen 250-item eval set, the NOVA
pipeline answered 250/250 correctly with a proof for every answer,
while Muse Spark 1.3 alone under template v1 answered 126/250. The
NOVA measurement reproduces exactly from the run files."

**Not sound as stated:** "Attaching NOVA improved the model from
0.504 to 1.000" — as a claim about the model's capability. The
alone-arm number is a measurement of the model *under template v1*,
a prompt that forbids text answers and suppresses reasoning. The
same model, given the raw question, answers an estimated 70–95% of
those misses correctly. The improvement attributable to NOVA's
machinery (as opposed to the prompt) is the remainder — roughly
7–37 items — plus verification.

**Claim to use until §8 is done:** "Under a terse-answer prompt,
Muse Spark 1.3 alone scored 0.504 while the NOVA pipeline scored
1.000 with proofs. The model itself, given room to reason, answers
most of those items too — NOVA's demonstrated edge is on the
remaining hard cases and on proving every answer."

## 8. What must change before the claim is finalized

1. **Measure the model alone under a fair prompt.** Run an
   "alone-raw" arm on the frozen set: raw item text, no template,
   scored by conclusion (read the answer, or a normalizer built for
   free-form text — the current normalizer's first-number bias
   undercounts free-form answers badly). The number that matters is
   NOVA − alone-raw, not NOVA − alone-template-v1.
2. **Fix template v1's answer schema.** Permit text answers, or use
   a per-kind template. As written it cannot express a definition,
   which forces the dictionary 0/20.
3. **Re-test knowledge on genuinely new terms.** Dictionary and
   encyclopedia items on terms the model and the store have not been
   tuned to — from the Phase 2 licensed WordNet/Wiktionary store —
   so the knowledge categories test retrieval of new knowledge, not
   of the test's own fixtures.
4. **Clean the docstring examples** in `nova/semantic/router.py`
   (replace the verbatim eval questions) so no eval text appears in
   the system code at all.
5. **State the conventions** (closed-world completeness, give≠take
   as a stated fact) in the submission, since several items turn on
   them.
6. **Holdout stays single-shot** (`--final`, once, after Phases 2–3
   settle). It was not run in this audit and must not be run to
   "check" intermediate states.

## Appendix — audit evidence index

- Run files: `eval/runs/20261027-025343-live-eval-comparison-alone.jsonl`,
  `...-nova.jsonl`, `....summary.json` (read-only; untouched).
- §9 of EVAL_RESULTS.md: reproduced in full (§1 table).
- Advisor sample: `/tmp/advisor_sample.txt` (30 items, seed 20261029),
  classified by reading; normalizer-vs-reading comparison in §3.
- Leakage checks: set-overlap computation (0/0/0), code grep for
  eval texts, fixture-derivation check via `nova_request.term`
  (30/30 frozen, 12/12 holdout).
- Harness code read: `eval/harness.py` (arms, oracle fallback,
  normalization), `eval/live_model.py` (single-message calls),
  `eval/normalize.py` (first-number bias), `eval/fixtures.py`
  (42 authored entries), `eval/gen_eval.py` (generator + overlap
  guards), `nova/semantic/router.py` (routing regexes).
