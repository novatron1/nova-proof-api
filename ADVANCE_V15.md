# ADVANCE v1.5 — merged NOVA, four advancements over v1.4 (2026-11-03)

Work copy only: `~/workspace/nova-proof-api-merge-v15/` (copied from
the promoted main repo, which is verified v1.4). The main repo
`~/workspace/nova-proof-api/` and the merge-v13/v14 copies are
untouched (verified at the end: none of them contains any v1.5
change); frozen baseline zip md5
`b8c7b5cb8a078a787cd85366779c9c5b` verified identical before and
after. **No live model calls. Spend: $0.**

## Fix 1 — Negated transfers (compound clauses)

Before: a story sentence is parsed as ONE unit. The v14-020 class
("Liam didn't give Lena $55, but Liam gave Samir $30") produced a
single heuristic frame — verb "give", quantity $55, recipient the
garbage string "Lena But Liam Gave Samir", polarity negative — so
the frame was unusable and the real $30 transfer in the second
clause was lost with it. The story answered the full $90 (truth
$60), in both v1.3 and v1.4.

Now (`nova/semantic/extract.py`, `_frames_for_sentence`): the
whole sentence is parsed first and a verified (certainty "known")
frame is kept exactly as before. Only when the whole sentence did
NOT deterministically parse, is not a question, and splits on a
clause boundary (`;`, ", but", ", yet", or " but " before a new
capitalised subject) is each clause parsed separately — and the
clause frames are used only when at least one clause parses
deterministically. Each clause carries its own polarity: the
negated clause yields a negative heuristic frame (which, per the
existing translate rule, never becomes a transfer) and the
affirmative clause yields its real verified transfer. Negation is
now scoped to its own clause across the parser's verb inventory
(gave / received / sent / handed clauses all behave this way;
ng-05 covers a negated *receive*, ng-07 "did not hand", ng-11
"did not send"). The deterministic tier also cannot match a
negated sentence directly — every pattern requires the verb
immediately after the giver's name, so "did not give" / "never
gave" break the anchor (unit-tested).

Effect on status, honestly: answers over these stories carry
`candidate_interpretation`, because the negated clause is a
heuristic-tier frame and the reasoner downgrades any answer whose
story contains one. The numbers are exact; the label is honest.

## Fix 2 — Refund phrasing expansion

Before: v1.4's five deterministic refund patterns left
"reimbursed", "paid back", "gave the money back", "returned the
money" unparsed. One before-behaviour is worth naming: "Tina
returned the money to Ruth" was silently dropped and the story
still certified the remaining-events answer ($35 where the truth
is $95) at **verified** status.

Now (`nova/concept/events.py`, all `kind="refund"`, checked before
the ordinary transfer patterns; validity + FIFO lot restoration
are the unchanged v1.4 Ledger rules):
- "X reimbursed Y $A" and "X reimbursed Y for $A"
- "X paid Y back $A" and "X paid $A back to Y"
- "X gave $A back to Y" and "X gave back $A to Y"
- Amount-less: "X gave the money back to Y", "X gave it back
  to Y", "X returned the money to Y". These carry
  `Transfer.amount = None` (`nova/concept/ledger.py`,
  `_apply_refund` resolves it): the refund is the pair's full
  outstanding balance (sent − already refunded) — the only
  determinate reading of an unqualified "gave the money back". If
  nothing is outstanding, it is an unmatched refund and the story
  abstains, like any excess refund. A stated partial refund
  followed by an amount-less one resolves to the remainder
  (rp-09: $30 stated, then $50 resolved, total restored $80).
  ("Gave SOME money back" deliberately does NOT match: no figure
  and no full-return claim — that is the genuinely ambiguous
  class, e.g. spent live item v14-038, GT unknown.)
- Negated refunds never restore money: "did not reimburse",
  "never paid … back", "did not refund" cannot match the anchored
  patterns (the verb must immediately follow the name), and
  "refused to refund" is kept negative at the heuristic tier —
  "refused" joins `_EXTRA_NEGATORS` in `extract.py`, since
  refusing negates the complement event.

`frame_to_transfer` (`nova/semantic/translate.py`) passes exactly
one quantity-less frame through: a refund (the Ledger resolves
it). Every other quantity-less frame still returns None.

## Fix 3 — Giver-named-scope abstention leak

Root cause, precisely: the question "How much money is left from
the $130 that Nils gave Pavel?" failed the deterministic balance
form (no relative-"that" tolerance), fell to the multi-word
fallback, which captured the giver as **"That Nils"**. The scope
then matched ZERO lots in `Ledger.answer`, which fell through to
`sum([])` and certified **$0** — over a story holding two
conflicting $130 lots. Both the harness and package paths did
this.

Fixes, three layers:
- `nova/concept/events.py`: `_BALANCE_FROM_RE` tolerates an
  optional relative "that" — the deterministic form now parses
  the question with giver "Nils".
- `nova/semantic/extract.py`: `_semantic_balance` strips a
  leading relative "that" from the multi-word fallback's giver
  capture, so the fallback resolves the same name.
- `nova/concept/ledger.py`: a scoped query resolving to **no**
  lot now abstains with the reason in the proof, instead of
  certifying `sum([]) == 0`. This closes the whole class —
  whatever the scope names and however its resolution fails, zero
  matches certify nothing. A lot that was fully spent is KEPT at
  0 and still matches, so a genuine $0 remainder still answers 0
  (unit-tested). `reason.py`'s abstention reason now reads "the
  scope of the question does not resolve to exactly one lot",
  covering both the multi-lot and no-lot cases.

With the giver resolving correctly, the v14-022 story lands on
two conflicting lots and the existing v1.4 duplicate-scope
abstention fires. Legit single-lot giver-named scopes still
answer (gs-03/gs-04: 65; gs-05: a giver-named scope resolving
uniquely among same-amount lots from different givers answers
70).

## Fix 4 — Honour the stated abstention reason (fullproof only)

First checked whether the reason reaches the model: it does.
For the v14-025 story the package's coverage carries
`duplicate_scope_ambiguity: true`, the WARNING line, the
`missing` text ("the scope of the question … ambiguous"), and the
reasoning trace's "ambiguous — the scope matches 2 separate lots"
line. No package change was needed; the loss was the prompt's
thrust ("NOVA is not an authority… never merely because NOVA
could not determine it") inviting the model to override exactly
this case — with the summed trace ($120) in view. So the fix is
wording in `nova/semantic/fullproof.py` only. Exact diff:

HEADER — one sentence added before "Never invent missing facts.":
> "One further case is the question's own ambiguity, not NOVA's
> limit: when NOVA's notes say the amount the question scopes to
> matches more than one transfer, or the same transfer is
> described with conflicting values, the question itself does not
> pick one — also say the answer cannot be determined, and do not
> combine the conflicting transfers into a single total."

ANSWER_INSTRUCTION — one clause added:
> 'Say "I don't know" only when the question itself lacks a fact
> the answer depends on and general knowledge does not supply it,
> **or when NOVA's notes state the question's own scope is
> ambiguous (the scoped amount matches more than one transfer)**
> — never merely because NOVA could not determine it.'

The anti-abstention clause for NOVA-unsupported/no-proof cases is
unchanged ("never merely because NOVA could not determine it" and
"does NOT mean the answer is unknowable" are verbatim). No
recorded experiment arm prompt was touched. Wording-only, like
v1.4's Fix 3: whether it changes the model's override behaviour
needs a future capped live run on a fresh set — not claimed here.

## Stretch — refund ordering: SKIPPED, deliberately

A refund stated before its justifying transfer is currently
unmatched and poisons the story to abstain (documented v1.4
limit). Making it apply "transfers-then-refunds" is NOT a small
clean fix in this engine: a refund's validity and its FIFO lot
restoration both depend on the ledger state at the refund's
position in the story — what the refunder currently holds and
which lots their spends have drawn. Deferring a refund past
intervening spends changes which lots get restored and can change
answers in stories that are currently correct, i.e. it is a
semantics change wearing a robustness fix's clothes. The narrow
version (defer only when nothing at all intervenes) repairs
almost no real text. Skipped; the honest abstention stands.

## Before / after (deterministic, model=None, production path)

NEW fresh probe sets (written for v1.5 from the failure classes;
no spent items; ground truth hand-derived in the files;
`probes_v15/run_probes.py`, run against BOTH copies):

| Set | v1.4 | v1.5 |
|---|---|---|
| Negation, 11 items | 3/11 | **11/11** |
| Refund phrasing, 14 items | 3/14 | **14/14** |
| Giver scope, 7 items | 3/7 | **7/7** |
| **Fresh total, 32** | **9/32** | **32/32** |

Spent diagnostics (labelled spent, NOT counted as evidence —
v14-020/022/025 from the v1.4 live set): v1.4 1/3 → v1.5 3/3
(020: $90 → $60; 022: certified $0 → abstain; 025: abstain,
unchanged).

Known probes: v1.4's probes_v14 still **25/25** in v1.5;
self-transfer Mira 45, $38 package probe, and the v1.4 refund
probe (80 verified) are inside the gate suites below and
unchanged.

## Gates (all run in this copy, final state)

- `python3 tests/run_all.py` → **OVERALL PASS**
- `python3 -W error::ResourceWarning -m unittest discover -s tests`
  → **377 tests OK** (v1.4's 356 + 21 new in
  `tests/test_advance_v15.py`)
- Frozen deterministic: `eval.run_eval nova --set eval` →
  **250/250 = 1.000** (run 20261103-092618)
- Fresh deterministic: `--set fresh` → **250/250 = 1.000**
  (run 20261103-092619)
- probes_v14 (v1.4's fresh sets) → **25/25**
- probes_v15 (this advance's fresh sets) → **32/32**, with the
  same files scoring 9/32 against the v1.4 copy
- v1.2 standalone suites (in `_v12_src`): **75/75 OK**, unchanged
- Compile: all edited modules pass `compileall`
- Taint regression: byte-identical original-question preservation
  passes under the new fullproof wording (existing merge/handoff
  tests + the new Fix 4 test, which also asserts the ambiguity
  reason and the carve-out appear in the built prompt and the
  question appears verbatim)
- Boundary 42/42: still NOT RUNNABLE HERE (no such set in this
  repo) — reported, not assumed, same as v1.3/v1.4.

## Honest limits — what the fixes do NOT cover

- Negation scope is the clause. A negated clause whose verb is
  outside the known inventory, or a negation expressed without a
  standard negator ("hardly gave", "barely gave"), is not caught.
  Compound sentences where NO clause parses deterministically
  stay on the heuristic path, unchanged.
- Answers over stories containing a negated clause carry
  candidate status (the negated clause is a heuristic frame).
  The deterministic tier has no negated-frame representation;
  giving it one is a schema change, not a parser fix.
- Amount-less refunds resolve to the pair's FULL outstanding
  balance. A text meaning a partial, unquantified return ("gave
  some money back", "gave a little back") is deliberately not
  parsed as a refund at all (it stays visibly unparsed) rather
  than guessed.
- Refund validity remains per-counterparty-pair and
  text-ordered; the refund-before-transfer abstention stands
  (see Stretch).
- The zero-match scope guard tightens semantics: a scoped
  question whose named inflow is absent from the story now
  abstains where pre-v1.5 code certified $0. No in-repo suite
  relied on the old behaviour (all gates green), but it is a
  behaviour change, recorded as one.
- Fix 4 is wording-only with NO live verification (this phase
  was $0 by instruction). The model may still override a correct
  abstention; the fix gives it an explicit instruction not to,
  for exactly the stated-reason case, and nothing more is
  claimed.
- Decimal-exact money remains the documented open gap (core
  pipeline is float), unchanged and out of scope here.
