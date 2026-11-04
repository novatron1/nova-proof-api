# NOVA Cognitive Adapter — fresh minimal wiring prototype

A new proof-of-wiring prototype, **not** a completed hackathon submission and **not** a reproduction of prior NOVA benchmarks.

## Run

Python 3.10+; no third-party dependencies.

```bash
python -m unittest discover -s tests -v
python demo.py
```

## Current working modules
- Safe arithmetic evaluator (restricted expression grammar; not a hardened execution sandbox)
- SQLite dictionary / encyclopedia storage (you must import licensed data)
- Simple propositional forward-chaining reasoner with trace and four-valued answers
- Shared request/response interface with evidence and explicit statuses
- Optional `model` callable for model text output (unverified)

## Not yet implemented
- Actual Meta Model API adapter, API authentication, model credentials
- Who/what/when/where/why/how language parser and concept frame generator
- WordNet/Wiktionary/Wikipedia ingestion and citations
- Semantic similarity, word sense disambiguation, concept graph, durable concept memory
- Robust first-order reasoning, proof certificates, multi-model evaluation
- HTTP API, cloud deployment, agent permissions and sandboxing

## Example API contract
`NovaAdapter.process({"task":"calculate","expression":"15*120*8"})`
`NovaAdapter.process({"task":"dictionary","term":"purchase"})`
`NovaAdapter.process({"task":"prove","facts":["a"],"rules":[[["a"],"b"]],"goal":"b"})`

Do not label an answer 'verified fact' simply because a proof follows from supplied premises.

## v0.2: Language and model wiring

New `task=analyze` extracts *candidate* 5W1H fields from a limited English verb set and returns a normalized concept frame. `task=compare_concepts` checks basic curated paraphrases and returns only a **candidate** match. `task=augment` passes the heuristic frame plus the original question to a configured model. No model response is considered verified. The parser is a deliberately narrow heuristic, not a trained general semantic parser; it may misidentify roles, locations and meanings.

### Run the local development API

```bash
python -m nova.server
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/process -H 'Content-Type: application/json' -d '{"task":"analyze","text":"Marcus gave his sister $50 yesterday at the store because she needed groceries."}'
```

### Optional Meta-model hosting integration

`nova/meta.py` implements an **OpenAI-compatible chat-completions HTTP client**. It has NOT been validated against Meta's native Model API; use it only with a confirmed compatible Meta-model serving endpoint. Set `NOVA_MODEL_ENDPOINT` to the *full* HTTPS chat-completions URL, `NOVA_MODEL_ID` to the deployed model ID, and `NOVA_MODEL_API_KEY` if required. Never commit keys. `python -m nova.server` then enables `task=augment`. For Meta's native API, adapt the transport to its documented request/response schema.

The development server binds to loopback and has **no authentication**. Do not expose it publicly. No live Meta call, public deployment, large dictionary ingestion, or comprehensive benchmark is claimed.

## v0.3: Concept contract and cautious semantic comparison

New `task=concept_frame` emits the original sentence, 5W1H slots, normalized event, lexical polarity, known/unknown slots and warnings. `task=concept_compare` returns **candidate_equivalent**, **possible_contradiction**, **undetermined** or **unknown** with `certified: false`. It intentionally does not pretend a dictionary substitution proves semantic equivalence. Negation scope, co-reference, event time, polysemy, and syntactic ambiguity remain open problems. Tests use a mock model; **no real Meta API request was executed**.

Examples:

```bash
python -m unittest discover -s tests -v
curl -s http://127.0.0.1:8765/process -H 'Content-Type: application/json' -d '{"task":"concept_frame","text":"Marcus gave his sister $50 yesterday at the store because she needed groceries."}'
curl -s http://127.0.0.1:8765/process -H 'Content-Type: application/json' -d '{"task":"concept_compare","a":"The kid bought a bicycle.","b":"The child purchased a bike."}'
```

### Next engineering gates
1. Confirm Meta serving endpoint and actual request/response schema from the participant portal; do not assume OpenAI compatibility.
2. Implement a structured Meta-model parser with schema validation, alternative parses, and explicit abstention.
3. Import a licensed lexical database and a small encyclopedia corpus with provenance.
4. Benchmark against small-model-only and ordinary-tool-calling baselines on frozen, independently generated examples.
5. Before public deployment, add authentication, request limits, input limits, and sandboxing.

## v0.4 rebuild — NCA dual-path research prototype

**New:** `nova.engine.CognitiveSystem` implements two modes without changing the original v0.3 APIs:

- `independent`: NOVA computes supported scoped-transfer answers, or returns `ASSIST`/`UNSUPPORTED` rather than fabricating an answer.
- `concepts`, `assist`, `full`: NOVA assembles lexical senses and 5W1H frames for a configured model callable. **The model callable generates the final response**, not NOVA. `full` can include a verified result; `concepts` withholds the final answer and proof.
- `UNSUPPORTED` means NOVA lacks a proof, **not** that the model must abstain. The handoff prompt explicitly says this.
- Dictionary-sense examples for run, charge, relinquish, give and borrow; candidate senses are preserved instead of conflated. This is a tiny illustrative lexicon, **not** a full dictionary or WordNet.
- A narrow ledger parser handles a subset of transfers, recipient/source forms and self-transfers. It is **not** a general English financial reasoner. Never use it for actual financial accounting.

Run locally: `python -m unittest discover -s tests -v` and `python demo_v04.py`.

Example:

```python
from nova.engine import CognitiveSystem
nova = CognitiveSystem(model=lambda prompt: my_model_generate(prompt))
result = nova.answer('She runs the studio.', mode='concepts')
print(result['answer'])  # response generated by your configured model
```

**Validation scope:** all local tests use deterministic logic or a fake model callable. There were **no live Spark calls, no cloud calls, no imported production NCA source, and no reproductions of the 600/600 or G1 benchmarks**. Do not equate passing unit tests with improved model intelligence. The supplied v0.3 source is a small prototype, not the agent's latest cloud repository. Import the actual cloud project before production work; compare code and tests rather than overwriting it.

**Next engineering gates:** add licensed WordNet/Wiktionary ingestion with word-sense provenance and a thread-safe lookup layer; add full semantic frames and temporal/negation scope; implement genuinely separate concept-only and reasoning-only model inputs with leakage checks; verify model-generated answers independently; benchmark on fresh, externally checked questions against model-alone and definition-only controls; add authentication, rate limits and real deployment controls.


## v0.5 reviewed rebuild — changes and limits

This release is a local incremental improvement of the v0.4 research prototype, **not** the unavailable cloud production implementation.

- Fixed chronological event ordering when distinct regex parsers matched transfer and receive sentences out of sequence.
- Uses decimal arithmetic internally for ledger transactions instead of binary floats.
- Prevents ambiguous duplicate matching deposits from being labeled VERIFIED.
- Retains self-transfer protection; outgoing amounts count only after the matched scoped incoming transfer.
- Uses separate SQLite connections per thread for file-backed dictionary lookups, preventing cross-thread connection errors. For cross-thread sharing, use a file-backed database rather than `:memory:` (which is per connection). Production should also add explicit connection lifecycle management.
- Keeps NOVA's lack of proof distinct from an unanswerable question; the LLM retains final-response control when configured.
- Adds regression coverage for ledger ordering, cents, duplicate deposits, self-transfers, unknowns, answer withholding, custom lexicons, and concurrent file-backed lookups.

**Research-informed roadmap:** Princeton WordNet groups word senses into synsets and semantic relations; integrate a properly licensed, sourced lexicon with sense IDs rather than unqualified synonym substitution. Python's sqlite3 defaults to restricting connections to their creating thread, so connections must not be silently shared across workers. See `RESEARCH_AND_AUDIT.md`.

**Not proven:** robust unrestricted English understanding, independent reasoning on unfamiliar domains, true answer reconstruction by a real LLM, any uplift on unseen benchmarks, security of a public-facing service, or compatibility with Meta's native API.
