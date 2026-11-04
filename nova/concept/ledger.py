"""Concept engine, part 2: the entity ledger + deterministic math.

The ledger is the concept engine's MEMORY: one running balance per person,
updated event by event. The math is exact — no model, no guessing.

A balance query can be asked two ways:
  * total balance: everything the person received minus everything they gave.
  * scoped balance: only money traceable to one incoming transfer
    ("how much does John have left from the $20 Marcus gave him?").
    Scoped tracking follows the money: each outgoing transfer draws from
    the person's oldest (FIFO) incoming funds first, so a scoped balance is
    the remainder of that specific inflow after all outflows that drew on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import BalanceQuery, Transfer


@dataclass
class Ledger:
    """Per-person running balances + FIFO inflow lots for scoped queries."""

    balances: dict[str, float] = field(default_factory=dict)
    # person -> list of [source_key, amount_remaining]; source_key is
    # (giver, amount) of the incoming transfer, or ("initial", amount).
    # Spent-out lots (remaining 0) are KEPT (v1.4): a later refund
    # must be able to restore the lot it belongs to, and duplicate
    # scope detection must be able to see that a scope matches more
    # than one lot. A zero lot contributes 0 to every sum, so keeping
    # it changes no total.
    lots: dict[str, list[list]] = field(default_factory=dict)
    trace: list[str] = field(default_factory=list)
    # Refund bookkeeping (v1.4, semantics from NOVA v1.2): plain
    # amounts sent per ordered pair, refunds returned per ordered
    # pair, and one issue string per refund that exceeds what the
    # earlier transfer in the opposite direction can justify.
    sent_totals: dict[tuple, float] = field(default_factory=dict)
    refund_totals: dict[tuple, float] = field(default_factory=dict)
    refund_issues: list[str] = field(default_factory=list)
    # Pending refunds (v1.6): stated-amount refunds narrated BEFORE
    # the transfer that justifies them. A refund is defined by the
    # transfer it returns, not by where the sentence sits, so an
    # unjustified-at-its-position refund is parked here and retried
    # after every later transfer; it applies at the first point the
    # pair's sent total covers it. Whatever is still parked at the
    # end of the story is settled by run_story through the ordinary
    # refund path, which records the unmatched-refund issue — the
    # story abstains, exactly the pre-v1.6 outcome. Parking triggers
    # only where the old code recorded an issue (and therefore
    # abstained), so no previously certified answer can change.
    pending_refunds: list[Transfer] = field(default_factory=list)

    def _draw_lots(self, person: str, amt: float) -> None:
        """Outgoing money draws FIFO from the person's lots."""
        remaining = amt
        for lot in self.lots.get(person, []):
            take = min(lot[1], remaining)
            lot[1] -= take
            remaining -= take
            if remaining == 0:
                break
        self.lots.setdefault(person, [])

    def _restore_lots(self, person: str, giver: str, amt: float) -> None:
        """A refund puts money back into the lots the person's
        earlier outflows drew on, oldest first, never above a lot's
        original amount. Any excess (the drawn-down room is smaller
        than the refund, e.g. the lot predates this ledger) becomes
        a new lot from the refunder, like an ordinary inflow."""
        remaining = amt
        for lot in self.lots.get(person, []):
            room = lot[0][1] - lot[1]
            add = min(room, remaining)
            lot[1] += add
            remaining -= add
            if remaining == 0:
                break
        if remaining > 0:
            self.lots.setdefault(person, []).append(
                [(giver, remaining), remaining])

    def apply(self, ev: Transfer) -> None:
        giver, recv, amt = ev.giver, ev.recipient, ev.amount
        # Self-transfer guard (merged from NOVA v1.2, 2026-11-02):
        # giving to yourself moves nothing — it must not draw down
        # your lots or read as spending. v1.2's ledger excludes
        # self-transfers from scoped spending; the FIFO ledger here
        # previously counted one as an outflow (Mira $60 -> Mira $20
        # -> Bo $15 answered 25 instead of 45).
        if giver == recv:
            self.trace.append(
                f"{giver} gave {recv} {_fmt_amt(amt)}: self-transfer, "
                f"no movement")
            return
        if ev.kind == "refund":
            if self._refund_justified(ev):
                self._apply_refund(ev)
            elif ev.amount is None:
                # Amount-less refunds are never parked (v1.6): the
                # amount would have to be resolved against transfers
                # the text has not narrated yet, and which of them
                # "the money" means is the text's own ambiguity.
                # The ordinary path records the unmatched issue and
                # the story abstains — the pre-v1.6 outcome.
                self._apply_refund(ev)
            else:
                # A stated refund narrated before its justifying
                # transfer (v1.6): park it instead of recording an
                # issue. It is retried after every later transfer
                # (see _retry_pending) and settled by run_story if
                # no transfer ever justifies it.
                self.pending_refunds.append(ev)
                self.trace.append(
                    f"{giver} refunded {recv} ${amt:g}: stated "
                    f"before any transfer from {recv} to {giver} "
                    f"justifies it — held pending a later transfer")
            return
        self.sent_totals[(giver, recv)] = \
            self.sent_totals.get((giver, recv), 0) + amt
        self.balances[giver] = self.balances.get(giver, 0) - amt
        self.balances[recv] = self.balances.get(recv, 0) + amt
        # Outgoing money draws FIFO from the giver's lots.
        self._draw_lots(giver, amt)
        # The incoming transfer becomes a new lot for the recipient.
        key = (giver, amt)
        self.lots.setdefault(recv, []).append([key, amt])
        self.trace.append(
            f"{giver} gave {recv} ${amt:g}: "
            f"{giver} balance ${self.balances[giver]:g}, "
            f"{recv} balance ${self.balances[recv]:g}")
        # A new transfer may justify a parked refund (v1.6).
        self._retry_pending()

    def _refund_justified(self, ev: Transfer) -> bool:
        """Would this refund be valid if applied right now? Mirrors
        ``_apply_refund``'s own checks against the current totals:
        a stated amount must fit in what the opposite direction has
        sent and not already refunded; an amount-less refund needs
        something outstanding."""
        sent = self.sent_totals.get((ev.recipient, ev.giver), 0)
        already = self.refund_totals.get((ev.giver, ev.recipient), 0)
        if ev.amount is None:
            return sent - already > 0
        return ev.amount <= sent - already + 1e-9

    def _retry_pending(self) -> None:
        """Apply any parked refunds that later narration has now
        justified, in narration order (v1.6). Applying a refund
        never justifies another refund — it only consumes the
        pair's outstanding — so one ordered pass is enough, and a
        refund that stays unjustified stays parked."""
        if not self.pending_refunds:
            return
        still_pending: list[Transfer] = []
        for ev in self.pending_refunds:
            if self._refund_justified(ev):
                self.trace.append(
                    f"{ev.giver} refunded {ev.recipient} "
                    f"${ev.amount:g}: the later transfer from "
                    f"{ev.recipient} to {ev.giver} justifies the "
                    f"pending refund — applied here")
                self._apply_refund(ev)
            else:
                still_pending.append(ev)
        self.pending_refunds = still_pending

    def settle_pending(self) -> None:
        """End of story (v1.6): retry once more, then settle any
        refund still parked through the ordinary refund path —
        which records the unmatched-refund issue, so the story
        abstains exactly as it did before v1.6."""
        self._retry_pending()
        for ev in self.pending_refunds:
            self._apply_refund(ev)
        self.pending_refunds = []

    def _apply_refund(self, ev: Transfer) -> None:
        """A refund (v1.4, semantics from NOVA v1.2): money returned
        from the recipient of an earlier transfer to that transfer's
        giver. Valid only up to what the earlier transfers in the
        opposite direction sent and have not already refunded; an
        excess is recorded in ``refund_issues`` and makes the story's
        balances uncertifiable (the reasoner abstains). A valid
        refund restores the refundee's lots instead of opening a
        new, unrelated lot — the money rejoins the pot it left."""
        giver, recv, amt = ev.giver, ev.recipient, ev.amount
        sent = self.sent_totals.get((recv, giver), 0)
        already = self.refund_totals.get((giver, recv), 0)
        if amt is None:
            # Amount-less refund (v1.5: "gave the money back",
            # "returned the money"): no figure is stated, so the
            # refund is the pair's full outstanding balance — what
            # the earlier transfers sent and have not already
            # refunded. Nothing outstanding means the refund
            # matches no earlier transfer, like an excess refund.
            amt = sent - already
            if amt <= 0:
                self.refund_issues.append(
                    f"{giver} gave the money back to {recv}, but "
                    f"{recv} had sent {giver} ${sent:g} and "
                    f"${already:g} was already refunded: nothing "
                    f"is outstanding, so the refund matches no "
                    f"earlier transfer")
                self.trace.append(
                    f"{giver} gave the money back to {recv}: "
                    f"nothing outstanding, refund unmatched")
                return
        if amt > sent - already + 1e-9:
            self.refund_issues.append(
                f"{giver} refunded {recv} ${amt:g}, but {recv} had "
                f"only sent {giver} ${sent:g} and ${already:g} was "
                f"already refunded: the refund matches no earlier "
                f"transfer")
        self.refund_totals[(giver, recv)] = already + amt
        self.balances[giver] = self.balances.get(giver, 0) - amt
        self.balances[recv] = self.balances.get(recv, 0) + amt
        # The refunder pays out of their own lots, FIFO, like any
        # outflow; the refundee's lots are restored, not appended.
        self._draw_lots(giver, amt)
        self._restore_lots(recv, giver, amt)
        self.trace.append(
            f"{giver} refunded {recv} ${amt:g}: "
            f"{giver} balance ${self.balances[giver]:g}, "
            f"{recv} balance ${self.balances[recv]:g}")

    def answer(self, q: BalanceQuery) -> tuple[float | None, list[str]]:
        """Return (answer, proof_steps) for a balance query.

        The answer is None when a scoped query does not resolve to
        exactly one lot (v1.4, duplicate-scope abstention, semantics
        from NOVA v1.2): the question points at "the $100" but the
        story holds two lots it could mean — two identical inflows
        from the same giver, or, for an amount-only scope, two
        inflows of that amount from anyone. Summing them (the
        pre-v1.4 behaviour: the $100 + $100 story answered 170)
        certifies a number the story does not determine. v1.5 adds
        the other end: a scope resolving to NO lot (its giver name
        failed to resolve) also abstains instead of certifying
        sum([]) == $0. A scope that resolves to exactly one lot
        answers as before (including a fully spent lot, kept at 0),
        and total (unscoped) balances are unaffected."""
        if q.scope_amount is None:
            total = _whole(self.balances.get(q.person, 0))
            steps = list(self.trace)
            steps.append(f"Total balance for {q.person}: ${total:g}")
            return total, steps
        # Scoped: remainder of the specific inflow. Match (giver, amount)
        # when the giver is known; otherwise match by amount alone (the
        # probe generator only uses the amount-only form when exactly one
        # inflow of that amount exists, so the match is unambiguous).
        matching = []
        for lot_key, left in self.lots.get(q.person, []):
            if q.scope_giver is not None:
                match = lot_key == (q.scope_giver, q.scope_amount)
            else:
                match = lot_key[1] == q.scope_amount
            if match:
                matching.append(left)
        steps = list(self.trace)
        if len(matching) > 1:
            steps.append(
                f"Scoped balance for {q.person} from "
                f"${q.scope_amount:g}"
                f"{' from ' + q.scope_giver if q.scope_giver else ''}: "
                f"ambiguous — the scope matches {len(matching)} "
                f"separate lots, so no single remainder is "
                f"determined")
            return None, steps
        if not matching:
            # v1.5: a scope that resolves to NO lot certifies
            # nothing. Pre-v1.5 this fell through to sum([]) == 0,
            # so a scope whose giver name failed to resolve (the
            # v14-022 leak: "the $130 that Nils gave Pavel" was
            # captured with the giver as "That Nils") certified $0
            # over a story holding two conflicting lots. A lot that
            # was fully spent is KEPT at 0 and still matches, so a
            # genuine $0 remainder still answers 0 — zero matches
            # means the scoped inflow itself is not in the story.
            steps.append(
                f"Scoped balance for {q.person} from "
                f"${q.scope_amount:g}"
                f"{' from ' + q.scope_giver if q.scope_giver else ''}: "
                f"unresolved — the scope matches no lot, so no "
                f"remainder is determined")
            return None, steps
        remainder = _whole(sum(matching))
        steps.append(
            f"Scoped balance for {q.person} from "
            f"${q.scope_amount:g}"
            f"{' from ' + q.scope_giver if q.scope_giver else ''}: "
            f"${remainder:g}")
        return remainder, steps


def _fmt_amt(amt: float | None) -> str:
    """'$10' for an amount, 'an unstated amount' for an amount-less
    refund (v1.5) — trace text only."""
    return "an unstated amount" if amt is None else f"${amt:g}"


def _whole(v: float) -> int | float:
    """Return an int when the value is whole, so proofs read $10 not $10.0."""
    return int(v) if float(v).is_integer() else v


def run_story(events: list[Transfer], q: BalanceQuery) -> dict:
    """Apply all events, answer the query, return answer + full proof.

    ``answer`` is None (with the reason in the proof and in the
    ``refund_issues`` / ``ambiguous_scope`` fields) when the story
    cannot certify one: an unmatched (over-) refund anywhere in the
    story, or a scoped query matching more than one lot."""
    ledger = Ledger()
    for ev in events:
        ledger.apply(ev)
    # v1.6: refunds narrated before their justifying transfer were
    # parked during the pass; settle whatever never got justified
    # (records the unmatched-refund issues, so the story abstains).
    ledger.settle_pending()
    answer, steps = ledger.answer(q)
    ambiguous_scope = q.scope_amount is not None and answer is None
    if ledger.refund_issues:
        answer = None
        steps = steps + [f"Unmatched refund: {issue}"
                         for issue in ledger.refund_issues]
    return {
        "answer": answer,
        "person": q.person,
        "events": [ev.as_dict() for ev in events],
        "proof": steps,
        "refund_issues": list(ledger.refund_issues),
        "ambiguous_scope": ambiguous_scope,
    }
