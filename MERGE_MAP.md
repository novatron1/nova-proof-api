# MERGE MAP — NOVA Cognitive Adapter v1.2 → main repo (merge work copy v1.3)

Date: 2026-11-02. Work copy: `~/workspace/nova-proof-api-merge-v13/`.
Main repo copied, never edited in place. Frozen baseline zip untouched
(md5 verified before and after: `b8c7b5cb8a078a787cd85366779c9c5b`).

Baseline in this work copy BEFORE any merge (my own runs):
`tests/run_all.py` OVERALL PASS (money 100/100 old + 100/100 integrated);
deterministic eval frozen (`--set eval`) 250/250; fresh (`--set fresh`)
250/250. No 42-item "boundary" set exists in this repo (probe files are
adversarial 49, ambiguous 12, paraphrase 36, new_terms 60) — the 42/42
boundary suite lives outside this repo, so that gate is reported as
not-runnable-here rather than assumed.

## Piece-by-piece assessment

### (a) External lexicon loading with shape validation
- v1.2: `load_lexicon(path)` — JSON object term → list of senses, each
  sense must have a non-empty string `meaning`; `synonyms`/`antonyms`/
  `cues`, when present, must be lists of strings. Malformed → ValueError.
  Never fabricates senses.
- Main: has a large licensed SQLite lexicon (`semantic/lexicon.py`,
  WordNet/Wiktionary) and a fixture Knowledge store, but NO loader for
  an externally supplied JSON sense dictionary with this validation
  contract.
- Verdict: **LACKS → MERGE** as new module `nova/semantic/sense_graph.py`
  (`load_external_lexicon`, ported validation semantics).

### (b) Separate sense graph (has_sense / synonym / antonym distinct)
- v1.2: `semantic_graph(lexical)` — nodes word/sense/related_word,
  edges `has_sense`, `synonym`, `antonym` kept as distinct relations.
- Main: `ConceptGraph` is frame/event-based; lexicon synonyms/antonyms
  are returned as flat lists (`_lexicon_block`), never as graph edges;
  no `has_sense` relation exists anywhere in the repo.
- Verdict: **LACKS → MERGE** in `nova/semantic/sense_graph.py`:
  `build_sense_graph(entries)` (v1.2 shape) + `sense_graph_for_terms()`
  built from the production Lexicon's real senses/synonyms/antonyms +
  `to_concept_graph()` bridge into the shared ConceptGraph format.

### (c) Handoff package: original + senses + cues + graph + proof status + coverage
- Main `semantic/handoff.py::build_explanation_package` already carries
  question (verbatim), definitions, lexicon relations + WSD sense,
  interpretations, graph lines, reasoning steps, verified answer,
  verdict, confidence/certification, provenance, `missing`, status.
  It does NOT expose an explicit parser-coverage block (what was NOT
  parsed), and its graph is frame-lines, not the sense graph of (b).
- v1.2 package carries `trace.coverage.unparsed_events` — unparsed
  money actions stay visible instead of disappearing.
- Verdict: **PARTIAL → MERGE (additive)**: package gains a `coverage`
  block (frames count, sentences count, unparsed sentence list computed
  by per-sentence frame parsing, missing list) and a `sense_graph`
  block from (b). No existing package key is changed or removed.

### (d) Concepts mode withholds verified answer (no leak)
- Main already has this: `no_answer` (H′) and `reasoning` (E) variants
  omit the verified answer; tests `test_no_answer_omits_verified_answer`,
  `test_ground_truth_does_not_leak_into_content`,
  `test_reasoning_no_answer_no_lexicon` already cover it.
- Verdict: **ALREADY PRESENT (section-level) → do not re-merge**;
  re-verified in `tests/test_merge_v13.py`. FINDING from that
  re-verification: the recorded `no_answer`/`reasoning` variants omit
  the verified-answer SECTION, but the value still appears inside the
  interpretations ("Reading 1: yes — $38") and the proof's final step
  for computation items — the same de-leakage limit the Arm D audit
  established (for calculator/multi-step the step IS the answer).
  The strict no-leak guarantee exists only in the new full-proof
  `concepts` mode, which withholds readings, proof and answer
  together (value-absence tested, $38 probe).

### (e) UNSUPPORTED does not force model abstention
- v1.2 prompt: "A NOVA UNSUPPORTED or ASSIST state means NOVA lacks a
  proof; it does NOT mean the answer is unknowable", plus
  `nova_authority: limited-domain evidence; not a verdict on
  answerability`.
- Main's recorded arm preambles say the OPPOSITE for the full arm:
  "If NOVA's analysis … says the answer cannot be determined, answer
  'I don't know' rather than guessing." Those prompt texts are frozen
  experiment instruments (recorded in the design doc + run configs);
  silently rewriting them would break comparability with every
  recorded run — the same class of distortion the taint rule forbids.
- Verdict: **CONFLICT → MERGE AS NEW PATH, recorded arms untouched**:
  new module `nova/semantic/fullproof.py` implements the v1.2
  authority semantics as the production-facing handoff (original
  question first, authority note, UNSUPPORTED ≠ unanswerable), while
  `handoff.py` arm prompts stay byte-identical for reproducibility.

### (f) Ledger hardening (v0.5–v1.1)
Main money engine is a different architecture (ConceptFrame events →
FIFO-lot Ledger in `nova/concept/ledger.py`; semantic pipeline on top).
Probed live in this work copy (answer_production, model=None):
- Decimal money: main uses float throughout (no `Decimal` anywhere).
  Cents probe ($10.10 − $0.20 = $9.90) happens to answer correctly.
  **WEAKER (exactness not guaranteed) → core conversion SKIPPED**
  (would touch every frame amount in the pipeline; documented gap).
- Chronological ordering: main parses sentences in text order; a
  give-before-receive probe answers correctly (120). **PRESENT.**
- Negation: negated-transfer probe answers 100, status candidate.
  **PRESENT** (and measured at scale in EVAL_RESULTS hard negatives).
- Self-transfer: main counts Mira→Mira $20 as spending → 25.
  v1.2 does not count it → 45. **MAIN WRONG → MERGE FIX** in
  `Ledger.apply` (giver == recipient: no balance/lot movement, trace
  note kept), gated by the full suite + both eval sets.
- Duplicate scoped deposit: main sums both matching $100 lots → 170
  and certifies it. v1.2 abstains (ambiguous scope). Changing the
  core answer type to abstention needs deep plumbing in the pipeline.
  **SAFETY GAP → documented; mitigated additively**: the new
  `coverage` block flags duplicate-scope ambiguity in the package so
  the model-facing handoff no longer presents it as clean.
- Refund counting: production path answers 70 (refund ignored,
  candidate status) where v1.2 gives VERIFIED 80. Root cause is in
  the free-text parser's verb coverage, not the Ledger. Parser surgery
  2 days before submission is the highest-risk change available.
  **GAP → documented, NOT merged in this pass.**

## Taint-rule audit (all prompt-building paths in this repo)
- `nova/semantic/handoff.py` — all 4 arm builders append
  `"Question: " + package["question"]` verbatim. Package question is
  the caller's text, unmodified. PASS (but see (e): full-arm preamble
  forces abstention on NOVA-unknown — recorded instrument, untouched).
- `eval/harness.py` — `build_prompt` = template.format(text=item text)
  verbatim; `build_retrieval_prompt` prepends a knowledge block and
  then the full verbatim prompt. PASS.
- `nova/semantic/pipeline.py` — advisor receives raw text or
  `advisor_template.format(text=text)`. PASS.
- No `redact` code exists anywhere in this repo — the redacted-step
  Arm D that produced tainted results (e.g. fresh-114) lived in the
  separate uplift branch, not in this codebase. Nothing to fix here;
  the new `fullproof.py` path is built taint-safe by construction and
  a regression test proves byte-identical original-question
  preservation, including a question whose only price ($80) appears
  in the question text itself (the fresh-114 pattern).
