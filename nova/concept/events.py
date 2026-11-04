"""Concept engine, part 1: event frames.

A money-transfer story is a sequence of EVENTS. Each event is a structured
frame — the shared concept representation the Language Brain writes and the
Reasoning Brain reads:

    {"kind": "transfer", "giver": "Marcus", "recipient": "John",
     "amount": 20, "object": "dollars"}

plus a QUESTION frame:

    {"kind": "balance_query", "person": "John",
     "scope": "from the $20 Marcus gave him"}   # optional, may be None

The deterministic parser below handles the templated phrasings used in the
Day-1 probe set. Free-form paraphrase ("handed", "a tenner") is the Day-4
learned semantic component — it maps to these same frames, so the rest of
the system never changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Transfer:
    giver: str
    recipient: str
    # Amount is None only for an amount-less REFUND (v1.5: "gave
    # the money back" states no figure). The Ledger resolves it at
    # apply time to the pair's outstanding balance (sent minus
    # already refunded); ordinary transfers always carry an amount.
    amount: float | None
    object: str = "dollars"
    # "transfer" (ordinary movement) or "refund" (money returned
    # from the recipient of an earlier transfer back to its giver).
    # The Ledger treats the two differently: a refund restores the
    # lots the original outflow drew on, and is only valid up to
    # what that earlier transfer sent (v1.4, from NOVA v1.2).
    kind: str = "transfer"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "giver": self.giver,
                "recipient": self.recipient, "amount": self.amount,
                "object": self.object}


@dataclass(frozen=True)
class BalanceQuery:
    person: str
    scope_amount: float | None = None   # "from the $20 ..." or None
    scope_giver: str | None = None

    def as_dict(self) -> dict:
        return {"kind": "balance_query", "person": self.person,
                "scope_amount": self.scope_amount,
                "scope_giver": self.scope_giver}


# ---------------------------------------------------------------------------
# Deterministic event parser
# ---------------------------------------------------------------------------

_NAME = r"([A-Z][a-z]+)"
_AMOUNT = r"\$?(\d+(?:\.\d{1,2})?)"
_OBJECT = r"(?:dollars|bucks|money)"  # non-capturing: must not shift group indices

# NOTE: the object word ("dollars") is optional, but when present it is
# preceded by a space — the space must be INSIDE the optional group, or a
# bare "$20." fails to match. Questions end with "?" — the terminator
# must accept [.?!].
_OBJ = rf"(?: (?:{_OBJECT}))?"  # fully non-capturing: must not shift group indices

# "Marcus gave John $20." / "John gave Sarah $10."
_GAVE_RE = re.compile(
    rf"^{_NAME} gave {_NAME} {_AMOUNT}{_OBJ}[.?!]?$", re.IGNORECASE)
# "Marcus gave $20 to John."
_GAVE_TO_RE = re.compile(
    rf"^{_NAME} gave {_AMOUNT}{_OBJ} to {_NAME}[.?!]?$", re.IGNORECASE)
# "John received $20 from Marcus." / "John got $20 from Marcus."
# Base form "receive" is included because yes/no questions embed it:
# "Did Elif receive $45 from Rosa?" parses its inner statement
# ("Elif receive $45 from Rosa") through this same pattern.
_RECEIVED_RE = re.compile(
    rf"^{_NAME} (?:received|got|receive) {_AMOUNT}{_OBJ} from {_NAME}[.?!]?$",
    re.IGNORECASE)

# Refunds (v1.4, semantics from NOVA v1.2): money flowing back from
# the recipient of an earlier transfer to that transfer's giver.
# "Noah refunded Eli $10." / "Noah repaid Eli $10."
_REFUNDED_RE = re.compile(
    rf"^{_NAME} (?:refunded|repaid) {_NAME} {_AMOUNT}{_OBJ}[.?!]?$",
    re.IGNORECASE)
# "Noah refunded $10 to Eli." / "Noah repaid $10 to Eli."
_REFUND_TO_RE = re.compile(
    rf"^{_NAME} (?:refunded|repaid) {_AMOUNT}{_OBJ} to {_NAME}[.?!]?$",
    re.IGNORECASE)
# "Noah returned $10 to Eli."
_RETURNED_TO_RE = re.compile(
    rf"^{_NAME} returned {_AMOUNT}{_OBJ} to {_NAME}[.?!]?$",
    re.IGNORECASE)
# "Eli received a refund of $10 from Noah." / "Eli got a refund of
# $10 from Noah."
_REFUND_FROM_RE = re.compile(
    rf"^{_NAME} (?:received|got) a refund of {_AMOUNT}{_OBJ} "
    rf"from {_NAME}[.?!]?$", re.IGNORECASE)
# "Eli was refunded $10 by Noah."
_REFUND_PASSIVE_RE = re.compile(
    rf"^{_NAME} was refunded {_AMOUNT}{_OBJ} by {_NAME}[.?!]?$",
    re.IGNORECASE)

# Refund phrasings added in v1.5 (the v1.4 set above left these at
# candidate status). Same semantics: money returned from the
# recipient of an earlier transfer to that transfer's giver.
# "Noah reimbursed Eli $10." / "Noah reimbursed Eli for $10."
_REIMBURSED_RE = re.compile(
    rf"^{_NAME} reimbursed {_NAME} (?:for )?{_AMOUNT}{_OBJ}[.?!]?$",
    re.IGNORECASE)
# "Noah paid Eli back $10."
_PAID_BACK_RE = re.compile(
    rf"^{_NAME} paid {_NAME} back {_AMOUNT}{_OBJ}[.?!]?$",
    re.IGNORECASE)
# "Noah paid $10 back to Eli."
_PAID_AMT_BACK_RE = re.compile(
    rf"^{_NAME} paid {_AMOUNT}{_OBJ} back to {_NAME}[.?!]?$",
    re.IGNORECASE)
# "Noah gave $10 back to Eli."
_GAVE_AMT_BACK_RE = re.compile(
    rf"^{_NAME} gave {_AMOUNT}{_OBJ} back to {_NAME}[.?!]?$",
    re.IGNORECASE)
# "Noah gave back $10 to Eli."
_GAVE_BACK_AMT_RE = re.compile(
    rf"^{_NAME} gave back {_AMOUNT}{_OBJ} to {_NAME}[.?!]?$",
    re.IGNORECASE)
# Amount-less refunds (v1.5): "Noah gave the money back to Eli.",
# "Noah gave it back to Eli.", "Noah returned the money to Eli."
# No figure is stated, so the Transfer carries amount=None and the
# Ledger resolves it to the pair's outstanding balance; when there
# is nothing outstanding it is an unmatched refund (abstain), like
# any other refund that matches no earlier transfer.
_GAVE_MONEY_BACK_RE = re.compile(
    rf"^{_NAME} gave (?:the money|it) back to {_NAME}[.?!]?$",
    re.IGNORECASE)
_RETURNED_MONEY_RE = re.compile(
    rf"^{_NAME} returned the money to {_NAME}[.?!]?$",
    re.IGNORECASE)

# "How much money does John have left from the $20?"
# "How much does John have left?" / "How much money does John have?"
_BALANCE_RE = re.compile(
    rf"^How much (?:money )?does {_NAME} have(?: left)?"
    rf"(?: from the {_AMOUNT})?[.?!]?$", re.IGNORECASE)
# "How much money is left from the $20 Marcus gave John?"
# A relative "that" may intervene ("from the $130 that Nils gave
# Pavel", v1.5): without tolerating it the deterministic form fails
# and the multi-word fallback captured "that" as part of the
# giver's name, so the scope resolved to no lot at all.
_BALANCE_FROM_RE = re.compile(
    rf"^How much (?:money )?is left from the {_AMOUNT} "
    rf"(?:that )?{_NAME} gave {_NAME}[.?!]?$", re.IGNORECASE)


def _num(s: str) -> float:
    v = float(s)
    return int(v) if v == int(v) else v


def parse_sentence(sentence: str) -> Transfer | BalanceQuery | None:
    """Parse one sentence into a frame, or None if it matches no template."""
    s = sentence.strip()
    # Refund forms first: none of them collide with the gave /
    # received templates below (the refund verb or the words
    # "a refund of" always intervene), and a refund must never be
    # read as an ordinary transfer — the Ledger rules differ.
    m = _REFUNDED_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(2),
                        amount=_num(m.group(3)), kind="refund")
    m = _REFUND_TO_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(3),
                        amount=_num(m.group(2)), kind="refund")
    m = _RETURNED_TO_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(3),
                        amount=_num(m.group(2)), kind="refund")
    m = _REFUND_FROM_RE.match(s)
    if m:
        return Transfer(giver=m.group(3), recipient=m.group(1),
                        amount=_num(m.group(2)), kind="refund")
    m = _REFUND_PASSIVE_RE.match(s)
    if m:
        return Transfer(giver=m.group(3), recipient=m.group(1),
                        amount=_num(m.group(2)), kind="refund")
    # v1.5 refund phrasings. None of them collides with the gave /
    # received templates: "reimbursed", "paid ... back",
    # "gave ... back" and "the money" always intervene. Negated
    # forms ("did not reimburse", "never paid back", "refused to
    # refund") cannot match: the verb must immediately follow the
    # giver's name, so a negator or "refused to" breaks the anchor
    # and the sentence falls through to the heuristic tier, which
    # keeps it negative.
    m = _REIMBURSED_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(2),
                        amount=_num(m.group(3)), kind="refund")
    m = _PAID_BACK_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(2),
                        amount=_num(m.group(3)), kind="refund")
    m = _PAID_AMT_BACK_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(3),
                        amount=_num(m.group(2)), kind="refund")
    m = _GAVE_AMT_BACK_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(3),
                        amount=_num(m.group(2)), kind="refund")
    m = _GAVE_BACK_AMT_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(3),
                        amount=_num(m.group(2)), kind="refund")
    m = _GAVE_MONEY_BACK_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(2),
                        amount=None, kind="refund")
    m = _RETURNED_MONEY_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(2),
                        amount=None, kind="refund")
    m = _GAVE_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(2),
                        amount=_num(m.group(3)))
    m = _GAVE_TO_RE.match(s)
    if m:
        return Transfer(giver=m.group(1), recipient=m.group(3),
                        amount=_num(m.group(2)))
    m = _RECEIVED_RE.match(s)
    if m:
        return Transfer(giver=m.group(3), recipient=m.group(1),
                        amount=_num(m.group(2)))
    m = _BALANCE_RE.match(s)
    if m:
        return BalanceQuery(person=m.group(1),
                            scope_amount=_num(m.group(2))
                            if m.group(2) else None)
    m = _BALANCE_FROM_RE.match(s)
    if m:
        # groups: (1) amount, (2) giver, (3) recipient
        return BalanceQuery(person=m.group(3),
                            scope_amount=_num(m.group(1)),
                            scope_giver=m.group(2))
    return None


def parse_story(text: str) -> tuple[list[Transfer], BalanceQuery | None]:
    """Split a story into transfer events + the (single) question frame.

    Returns (events, query). Sentences that match no template are returned
    as unparsed — the caller decides whether to fail honestly or fall back
    to the language brain.
    """
    events: list[Transfer] = []
    query: BalanceQuery | None = None
    unparsed: list[str] = []
    for raw in re.split(r"(?<=[.?!])\s+", text.strip()):
        if not raw.strip():
            continue
        frame = parse_sentence(raw)
        if isinstance(frame, Transfer):
            events.append(frame)
        elif isinstance(frame, BalanceQuery):
            query = frame
        else:
            unparsed.append(raw)
    if unparsed:
        raise ValueError(f"unparsed sentences (no template match): {unparsed}")
    if query is None:
        raise ValueError("no balance question found in story")
    return events, query
