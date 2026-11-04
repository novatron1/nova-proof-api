# Phase 1 Audit — NOVA Cognitive Adapter master program (independent)

**Auditor:** Phase 1 audit agent (independent — did not build any of this).
**Date:** 2026-10-27. **Scope:** the reported 600/600 claim in `EVAL_RESULTS.md` §§9, 11, 13, 16.
**Method:** every number below was recomputed from the raw `.jsonl` run files with
`eval/normalize.py`'s own functions; no number was copied from `EVAL_RESULTS.md` or
another agent's text without recomputation. No live model calls were made ($0).
Deterministic replays were limited to frozen/fresh records already on disk; the
holdout was **not** re-run in any form (it is spent — only its run files were read).
**Classification file:** `eval/runs/audit-phase1-classification-20261027.jsonl`
(600 records, one per question: set, category, alone/retrieval/nova correctness,
NOVA provenance class, advisor correctness, deterministic-match flag, leak/shortcut/
override flags).

## 0. Headline recomputation — the arithmetic reproduces exactly

| Set (template v2, Muse Spark 1.3) | Alone | Retrieval | NOVA | retr−alone | nova−retr | net |
|---|---|---|---|---|---|---|
| Frozen 250 (`20261027-041018`) | 132/250 = 0.528 | 149/250 = 0.596 | 250/250 = 1.000 | +0.068 | **+0.404** | +0.472 |
| Fresh 250 (`20261027-040137`) | 135/250 = 0.540 | 149/250 = 0.596 | 250/250 = 1.000 | +0.056 | **+0.404** | +0.460 |
| Holdout 100 (`20261027-053001`) | 57/100 = 0.570 | 57/100 = 0.570 | 100/100 = 1.000 | +0.000 | **+0.430** | +0.430 |
| **Total 600** | **324/600** | **355/600** | **600/600** | — | — | — |

Regression (alone-correct → nova-wrong): **0 in all three v2 sets** (0/132, 0/135, 0/57;
also 0 vs retrieval in all three). Classifications alone→nova: frozen 118 wrong→correct /
0 correct→wrong; fresh 115/0; holdout 43/0. Per-category tables in §§13.3 and 16
reproduce cell-for-cell from the raw files (checked every cell). Deterministic path
(model=None, `20261027-035709`): frozen **250/250**, fresh **250/250** — reproduces.
Disjointness verified by script, not by manifest text: **0 text overlaps** frozen↔fresh,
frozen↔holdout, fresh↔holdout, and vs the 100 money probes; manifest SHA-256 values
match the files (frozen `84c8bf24…`, fresh `f9560c12…`, holdout `41fd77a8…`).
Template v1 numbers also reproduce: fresh v1 alone 126 / retrieval 124 / nova 248
(`20261027-033104`); frozen v1 alone 126 / nova 250 (`20261027-025343`).

**No headline number failed to reproduce.** Two non-headline statements did not survive
(see §6.5, §6.6), and the claim needs narrowing even though the arithmetic is sound (§8).

## 1. Q1 — How many answers came directly from NOVA's deterministic reasoner?

Two different things hide under "the deterministic reasoner", and the audit answers both.

**(a) The SupervisoryReasoner (propositional yes/no reasoner) specifically: 175/600.**
Trace modules contain `reasoner` for 175 items (frozen 75, fresh 69, holdout 31).
By category: symbolic 72/72 (66 non-oracle + 6 oracle), antonym 36/36, negation 22/48,
hard_negative 17/36, ambiguous 11/24, synonym 11/48, knowledge_combo 6/24. The money
ledger, calculator and dictionary modules do **not** route through it.

**(b) The whole deterministic pipeline, with no model output used as the answer: 600/600.**
The NOVA answer is never the model's words. Evidence, three independent lines:

- **Code:** `_normalize_nova` (`eval/harness.py`) reads the structured envelope
  (`answer` / `verdict` / `answer.meaning`) and never touches `model_output`;
  `answer_text` (`nova/semantic/pipeline.py`) labels the advisor output
  `unverified_model_output` and never substitutes it.
- **Direct replay:** live NOVA normalized answers equal the model-free deterministic
  run's answers on **500/500** frozen+fresh items (`20261027-035709` det runs, 250/250
  each). For the holdout there is no deterministic run on disk and I did not create
  one (spent set) — so the holdout's 100/100 is deterministic *by trace mechanism*
  (same modules, same code path, advisor output unused), not by direct replay. That
  is a stated gap, not a verified fact.
- **Adversarial cases inside the live runs:** on the 10 live NOVA items where the
  advisor output was empty (4 oracle items where the model was never even called,
  plus truncated advisor calls on fresh-014, fresh-067, eval-129, holdout-097),
  NOVA still answered correctly on 10/10. An answer that survives its advisor
  being absent does not come from its advisor.

Provenance breakdown of the 600 (from the classification file; classes are exclusive,
priority oracle > lookup > reasoner > calculator > ledger > mixed):

| Provenance class | Frozen | Fresh | Holdout | Total |
|---|---|---|---|---|
| deterministic-ledger (money_engine only) | 86 | 86 | 32 | **204** |
| deterministic-reasoner (reasoner in trace, non-oracle) | 73 | 65 | 31 | **169** |
| mixed-deterministic (concept_translation + ledger/reasoner, or translation alone) | 36 | 43 | 17 | **96** |
| lookup (dictionary module only) | 30 | 30 | 12 | **72** |
| deterministic-calculator (calculator only) | 23 | 22 | 8 | **53** |
| structured_oracle (frames/task fallback) | 2 | 4 | 0 | **6** |
| **Total** | 250 | 250 | 100 | **600** |

So: the reasoner proper is 175/600 (29%); the deterministic pipeline as a whole is
600/600 (100%). Any submission text that says "the reasoner solved 600/600" is wrong;
"the deterministic NOVA pipeline solved 600/600, of which the propositional reasoner
handled 175" is right.

## 2. Q2 — How many were produced by Muse Spark after receiving NOVA's concept explanations?

**0/600. The described path does not exist in this system.**

NOVA never shows the model its concept explanations, frames, proofs, or any
system-generated analysis. The advisor prompt is the template-v2 prompt plus the
question text only (`advisor_prompt = advisor_template.format(text=text)` in
`pipeline.py`; `run_arm_nova` passes `PROMPT_TEMPLATE` when a model is supplied).
Verification from the records:

- Advisor output is byte-identical to the alone arm's raw response on **565/600**
  items (frozen 236/250, fresh 232/250, holdout 97/100) — the residual differences
  are run-to-run model variance on identical prompts, not extra information.
- Advisor accuracy, rescored from the recorded `model_output.text` with the same
  normalizer: frozen **132/250**, fresh **133/250**, holdout **55/100** — statistically
  the alone arm (132/135/57), exactly as §13.2 claims for the first two. The holdout
  advisor score (55/100) is new here; it was not reported in §16.
- Advisor outputs are terse: **0/600** exceed 200 characters (max 67). There is no
  explanatory content for the model to have received or produced.

The honest description is: **the model is a passive advisor whose output is recorded
and discarded; the uplift is the deterministic pipeline *replacing* the model, not
the model being helped by NOVA.** Any "model + NOVA explanations" framing must be
removed from submission materials. (Related: in the 6 oracle items the model is not
even called — `model_output` is absent entirely, because the `process_request`
frames branch never invokes the advisor.)

## 3. Q3 — How many required actual multi-step inference?

Depends on the definition; all three defensible counts are given so the claim cannot
be inflated by picking the largest silently.

| Definition | Count / 600 |
|---|---|
| Labelled `multi_step` category only | **48** (20 + 20 + 8) |
| Multi-operation categories: money + multi_step + symbolic (each needs ≥2 transfers/premises, or a 2-premise syllogism) | **264** (144 + 48 + 72) |
| Classification-file flag: above, plus any other item with ≥3 sentences | **324** |
| Clearly single-step: calculator (single expression, 48) + dictionary/encyclopedia (single lookup, 72) | **120** |

Supporting detail: money items carry 2–4 `$` amounts each (frozen 2:21 / 3:22 / 4:17;
fresh 2:9 / 3:28 / 4:23; holdout 2:6 / 3:13 / 4:5) — a balance answer requires parsing
2–3 transfers and maintaining a ledger, which is genuinely multi-step, though the
chains are short (longest is 3 transfers). The labelled `multi_step` items are often
only 2 transfers with a distractor (e.g. fresh "Noor gave his sister $7. Noor gave
Ivy $7. How much does Ivy have?"). Symbolic items are 2-premise syllogisms or
single-transfer entailments. **Nothing in the 600 requires a chain longer than ~3
operations.** A claim of "multi-step reasoning" should say "2–3 operation chains",
not imply deep inference.

## 4. Q4 — How many were solved through dictionary or encyclopedia lookup?

**72/600** — dictionary 48 (20+20+8) + encyclopedia 24 (10+10+4). All 72 have trace
modules `('dictionary',)` only, and all 72 NOVA answers are the **verbatim fixture
meaning** (`answer: {term, meaning}` from the authored store). The retrieval arm
solves the same 72 items by the same lookup (dictionary 48/48, encyclopedia 15/24 —
see §6.3 for why it loses 9 encyclopedia items).

Not lookup, and must not be counted as such: synonym/antonym items (the fixture store
contains **no** synonym/antonym relations — those items are solved by verb
canonicalization in the money parser plus the reasoner, i.e. code, not a store) and
knowledge_combo items (24/24 are premise entailment or single-amount extraction from
the question's own sentences, e.g. "Bees produce honey. Do bees produce honey?").

## 5. Q5 — How many depended on structured oracle inputs rather than natural-language understanding?

**6/600 actually used the oracle; 128/600 had one available.**

- `input_mode == "structured_oracle"` in the live NOVA traces: frozen eval-018,
  eval-056; fresh fresh-048, fresh-098, fresh-192, fresh-208; holdout **0**
  (the holdout carries no `rules` items, so no syllogism fallback was possible).
  All 6 are the prove/syllogism items whose text path returned no frames.
- **All 6 were already alone-correct** (the model answered "yes" on each), so the
  oracle contributed **0 fixes** to the 600/600. The 600/600 stands without them.
- The qualifier: the data files carry a `nova_request` on **128/600** items
  (54 frozen + 54 fresh + 20 holdout: dictionary 48, calculate 48, encyclopedia 24,
  prove 8). The fallback in `_nova_answer` only fires when the text path yields no
  answer and the ground truth is not "unknown", so 122 of the 128 were solved from
  text alone and the oracle never engaged. The system is therefore *text-first with
  a structured fallback*, not text-only — and the fallback's availability is a
  property of the evaluation data (the items ship with their own answer key in
  structured form), which must be disclosed. A clean external test would strip
  `nova_request` entirely; on current evidence that would change 0 items, but it
  has not been run that way.

## 6. Q6 — Leaks, shortcuts, unfair differences?

### 6.1 No answer leak into any prompt — checked, clean
Alone/retrieval/advisor prompts contain only the template + the question text
(+ a retrieved fixture definition in the retrieval arm). No ground truth, no
keywords, no NOVA frames/proofs/explanations appear in any prompt I could inspect
(code path + 565/600 advisor/alone byte-identical outputs + prompt fields in the
alone/retrieval records; NOVA records store `prompt: null` and the advisor prompt
is constructed in code, so the advisor side is verified by code + output identity,
not by a stored prompt string). When nothing is retrieved, the retrieval prompt is
byte-identical to the alone prompt on **528/528** such items (220+220+88).

### 6.2 Fixture-echo circularity — the sharpest finding (dictionary/encyclopedia, 72/600)
The 42 authored fixture entries (`eval/fixtures.py`) are simultaneously (i) the
knowledge store both lookup arms query, and (ii) the source of the ground-truth
keywords the normalizer requires. This is circular by construction:

- NOVA dictionary/encyclopedia answers are the fixture meaning verbatim → keyword
  containment passes automatically (72/72).
- Retrieval prompts contain **all** ground-truth keywords on 72/72 lookup items
  (the retrieved definition *is* the keyword source) → retrieval dictionary 48/48
  is faithful copying, not knowledge.
- The alone arm is scored against the same keywords, and its dictionary score
  (4–5/20 frozen/fresh, 7/8 holdout) **understates its knowledge**: of its 15 fresh
  dictionary misses, **13 are definitions a human grader would accept** (e.g.
  contract → "A legally binding agreement" vs the fixture's minority verb sense
  "become smaller in size", keyword "smaller"; photosynthesis → a correct
  scientific definition that says "light energy" instead of the keyword
  "sunlight"; orbit → "the curved path of an object around another in space",
  missing only the keyword "planet"); of its 16 frozen misses, **14** are the same
  pattern (auditor judgement — the full list is in the working notes; the pattern,
  not any single item, is the evidence). The fixture senses are in several cases
  idiosyncratic (contract-as-shrink, deposit-as-first-instalment, receipt-as-record),
  so the dictionary cell measures *agreement with the author's phrasing*, not
  definition knowledge, for every arm.

### 6.3 Digit-vs-word normalizer artifact — small, and it cuts against the model arms
`normalize_text_keywords` keeps digits as digits while several encyclopedia keywords
are number-words ("eight", "six"). The model answering "8"/"6" — correct content —
scores **wrong**. Affected items: fresh-012, fresh-145; eval-004, eval-240;
holdout-092 (plus fresh-141/eval-166 "expand" missing "heated", which is a real
content gap, not an artifact). With digit↔word equivalence, alone would be
137/135/58 instead of 135/132/57 and retrieval 151/151/58 instead of 149/149/57;
nova−retrieval would be +0.396/+0.396/+0.420 instead of +0.404/+0.404/+0.430.
NOVA is immune to this artifact because its structured answer always contains the
word form. Effect is small and does not change the conclusion, but the normalizer
should be fixed (or the asymmetry disclosed) before submission — it is currently
the only scoring rule that systematically favours the NOVA arm.

### 6.4 Scoring-channel asymmetry (structural, not a leak)
NOVA is scored from structured envelope fields (exact `answer`/`verdict`); the model
arms are scored from free-text normalization. NOVA never has to emit parseable
prose, and a truncated or empty advisor still scores correct (10/10 such items).
This is legitimate for a *pipeline* claim and is mitigated by the model-free
deterministic runs (250/250), but it is not a like-for-like answer comparison.
The v2 template fix closed the *prompt* asymmetry; the scoring-channel asymmetry
remains and should be disclosed in one sentence wherever the comparison is shown.

### 6.5 The v1→v2 template change — verified, and it confirms the audit's earlier point
v1→v2 (frozen): alone 126→132 (+6), nova 250→250. v1→v2 (fresh): alone 126→135 (+9),
retrieval 124→149 (+25: dictionary 0→20 accounts for +20, encyclopedia +4, plus
variance), nova 248→250 (+2, entirely the reasoner bug fix, not the template).
The v1 net +0.496 was inflated by ≈0.03, exactly as §13 states; the v2 nets
(+0.472/+0.460) are the sound ones. Retrieval's v2 gain over alone is concentrated
in knowledge items (fresh: 16 of 17 fixes had retrieved knowledge; the 17th,
fresh-109, had none and is variance; all 3 fresh losses had no retrieval, i.e.
byte-identical prompts — variance, not harm; frozen: 17 fixes / 0 losses).

### 6.6 Two statements that did not survive checking
- **§16, "the [2048-token] cap cost retrieval 3 items" (holdout-011/-028/-078): unsupported.**
  All three were *also* wrong in the alone arm (011 "I don't know", 028 "yes",
  078 "I don't know"), so truncation cost retrieval nothing measurable against
  alone. The correct statement is: "3 retrieval answers were empty due to
  truncation; all 3 were also wrong in the alone arm, so no loss vs alone is
  established." (The companion claim — NOVA's truncated holdout-097 still correct
  because the answer does not depend on the advisor — **is** verified.)
- **Frozen baseline ZIP md5 `b8c7b5cb8a078a787cd85366779c9c5b`: unverifiable.**
  No baseline ZIP exists anywhere in the repo or workspace I could search, so the
  value cannot be checked against a file. This is *not* evidence of tampering —
  the frozen set file itself hashes to its manifest SHA-256, and the frozen
  deterministic run is unchanged (0 diffs pre/post-fix) — but the md5 claim should
  be dropped or re-anchored to the actual ZIP before submission.
- Minor: §9's "5 of 500 calls truncated" count reproduces (alone eval-029, eval-123;
  nova eval-001, eval-097, eval-107), but the two alone truncations scored **wrong**,
  not as correct abstentions (their ground truths were 90 and "no").

### 6.7 Retrieval coverage vs what NOVA could access — the +0.404 needs its label
The retrieval arm receives definition frames only (30/250 per 250-set, 12/100
holdout). NOVA additionally uses the money ledger, the calculator, verb
canonicalization and the propositional reasoner — all from the same fixture store
plus code. The +0.404 is therefore "deterministic computation (ledger + arithmetic
+ verb handling + reasoning) minus lookup", **not** pure propositional reasoning
(that is 175/600 of the provenance). The §13 label "reasoning, not lookup" is
accurate only in that broad sense.
Two related disclosures: the production store (`data/knowledge.db`, 285 licensed
entries) is **never** loaded by the eval harness — `build_knowledge()` seeds only
the 42 fixtures — so there is no production-store leak into the eval; conversely
the 600/600 does **not** transfer to production (the production path's own frozen
score is reported as 222/250 in `PROVENANCE.md`, a number this audit did **not**
re-verify). And the holdout terms were in the fixture store from the start
(`build_knowledge` seeds all 42 entries for every run) — "unseen" means unseen
*questions*, not unseen store terms; the holdout is a new draw from the same
grammar, not a test of unseen vocabulary.

### 6.8 Template-generated distribution — the generalisation caveat
All 600 questions come from ~12 templates: masking names/numbers leaves only
128 distinct question shapes in the frozen 250, 129 in fresh, 71 in holdout.
Money verbs are dominated by "gave" (89/93/39 mentions); amounts and names come
from small fixed pools; 73/600 ground truths are "unknown". The generator and the
pipeline's parsers share this grammar (the parsers handle the generator's exact
constructions, e.g. the "gave his sister $7" distractor). The 600/600 therefore
measures competence on **this synthetic distribution**, and says nothing directly
about open natural language, unseen verbs, or unseen question forms. The fresh and
holdout sets are independent draws from the *same* generator, so they test
seed-variance, not distribution shift.

## 7. Q7 — Did NOVA ever override a correct model answer with an incorrect one?

**Yes — twice, under template v1. Zero times under template v2 (the submitted system).**

| Run | Alone-correct → nova-wrong | Retrieval-correct → nova-wrong | Advisor-correct → nova-wrong |
|---|---|---|---|
| Fresh v1 (`033104`, 250) | **2** — fresh-006, fresh-078 | **2** — same items | 0 |
| Fresh v1 smoke (`032938`, 10) | **1** — fresh-006 | 1 — fresh-006 | 0 |
| Frozen v1 (`025343`, 250) | 0 | — (no retrieval arm) | 0 |
| Frozen v2, fresh v2, holdout v2 | **0 / 0 / 0** | **0 / 0 / 0** | **0** (advisor correct on 320 items, all also nova-correct) |

The two v1 overrides are the same closed-world overreach already diagnosed in §13.1:
fresh-006 "Omar gave Felix $22. Did Omar pay Nina $22?" and fresh-078 "Noor gave Kofi
$7. Did Noor pay Owen $7?" — ground truth "unknown", alone arm correctly abstained
("I don't know"), NOVA answered "no". The deterministic pre-fix runs show the same
two misses (fresh det 248/250 at `035026`/`035239`); the post-fix deterministic diff
is **exactly those two items** (no → unknown), with **zero** frozen items changed,
and the post-fix det runs are 250/250 on both sets. The fix is verified, not merely
claimed — but the v1 overrides are a real part of the record and the submission
must not claim "NOVA never overrode a correct answer" without the v2 qualifier.
No override of any kind exists in any v2 run, any deterministic run post-fix, or
via the advisor (the advisor's output is never substituted, so it cannot override).

## 8. Verdict — is 600/600 sound as stated, and what is the honest claim?

**The arithmetic is sound; the claim as usually stated is not.** Every headline
number reproduces exactly from the raw files, the sets are disjoint, the deterministic
path reproduces model-free on frozen+fresh, and the v2 regression rate is genuinely
0.000. What fails is the *interpretation* that the numbers invite:

- It is not a model result. Muse Spark contributes **0** of the 600 answers; the
  model-free pipeline scores 250/250 on both 250-sets. The uplift is a
  *replacement* effect, not an *assistance* effect.
- It is not 600 tests of reasoning. By provenance: lookup 72, single-expression
  arithmetic 53, money ledger 204, mixed deterministic 96, propositional reasoner
  175 (incl. 6 oracle), structured oracle 6. Only 48 items are even labelled
  multi-step, and no chain exceeds ~3 operations.
- The knowledge cells (72/600) are fixture-echo tests: the store, the ground-truth
  keywords and the NOVA/retrieval answers are the same authored text. The alone
  arm's dictionary score understates its knowledge by roughly 3× on those items.
- The benchmark is a single synthetic grammar. Fresh and holdout are new draws
  from the same generator, not distribution shift; generalisation to open language
  is untested by these 600.

**The honest claim (recommended submission wording):**

> "On 600 synthetic template-generated questions across three disjoint sets
> (frozen 250, fresh 250, holdout 100), Muse Spark 1.3 alone scored 0.528–0.570,
> with retrieval 0.570–0.596, and with the deterministic NOVA pipeline 1.000 on
> all three (same prompt, template v2). NOVA over retrieval is +0.404/+0.404/+0.430;
> regression 0.000 under v2. The pipeline's answers are fully deterministic:
> the model-free run scores 250/250 on both 250-sets, the model acts only as a
> recorded-and-discarded advisor (0 answers come from it), and the structured
> oracle fallback fired on only 6/600 items (0 fixes). By provenance the 600 are:
> money ledger 204, propositional reasoner 175, mixed deterministic 96,
> dictionary/encyclopedia lookup 72 (verbatim fixture meanings), single-expression
> arithmetic 53. The lookup cells measure agreement with the authored fixture
> definitions, not open vocabulary knowledge, and all 600 questions come from one
> synthetic grammar, so this is a demonstration of reliable deterministic
> computation over a narrow distribution — not a general-intelligence result."

**Do not describe 600/600 as a general intelligence breakthrough.** The evidence
supports "a small deterministic system reliably solves the narrow synthetic
distribution it was built against, and the model adds nothing to it" — which is a
real, checkable engineering result, and is the claim that survives this audit.

## 9. What must change before submission

1. **Reword the claim** to the honest version in §8 everywhere it appears
   (submission, demo, paper draft): pipeline-not-model, provenance breakdown,
   lookup-echo caveat, synthetic-distribution scope. Remove any "model +
   NOVA explanations" phrasing — that path does not exist.
2. **Fix or disclose the digit-vs-word normalizer artifact** (§6.3): map number
   words ↔ digits in `normalize_text_keywords` (or re-score and report both
   ways). One-line fix, ~0.008 effect on the headline gaps.
3. **Correct the §16 truncation sentence** (§6.6): the cap did not measurably cost
   retrieval any items vs alone.
4. **Re-anchor or drop the baseline-ZIP md5** (§6.6): locate the actual ZIP and
   hash it, or remove the md5 from the record.
5. **Do not re-run the holdout** — including no deterministic replay of it — and
   do not claim its 100/100 is verified model-free (it is verified by trace
   mechanism only; see §1b).
6. **Do not claim "NOVA never overrode a correct answer" unqualified** — the v1
   overrides (fresh-006/078) are on the record; the true statement is "zero
   overrides under template v2".
7. **If an external-validity claim is wanted, earn it with a new test**, not with
   these 600: strip `nova_request` from the items and re-run frozen/fresh
   (predicted 0 changes — but unrun), and/or run a genuinely new-vocabulary or
   paraphrase set (Phase 2's new-terms 30/30 is the existing candidate; it was
   not re-audited here). Do not present the holdout as that test — it is the
   same grammar.
8. **No code or data fix is required for the 600/600 itself.** The v2 system as
   measured is what it claims to be arithmetically; the work is in the wording,
   the normalizer, and the two sentences above.

## Appendix — files and reproduction

- Runs recomputed: `20261027-040137` (fresh v2), `20261027-041018` (frozen v2),
  `20261027-053001` (holdout v2), `20261027-033104` (fresh v1), `20261027-025343`
  (frozen v1), `20261027-035709` (det post-fix), `20261027-035026/035239/035522`
  (det pre/post-fix), smokes `032938`/`035719`.
- Recomputation used the repo's own `eval/normalize.py` (`normalize_answer`,
  `is_correct`) and the harness `check_correct` rule; alone/retrieval
  recomputed-vs-recorded mismatches: **0** on all v2 arms (600×2 checks).
- Advisor rescoring: same normalizer applied to recorded `model_output.text`.
- Code read: `eval/harness.py`, `eval/normalize.py`, `eval/metrics.py`,
  `nova/semantic/pipeline.py`, `nova/semantic/production.py`,
  `nova/semantic/reason.py` (closed-world rule), `nova/semantic/router.py`,
  `eval/fixtures.py`, `eval/run_eval.py`, `data/eval_uplift*.jsonl`,
  manifests, `data/PROVENANCE.md`.
- Audit working notes: `/tmp/audit_phase1.py`, `/tmp/audit_phase1_out.txt`,
  `/tmp/build_classification.py` (not part of the repo).
