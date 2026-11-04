# RELEASE v0.3.0 — Stabilization freeze

**Date:** 2026-10-26
**API version:** `0.3.0` (`nova/api.py` `VERSION`)
**Status:** frozen. Full integration + reliability first; large-scale
model comparisons come after (they wait on model access).

## What changed (the user's 10 stabilization items)

1. **Natural-language routing** — `nova/semantic/router.py`: calculator,
   dictionary, encyclopedia, and prove/show requests route through the
   shared ConceptFrame path. Unroutable requests return honest unknown.
2. **Zero-audit** — unknown stays unknown in every path: ledger
   (undetermined balance → None, never $0), calculator (bad input
   raises, never 0), renderer ("unknown amount", never "$0"), API
   envelope (answer null). 8 tests in `tests/test_stabilization.py`.
3. **Extraction & comparison** — `nova/semantic/facts.py`: is-a /
   has-a / state / cannot / rule extraction; adjective antonyms
   (open/closed, hot/cold, full/empty, on/off, …); send/give/pay/receive
   canonicalized to one `give` predicate in facts, transfers, and the
   ledger; negation scope (negated receive settles "Did B receive…?"
   as "no"; "not on" does NOT prove "off").
4. **Knowledge bridges** — a stated or stored has-a fact feeds the
   per-unit calculation ("A spider has eight legs" → 2 spiders have
   16 legs); an amount-paid question reads the story's single payment
   ("Yusuf purchased a bicycle for $120" → $120); dictionary and
   encyclopedia definitions answer "What does 'X' mean?" / "Define X".
   Every fact used in reasoning carries its evidence/provenance.
5. **Round-trip concept preservation** — `nova/semantic/roundtrip.py`
   + `tests/test_roundtrip.py`: NL → frames → NL preserves **114/114
   slots (1.000)** on 26 sentences; zero dropped slots, zero invented
   slots, zero polarity flips, zero lost negation.
6. **Neural fixtures** — `nova/neural/`: the push1 learned reasoner
   and push2 parser checkpoints (FLAN-T5-small, ~308 MB each) wired
   as OPTIONAL fixtures behind the model interface. **Not loadable
   here**: torch, transformers, and sentencepiece are absent and no
   pip installs are allowed — the layer raises `NeuralUnavailable`
   naming the missing modules and the deterministic path is
   unaffected. The schema translation IS verified against the
   recorded data: push1 prompt parses on all 2000 test rows, frame
   round-trip lossless, deterministic `rule_applies` reproduces the
   gold answers 2000/2000; push2 gold frames round-trip (500 sampled).
7. **Regression preservation** — all pre-existing suites pass
   unchanged; raw eval traces kept (`eval/runs/`). One harness fix
   (see below) is documented in `EVAL_RESULTS.md` §8. No test was
   weakened or deleted.
8. **Component + adversarial testing** — 10 suites in
   `tests/run_all.py`, all PASS; fresh 49-item adversarial set
   (seed 20261030, `eval/data/adversarial.jsonl`), 38/46 scored +
   3/3 abstention checks.
9. **Model-independent interface** — `nova/model_interface.py`:
   `LanguageModel` protocol, `ModelConfig`, `CallableModel`,
   `MetaModelAdapter` (vendored client, UNVALIDATED vs Meta's native
   API), `MockModel`, registry (`meta`, `mock`). Qwen/Llama attach by
   registering an adapter — no fake provider implementations.
10. **Frozen benchmark integrity** — eval set and holdout unchanged:
    eval sha256 `84c8bf24…` (250 items), holdout sha256 `41fd77a8…`
    (100 items), verified against `data/eval_manifest.json` before
    and after. Holdout never run.

## Measured results

| | Before (honest) | After (v0.3.0) |
|---|---|---|
| Frozen eval, deterministic | 234/250 = 0.936 | **250/250 = 1.000** |
| Per category | antonym 11/15, knowledge_combo 4/10, synonym 18/20, rest full | **every category full** |
| Mock comparison (MOCK) | alone 64/250, nova 238/250, net +0.696, 6 regressions | alone 64/250, nova **250/250, net +0.744, 0 regressions** |
| Ablations (honest) | no_heuristic 0.672, no_reasoner 0.700 | same (measurement fixed, not the system) |
| Latency (deterministic) | mean 0.21 ms | mean **0.18 ms**, max 1.79 ms |
| Round-trip loss | 71/77 slots (0.922) pre-fix | **114/114 (1.000)** |
| Adversarial (fresh set) | n/a | 38/46 = 0.826 + 3/3 abstentions |

The recorded pre-stabilization score was 238/250, but 4 of those
were false passes: the harness mined numbers out of the rendered
analysis prose for items the system had honestly abstained on
("How much money did Yusuf pay?" → envelope unknown, prose "$120").
The honest before-score is 234/250. The amount-paid bridge now
answers those 4 items genuinely, in the envelope.

## Harness fix (measurement integrity, 2026-10-26)

`eval/harness.py` `_normalize_nova`: when the envelope verdict is
"unknown" and the answer is None, the normalized answer is now None
— never mined from the rendered prose. The analysis text quotes the
story's own numbers, and reading one as the answer scored honest
abstentions as wrong numbers (and, in the ablated arms, scored
abstentions as correct numbers: 22 false passes in each of the
no_heuristic and no_reasoner arms). Verified: the frozen eval
re-run after the fix is unchanged at 250/250 with 0 prose-mined
records; the ablations now measure honestly (no_heuristic 0.672,
no_reasoner 0.700).

## Remaining failures (frozen eval: none)

The frozen eval has **zero** remaining failures. The adversarial
set's 8 failures are all recorded coverage gaps for the Day-4
learned component — see `EVAL_RESULTS.md` §8:

- Uncovered verbs: handed, wired, passed, transferred (4)
- "How much did Leo receive?" after selling (1)
- Modal rule consequent: "If someone is a bird, they can fly" (1)
- Has-a rule consequent: "If something is a fruit, it has seeds" (1)
- Per-unit fact stated only as an is-a definition: "A dozen is 12" (1)

## Pending (out of scope for this release)

- Multi-model-size before/after benchmarks — wait on model access
  (Meta credits ~Oct 28, native API endpoint/schema unvalidated).
- Live model-alone vs model+NOVA comparison — same blocker.
- Day-4 paraphrase fine-tune — kill criterion Oct 30.
