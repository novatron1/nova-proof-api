"""Natural-language rendering: frames + proof -> an answer in words.

The final answer is GENERATED FROM THE FRAME AND THE PROOF by templates,
never from a free-form model guess. A slot that is None is rendered as
unknown or omitted — never filled in. If a model is configured, its
output is returned separately as ``unverified_model_output`` and is never
the answer.
"""

from __future__ import annotations

from .frame import ConceptFrame


def _money(n) -> str:
    if n is None:
        return "an unknown amount"
    v = float(n)
    return f"${int(v)}" if v.is_integer() else f"${v:g}"


def _quantity_text(frame: ConceptFrame) -> str | None:
    """A quantity rendered in its own units — never as dollars when the
    units are not money ("Nina bought 3 bicycles" must not come back
    as "$3"). Returns None when the frame has no quantity."""
    if frame.quantity is None:
        return None
    if frame.units in ("dollars", "bucks", "money"):
        return _money(frame.quantity)
    if frame.units:
        v = float(frame.quantity)
        return f"{int(v) if v.is_integer() else v:g} {frame.units}"
    v = float(frame.quantity)
    return f"{int(v) if v.is_integer() else v:g}"


def render_frame_sentence(frame: ConceptFrame) -> str:
    """One frame back into a plain sentence, using only its known slots.

    Round-trip rule: the rendered sentence must re-parse to the same
    frame. That constrains the wording: ``when`` is rendered bare (the
    old "(yesterday)" parentheses leaked into the re-parsed recipient/
    object tail), ``how`` is rendered ("by {how}" — it was dropped
    entirely), and a quantity keeps its units instead of defaulting
    to dollars. Fact forms get their own wording, because the generic
    "{who} {what} {object}" shape does not re-parse for them: a state
    renders as an "is" sentence, a has-a as "X has N <part>", a rule
    as its "If ... they ..." form, and a negated ability as "cannot".
    """
    if frame.kind == "query" and frame.what == "balance":
        scope = (f" from the {_money(frame.quantity)}"
                 if frame.quantity is not None else "")
        return f"How much money does {frame.who or 'someone'} have{scope}?"
    who = frame.who or "Someone"
    if frame.kind == "rule":
        # "If someone is human, they are mortal." — the only wording
        # the rule parser reads. The consequent comes from the
        # "implies" relationship; without it the rule cannot be
        # rendered and the generic form is used instead.
        implies = next((r.get("target") for r in frame.relationships
                        if r.get("rel") == "implies"), None)
        if frame.object is not None and implies is not None:
            return (f"If someone is {frame.object}, "
                    f"they are {implies}.")
    if frame.what == "state":
        # "The light is on." — an "is" sentence, which the fact tier
        # reads back as a state frame.
        if frame.polarity == "negative":
            return f"{who} is not {frame.object or 'something'}."
        return f"{who} is {frame.object or 'something'}."
    if frame.what == "has" and frame.quantity is not None:
        # "A spider has 8 legs." — the has-a form, with its article.
        return f"A {who} has {_quantity_text(frame)}."
    parts = []
    what = frame.what or "did something"
    if frame.polarity == "negative":
        # A negated ability ("cannot fly") renders as "cannot": the
        # generic "did not fly" does not re-parse for verbs the
        # heuristic tier does not know. Negated money actions keep
        # "did not", which the money parser reads back.
        if frame.kind == "fact":
            parts.append(f"{who} cannot {what}")
        else:
            parts.append(f"{who} did not {what}")
    else:
        parts.append(f"{who} {what}")
    if frame.recipient:
        parts[-1] += f" {frame.recipient}"
    qty = _quantity_text(frame)
    obj = frame.object
    if obj and obj.lower().startswith("from "):
        # "Omar received $40 from Lena": the giver phrase goes after
        # the amount, as in the original sentence.
        if qty is not None:
            parts[-1] += f" {qty}"
        parts[-1] += f" {obj}"
    elif obj and qty is not None and obj.lower() not in qty.lower() \
            and obj.lower() not in ("dollars", "bucks", "money"):
        # "Yusuf purchase bicycle for $120": the object and the price
        # are both real slots — dropping either loses meaning. (When
        # the quantity text already contains the object, as in "3
        # bicycles", the quantity alone carries both.)
        parts[-1] += f" {obj} for {qty}"
    elif qty is not None:
        parts[-1] += f" {qty}"
    elif obj:
        parts[-1] += f" {obj}"
    if frame.when:
        parts.append(frame.when)
    if frame.where:
        parts.append(f"at {frame.where}")
    if frame.why:
        parts.append(f"because {frame.why}")
    if frame.how:
        parts.append(f"by {frame.how}")
    return " ".join(parts) + "."


def render_balance_answer(query: ConceptFrame, answer,
                          proof: list[str]) -> str:
    """The NL answer for a balance question, from the query frame + proof."""
    person = query.who or "the person"
    scope = ""
    if query.quantity is not None:
        scope = f" from the {_money(query.quantity)}"
        for rel in query.relationships:
            if rel.get("rel") == "scoped_from" and rel.get("target"):
                scope += f" {rel['target']} gave {person}"
                break
    lines = [f"{person} has {_money(answer)} left{scope}."
             if scope else f"{person} has {_money(answer)}."]
    lines.append("Proof:")
    for step in proof:
        lines.append(f"  - {step}")
    return "\n".join(lines)


def render_per_unit_answer(query: ConceptFrame, answer,
                           proof: list[str]) -> str:
    """The NL answer for a per-unit-total question, from the query
    frame + proof. An undetermined answer renders as unknown, never
    as a guessed number."""
    thing = None
    for rel in query.relationships:
        if rel.get("rel") == "per_unit_of":
            thing = rel.get("target")
    if answer is None:
        lines = ["I don't know — no per-unit fact was found for "
                 f"{thing or 'that'}.", "Proof:"]
    else:
        lines = [f"{query.quantity:g} {thing} have "
                 f"{answer:g} {query.object}.", "Proof:"]
    for step in proof:
        lines.append(f"  - {step}")
    return "\n".join(lines)


def render_amount_paid_answer(query: ConceptFrame, answer,
                              proof: list[str]) -> str:
    """The NL answer for an amount-paid question."""
    person = query.who or "the person"
    if answer is None:
        lines = [f"I don't know — no single payment by {person} is in "
                 "the story.", "Proof:"]
    else:
        lines = [f"{person} paid {_money(answer)}.", "Proof:"]
    for step in proof:
        lines.append(f"  - {step}")
    return "\n".join(lines)


def render_verdict_answer(verdict: str, goal: str, proof: list[str],
                          missing: list[str]) -> str:
    """The NL answer for a yes/no goal, from the verdict + proof trace."""
    if verdict == "yes":
        lines = ["Yes."]
    elif verdict == "no":
        lines = ["No."]
    elif verdict == "both":
        lines = ["Both — the evidence supports the statement and its "
                 "negation. The premises contradict each other."]
    else:
        lines = ["I don't know — the frames do not settle this."]
    lines.append(f"Goal: {goal}")
    if proof:
        lines.append("Proof:")
        for step in proof:
            lines.append(f"  - {step}")
    if missing:
        lines.append("Missing / unusable:")
        for m in missing:
            lines.append(f"  - {m}")
    return "\n".join(lines)


def render_analysis(frames: list[ConceptFrame]) -> str:
    """No question was asked: report what was understood, slot by slot."""
    lines = ["Understood frames:"]
    for f in frames:
        lines.append(f"  - {render_frame_sentence(f)} "
                     f"[{f.status}; unknown: "
                     f"{', '.join(f.unknown_slots()) or 'none'}]")
    return "\n".join(lines)
