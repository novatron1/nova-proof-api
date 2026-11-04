# NOVA Integration Results — Universal Semantic Event System

Date: **2026-10-26** (Day 2/3 build). All numbers below come from test runs
executed on this machine — command: `python3 tests/run_all.py` from the
repo root. Nothing here is claimed without a run behind it.

## Headline

| Check | Result |
|---|---|
| Money probes through the **integrated** system (text → shared frames → supervisory reasoner → words) | **100/100**, status `verified`, complete |
| Money probes through the old path (parser + ledger directly) | **100/100** (no regression) |
| New semantic suites (synonyms / antonyms / negation / multi-step / 5W1H) | **24/24** |
| Vendored adapter v0.3, in-repo copy | **20/20** |
| Original adapter v0.3 suite, source artifact (read-only) | **20/20** |
| Regression suite (old path + live HTTP API) | **9/9** |
| **Overall** (`tests/run_all.py`) | **PASS** |

## 1. Money probes through the integrated system — 100/100

Runner: `python3 -m tests.test_integration_money`. Each probe's story +
question goes through `nova.semantic.answer_text` — the full path:
natural language → ConceptFrames → SupervisoryReasoner → rendered
natural-language answer. A probe counts only if the answer is exact
**and** status is `verified` **and** `complete` is true.

- Correct: **100/100** (types: scoped2 26, multi_inflow 20, total2 20,
  chain3 20, distractor 14)
- Failures: 0
- Latency (measured in-run): total **8.0 ms** for 100 probes,
  mean **0.08 ms/probe**, max **0.43 ms**

## 2. New semantic suites — 24/24

Runner: `python -m unittest discover -s tests -p "test_semantic.py"`.
Wall time 0.007 s for the suite.

| Suite | Tests | Pass | What it proves |
|---|---|---|---|
| Synonyms | 4 | 4 | kid/child, bicycle/bike, automobile/car normalize to the same concept; give/send move money identically; a paraphrased story still answers "yes" |
| Antonyms | 4 | 4 | buy vs sell are not equivalent; give vs take differ in roles; opposite polarity is a possible contradiction (never certified) |
| Negation | 6 | 6 | "did not give" stays negative (actor is John, not "not"); a negated transfer never moves money; negated balance is $0; negated yes/no is "no" with the negated premise in the proof; negation does not poison a real transfer; "never" is negation |
| Multi-step events | 6 | 6 | 4-step chain; scoped remainder; multi-inflow partial spend; heuristic chain ("his sister"); distractor ignored; mixed deterministic + heuristic stories |
| 5W1H extraction | 4 | 4 | the Marcus-sister sentence yields who/what/recipient/quantity=50/units=dollars/when/where/why with how=None; unknowns are never invented; frames round-trip through dict form exactly |

## 3. Regression — nothing broke

| Check | Result |
|---|---|
| Old money path (`tests/test_money.py`, subprocess) | 100/100, exit 0 |
| Vendored adapter v0.3, in-repo copy (`test_adapter_vendored.py`) | 20/20 |
| Original v0.3 suite in its own directory (read-only source) | 20/20 |
| Live HTTP API (`test_regression.py`, loopback server) | 9/9 — /health, /reason canonical (200, answer 10), /reason unparseable (422), /concept text (200, answer 10, verified), /concept frames input (external-LM frames → answer 10), /concept adapter passthrough (calculate → 14400), /concept unparseable (422), /concept yes/no (verdict "no") |

Vendored-file integrity after the build (md5-verified identical to the
user's v0.3 upload): `core.py`, `language.py`, `concepts.py`, `meta.py`,
`__init__.py` — all identical, no edits.

## 4. API latency (measured, loopback, port 8099)

| Request | Latency | Answer |
|---|---|---|
| POST /concept — canonical money story | 32.29 ms | 10, `verified` |
| POST /concept — negated yes/no | 2.94 ms | verdict `no`, `candidate_interpretation` |
| POST /concept — sister story (heuristic) | 1.55 ms | 50, `candidate_interpretation` |
| POST /reason — canonical money story | 1.06 ms | 10 |

Steady-state loopback latency is ~1–3 ms per request; the first request
after server start measured 32 ms (warm-up). No network, no model calls.

## 5. The v0.3 gap, closed — with evidence

"Marcus gave his sister $50 yesterday at the store because she needed
groceries." now parses to a structured frame instead of trapping the
amount in a text field:

```
who=Marcus, what=give, recipient=Sister, quantity=50, units=dollars,
when=yesterday, where=store, why="she needed groceries", how=None,
polarity=positive, certainty=uncertain
```

End to end: "Marcus gave his sister $50. How much money does Sister
have?" → **$50**, status `candidate_interpretation` (the parse is
heuristic, so the answer is labeled candidate, not verified).

## 6. Failures found during the build (fixed, with causes)

Three semantic tests failed on first run; all three were real bugs, not
test errors:

1. **Base-form verbs missing from the vendored verb set.** The v0.3
   extractor has inflected forms (`paid`/`pays`, `sent`/`sends`) but not
   the base forms (`pay`, `send`, `purchase`, `approach`, `leave`,
   `visit`, `carry`). "Did Marcus pay John?" therefore had no verb and
   no frame. Fixed in the semantic layer (not the vendored file) with an
   extended verb map + fallback extraction.
2. **Actor synonyms did not join up.** "The kid bought a bicycle" and
   "Did the child purchase a bike?" produced different actor keys
   (`kid` vs `child`), so the yes/no goal was "unknown". Fixed:
   person normalization now applies the adapter's synonym map.
3. **Vendored comparison misreads negated actors.** The adapter's
   `compare_frames` sees "John did not buy a bike" as actor "not" and
   returns "undetermined" instead of "possible_contradiction". Fixed by
   adding the semantic layer's own comparison over corrected frames
   (`nova/semantic/compare.py`); the vendored function is untouched.

## 7. Known limits / open gaps (honest, not fixed yet)

- **Heuristic tier is still a heuristic.** The 5W1H extractor's verb
  set is small and role assignment can be wrong on unusual phrasing.
  Heuristic-derived answers are labeled `candidate_interpretation`;
  only deterministic parses earn `verified`. The Day 4 learned
  semantic component (paraphrase grounding) is still the plan for
  free-form language ("handed", "a tenner" still 422 on /reason).
- **Vendored comparison limit (see #6.3).** The adapter's own
  `compare_frames` still returns "undetermined" for negated pairs; the
  semantic `compare_texts` is the corrected path. The vendored file
  was intentionally not modified.
- **"sell" is parsed but unprovable.** "Did John sell a bike?" after
  "John bought a bike" returns `unknown`, not `no` — the system has no
  rule that buying implies not-selling, and it does not guess one.
  (Recorded in `test_antonym_story_answers_no`.)
- **No licensed dictionary/encyclopedia data.** The Knowledge store
  ships empty, as in v0.3; lookups return `unknown` until data is
  imported.
- **Meta client unvalidated.** `nova/adapter/meta.py` is an
  OpenAI-compatible chat-completions client, NOT validated against
  Meta's native Model API. No model calls were made in any test; every
  deterministic path runs with `model=None`.
- **Memory is in-process only.** `FrameMemory` is an in-memory store;
  the HTTP API is stateless per request. A persistent memory is a
  later step.
- **No proof certificates yet.** Proofs are traces (ordered steps),
  not signed/certified artifacts. Comparison results are always
  `certified: false` by design.
