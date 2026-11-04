# ADVANCE v1.4 — merged NOVA, three advancements over v1.3 (2026-11-02)

Work copy only: `~/workspace/nova-proof-api-merge-v14/` (copied from
merge-v13; v1.3 left intact as the verified fallback).
`~/workspace/nova-proof-api/` untouched; frozen baseline zip md5
`b8c7b5cb8a078a787cd85366779c9c5b` verified identical before and
after. **No live model calls. Spend: $0.**

## Fix 1 — Refund verb parsing (core engine)

Before: the production engine had no refund concept at all. A refund
sentence fell to the heuristic tier, produced no transfer, and was
silently dropped from the math (visible only as an "unusable frame"
note). On the canonical probe the engine verified **$70
(candidate)** where the truth is $80; on the live-40 refund class it
verified $55 where the truth was $75 (the model, not NOVA, found
the $75 live).

Semantics (ported from the v1.2 standalone engine, `_v12_src`):
a refund is money returned from the recipient of an earlier
transfer back to that transfer's giver. It is valid only up to what
the earlier transfers in the opposite direction sent, minus refunds
already made; an excess is an *unmatched refund* and the story's
balances are uncertifiable (abstain). A valid refund restores the
refundee's FIFO lots (oldest drawn lot first, capped at the lot's
original amount) instead of opening an unrelated new lot.

Where it lives:
- `nova/concept/events.py` — `Transfer` gains `kind`
  ("transfer" | "refund"); five new deterministic patterns:
  "X refunded/repaid Y $A", "X refunded/repaid $A to Y",
  "X returned $A to Y", "Y received/got a refund of $A from X",
  "Y was refunded $A by X".
- `nova/concept/ledger.py` — `Ledger._apply_refund` (validity via
  per-pair sent/refund totals, lot restoration via `_restore_lots`,
  refunder pays FIFO out of their own lots); spent-out lots are now
  KEPT at 0 so a later refund can restore them (a zero lot adds 0 to
  every sum, so no total changes); `run_story` exposes
  `refund_issues` and withholds the answer when any exist.
- `nova/semantic/extract.py` / `translate.py` — refund frames
  (`what="refund"`) round-trip to refund Transfers.
- `nova/semantic/reason.py` — a refund frame counts as a quantified
  money mention for `_balance_determined`; `reason_balance` returns
  an honest unknown envelope when the ledger withholds the answer;
  the balance yes/no path abstains on an unmatched refund too.
- `nova/semantic/handoff.py` — coverage's duplicate-inflow count
  excludes refund frames (money coming back is not a second lot).

## Fix 2 — Duplicate-scope abstention (core engine)

Before: a scoped question whose scope matched two lots SUMMED them
and certified the sum — the known probe ("Sam gave Eli $100" twice,
Eli spends $30, "left from the $100?") verified **170** on every
path (production, pipeline, handoff package). The v1.3 merge only
flagged it in coverage.

Now (`nova/concept/ledger.py`, `Ledger.answer` scoped branch): if
the scope matches more than one lot — identical (giver, amount)
lots, or, for an amount-only scope, more than one lot of that
amount from anyone — the answer is withheld (None) with the reason
in the proof; `run_story` reports `ambiguous_scope: true` and
`reason_balance` abstains. Uniquely-resolving scopes (giver named
and unique, or a unique amount) answer exactly as before, and
TOTAL (unscoped) balances are unchanged: they still sum, because a
total is not a scope question. This matches the live set's
rule-derived duplicate-scope ground truth ("scoped remainder
indeterminate") and the v1.2 rule (certify only when exactly one
inflow matches).

## Fix 3 — Fullproof prompt: the question-missing-info line

B's only live loss (live-040, gave/take framing) came from the
anti-abstention wording overshooting: the model answered a question
whose own content did not determine the answer. The fix draws the
line on the QUESTION, in `nova/semantic/fullproof.py` only (no
recorded arm prompt in `handoff.py` was touched). The
anti-abstention clause for NOVA-unsupported cases is preserved
("never merely because NOVA could not determine it" is verbatim in
the new instruction; "does NOT mean the answer is unknowable" is
verbatim in the new header).

HEADER — old ending:
> "…If a verified answer is given, check it against the question
> before using it. If the question genuinely lacks required facts,
> say so. Never invent missing facts."

HEADER — new ending:
> "…If a verified answer is given, check it against the question
> before using it. Judge answerability from the question itself,
> never from NOVA's notes: if every fact the answer depends on is
> stated in the question, follows from what it states, or is
> general knowledge, answer it — even when NOVA has no proof. Say
> the answer cannot be determined only when a fact the answer
> depends on is missing from the question itself and is not
> general knowledge: the question asks about an amount, an event,
> or a detail it never gives. Never invent missing facts."

ANSWER_INSTRUCTION — old:
> "Put your final answer alone on the first line: a number, yes,
> no, a short definition, or "I don't know" — but only say "I
> don't know" when the question itself lacks the facts, never
> merely because NOVA could not determine it. You may add at most
> one short sentence after it."

ANSWER_INSTRUCTION — new:
> "Put your final answer alone on the first line: a number, yes,
> no, a short definition, or "I don't know". Say "I don't know"
> only when the question itself lacks a fact the answer depends
> on and general knowledge does not supply it — never merely
> because NOVA could not determine it. You may add at most one
> short sentence after it."

Byte-identical question preservation under the new wording is
covered by the existing taint regression tests (all pass) plus a
new refund-question taint test in `tests/test_advance_v14.py`.

## Before / after (deterministic, model=None)

Known probes, all paths (production / pipeline / package agreed):

| Probe | v1.3 | v1.4 |
|---|---|---|
| Refund: Eli $100, gave $30, refunded $10, scoped | 70 (candidate) | **80 (verified)** |
| Duplicate scope: $100 ×2, spent $30, scoped | 170 (verified) | **unknown (abstain)** |
| Distinct givers, same amount, amount-only scope | 170 (verified) | **unknown (abstain)** |
| Self-transfer Mira (regression) | 45 | 45 |
| $38 package probe (regression) | 38 | 38 |

Diagnostic only (NOT a benchmark): the spent live-011 item's NOVA
verified answer moves $55 → $75, i.e. NOVA itself now verifies the
amount the model previously had to recover on its own. The live-40
set is spent as a benchmark for these fixes and was not re-scored.

NEW fresh probe sets (written for v1.4, no overlap with live-40
items; ground truth hand-derived in the files;
`probes_v14/run_probes.py`, production path):
- Refund set, 14 items across all five phrasings + total queries,
  multi-lot FIFO restoration, over-refund / duplicate-refund /
  stranger-refund abstentions, negated refund, fully-spent-lot
  restoration, cents: **14/14**.
- Duplicate-scope set, 11 items (true duplicates abstain;
  distinct-lot scopes that resolve uniquely answer; totals and
  total-based yes/no unchanged): **11/11**.

## Gates (all run in this copy, final state)

- `python3 tests/run_all.py` → **OVERALL PASS**
- `python3 -W error::ResourceWarning -m unittest discover -s tests`
  → **356 tests OK** (v1.3's 339 + 17 new in
  `tests/test_advance_v14.py`)
- Frozen deterministic: `eval.run_eval nova --set eval` →
  **250/250 = 1.000** (run 20261102-185245)
- Fresh deterministic: `--set fresh` → **250/250 = 1.000** (same run)
- v1.2 standalone suites (in `_v12_src`): **75/75 OK**, unchanged
- Compile: all edited modules pass `compileall`
- Boundary 42/42: still NOT RUNNABLE HERE (no such set in this
  repo) — reported, not assumed, same as v1.3.

## Honest limits — what the fixes do NOT cover

- Refund phrasings beyond the five patterns: "gave the money
  back", "sent it back", "gave Y a refund", "paid Y back",
  "reimbursed" are NOT parsed (they fall through to the heuristic
  tier and stay visible as unusable frames; the answer then rests
  on the remaining parsed events with candidate status). Negated
  refunds ("did not refund") likewise have no deterministic event —
  rf-12 answers correctly (60) but at candidate status.
- Refund validity is per-counterparty-pair and text-ordered, as in
  v1.2: a refund stated BEFORE its justifying transfer is unmatched
  and poisons the story's balances (abstain), even for unrelated
  queries in the same story.
- Lot restoration follows the ledger's FIFO convention (oldest
  drawn lot first). In interleaved multi-party flows that is a
  convention, not a fact stated in the text.
- Duplicate abstention is scoped-only, and conservative: it
  abstains when one identical lot is fully spent and a FIFO reading
  could have picked the survivor (probe dp-09 documents this).
  Totals still sum duplicate inflows — if a story literally repeats
  one gift as narration rather than two gifts, the total follows
  the text as written.
- Fix 3 is wording-only and has NO live verification (this phase
  was $0 by instruction). Whether it repairs the live-040 class
  without costing correct answers needs a future capped live run on
  a fresh set.
- Decimal-exact money is still not done (core pipeline is float;
  rf-14's raw answer is 35.199999999999996, within its stated
  tolerance) — the documented v1.3 gap is unchanged.
