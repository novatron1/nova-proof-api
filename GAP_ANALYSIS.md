# NOVA Cognitive Adapter — Gap Analysis

**Date:** 2026-10-26 (evening, after the v0.3.0 stabilization freeze)
**Scope:** read-only review of `~/workspace/nova-proof-api/` against the 7
requirements of the Meta Global AI Developer Hackathon project decision
(Oct 26, 10:41 PM EDT). **Submission deadline: Wed Nov 4, 2026, 9:00 PM ET.**
**Method:** read the code listed in the task; ran two read-only probes only
(`python3 tests/run_all.py`, and `nova.neural.fixtures.fixture_status()`).
No live API calls, no eval/holdout runs, no files modified.

**Verified baseline state (re-confirmed this session):**

- Full test suite `python3 tests/run_all.py`: **OVERALL PASS, 10 suites**
  (money 100/100 old path + 100/100 integrated, semantic 38, vendored
  adapter 20, regression 9, original v0.3 suite 20, harness mechanics 19,
  round-trip 4, stabilization 51, neural fixtures 11).
- Deterministic path on the frozen 250-item eval set: **250/250 = 1.000**
  (per `EVAL_RESULTS.md` §8; run `eval/runs/20261026-211242-*.jsonl`).
  Mock comparison (MOCK, not evidence): alone 64/250 vs mock+NOVA 250/250,
  net +0.744, 0 regressions.
- Neural fixtures: both checkpoint dirs present, all 5 required files each,
  weights 307,867,048 bytes each — but **`torch`, `transformers`, and
  `sentencepiece` are all absent** in this environment (verified by
  `fixture_status()` just now: `"loadable": false`). No pip installs allowed.
  `FlanT5Component.load()` raises `NeuralUnavailable` naming the missing
  modules. Translation-only verification (push1 2000/2000) stands.
- The Meta Model API connector exists at
  `~/workspace/custom-connectors/custom.meta-model-api/` and is verified
  working (base URL `https://api.meta.ai/v1`, `POST /chat/completions`,
  default model `muse-spark-1.3`, key held in the Secure Vault, verified
  Oct 26 with a hello call and a wug round trip). The vendored client does
  **not** yet use it (see Req 6).

**How to read this report:** for each requirement, (a) what exists, with
file/line references; (b) what is genuinely missing; (c) build steps for
Phases 2–4 in dependency order, each with an honest size note. Nothing
here is claimed without a code reference. Where a requirement is
unimplemented, this report says so plainly rather than re-describing a
neighbouring feature as if it covered it.

---

## Req 1 — Dictionary and encyclopedia integration for concept discovery and definition decomposition

### (a) What exists

- **Store + lookup.** `nova/adapter/core.py:29-37` — `Knowledge`, a SQLite
  store (`entries(kind, term, meaning, source)`, PK `(kind, term)`) with
  `add()` / `lookup()`. `NovaAdapter.process()` (`core.py:57-91`) serves
  `task: "dictionary"` / `"encyclopedia"` lookups, returning
  `retrieved`/`unknown` with an evidence record.
- **NL routing to the store.** `nova/semantic/router.py:79-122` —
  `_dictionary_term()` matches `What does 'X' mean?` / `Define X.`; the
  encyclopedia matcher (`_encyclopedia_term()`, lines 94-122) scores store
  entries by term-in-question plus shared content words and requires a
  strict best-beats-runner-up win (a tie routes to unknown, never a guess).
  `route_sentence()` (line 124) is wired into the parse order in
  `nova/semantic/extract.py` (after money tiers, before the heuristic tier).
- **Frames for definitions.** `nova/semantic/translate.py` —
  `knowledge_hit_to_frame()` builds a `kind="definition"` frame with a
  `defined_as` relationship and retrieval evidence; `frame_to_lookup()`
  maps a definition frame back to a store lookup. The reasoner answers
  retrieved definitions directly (`nova/semantic/reason.py`, `reason()`,
  definition branch).
- **Knowledge → reasoning/calculation bridges.** `nova/semantic/facts.py`,
  `find_per_unit_fact()` — a per-unit fact is found first in the story's
  frames, then in the store (the stored meaning is re-parsed with the
  same has-a extractor). `reason.py:231-270` (`reason_per_unit_total`)
  multiplies it out. This is the only place a stored definition is
  *decomposed* into structure rather than returned as an opaque string.
- **Eval stand-in data.** `eval/fixtures.py` — 20 hand-authored dictionary
  entries, 10 encyclopedia entries, plus 12 holdout-only terms
  (`DICTIONARY_HOLDOUT`, `ENCYCLOPEDIA_HOLDOUT`). `build_knowledge()`
  seeds a `Knowledge` store from them. The file header states explicitly
  that these are authored for the harness, NOT scraped and NOT a licensed
  import.

### (b) What is genuinely missing

1. **The production store ships empty.** `Knowledge()` defaults to
   `:memory:` with no seed data (`core.py:30`); `nova/api.py` and
   `nova/semantic/pipeline.py` construct it empty (`Knowledge()` with no
   arguments) unless a caller passes one in. Any dictionary/encyclopedia
   question about a term outside the 42 eval-fixture entries returns
   `unknown` in production. There is no data file, no seed script, and no
   import pipeline anywhere in the repo.
2. **No licensed data source has been chosen or imported.** No WordNet /
   Wiktionary / Wikipedia (or any other) dump, licence note, or attribution
   exists in the repo. `nova/adapter/PROVENANCE.md` states the store
   "ships empty; licensed dictionary/encyclopedia data must be imported by
   the user."
3. **Definition decomposition is nearly absent.** A retrieved definition is
   stored and returned as one opaque `meaning` string. The only
   decomposition is the has-a re-parse inside `find_per_unit_fact()`
   (e.g. "a spider has eight legs" → per-unit count). There is no general
   mechanism that breaks a definition into concept frames (genus +
   differentia, parts, properties, relations), and no `definition` frame
   ever becomes premises for the reasoner except through that one has-a
   path. The adversarial failure "A dozen is 12. How many eggs are in two
   dozen?" (`EVAL_RESULTS.md` §8) is exactly this gap: a per-unit fact
   stated only as an is-a definition is not read.
4. **Lookup is exact-term only for dictionary.** `Knowledge.lookup()` is an
   exact `(kind, term.lower())` match. Synonym/alias resolution for
   *lookup terms* does not go through the alias map (the alias map in
   `language.py:6` normalizes frame tokens, not store keys), so
   "What does 'auto' mean?" finds nothing even if "automobile" is stored.
   The encyclopedia matcher compensates partially with content-word
   scoring, but the dictionary path has no fallback.
5. **No concept discovery.** Nothing browses or suggests related concepts:
   no hypernym/hyponym, part-of, or "see also" relations in the schema or
   the store (the `entries` table has no relations column; `ConceptFrame`
   has a generic `relationships` list but nothing populates it from the
   store).

### (c) Build steps (dependency order)

1. **Choose and licence a data source** — pick one permissively licensed
   source that fits the demo (e.g. a small curated subset: WordNet-style
   glosses are licence-encumbered in some distributions; Wiktionary is
   CC BY-SA; a hand-curated seed list is licence-clean but small).
   Record the licence + attribution in the repo. *Small (decision +
   half a day of verification); blocks everything below.*
2. **Import script + seeded store file** — a script (e.g.
   `data/import_knowledge.py`) that builds a SQLite `.db` from the chosen
   source and a committed seed file the API loads at startup instead of
   an empty `:memory:` store. Must keep the eval fixtures separate so the
   frozen benchmark is untouched. *Medium (1 day); the single most
   valuable Req 1 step for the demo.*
3. **Alias-aware lookup** — route dictionary terms through the existing
   alias/normalization map before the exact lookup, and add a
   "no exact match → encyclopedia fallback" already present for `Define`
   to the `What does X mean?` path as well. *Small (half a day).*
4. **Definition decomposition (narrow, then general)** — first, extend
   `find_per_unit_fact()`-style re-parsing to is-a definitions ("A dozen
   is 12" → per-unit fact). Then, a decomposition pass that parses a
   retrieved definition with the existing fact extractors (is-a / has-a /
   state) into frames with `defined_as` provenance. *Medium (1–2 days
   for the narrow fix; the general pass is open-ended — cap it).*
5. **Concept-discovery relations (optional for Nov 4)** — add a relations
   table / `related_to` entries and surface them in definition frames.
   *Medium; deferrable — cut first if time is short.*

---

## Req 2 — 5W1H semantic interpretation: who, what, when, where, why, how

### (a) What exists

- **Shared 5W1H slots.** `nova/semantic/frame.py` — `ConceptFrame` carries
  `who / what / when / where / why / how` plus `recipient / object /
  quantity / units / polarity / certainty / relationships / evidence /
  source_text`. Unknown slots are explicit `None`, never invented.
- **Vendored heuristic extractor.** `nova/adapter/language.py:16-43` —
  `extract()` fills all six slots by regex: `who` = last meaningful word
  before the first known verb; `what` = verb from a closed map;
  `when` = date regex (`DATE`, line 10: yesterday/today/tomorrow/weekday/
  month+day); `where` = `PLACE` regex (`at|in|inside|near` + up to 4 words);
  `why` = `because|since` clause; `how` = `by|using` clause. Returns
  `coverage` (count of non-None slots) and a `partial_interpretation`
  status with a warning that roles/word senses need validation.
- **Semantic-layer extension.** `nova/semantic/extract.py` — tier-2
  `_heuristic_to_frame()` adds structured quantity/recipient/object
  recovery on top of the vendored extractor, an extended verb map
  (`_EXTRA_VERBS`, lines ~38-48: base forms the vendored map lacks —
  pay/send/purchase/approach/leave/visit/carry, plus sell/take/hand/
  lend/borrow/produce/make/receive), extended negators, and a corrected
  actor picker (`_who_from_prefix()`). Verified: "Marcus gave his sister
  $50 yesterday at the store because she needed groceries" → all slots
  filled, `how=None` (`RESULTS_INTEGRATION.md` §5).
- **Measurement.** `nova/semantic/roundtrip.py` — NL → frames → NL
  preserves 114/114 slots (1.000) on the 26-sentence probe set
  (`tests/test_roundtrip.py`).

### (b) What is genuinely missing

1. **The verb inventory is tiny and hand-listed.** Vendored `VERBS`
   (`language.py:5`) has 19 entries covering 8 actions; the semantic
   extension adds ~17 more. Anything outside the list yields `what=None`
   and (usually) no frame. Adversarial set: 38/46, with 4 failures on
   uncovered money verbs alone — "handed", "wired", "passed",
   "transferred" (`EVAL_RESULTS.md` §8). Free-form paraphrase ("a
   tenner") still 422s on `/reason`.
2. **When/where/why/how are shallow regexes, not interpretation.**
   `when` matches only a fixed date vocabulary (no durations, no
   relative clauses, no "after X"); `where` is a preposition + noun
   chunk (no nested locations); `why`/`how` are single-clause captures
   that stop at the first boundary word. There is no disambiguation when
   several candidates match, and no slot is ever validated against the
   others.
3. **Role assignment is positional, not semantic.** `who` is "the last
   meaningful word before the verb" — it breaks on multi-word actors
   except where special-cased (balance questions), on passives, and on
   any sentence whose subject is not adjacent to the verb. The
   deterministic money parser (`nova/concept/events.py`) covers only
   single-name actors in three fixed templates.
4. **No coverage target beyond the eval set.** The 5W1H extractor is
   measured only on the frozen eval + 26 round-trip sentences, all of
   which were written to fit it. There is no held-out paraphrase suite
   for 5W1H specifically (the adversarial set is the closest thing, and
   it scores 3/8 on unfamiliar paraphrase).

### (c) Build steps (dependency order)

1. **Widen the verb map from the failure list first** — add the four
   adversarial verbs (handed/wired/passed/transferred) plus their
   inflections to `_EXTRA_VERBS`, with tests. *Tiny (1–2 hours); closes
   4 known failures immediately.*
2. **Paraphrase grounding via the language model (Day-4 component)** —
   use Muse Spark (via the Req 6 adapter) to map an unfamiliar sentence
   to a canonical frame / simplified paraphrase the deterministic tiers
   can read, with the frame — not the model's words — as the answer
   input. This is the planned fix for the whole class, not just four
   verbs. *Large (2–3 days); has an explicit kill criterion — if not
   converging by Oct 30, cut it and ship the deterministic core
   (`RELEASE.md`, README "What is NOT here yet").*
3. **Slot validation pass** — cross-check slots (e.g. a `where` that is
   really a time phrase, a `who` that is a verb) and report conflicts
   in `missing` instead of silently keeping the first regex match.
   *Medium (1 day); do after step 2 so it validates model-produced
   frames too.*
4. **A paraphrase probe set for 5W1H** — a fresh, frozen set of
   paraphrased sentences with expected frames, separate from the eval
   set, so step 2 is measured rather than eyeballed. *Small (half a day
   to generate + verify by hand).*

---

## Req 3 — Synonym, antonym, negation, and intent-preserving concept translation

### (a) What exists

- **Synonyms.** `nova/adapter/language.py:6` — `ALIASES` (kid→child,
  bicycle→bike, automobile→car, vehicle→car, scared/frightened→afraid,
  verb forms). Applied by `normalize()` and by `normalize_person()` in
  `nova/semantic/frame.py` (person keys join up: "his sister" and
  "sister" → "Sister"). `nova/semantic/translate.py` — money verbs
  give/send/pay canonicalize to one `give` predicate in facts
  (`frame_to_fact()`), and `receive` is inverted to `give(A,B,X)`.
- **Antonyms.** `nova/semantic/facts.py` — `ANTONYM_ADJECTIVES`, 21
  adjective pairs (open/closed, hot/cold, full/empty, on/off, big/small,
  tall/short, fast/slow, light/dark, high/low, long/short, wide/narrow,
  strong/weak, rich/poor, happy/sad, early/late, new/old, clean/dirty,
  safe/dangerous, loud/quiet, hard/soft, deep/shallow). Used by
  `_state_antonym()` in `nova/semantic/reason.py:414-438` to prove a
  "no" from a stated opposite state, and by the adjective is/state
  equivalence in `_adjective_alt_goal()` (`reason.py:47-63`).
- **Negation.** First-class `polarity` field on every frame
  (`frame.py`); vendored negator set (`concepts.py:5`) plus extended
  negators (`cannot`, `can't`, …) in `extract.py`; a negated frame
  **never** becomes a positive transfer (`translate.py`,
  `frame_to_transfer()` returns `None`) or a positive fact
  (`frame_to_fact()` prefixes `not …`); negated receive settles
  "Did B receive…?" as "no"; a negated state ("not on") does **not**
  prove the opposite ("off") — scope discipline is tested
  (`tests/test_stabilization.py`).
- **Concept translation (frame ↔ module).** `nova/semantic/translate.py`
  — total, strict adapters between ConceptFrame and money engine,
  Knowledge store, calculator, memory, and the symbolic reasoner.
  `nova/neural/translate.py` — checkpoint JSON frames ↔ ConceptFrame,
  verified lossless on the recorded push1 data (2000 rows) and push2
  gold frames (500 sampled).
- **Comparison (candidate only).** `nova/semantic/compare.py:23-39` —
  `compare_concept_frames()` returns `candidate_equivalent` /
  `possible_contradiction` / `undetermined` / `unknown`, with
  `certified: False` **always**. Same contract in the vendored
  `nova/adapter/concepts.py:19-28` (`compare_frames()`).

### (b) What is genuinely missing

1. **The synonym inventory is a dozen hand-written pairs.** No
   WordNet-style synonym resource, no verb synonym expansion beyond the
   verb map, no noun synonyms beyond the alias list. Any synonym outside
   the list (e.g. "auto", "sofa/couch", "purchase/acquire") fails to join
   up. This is the same root cause as the Req 2 verb gap, seen from the
   translation side.
2. **Antonyms cover adjectives in state facts only.** No noun antonyms,
   no verb antonyms (buy/sell is handled only as "not equivalent" in
   comparison, never as a provable "no" — "Did John sell a bike?" after
   "John bought a bike" returns `unknown`, recorded in
   `RESULTS_INTEGRATION.md` §7 and `test_antonym_story_answers_no`).
   The antonym map itself is hand-listed; there is no source or
   completeness claim for it.
3. **No intent-preserving translation step exists as a component.**
   There is no function that takes a concept and produces an
   intent-equivalent paraphrase, or that certifies two phrasings share
   intent. What exists is (i) normalization (same surface → same token)
   and (ii) comparison (two texts → a candidate relation). "Intent
   preservation" is asserted by construction in the round-trip test
   (114/114 slots), not by a translation module. The Day-4 learned
   component is the intended home for this; it does not exist yet.
4. **Comparison can never certify.** `certified` is hard-coded `False`
   in every return path of both compare implementations. That is honest
   for heuristic input, but it means the "agreement and contradiction
   checks" the project description promises can only ever return
   candidates — there is no defined bar (e.g. deterministic-parse +
   identical signature + same polarity) under which a comparison
   *would* be certified. No such bar is specified anywhere in the docs.

### (c) Build steps (dependency order)

1. **Define the certification bar** — write down, in code + test, the
   conditions under which `compare_concept_frames()` may return
   `certified: True` (proposed: both frames deterministic/`verified`,
   identical signature, same polarity, same source scope). Without this
   decision the field stays decorative. *Small (half a day, mostly a
   decision + tests).*
2. **Verb-antonym "no" for buy/sell (and give/take)** — extend the
   closed-world/state-antonym logic so a stated purchase settles a
   sell-question as "no" where the story supports it, with the same
   scope discipline as the adjective case. *Medium (1 day).*
3. **Synonym resource import** — same import pipeline as Req 1 step 2,
   for synonyms/antonyms (a licensed thesaurus subset or a curated list
   scoped to the demo domain). Feeds both the alias map and lookup.
   *Medium (1 day); depends on the Req 1 licencing decision.*
4. **Intent-preserving paraphrase via the model (Day-4 component)** —
   the model proposes a simplified paraphrase; NOVA re-parses it and
   compares frames (Req 4's machinery) before accepting it as
   intent-preserving. *Large (2–3 days); same kill criterion as Req 2
   step 2 — this is the same component viewed from the translation side.*

---

## Req 4 — Multiple simplified interpretations of difficult questions, with agreement and contradiction checks

### (a) What exists

- **Almost nothing that matches the requirement as written.** A grep for
  `simplif`, `multiple interpretation`, `agreement`, `ensemble`, `vote`,
  `consensus` across `nova/`, `eval/`, and `tests/` returns **zero hits**.
- The nearest neighbours, none of which generate multiple
  interpretations:
  - `nova/semantic/compare.py:41-48` (`compare_texts()`) compares
    **two** given sentences via their first frames.
  - `nova/adapter/concepts.py:19-28` (`compare_frames()`) and
    `nova/adapter/language.py:45-49` (`compare()`) do the same pairwise
    candidate comparison.
  - `nova/semantic/roundtrip.py` measures whether **one** interpretation
    survives NL → frames → NL (114/114 slots).
  - The supervisory reasoner returns verdict `both` when the frames
    support a goal **and** its negation (`nova/adapter/core.py:39-52`,
    `Reasoner.prove()`; surfaced in `nova/semantic/reason.py`), i.e.
    contradiction *detection over given premises* — but nothing
    generates the alternative readings that could contradict each other.
  - `nova/adapter/core.py:57-91` (`NovaAdapter.process`, task
    `"augment"`) sends one heuristic analysis to the model and returns
    its output as `unverified_model_output`. That is one model opinion,
    not multiple interpretations, and it is never compared against
    anything.
- The pipeline has exactly one parse path per sentence
  (`nova/semantic/extract.py`, `parse_sentence_to_frame()`): tiers are
  tried in order and the first that matches wins. There is no code path
  that keeps two candidate parses of the same sentence alive.

### (b) What is genuinely missing

Everything, as a feature: (1) a **simplification step** that produces
simpler restatements of a difficult question; (2) **multiple**
interpretations held simultaneously (the frame schema and the pipeline
both assume one frame per sentence — `parse_text_to_frames()` returns a
flat list, and `find_query()` takes the first query frame); (3)
**agreement checking** across interpretations (no voting, scoring, or
consensus rule); (4) **contradiction checking** across interpretations
(the `both` verdict and `possible_contradiction` relation operate on
premises and on two externally supplied texts, not on generated
alternatives); (5) an **adjudication rule** for what the system answers
when interpretations disagree (majority? abstain? ask?).

### (c) Build steps (dependency order)

1. **Multi-parse representation** — allow `parse_sentence_to_frame()`
   (or a new wrapper) to return a *list* of candidate frames per
   sentence with a source tag each (deterministic / heuristic /
   model-simplified), and carry that list through the envelope instead
   of collapsing to one frame. This is a schema + pipeline change that
   every later step depends on. *Medium (1 day); the riskiest
   refactor in this requirement — keep the single-frame path as the
   default so the frozen eval still passes.*
2. **Simplification generator** — two sources, in order: (a) template
   simplifications the system can already do (strip subordinate
   clauses, split a compound sentence, replace a verb with its alias
   canonical form); (b) model-proposed simplifications via the Req 6
   adapter ("restate this question in the simplest words, keeping the
   same meaning"). *Small for (a) (half a day); medium for (b) (1 day,
   needs Req 6 working).*
3. **Agreement / contradiction check over candidates** — reuse the
   existing `compare_concept_frames()` pairwise over the candidate set:
   all-agree → answer from the agreed frame; any
   `possible_contradiction` → surface the conflict and abstain or
   answer with the disagreement named; partial agreement → report the
   split. Add the certification bar from Req 3 step 1 so an all-agree
   deterministic set can be reported as more than a candidate.
   *Medium (1 day); depends on steps 1–2.*
4. **Adjudication + rendering** — extend `render.py` so a disagreement
   renders as "I read this two ways…" with both readings and their
   proofs, instead of today's single-answer envelope. Add tests +
   a small probe set (ambiguous questions with two defensible readings).
   *Medium (1 day); depends on step 3.*
5. **Wire into the demo** — one scripted demo question that genuinely
   benefits (e.g. an ambiguous scope question), so the feature is shown
   rather than asserted. *Small (half a day).*

---

## Req 5 — Supervisory symbolic reasoning, calculator integration, evidence tracing, and calibrated confidence

### (a) What exists

- **Symbolic reasoning.** Vendored four-valued prover
  (`nova/adapter/core.py:39-52`, `Reasoner.prove()` — forward chaining,
  verdicts yes/no/both/unknown + trace, `max_steps=100`). Supervisory
  layer `nova/semantic/reason.py:95` (`SupervisoryReasoner`) routes to:
  ledger balance (`reason_balance`, line 109), balance yes/no with
  closed-world reasoning (`reason_balance_yes_no`, line 167), per-unit
  totals (`reason_per_unit_total`, line 231), amount-paid
  (`reason_amount_paid`, line 272), and propositional goals
  (`reason_goal`, line 344) with rule instantiation
  (`_instantiate_rules`, line 311 — universal instantiation over
  `is(...)` facts), adjective is/state equivalence, state-antonym
  "no", and closed-world near-miss "no" for transfers. Ablation
  (v0.3.0, honest): removing the reasoner costs −30.0 points.
- **Calculator.** Safe AST evaluator (`core.py:6-22`, `calculate()` —
  depth ≤ 15, length ≤ 120, magnitude caps, no names/attributes/calls,
  code-injection rejected). Wired via the router
  (`router.py:59-77`, word operators translated, strict charset check),
  via `translate.py` (`frame_to_calculation()`), and via the adapter
  passthrough (`task: "calculate"`). Ablation: removing it costs 0.0 on
  the frozen set only because the fact/router tiers now cover those
  items — the module still matters for questions the fact tier cannot
  read (see `EVAL_RESULTS.md` §8).
- **Evidence tracing.** Every frame carries `evidence` (source /
  statement / kind) and `source_text`; every reasoner result returns
  `proof` (ordered steps), `evidence`, `missing`, and
  `unusable_frames`; the renderer prints the proof with the answer
  (`nova/semantic/render.py`). Unusable frames are reported, never
  silently dropped. The zero-audit is tested (`tests/test_stabilization.py`):
  unknown stays unknown in the ledger, calculator, renderer, and API
  envelope.
- **Honest status vocabulary (not confidence).** Statuses
  `verified / verified_logic / candidate_interpretation /
  partial_interpretation / unknown / retrieved` plus `certainty`
  (`known / uncertain / unknown`) on frames and `complete` (bool) on
  results. Model output is always labelled `unverified_model_output`
  and never substituted for a proven answer (`pipeline.py`,
  `answer_text()`).

### (b) What is genuinely missing

1. **Calibrated confidence does not exist.** There is **no numeric
   confidence anywhere** in `nova/` or `eval/` — a grep for
   `confidence`/`calibrat` finds only "Wilson 95% confidence interval"
   in the eval metrics, which is a property of the benchmark, not of
   any answer. No confidence field on `ConceptFrame`, no confidence in
   any envelope, no calibration data, no mapping from
   (deterministic/heuristic, complete/incomplete, agree/disagree) to a
   number. The status vocabulary is doing the job confidence would do,
   categorically. Any demo slide or submission text claiming
   "calibrated confidence" would currently be unfounded.
2. **No proof certificates.** Proofs are traces (ordered strings), not
   signed or checkable artifacts. Recorded as an open gap in
   `RESULTS_INTEGRATION.md` §7. A verifier that replays a proof
   independently of the prover does not exist.
3. **Reasoner expressiveness limits (known, measured).** Rules
   instantiate only over `is(...)` facts with is-a consequents; modal
   consequents ("If someone is a bird, they can fly") and has-a
   consequents ("If something is a fruit, it has seeds") are left
   unparsed — 2 of the 8 adversarial failures (`EVAL_RESULTS.md` §8).
   No quantifiers beyond the single "if someone/something is A" form;
   no chaining beyond one instantiation step per rule application
   (forward chaining iterates, but each rule only fires on `is(...)`
   facts).
4. **Evidence is string-shaped, not structured.** Evidence records are
   free-text statements; there is no frame-ID back-pointer from a proof
   step to the exact frame(s) it used, so a consumer cannot
   programmatically audit which premise justified which step.

### (c) Build steps (dependency order)

1. **Confidence as a derived, honest score (not a model logit)** —
   define `confidence` in the envelope as a stated function of auditable
   inputs (parse tier: deterministic 1.0 / heuristic <1.0; `complete`;
   agreement across interpretations once Req 4 exists; contradiction
   present → low). Ship it as a small table in code with tests, and
   label it clearly as a *status-derived* score. *Small–medium (1 day).*
   Do **not** present it as calibrated until step 2 exists.
2. **Calibration measurement** — run the score from step 1 over the
   frozen eval + adversarial sets and report calibration (e.g. mean
   confidence of correct vs incorrect answers, by bucket). If the
   numbers do not separate, say so and keep the categorical statuses as
   the claim. *Small (half a day of runs + a table); depends on step 1.*
3. **Proof certificates (deferrable)** — a canonical proof serialization
   + a standalone replay checker that re-derives the verdict from
   premises + rules without the prover. *Medium (1–2 days); cut for
   Nov 4 unless the demo needs it — traces already satisfy "evidence
   tracing" for judging.*
4. **Rule-consequent extension** — modal and has-a consequents in
   `extract_rule_frame()` / `_instantiate_rules()`. *Medium (1 day);
   closes 2 known adversarial failures.*
5. **Structured evidence pointers** — give each frame a stable id and
   reference it from proof steps. *Small (half a day); do after step 3
   if certificates are built, otherwise skip.*

---

## Req 6 — A plug-and-play adapter for Meta models and other supported LLMs without requiring fine-tuning

### (a) What exists

- **Model-independent interface.** `nova/model_interface.py` —
  `LanguageModel` protocol (one method, `complete(prompt)`, returning a
  `ModelResponse` with text + model id + optional token count; lines
  61-71), `ModelConfig` (id / endpoint / key env var / generation
  settings; no secrets stored), `CallableModel` (any callable as a
  model), `MetaModelAdapter` (lines 92-130), `MockModel`
  (deterministic canned model, labelled mock everywhere), and a registry
  (`register_model` / `get_model` / `list_models`, lines 159-189).
  Built-ins registered: **`meta` and `mock` only**. The module docstring
  states Qwen/Llama attach by registering an adapter and that there are
  no fake provider implementations — verified: no Qwen/Llama/other
  adapter code exists in the repo.
- **Vendored Meta client.** `nova/adapter/meta.py:3-20` —
  `MetaModelClient`, OpenAI-compatible chat completions over HTTPS
  (loopback HTTP allowed), `temperature: 0`, 25 s timeout, key/endpoint/
  model from env vars `NOVA_MODEL_ENDPOINT` / `NOVA_MODEL_ID` /
  `NOVA_MODEL_API_KEY`. `MetaModelAdapter` reads the key from the env at
  build time.
- **Pipeline integration.** `nova/semantic/pipeline.py` — `answer_text()`
  coerces any model (`coerce_model()`: `LanguageModel`, plain callable,
  or `None`) and returns its output separately as
  `unverified_model_output`; the deterministic path works with
  `model=None`. `process_request()` wraps a `LanguageModel` as a plain
  callable for the vendored adapter's `augment`/`language` tasks.
  Verified by test: a mock guessing "$99" leaves the $20 proven answer
  intact (`EVAL_RESULTS.md` §8).
- **HTTP surface.** `nova/api.py` — `POST /concept` accepts `{"text"}`
  or `{"frames"}` (structured ConceptFrames from an external LM) or a
  vendored-adapter `{"task"}` request, and returns frames + proof +
  evidence. This is the plug-and-play surface for other LMs. `VERSION =
  "0.3.0"`, stdlib only, no auth, 64 KB body limit.
- **Neural specialist as a model.** `nova/neural/components.py` —
  `FlanT5Component` implements the `LanguageModel` protocol
  (`complete()`, line 88) behind lazy imports; `nova/neural/translate.py`
  maps checkpoint frames ↔ ConceptFrame losslessly (verified on recorded
  data). It cannot load here (see baseline: torch/transformers/
  sentencepiece absent).

### (b) What is genuinely missing

1. **The Meta adapter is unvalidated against Meta's native API and not
   yet pointed at the working connector.** `meta.py` speaks
   OpenAI-compatible chat completions; its header says "Endpoint/schema
   must be verified against the user's provider" and "not a claim of
   Meta-native compatibility." `PROVENANCE.md` and `model_interface.py`
   repeat the warning. The connector at
   `~/workspace/custom-connectors/custom.meta-model-api/` **is** verified
   working (base `https://api.meta.ai/v1`, `POST /chat/completions`,
   `muse-spark-1.3`, key via Secure Vault surrogate, 180 s timeout
   recommended — the first call timed out once at 60 s). The vendored
   client still reads its key from env vars and has a 25 s timeout.
   Re-pointing means: build a `LanguageModel` adapter around the
   connector's helper (`bin/meta_api.py`) or its credential flow, and
   register it — **do not rebuild the client and do not paste the key
   anywhere** (the connector doc forbids keys in docs, args, env vars,
   or logs).
2. **No second model is attached.** The registry has `meta` + `mock`.
   Qwen, Llama, and "other supported LLMs" are docstring-only. The
   "plug-and-play" claim therefore rests on one unvalidated adapter +
   the protocol design, not on a demonstrated second plug-in.
3. **No deployment.** `nova/api.py`'s docstring gives a Cloud Run deploy
   command, but no deployment is recorded in the repo docs (README lists
   "Day 2: HTTP API (Cloud Run), GitHub public repo" under "What is NOT
   here yet"), and no public repo exists yet in the repo's own records.
   A plug-and-play adapter nobody can reach is a local demo, not a
   product surface.
4. **The `/concept` endpoint has no auth, no rate limiting, and no
   model selection.** A caller cannot say "use model X"; the server
   constructs no model at all (the API layer never builds a model from
   the registry — `process_request` receives `model=None` unless the
   caller passes one in-process). Model choice is a code-level concern,
   not an API concern.
5. **Neural fixtures cannot load in this environment.** If the demo
   wants the FLAN-T5 specialist live (not just translation-verified),
   it needs either a runtime with torch/transformers installed or a
   hosted inference endpoint for the checkpoints. Neither exists here.

### (c) Build steps (dependency order)

1. **Re-point Meta access at the connector (do not rebuild)** — write a
   thin `LanguageModel` adapter that shells to / imports the connector's
   `bin/meta_api.py` helper (or its credential flow), register it as
   `meta` (replacing the env-var path), and verify with the connector's
   own harmless read (`ask "Reply with the single word: hello"`).
   Raise the timeout toward the connector's 180 s guidance for first
   calls. Keep `MetaModelClient` as the fallback transport; keep the
   vendored file untouched per `PROVENANCE.md`. *Small (half a day);
   the highest-leverage Req 6 step — it unblocks Req 7.*
2. **Validate endpoint/schema live, once** — one real call through the
   new adapter confirming response shape (`choices[0].message.content`,
   usage tokens), then record the confirmation in `PROVENANCE.md` /
   `EVAL_RESULTS.md` and remove the "UNVALIDATED" warnings where they
   no longer apply. *Tiny (1 hour of calls + notes); depends on step 1
   and on credits being live.*
3. **Attach one second model** — the cheapest honest second plug-in is
   a different Muse Spark model id through the same connector, or a
   hosted Qwen/Llama endpoint if credentials exist. Register it,
   run the harness's mock-style comparison shape against it, and record
   the result. *Medium (1 day if credentials exist; blocked otherwise
   — do not fake it).*
4. **Deploy the API + public repo** — Cloud Run deploy per the `api.py`
   docstring; GitHub public repo (connection required first). Add a
   minimal auth/rate-limit story or keep it unauthenticated-but-
   documented as a demo. *Medium (1 day); required for the submission
   (public repo is a judging requirement).*
5. **Model selection on `/concept`** — accept an optional `"model"`
   field, resolve it through the registry, and return `model_id` in the
   envelope. *Small (half a day); depends on steps 1–3.*
6. **Neural specialist hosting (deferrable)** — only if the demo needs
   the FLAN-T5 reasoner live: install torch/transformers in a separate
   runtime or serve the checkpoints from a hosted endpoint. *Large
   (1–2 days + hosting decisions); defer — translation-verified
   fixtures are enough for the submission narrative.*

---

## Req 7 — Controlled benchmarks comparing each unchanged model against the same model with NOVA attached

### (a) What exists

- **The harness.** `eval/harness.py` — two arms on the same frozen
  items: `run_arm_alone()` (line 225: prompt in, raw model text out,
  normalized) vs `run_arm_nova()` (line 255: deterministic pipeline,
  model attached as advisor when supplied). `run_comparison()` (line
  350) refuses mismatched item counts or model configs; a `model=None`
  run is a standalone measurement, never one side of a comparison.
  Fixed prompt template v1 (`PROMPT_TEMPLATE`, lines 37-42:
  "Answer the following question. Give only the answer: a number, yes,
  no, or 'I don't know'…", temperature 0, max_tokens 128 in
  `RunConfig`, lines 50-68). Per-question append-only JSONL records
  (raw response, normalized answer, ground truth, latency, tokens,
  trace), four transition buckets (wrong→correct / correct→wrong /
  correct→correct / wrong→wrong), Wilson 95% CIs + paired bootstrap
  CIs (`eval/metrics.py`), ablation toggles, and an `analyze` command
  that clusters failures by module.
- **Frozen sets, guarded.** Eval 250 items (seed 20261027, sha256
  `84c8bf24…`), holdout 100 items (seed 20261028, sha256 `41fd77a8…`),
  verified against `data/eval_manifest.json`; zero text overlap with
  dev probes and between sets. `eval/run_eval.py:55-68` — the holdout
  guard refuses `--set holdout` without `--final`, and logs the flag.
  Holdout never run (stated in `EVAL_RESULTS.md` §8).
- **Measured so far.** Deterministic NOVA: 250/250 (Wilson CI
  0.985–1.000, mean latency 0.18 ms). Honest ablations: no-heuristic
  −32.8 pts, no-reasoner −30.0, dictionary/calculator/memory 0.0 on the
  frozen set. Mock mechanics validation: alone 64/250, mock+NOVA
  250/250, net +0.744, regression rate 0.000 — **labelled MOCK
  throughout; it validates the harness, not the uplift claim.**
  Adversarial fresh set: 38/46 + 3/3 abstention checks.
- **Harness integrity fix (verified).** `_normalize_nova()`:
  verdict-unknown + answer-None now normalizes to None, never mined
  from rendered prose — this removed 4 false passes from the recorded
  238/250 and 22 false passes per ablated arm (`EVAL_RESULTS.md` §8).

### (b) What is genuinely missing

1. **No live comparison exists or can currently be run.** The CLI
   (`eval/run_eval.py`) has exactly five subcommands — `nova`, `mock`,
   `ablations`, `compare`, `analyze` — and **no `live` command**.
   There is no code path that builds a real model (e.g.
   `get_model("meta", …)`) and passes it to `run_arm_alone` /
   `run_arm_nova`. The parallel live-benchmark agent is doing this work
   now; until it lands, the central claim of the project ("attaching
   NOVA improves a model") has **only mock evidence**, and the mock is
   explicitly not evidence.
2. **The live run is blocked on two external confirmations** (per
   `EVAL_RESULTS.md` §7): Meta $150 credits landing (~Oct 28; claimed
   Oct 26) and native endpoint/schema confirmation. Both are outside
   the repo. Until they land, no live calls may be made.
3. **One model, one size.** The design promises "each unchanged model"
   and "multiple model sizes" (Qwen, Llama, other sizes — `EVAL_RESULTS.md`
   §8, "Still pending"). Only Muse Spark 1.3 is actually available
   through the connector. A single-model comparison proves uplift for
   one model, not the "universal adapter" claim.
4. **The NOVA arm's model role is advisory-only by design.** In the
   NOVA arm the deterministic pipeline produces the answer and the
   model output is recorded separately (`model_output_present` in the
   record). That is the honest architecture — but it means the live
   comparison measures "deterministic NOVA + model advisor" against
   "model alone", and the write-up must say exactly that rather than
   implying the model itself got smarter. The harness already records
   this correctly; the submission text must not overclaim it.
5. **Cost/latency accounting for live arms is unwritten.** Run records
   carry `cost_basis: "no_live_model_calls"` and tokens null. Live
   pricing (credits consumed, $/run) and live latency need to be
   recorded from real usage objects once calls happen; no code does
   this yet.

### (c) Build steps (dependency order)

1. **Land the live CLI arm** — add a `live` subcommand to
   `eval/run_eval.py` that builds the model via `get_model()` (Req 6
   step 1's connector-backed adapter), runs `run_arm_alone` then
   `run_arm_nova` with the identical `RunConfig`, and calls
   `run_comparison()`. Reuse the existing guard + recording machinery;
   do not write a second harness. *Medium (1 day); depends on Req 6
   steps 1–2 and on credits landing.*
2. **Run the live comparison on the frozen eval set** — Muse Spark 1.3
   alone vs +NOVA, temperature 0, max_tokens 128, prompt v1. Record
   tokens + credits consumed per run. *Small in code (a run); the cost
   is wall-clock + credits. Depends on step 1.*
3. **Report honestly, including regressions** — publish the comparison
   summary (net uplift, the four buckets, regression rate, per-category
   table) in `EVAL_RESULTS.md` §7, with the same candour as the mock
   section. If the model alone already scores near 250/250, the uplift
   is small and the story becomes "NOVA adds proofs + abstention",
   not "NOVA adds accuracy" — decide the framing from the numbers.
   *Small (half a day of writing); depends on step 2.*
4. **Final holdout run, once, with `--final`** — after the eval-set
   numbers are in and frozen. Never before. *Tiny (one run); the
   guard already enforces the discipline.*
5. **Second model comparison (if Req 6 step 3 lands)** — repeat steps
   2–3 for the second model; this is what turns one data point into
   the "each model" claim. *Small per model once step 1 exists.*
6. **Live cost/latency recording** — populate tokens + cost from the
   real usage object in `_base_record()` instead of null/0.0.
   *Small (half a day); do with step 1.*

---

## Ranked top 5 gaps that most threaten the Nov 4 submission

Deadline-driven, not a wishlist. Ranked by (likelihood × damage to the
submission's central claim) with 9 days left.

### 1. No live model-alone vs model+NOVA benchmark can be run yet (Req 7) — CRITICAL
The submission's thesis is "attaching NOVA improves an unchanged model."
Today the only comparison numbers are from a labelled mock (64/250 vs
250/250), which the docs themselves say is not evidence. There is no
`live` CLI command, no real model wired into the harness, and the run
depends on credits landing (~Oct 28) plus endpoint/schema confirmation.
If this does not land by ~Nov 2, the submission has a deterministic
250/250 and a demo — but no measured uplift claim at all. Mitigation:
Req 6 step 1 (connector re-point) + Req 7 step 1 (live arm) are the two
highest-priority builds; everything else is secondary to them.

### 2. Multiple simplified interpretations do not exist at all (Req 4) — HIGH
Req 4 is the only requirement with **zero** implementation — no
simplification step, no multi-parse representation, no agreement vote,
no adjudication. It is also the most distinctive-sounding requirement
in the project description, so a judge probing it finds nothing. It is
a genuine multi-day build (schema change + generator + checker +
renderer). If it cannot be built properly, the honest fallback is to
narrow the claim in the submission (frame Req 4 as "pairwise
agreement/contradiction checks over candidate readings", which *do*
exist) rather than ship a Potemkin version — but a narrowed claim
should be decided deliberately, not discovered on Nov 3.

### 3. The Meta adapter is unvalidated and not pointed at the working connector (Req 6) — HIGH
The verified-working connector (`custom.meta-model-api`, muse-spark-1.3,
Secure Vault key) and the vendored client (env-var key, 25 s timeout,
OpenAI-compatible, explicitly unvalidated) are two separate paths and
only the second is wired into the code. Every live call — the Req 7
benchmark, the Day-3 language-brain demo, the Req 2/3 paraphrase
component — depends on this one re-point. It is small work (half a day)
with a large blast radius if left: a wrong endpoint/schema assumption
discovered during the live run burns credits and the schedule. Also:
no second model is attached, so "plug-and-play for other LLMs" is
currently a protocol design, not a demonstration.

### 4. The production knowledge store ships empty (Req 1) — MEDIUM-HIGH
Any demo question outside the 42 hand-authored eval-fixture terms
returns `unknown` for dictionary/encyclopedia. The deterministic 250/250
is partly a product of the eval set asking only about terms the fixture
store contains. A live demo that asks "What does 'photosynthesis' mean?"
works (fixture term); one that asks about an unlisted term fails
visibly. The fix is a licenced import + seed file (1 day), but the
licence decision has no owner yet and must not be improvised — an
unlicenced scrape into a public repo is a submission-ending problem,
not a shortcut.

### 5. Paraphrase coverage is the known weak flank, and the fix has a hard kill date (Reqs 2–3) — MEDIUM
Adversarial unfamiliar paraphrase is 3/8; uncovered verbs (handed /
wired / passed / transferred) are 4 recorded failures; "Did John sell a
bike?" is unprovable; definition decomposition fails on "A dozen is 12".
The planned fix (Day-4 learned paraphrase component) has an explicit
kill criterion of Oct 30 and cannot train locally — torch/transformers/
sentencepiece are absent and no pip installs are allowed, so the
component must run through the API (Req 6) or not at all. If Oct 30
kills it, the fallback is the four-verb patch + honest scope limits in
the demo script. The risk is not the gap itself (it is measured and
bounded) but spending past Oct 30 chasing it instead of shipping.

**Not in the top 5, deliberately:** calibrated confidence (Req 5) is a
real gap but a wording-level one — the categorical statuses already do
the job in the demo, and a status-derived score is a day's work.
Proof certificates and persistent memory are deferrable without
affecting the submission's core claim. The public repo + Cloud Run
deploy (Req 6 steps 4) matter for judging but are mechanical once the
code is frozen; they should be scheduled, not worried about.
