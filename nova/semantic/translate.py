"""Translation adapters: every module speaks ConceptFrame.

Each adapter is a pair of small, total functions (frame -> module type,
module type -> frame). They are deliberately strict:

* A negated frame NEVER becomes a positive fact or transfer.
* An uncertain (heuristic) frame NEVER becomes a ledger transfer unless
  the caller explicitly opts in — and then the answer is downgraded to
  ``candidate_interpretation``. Exact math on a guessed parse is still a
  guess.
* A frame with a missing slot NEVER gets the slot invented for it.

Modules covered: money engine (Transfer / BalanceQuery), dictionary /
encyclopedia (Knowledge store), calculator, memory (frame store), and the
symbolic reasoner (propositional facts).
"""

from __future__ import annotations

from ..adapter.core import Knowledge, calculate
from ..concept.events import BalanceQuery, Transfer
from .frame import (MONEY_ACTIONS, MONEY_UNITS, ConceptFrame,
                    evidence as ev, normalize_person)

# ---------------------------------------------------------------------------
# Money engine <-> frames
# ---------------------------------------------------------------------------

def transfer_to_frame(transfer: Transfer,
                      source_text: str | None = None) -> ConceptFrame:
    if transfer.kind == "refund":
        amt_txt = ("an unstated amount" if transfer.amount is None
                   else f"${transfer.amount:g}")
        return ConceptFrame(
            kind="transfer", who=transfer.giver, what="refund",
            recipient=transfer.recipient, object="dollars",
            quantity=transfer.amount, units="dollars",
            polarity="positive", certainty="known", status="verified",
            source_text=source_text,
            evidence=[ev("money-engine",
                         f"{transfer.giver} refunded {transfer.recipient} "
                         f"{amt_txt}", "transfer")])
    return ConceptFrame(
        kind="transfer", who=transfer.giver, what="give",
        recipient=transfer.recipient, object="dollars",
        quantity=transfer.amount, units="dollars",
        polarity="positive", certainty="known", status="verified",
        source_text=source_text,
        evidence=[ev("money-engine",
                     f"{transfer.giver} gave {transfer.recipient} "
                     f"${transfer.amount:g}", "transfer")])


def balance_query_to_frame(query: BalanceQuery,
                           source_text: str | None = None) -> ConceptFrame:
    rels = ([{"rel": "scoped_from", "target": query.scope_giver}]
            if query.scope_giver is not None else [])
    return ConceptFrame(
        kind="query", who=query.person, what="balance",
        quantity=query.scope_amount,
        units="dollars" if query.scope_amount is not None else None,
        relationships=rels,
        polarity="positive", certainty="known", status="verified",
        source_text=source_text,
        evidence=[ev("money-engine",
                     f"balance query for {query.person}", "query")])


def frame_to_transfer(frame: ConceptFrame,
                      allow_heuristic: bool = False) -> Transfer | None:
    """A frame -> a ledger Transfer, or None if it must not move money.

    Returns None for: negated frames, non-money actions, missing
    who/recipient/quantity, non-money units, and (by default) heuristic
    frames. ``allow_heuristic=True`` is the pipeline's explicit opt-in
    for sentences like "Marcus gave his sister $50", which only the
    heuristic tier can parse — and the pipeline downgrades the answer
    status when it uses one.
    """
    if frame.polarity != "positive":
        return None
    if frame.what not in MONEY_ACTIONS and frame.what not in (
            "receive", "refund"):
        return None
    if frame.kind not in ("transfer", "event"):
        return None
    if frame.certainty == "uncertain" and not allow_heuristic:
        return None
    if frame.certainty == "unknown":
        return None
    if frame.what == "receive":
        # "B received $X from A" moves money A -> B, same as give.
        giver = None
        if frame.object and frame.object.strip().lower().startswith(
                "from "):
            giver = normalize_person(frame.object.strip()[5:])
        who = giver
        recipient = normalize_person(frame.who)
    else:
        who = normalize_person(frame.who)
        recipient = normalize_person(frame.recipient)
    if who is None or recipient is None:
        return None
    if frame.quantity is None and frame.what != "refund":
        return None
    # An amount-less refund ("gave the money back", v1.5) is the one
    # frame allowed through with quantity None: the Ledger resolves
    # it to the pair's outstanding balance at apply time. A refund
    # frame WITH a quantity is the ordinary v1.4 case.
    if frame.units not in MONEY_UNITS:
        return None
    return Transfer(giver=who, recipient=recipient,
                    amount=frame.quantity, object="dollars",
                    kind="refund" if frame.what == "refund"
                    else "transfer")


def frame_to_balance_query(frame: ConceptFrame) -> BalanceQuery | None:
    """A query frame -> a ledger BalanceQuery, or None."""
    if frame.kind != "query" or frame.what != "balance":
        return None
    person = normalize_person(frame.who)
    if person is None:
        return None
    scope_giver = None
    for rel in frame.relationships:
        if rel.get("rel") == "scoped_from":
            scope_giver = normalize_person(rel.get("target"))
    return BalanceQuery(person=person, scope_amount=frame.quantity,
                        scope_giver=scope_giver)


def split_story_frames(frames: list[ConceptFrame],
                       allow_heuristic: bool = False
                       ) -> tuple[list[Transfer], BalanceQuery | None,
                                  list[ConceptFrame], bool]:
    """Split frames into (transfers, balance query, unusable, used_heuristic).

    ``unusable`` holds frames that could not become transfers (negated,
    incomplete, non-money) — reported, never silently dropped.
    """
    transfers, query, unusable = [], None, []
    used_heuristic = False
    for f in frames:
        if f.kind == "query" and f.what == "balance":
            query = frame_to_balance_query(f)
            if query is None:
                unusable.append(f)
            continue
        if f.kind == "query":
            continue  # yes/no goals are not ledger inputs
        t = frame_to_transfer(f, allow_heuristic=allow_heuristic)
        if t is None:
            unusable.append(f)
        else:
            transfers.append(t)
            if f.certainty == "uncertain":
                used_heuristic = True
    return transfers, query, unusable, used_heuristic


# ---------------------------------------------------------------------------
# Dictionary / encyclopedia <-> frames
# ---------------------------------------------------------------------------

def list_knowledge_entries(knowledge) -> list[tuple]:
    """All (kind, term, meaning, source) rows in a Knowledge store.

    The router scores them to find which term a question is asking
    about. Reads the store's own sqlite connection (the vendored
    Knowledge class exposes it as ``.db``); an unreadable store
    yields an empty list instead of an exception.
    """
    if knowledge is None:
        return []
    try:
        rows = knowledge.db.execute(
            "SELECT kind, term, meaning, source FROM entries").fetchall()
    except Exception:
        return []
    return [(k, t, m, s) for (k, t, m, s) in rows]


def knowledge_hit_to_frame(kind: str, term: str, hit: dict | None
                           ) -> ConceptFrame:
    """A Knowledge lookup result -> a definition frame (or an unknown one)."""
    if hit is None:
        return ConceptFrame(
            kind="definition", what="define", object=term,
            polarity="unknown", certainty="unknown", status="unknown",
            evidence=[ev("knowledge-store",
                         f"no {kind} entry for '{term}'", "lookup")])
    return ConceptFrame(
        kind="definition", what="define", object=term,
        why=hit["meaning"],
        polarity="positive", certainty="known", status="retrieved",
        relationships=[{"rel": "defined_as", "target": hit["meaning"]}],
        evidence=[ev(hit["source"], hit["meaning"], "retrieval")])


def frame_to_lookup(frame: ConceptFrame) -> tuple[str, str] | None:
    """A definition frame -> (kind, term) for the Knowledge store."""
    if frame.kind != "definition" or frame.object is None:
        return None
    return ("dictionary", frame.object)


# ---------------------------------------------------------------------------
# Calculator <-> frames
# ---------------------------------------------------------------------------

def frame_to_calculation(frame: ConceptFrame) -> ConceptFrame | None:
    """A calculation frame -> a verified result frame, or None.

    The expression lives in ``object`` (e.g. "15*120*8"). The safe AST
    evaluator from the adapter does the math; a rejected expression
    returns None instead of an invented number.
    """
    if frame.kind != "calculation" or frame.object is None:
        return None
    try:
        value = calculate(frame.object)
    except Exception:
        return None
    return ConceptFrame(
        kind="calculation", what="calculate", object=frame.object,
        quantity=value, units=None,
        polarity="positive", certainty="known", status="verified",
        source_text=frame.source_text,
        evidence=[ev("local-calculator", frame.object, "computation")])


# ---------------------------------------------------------------------------
# Symbolic reasoner <-> frames (propositional facts)
# ---------------------------------------------------------------------------

def _atom(text: str | None) -> str | None:
    """One fact argument: lowercase, spaces to underscores."""
    if text is None:
        return None
    return text.strip().lower().replace(" ", "_") or None


def _num(q) -> str:
    return str(int(q) if float(q).is_integer() else q)


def frame_to_fact(frame: ConceptFrame) -> str | None:
    """One frame -> one propositional fact string, or None.

    Positive frames become facts (``give(marcus,john,20)``). Negated
    frames become negated facts (``not give(john,sarah,10)``) — the
    negation is preserved, never flipped. A frame with certainty
    "unknown" becomes no fact at all.

    Money verbs are canonicalized: give/send/pay all become ``give``
    in the fact, because the ledger already treats them as the same
    money action — "A sent B $X" and "Did A give B $X?" must join up
    in the reasoner, not miss each other on the verb. Is-a, has-a, and
    state facts get their own predicates (``is``, ``has``, ``state``).

    Heuristic ("uncertain") frames DO become facts: a story sentence is
    a supplied premise, and the reasoner proves things *from premises*
    (the adapter's own rule). The supervisory reasoner downgrades the
    verdict status to ``candidate_interpretation`` when any heuristic
    premise contributed, so a proof from a guessed parse is never
    labeled verified logic.
    """
    if frame.what is None or frame.certainty == "unknown":
        return None
    if frame.kind not in ("transfer", "event", "fact"):
        return None
    who = _atom(frame.who)
    if not who:
        return None
    if frame.what == "receive":
        # "B received $X from A" is give(A, B, X). The giver rides in
        # the object slot as "from A" (heuristic tier). Without a
        # giver the frame cannot be canonicalized — no fact, never a
        # guessed one. A negated receive becomes "not give(A,B,X)",
        # which is what settles "Did B receive $X from A?" as "no".
        giver = None
        if frame.object:
            obj = frame.object.strip()
            if obj.lower().startswith("from "):
                giver = _atom(obj[5:])
        if giver is None or frame.quantity is None:
            return None
        args = [giver, who, _num(frame.quantity)]
        predicate = "give"
    elif frame.what in MONEY_ACTIONS:
        args = [who]
        if frame.recipient:
            args.append(_atom(frame.recipient))
        if frame.quantity is not None:
            args.append(_num(frame.quantity))
        predicate = "give"
    elif frame.what == "has":
        obj = _atom(frame.object)
        if obj is None or frame.quantity is None:
            return None
        args = [who, obj, _num(frame.quantity)]
        predicate = "has"
    elif frame.what in ("is", "state"):
        obj = _atom(frame.object)
        if obj is None:
            return None
        args = [who, obj]
        predicate = frame.what
    else:
        args = [who]
        if frame.recipient:
            args.append(_atom(frame.recipient))
        if frame.quantity is not None:
            args.append(_num(frame.quantity))
        elif frame.object:
            args.append(_atom(frame.object))
        predicate = frame.what
    fact = f"{predicate}({','.join(a for a in args if a)})"
    if frame.polarity == "negative":
        return f"not {fact}"
    if frame.polarity != "positive":
        return None
    return fact


def frames_to_facts(frames: list[ConceptFrame]
                    ) -> tuple[list[str], list[str], bool]:
    """Frames -> (facts, blocked, used_heuristic).

    ``facts`` are what the reasoner may use; ``blocked`` records why
    some frames contributed nothing (unknowns stay visible);
    ``used_heuristic`` is True when any fact came from a heuristic
    parse, so the verdict status can be downgraded honestly.
    """
    facts, blocked, used_heuristic = [], [], False
    for f in frames:
        # Rule frames are not facts and are never "blocked": the
        # reasoner instantiates them separately (_instantiate_rules).
        # Listing them as unusable would be noise in the proof.
        if f.kind == "rule":
            continue
        fact = frame_to_fact(f)
        if fact is None:
            blocked.append(
                f"{f.source_text or f.what}: no fact — "
                f"polarity={f.polarity}, certainty={f.certainty}, "
                f"missing={f.unknown_slots()}")
        else:
            facts.append(fact)
            if f.certainty == "uncertain":
                used_heuristic = True
    return facts, blocked, used_heuristic


def goal_frame_to_fact(frame: ConceptFrame) -> str | None:
    """A yes/no query frame -> the goal fact to prove, or None."""
    if frame.kind != "query":
        return None
    probe = ConceptFrame(**{**frame.to_dict(), "kind": "event",
                            "certainty": "known"})
    return frame_to_fact(probe)
