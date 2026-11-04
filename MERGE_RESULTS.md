# MERGE RESULTS — v1.3 work copy (2026-11-02)

Work copy only. Main repo `~/workspace/nova-proof-api/` untouched;
frozen baseline zip md5 `b8c7b5cb8a078a787cd85366779c9c5b` verified
identical at start and end. No live model calls, $0 spent.

## Changed / added in this copy
- `MERGE_MAP.md` — piece-by-piece assessment + taint audit.
- `nova/semantic/sense_graph.py` (NEW) — (a) external lexicon loader
  with v1.2 validation; (b) sense graph (has_sense/synonym/antonym
  distinct) + production-Lexicon bridge + ConceptGraph bridge.
- `nova/semantic/fullproof.py` (NEW) — taint-safe production handoff:
  original question verbatim first; UNSUPPORTED ≠ unanswerable;
  concepts mode withholds readings + proof + answer (strict no-leak).
- `nova/semantic/handoff.py` (ADDITIVE) — package gains `coverage`
  (per-sentence unparsed list, duplicate-scope flag), `sense_graph`,
  `nova_authority`. No existing key or arm prompt changed.
- `nova/concept/ledger.py` (FIX) — self-transfer guard in
  `Ledger.apply`: giver == recipient moves nothing (was: counted as
  spending; Mira probe 25 → 45, matching v1.2).
- `tests/test_merge_v13.py` (NEW) — 16 tests incl. taint-rule
  byte-identical preservation across all prompt builders.

## Gates (all run locally, model=None)
- Merge tests: `python3 -W error::ResourceWarning -m unittest
  tests.test_merge_v13` → Ran 16, OK.
- v1.2 standalone: `python3 -W error::ResourceWarning -m unittest
  discover -s tests` in `_v12_src/nova_v12` → Ran 75, OK.
- Full suite: `python3 tests/run_all.py` → OVERALL PASS (money
  100/100 old path + 100/100 integrated included).
- Unit discover: `python3 -m unittest discover -s tests` → Ran 339, OK.
- Frozen deterministic: `python3 -m eval.run_eval nova --set eval`
  → 250/250 = 1.000 (run 20261102-173114).
- Fresh deterministic: `python3 -m eval.run_eval nova --set fresh`
  → 250/250 = 1.000 (run 20261102-173114).
- Boundary 42/42: NOT RUNNABLE HERE — no 42-item boundary set exists
  in this repo (adversarial 49, ambiguous 12, paraphrase 36,
  new_terms 60). Reported, not assumed.
- Pre-merge baselines in this copy were identical (suite PASS,
  frozen 250/250, fresh 250/250), so the merge changed no score.

## Not merged (documented in MERGE_MAP.md)
- Decimal conversion of the core money pipeline (float throughout).
- Duplicate-scope abstention in the core engine (flagged in
  coverage instead; core still sums matching lots → 170 probe).
- Refund counting in the free-text parser (production probe answers
  70, refund ignored; v1.2 gives 80). Parser surgery deferred.
- Recorded arm preambles' forced-abstention wording (frozen
  experiment instruments; superseded for production use by
  fullproof.py, left byte-identical for reproducibility).
