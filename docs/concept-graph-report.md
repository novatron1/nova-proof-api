# Concept Graphs — Phase 2 Gap Closure Report

**Date:** 2026-10-27 (early morning, concurrent with the Phase 1 audit)
**Scope:** close the one remaining structural gap in Phase 2 — concept
graphs as an explicit structure — without touching anything the audit
measures. No live model calls, $0 spent, no fine-tuning, no weight
changes.

## 1. Checklist verification (read against the code)

Verified by reading `nova/semantic/*.py`, `nova/concept/*.py`,
`nova/adapter/core.py`, `nova/model_interface.py`, and `eval/live_*.py`:

| Checklist item | Exists? | Where |
|---|---|---|
| 5W1H decomposition | ✅ | `extract.py` (`parse_text_to_frames`, heuristic tier), `frame.py` (who/what/recipient/object/quantity/units/when/where/why/how) |
| Concept identification | ✅ | `extract.py` tiers, `router.py` routing |
| Dictionary / encyclopedia lookup | ✅ | `lexicon.py` (`Lexicon`, WordNet-primary / Wiktionary-secondary), `adapter/core.py` `Knowledge`, `router.py` |
| Multiple simplified interpretations | ✅ | `interpret.py` (`deterministic_simplifications`, `interpret`, `_adjudicate`) |
| Semantic agreement / contradiction checks | ✅ | `interpret.py` (`_adjudicate`, `contradicting_pairs`), `compare.py` |
| Supervisory reasoning | ✅ | `reason.py` (`SupervisoryReasoner`), `adapter/core.py` `Reasoner.prove` |
| Verified concept explanation | ✅ | `translate.py` (`knowledge_hit_to_frame`, `defined_as`), `render.py` (`render_analysis`), `reason.py` definition branch |
| Confidence scoring (+ calibration / certification) | ✅ | `confidence.py` (`score`, `calibration_buckets`, `CERTIFICATION_BAR`) |
| Symbolic reasoning | ✅ | `reason.py`, `adapter/core.py` (four-valued propositional reasoner) |
| Calculator | ✅ | `adapter/core.py` (`calculate`), `router.py`, `reason.py` `reason_per_unit_total` |
| Proof traces | ✅ | `reason.py` (every verdict carries a `proof` list), `ledger.py` |
| Unknown / Contradictory / Incomplete outcomes | ✅ | `interpret.py` (`verdict: "unknown"`, contradiction flag), `reason.py` (`verdict: "unknown"`), `frame.py` (`status`, `certainty: unknown`) |
| Meta + open-weight model compatibility | ✅ | `model_interface.py` (`MetaModelAdapter`, `OpenAICompatibleAdapter`), `eval/live_model.py`, `eval/live_baseten.py` (`meta-models/muse-spark-open-1026` via Baseten) |
| Licensed concept store (285 entries) | ✅ | `data/knowledge.db` — verified this session: 285 entries, 3,418 senses |
| Recursive definition decomposition | ✅ | `lexicon.py` (`Lexicon.decompose`, depth-capped, cycle-safe) |
| **Explicit concept graphs** | ❌ **THE GAP** | No graph structure existed anywhere (`grep graph` hit only `lexicon.py`'s "reverse synonym graph" comment and `test_phase2.py`). Frames were flat lists. |

## 2. What was built

**New files only (nothing existing modified):**

- `nova/semantic/graph.py` — the `ConceptGraph` module (~600 lines)
- `tests/test_concept_graph.py` — 27 tests
- `docs/concept-graph-report.md` — this report

### `nova/semantic/graph.py` — API

- **Nodes** (`ConceptNode`): typed `actor` / `action` / `object` /
  `condition` / `relationship` / `consequence`, with a `label` and an
  `attrs` dict (quantity, units, polarity, certainty, gloss, …).
- **Edges** (`ConceptEdge`): directed, labelled `agent`, `patient`,
  `recipient`, `quantity`, `polarity`, `temporal`, `causation`,
  `condition`, `defined_as`, `is_a`, `has_a`, `expands`.
- **Construction — `ConceptGraph.from_frames(frames)`:** builds from the
  shared `ConceptFrame` schema (`frame.py`) — no second frame schema.
  Per frame: `who` → actor, `what` → action, `object` → object,
  `recipient` → actor, `when`/`where`/`why`/`how` → condition nodes,
  `quantity` → `quantity` edge, `kind == "calculation"` → consequence
  node, frame `relationships` → `relationship` nodes. `None` slots
  produce nothing; negation is kept as a `polarity` edge, not dropped.
- **Identity rule (deliberate, tested):** actors/objects/conditions
  deduplicate by (type, label) so the same person joins up across
  sentences; **action and relationship nodes are unique per frame**,
  because "gave" vs "did not give" are two distinct claims and
  collapsing them would erase the contradiction the graph must report.
  This was caught by the tests during development, not assumed.
- **Causation is explicit-only:** `add_causation(cause, effect)` is the
  only way to add a `causation` edge; frames never imply causation
  from mere sequence.
- **Definition expansion — `expand_definition(term, lexicon, depth=3)`:**
  reuses `Lexicon.decompose` trees; the term becomes an `object` node,
  each level's frames are merged in and linked with `defined_as`
  edges, component terms link with `expands` edges. Depth-limited and
  cycle-safe three ways: the lexicon's own visited set, the graph's
  `_expanded_terms` set (re-expanding a term is a no-op), and a
  per-path set guarding hand-built cyclic trees.
- **Queries:** `actors()`, `actions()`, `objects()`, `conditions()`,
  `relationships()`, `consequences()`, `nodes_by_type(t)`,
  `find_nodes(label, type)`, `neighbors(id, rel, direction)`,
  `edges_from(id, rel)`, `edges_to(id, rel)`,
  `path_between(a, b, rel=None)` (BFS, directed, `None` when
  unreachable), `subgraph_by_condition(label)` (empty graph when the
  condition is absent — never a guess), `find_contradictions()` (same
  actor + action + object with opposite polarity, or conflicting
  quantities; agreement is not reported).
- **Serialization:** `to_dict()` / `from_dict()`, `to_json()` /
  `from_json()` — exact round-trip, including `expanded_terms`.
  `merge(other)` remaps ids, so merged graphs never collide.

### Example

```python
from nova.semantic.extract import parse_text_to_frames
from nova.semantic.graph import ConceptGraph
from nova.semantic.lexicon import Lexicon

frames = parse_text_to_frames("Marcus gave John $20. John gave Sarah $10.")
g = ConceptGraph.from_frames(frames)
g.actors()          # [Marcus, John, Sarah] — John is one node
g.actions()         # two distinct "give" nodes (two events)
marcus = g.find_nodes("Marcus", "actor")[0]
sarah = g.find_nodes("Sarah", "actor")[0]
g.path_between(marcus.id, sarah.id)   # Marcus -> give -> John -> give -> Sarah

g.expand_definition("bicycle", Lexicon(), depth=2)
# "bicycle" object node --defined_as--> "has" action,
#           --expands--> "vehicle", "wheels" term nodes
g.to_json()         # exact round-trip via ConceptGraph.from_json(...)
```

## 3. Test results

- **New suite:** `python3 -m unittest discover -s tests -p
  "test_concept_graph.py"` — **27 tests, OK.** Covers: construction
  from frames (money story via the real parser + hand-built frames),
  node/edge typing, actor dedup vs action uniqueness, unknown slots,
  negation/polarity edges, relationship nodes, calculation
  consequences, path queries (incl. unreachable → `None`),
  condition subgraphs (incl. absent condition → empty graph),
  polarity + quantity contradictions (incl. agreement → none),
  JSON/dict round-trip exactness, merge id-remapping, real-store
  definition expansion (`bicycle` → `vehicle`/`wheels`), unknown-term
  expansion → `None`, re-expansion idempotence, depth limit (depth 1
  adds no `expands` edges, depth 2 does), and cycle safety (a fake
  self-referential A→B→A lexicon terminates; depth 50 still bounded).
- **Full suite:** `python3 tests/run_all.py` — **OVERALL: PASS, all 13
  suites** (money 100/100 old path + 100/100 integrated, semantic 39,
  vendored adapter 20, regression 9, original v0.3 suite 20, harness
  mechanics 34, round-trip 4, stabilization 51, neural fixtures 11,
  multi-interpretation + confidence 24, calibrated confidence 24,
  model backends 22).
- **Phase 2 suite (not in `run_all.py`):**
  `test_phase2.py` — **36 tests, OK.**
- Two test failures during development caught two real module bugs
  (subgraph edge ids not remapped after node insertion; `agent` edge
  direction mishandled in contradiction detection) and one bad test
  expectation (two frames with different actors/objects are not a
  contradiction). All fixed; the final run is green.

## 4. Deliberately NOT wired in (and why)

- **Not imported by `nova/semantic/__init__.py`, `pipeline.py`,
  `production.py`, or anything under `eval/`.** The Phase 1 audit is
  running concurrently and must measure exactly the artifacts that
  exist now; wiring the graph into the evaluated NOVA path would
  change what is measured. The graph is a standalone structure the
  rest of the system can query.
- **`tests/run_all.py` was not modified** (adding the new suite there
  would change the harness the audit measures). The graph suite is
  run separately: `python3 -m unittest discover -s tests -p
  "test_concept_graph.py"`.
- **No `causation` is ever inferred** from frame order or co-occurrence;
  it requires an explicit caller claim (`add_causation`).
- **No new frame schema, no eval-set changes, no pipeline changes.**
  Only three files were added; no existing file was edited.
  `EVAL_RESULTS.md` untouched (coordinator appends results).

## 5. Open items / notes for the coordinator

- **Frozen baseline ZIP:** the md5 `b8c7b5cb8a078a787cd85366779c9c5b`
  was not matched to any ZIP found under `~/workspace` (the two
  `NOVA_completed_*.zip` files in `~/workspace/your_files/` have
  different md5s). No ZIP was touched in this session — the only
  files written are the three new ones listed above — so the frozen
  baseline cannot have changed from this work, but the coordinator
  should re-verify the md5 against wherever the frozen ZIP lives.
- **Suggested next step (not done here):** wire `ConceptGraph` into
  the pipeline as an *additional, non-scoring* output (e.g. attach
  `graph` to the `answer_text` envelope) in a later phase, after the
  audit closes, and add the graph suite to `run_all.py` at the same
  time.
- **Known limitation:** `find_contradictions` compares only exact
  (actor, action, object) triples — synonym/antonym-aware
  contradiction (e.g. "gave" vs "took") is not attempted; the
  lexicon's antonym data could extend it later.
