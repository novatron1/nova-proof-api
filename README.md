# NOVA — Proof-First Reasoning API

**Meta Global AI Developer Hackathon 2026 — Day 1–3 build. Current
release: v1.6 (2026-11-03, the submission system — API 0.4.0; the
earlier stabilization freeze was v0.3.0, see `RELEASE.md`).**

Three cooperating systems, not one big model:

1. **Language Brain** — turns free-form questions into structured concept frames.
   (Day 3: Muse Spark. Days 1–2: deterministic parser + heuristic 5W1H
   extractor, `nova/semantic/extract.py`.)
2. **Concept Engine** — one shared Concept/Event schema (`nova/semantic/frame.py`)
   that every module reads and writes, plus the entity ledger +
   deterministic math + memory + verification (`nova/concept/ledger.py`,
   `nova/semantic/memory.py`).
3. **Reasoning Brain** — symbolic reasoner (small, exact, deterministic) +
   learned neural reasoner (FLAN-T5-small specialist). Every answer ships
   with an inspectable proof. The supervisory reasoner
   (`nova/semantic/reason.py`) returns Yes / No / Both / Unknown with
   proof traces and a completeness status.

## The universal integration (Day 2/3)

One cognitive language shared by every module — not a collection of
separate tools. See `RESULTS_INTEGRATION.md` for measured results.

- **Shared schema** — `ConceptFrame`: WHO, WHAT, WHEN, WHERE, WHY, HOW,
  recipient, object, quantity, units, polarity, relationships, evidence.
  Unknown slots are explicit `None`, never invented. Negation and
  uncertainty survive translation.
- **Translation adapters** — `nova/semantic/translate.py`: money engine,
  dictionary, encyclopedia, calculator, memory, and symbolic reasoner all
  exchange structured information through the shared frame. The v0.3 gap
  is closed: "Marcus gave his sister $50" now yields quantity=50,
  units=dollars as structured fields, so balance questions can be answered.
- **Vendored adapter** — `nova/adapter/` is the user's Cognitive Adapter
  v0.3, copied verbatim (md5-verified, see `nova/adapter/PROVENANCE.md`),
  with its calculator, SQLite knowledge store, four-valued reasoner,
  5W1H extractor, and Meta model client.
- **API** — `POST /concept` exposes the frames so other language models
  can use NOVA as an external cognitive adapter: send text or frames,
  get frames + reasoning + evidence back. `POST /reason` is unchanged.
- **Bidirectional** — natural language → structured concepts → reasoning
  → natural language, with the final answer generated from the frame +
  proof by templates, never from a free-form guess.

## The demo

> "Marcus gave John $20. John gave Sarah $10. How much money does John
> have left from the $20?"

NOVA answers **$10**, with the proof:

```
Marcus gave John $20: Marcus balance $-20, John balance $20
John gave Sarah $10: John balance $10, Sarah balance $10
Scoped balance for John from $20: $10
```

## Run the tests

```sh
python3 data/gen_money_probes.py   # regenerate the 100-question probe set
python3 -m tests.test_money        # 100/100 correct (Day 1, old path)
python3 -m tests.test_integration_money  # 100/100 through the integrated system
python3 tests/run_all.py           # every suite + timings (see RESULTS_INTEGRATION.md)
```

## Capability Uplift Test (the experiment)

Does NOVA make a small model more capable? The harness
(`eval/`, see `EVAL_HARNESS.md`) compares the model alone vs the
same model with NOVA attached on a frozen 250-question eval set
(plus a guarded 100-question holdout). Measured so far
(`EVAL_RESULTS.md`):

- **NOVA deterministic path (model=None): 250/250 = 1.000**
  (Wilson 95% CI 0.985–1.000; mean latency 0.18 ms/question) —
  after the Oct 26 stabilization (v0.3.0). Before stabilization the
  honest score was 234/250 = 0.936 (the recorded 238/250 included 4
  false passes from a harness artifact — see `EVAL_RESULTS.md` §8).
- **Ablation (v0.3.0, measured cleanly):** removing the heuristic
  tier −32.8 pts, the symbolic reasoner −30.0, the knowledge store
  0.0, the calculator 0.0, memory 0.0 (single-question eval). The
  pre-fix ablation deltas were understated because the same harness
  artifact inflated the ablated arms.
- **Round-trip concept preservation: 114/114 slots (1.000)** —
  NL → frames → NL loses nothing on the 26-sentence probe set
  (`tests/test_roundtrip.py`).
- **Adversarial probes: 38/46 = 0.826** on a fresh 49-item stress
  set (seed 20261030, `eval/data/adversarial.jsonl`), plus 3/3
  abstention checks. The 8 failures are all recorded coverage gaps
  for the Day-4 learned component (uncovered verbs, modal/has-a
  rule consequents, per-unit-as-definition).
- **Mock mechanics validation:** mock alone 64/250 = 0.256, mock+NOVA
  214/250 = 0.856 — the harness works end to end, but the mock is
  NOT uplift evidence
- **Live comparison: PENDING** — Meta credits land ~Oct 28 and the
  native API endpoint/schema is unvalidated; no live calls until then

```sh
python3 -m eval.run_eval nova --set eval        # deterministic NOVA run
python3 -m eval.run_eval ablations --set eval   # per-module contribution
python3 -m eval.run_eval mock --set eval        # mock mechanics check
python3 -m eval.run_eval analyze eval/runs/<run>.jsonl  # failure clusters
```

## Layout

- `nova/concept/events.py` — event frames + deterministic parser
  ("X gave Y $N", "X gave $N to Y", "Y received $N from X", balance questions)
- `nova/concept/ledger.py` — entity ledger (running balances, FIFO inflow
  lots for scoped queries) + deterministic math
- `nova/adapter/` — vendored Cognitive Adapter v0.3 (verbatim, see PROVENANCE.md)
- `nova/semantic/` — the universal integration: shared frame schema,
  NL→frame extraction, translation adapters, supervisory reasoner,
  frame memory, NL rendering, integrated pipeline, plus the
  stabilization additions: `facts.py` (is-a/has-a/state/rule
  extraction), `router.py` (NL routing to calculator/dictionary/
  encyclopedia/prove), `roundtrip.py` (concept-preservation metric)
- `nova/model_interface.py` — model-independent interface
  (`LanguageModel` protocol, `MetaModelAdapter`, `CallableModel`,
  `MockModel`, registry). Qwen/Llama attach by registering an
  adapter; there are no fake provider implementations.
- `nova/neural/` — the trained FLAN-T5-small checkpoints as optional
  fixtures (push1 learned reasoner, push2 parser). Not loadable in
  this environment (no torch/transformers/sentencepiece) — the layer
  reports the exact blocker and the schema translation is verified
  against the recorded data instead.
- `nova/api.py` — HTTP API: GET /health, POST /reason, POST /concept
- `data/gen_money_probes.py` — probe-set generator (seeded, reproducible)
- `data/money_probes.jsonl` — 100 money-transfer probes with exact answers
- `tests/test_money.py` — end-to-end probe runner (old path)
- `tests/test_integration_money.py` — probes through the integrated system
- `tests/test_semantic.py` — synonyms / antonyms / negation / multi-step / 5W1H
- `tests/test_adapter_vendored.py` — vendored adapter regression (20 tests)
- `tests/test_regression.py` — old path + live HTTP API regression
- `tests/test_eval_harness.py` — harness mechanics (19 tests)
- `tests/test_roundtrip.py` — round-trip concept preservation
  (26 sentences, 114/114 slots)
- `tests/test_stabilization.py` — routing, zero-audit, antonyms,
  send/give/receive, rules, model interface (51 tests)
- `tests/test_neural_fixtures.py` — checkpoint presence, graceful
  degradation, schema translation vs recorded data (11 tests)
- `tests/run_all.py` — full run with timings (10 suites, all PASS)
- `RESULTS_INTEGRATION.md` — measured results, failures, open gaps
- `eval/` — Capability Uplift Test harness (see `EVAL_HARNESS.md`)
- `eval/data/adversarial.jsonl` — fresh 49-item stress set
  (seed 20261030, NOT part of the frozen eval)
- `EVAL_RESULTS.md` — uplift-test results (deterministic 250/250
  after stabilization; live comparison pending)
- `RELEASE.md` — v0.3.0 stabilization release notes
- `data/eval_uplift.jsonl` — frozen 250-question eval set
- `data/eval_uplift_holdout.jsonl` — frozen 100-question holdout
  (guarded: `--final` required to run)

## What is NOT here yet (per the 9-day plan)

- Day 2: HTTP API (Cloud Run), GitHub public repo
- Day 3: Muse Spark as the language brain (+ deterministic fallback)
- Day 4: learned semantic component (paraphrase grounding) — kill criterion
  if not converging by end of Day 4
- Day 5: full measurement (RESULTS.md)
- Day 7: 3-minute demo video
- Day 9 (Nov 4, 9:00 PM ET): submission
