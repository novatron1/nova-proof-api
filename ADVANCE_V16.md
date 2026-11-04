# ADVANCE v1.6 (candidate) — refund-before-transfer reordering (2026-11-03)

Work copy only: `~/workspace/nova-proof-api-merge-v16/` (copied from
the promoted main repo, which is verified v1.5). The main repo
`~/workspace/nova-proof-api/` is untouched — verified at the end by
md5 against a snapshot taken before work began (168 files,
identical). **No live model calls. Spend: $0.** Nothing is
promoted; v1.6 is a candidate, and the decision rule is the usual
one: it replaces v1.5 only if it wins under verification with no
regression anywhere.

This advance takes up the one fix v1.5 deliberately skipped
(ADVANCE_V15.md, "Stretch — refund ordering"): a refund stated
before its justifying transfer was unmatched at its narration
position and poisoned the story to abstain.

## The design question — what SHOULD the semantics be?

Three options were weighed:

**(a) Reorder by dependency: apply all transfers first, then all
refunds.** REJECTED — the v1.5 objection stands, with a concrete
counterexample. A refund's FIFO lot restoration depends on the
ledger state at its application position. Story: Dan gave Ana
$100; Ana gave Ben $80; Ben refunded Ana $30; Ana gave Cleo $50.
In narration order the scoped remainder of Dan's $100 lot is $0
(the refund replenished the lot to $50, then the $50 spend drew
it down). Under transfers-then-refunds the refund moves after
the Cleo spend and the same question certifies $30. The text's
only chronology is its narration order; overriding it
manufactures a different certified answer in stories that are
currently correct. That is a semantics change wearing a
robustness fix's clothes.

**(b) Pending refunds: park an unjustified refund and resolve it
when its transfer appears.** CHOSEN, with the disciplines below.
A refund is *defined* by the transfer it returns — the pair and
the amount — not by where its sentence sits. Validity in this
engine has always been a per-ordered-pair cumulative property
(`sent_totals` / `refund_totals`, v1.4), never a per-sentence
one, so "the transfer had not been narrated yet" is a fact about
the text layout, not about whether the refund is justified.

**(c) Abstain whenever the pairing is not positionally explicit
(the pre-v1.6 behaviour, generalised).** REJECTED as the general
rule: the common case is not ambiguous at all — a later transfer
(or the cumulative total of several) determines validity exactly.
Abstention is kept precisely where ambiguity is real (below).

### The chosen semantics (all in `nova/concept/ledger.py`)

- A **stated-amount** refund that is not justified at its
  narration position (pair's sent − already-refunded < amount)
  is **parked** in `Ledger.pending_refunds` instead of recording
  an unmatched-refund issue. The proof trace says so, in words.
- After every subsequent ordinary transfer is applied, parked
  refunds are **retried in narration order**; a parked refund
  applies at the first point where the pair's cumulative sent
  covers cumulative refunds including it. It lands immediately
  after the transfer that justifies it — the earliest faithful
  position, and exactly where the same story narrated in order
  would put it (probe rr-01 vs its in-order twin rr-19: both 125;
  also unit-tested). **No other event is ever reordered.**
- If no later transfer ever justifies a parked refund,
  `run_story` settles it through the ordinary `_apply_refund`,
  which records the unmatched-refund issue — the story abstains,
  the pre-v1.6 outcome, word for word in the issue list.
- **Amount-less refunds are never parked.** "Gave the money
  back" resolves (v1.5) to the pair's full outstanding balance;
  stated before any opposite transfer exists, both the amount
  and the lot-restoration position would have to be guessed
  against transfers the text has not narrated yet, and the two
  can disagree: with two inflow lots and an intervening outflow,
  restoring at the end vs in place gives different scoped
  remainders (50 vs 100 on the constructed case in the design
  notes), and the text determines neither. An amount-less refund
  unjustified at its position abstains, exactly as in v1.5
  (probe rr-24); justified at its position it resolves exactly
  as in v1.5 (rr-25).

### The safety invariant

Parking triggers **exactly** where the old code recorded a
refund issue — and any story with a refund issue abstains. So no
story v1.5 certifies can change its answer under v1.6: v1.6 can
only turn some v1.5 abstentions into answers, and only when a
later transfer makes the refund determinate. Everything else —
negative controls, over-refunds, normal-order stories — is
bit-for-bit the old behaviour, which the gates below confirm
empirically (the 40-item live-test deterministic set shows **zero
differing items**).

### Edge cases, decided

- **Two transfers, same amount, same pair:** validity is
  per-pair cumulative (existing v1.4 semantics — a refund is
  justified by what the pair sent in total, not tied to one
  specific transfer). A refund narrated first is justified as
  soon as the cumulative sent covers it. Scoped questions still
  resolve through FIFO lots exactly as before; no new ambiguity
  is introduced. (rr-13.)
- **Refund amount differs from the transfer:** a partial refund
  (amount < transfer) is justified the moment cumulative sent
  covers it (the whole class-A set). An amount exceeding
  everything the pair ever sends is never justified → abstain
  (rr-16).
- **Partial justification across two transfers:** refund $70,
  transfers $40 then $40 — the refund applies only after the
  second transfer lands (unit-tested).
- **Several parked refunds, one pair:** applied in narration
  order, each consuming the pair's outstanding; if the
  cumulative claims exceed what was sent, the excess one stays
  parked and settles as unmatched → abstain. A story claiming
  $90 back against $80 sent cannot be certified (rr-15).
- **Negated refunds** ("did not refund", "never paid back")
  never become transfer frames at either tier, so they never
  park and never apply (rr-22, rr-23 — identical before/after).
- **Intervening events** between the refund sentence and its
  transfer keep their positions and their effects; only the
  refund moves, to just after its justifying transfer (rr-11,
  rr-12, rr-27).
- **Residual limit, stated honestly:** totals never depend on
  application position (they are sums). A *scoped* remainder can,
  in a constructed multi-lot story, depend on where in the
  refundee's later outflow sequence a restore lands; v1.6's
  convention — the earliest justified point, immediately after
  the transfer the refund returns — is the most defensible
  reading of the text, and it is the same convention an in-order
  narration of the same story would produce. The proof trace
  narrates both the parking and the application, so the
  assumption is inspectable in every verified answer.

## Before / after (deterministic, model=None, production path)

NEW fresh probe set written for v1.6 BEFORE the fix, from the
documented skip class (`probes_v16/refund_reorder_probes.json`,
30 items, ground truth hand-derived in the file; no spent items).
Run against BOTH repos with the same runner
(`probes_v16/run_probes.py --root <repo>`):

| Set | v1.5 (main) | v1.6 (this copy) |
|---|---|---|
| A — refund-first, 10 phrasings | 0/12* | **12/12** |
| B — refund-first, intervening events | 0/2 | **2/2** |
| C — two transfers / two refunds | 1/3 | **3/3** |
| D — negative controls (must abstain) | 3/3 | **3/3** |
| E — normal-order controls | 3/3 | **3/3** |
| F — negated refund first | 2/2 | **2/2** |
| G — amount-less (carve-out + control) | 2/2 | **2/2** |
| H — giver-named scope, refund-first | 0/1 | **1/1** |
| I — spend after justifying transfer | 0/1 | **1/1** |
| J — total balance, refund-first | 0/1 | **1/1** |
| **Fresh total, 30** | **11/30** | **30/30** |

\* Class A has 12 items here (rr-01…rr-10, rr-29, rr-30). Every
item v1.5 already passed still passes with the identical answer;
every gain is a v1.5 abstention (actual=None) turned into the
hand-derived answer, at **verified** status — the proof is
complete, with the parking and its resolution narrated in the
trace.

## Gates (all run in this copy, final state)

- `python3 tests/run_all.py` → **OVERALL PASS**
- `python3 -W error::ResourceWarning -m unittest discover -s tests`
  → **391 tests OK** (v1.5's 377 + 14 new in
  `tests/test_advance_v16.py`)
- Frozen deterministic: `eval.run_eval nova --set eval` →
  **250/250 = 1.000** (run 20261103-182311)
- Fresh deterministic: `--set fresh` → **250/250 = 1.000**
  (run 20261103-182311)
- probes_v14 (v1.4's fresh sets) → **25/25**
- probes_v15 (v1.5's fresh sets) → **32/32**
- probes_v16 (this advance's fresh set) → **30/30**, with the
  same files scoring 11/30 against the v1.5 main repo
- v1.5 live-test deterministic side, re-run from
  `live_det_recheck/` (the recorded set + runner from
  `live_test_2026-11-03_v15/`): **25/40 — zero differing items**
  vs the recorded det_B (same answers, same statuses on all 40)
- `_v12_src` standalone suites: the tree is byte-identical to
  main (verified by diff) and untouched by this advance; not
  re-run, reported as unchanged-by-construction
- Compile: the edited module passes `compileall`
- Main repo integrity: md5 snapshot of `nova/ tests/ probes_v14/
  probes_v15/ eval/` (168 files) taken before work began;
  re-verified identical after. The whole v1.6 change surface in
  this copy is `nova/concept/ledger.py` + the new test file +
  `probes_v16/` + gate artifacts.

## Honest limits — what this does NOT cover

- Amount-less refunds narrated before any opposite transfer
  still abstain (deliberate carve-out, above). A text meaning
  "gave the money back" ahead of its transfer gets no certified
  answer until the class gets a semantics of its own.
- Refund validity remains per-counterparty-pair; a refund whose
  justifying transfer is described with a *different* pair
  (e.g. routed through a third person) is still unmatched.
- The fix lives in the Ledger, so it covers every path that
  runs a story through `run_story` (concept API and semantic
  production path alike — the only two callers). It does not
  change parsing: a refund phrasing the parser does not know is
  still unparsed, in any position.
- No live verification (this phase was $0 by instruction): the
  model's behaviour over the newly-verified proofs is untested,
  same caveat as v1.4 Fix 3 / v1.5 Fix 4.
