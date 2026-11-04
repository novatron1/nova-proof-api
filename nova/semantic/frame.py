"""The one shared Concept/Event schema for all of NOVA.

Every module — money engine, dictionary, encyclopedia, calculator, memory,
symbolic reasoner, language brain — reads and writes this single format.
That is the whole point of the integration: one universal cognitive
language, not a collection of tools that cannot understand one another.

Design rules (the user's engineering rule, enforced here):

* Unknown slots are explicit ``None``. A missing fact is never invented,
  never defaulted, never guessed from context.
* Negation, uncertainty, and unknown information are first-class fields
  (``polarity``, ``certainty``), not dropped in translation.
* Every frame carries its ``evidence`` and its ``source_text`` so any
  conclusion can be traced back to where it came from.
* The dict form is the wire form (JSON over the API). The dataclass is the
  in-process form. They round-trip exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..adapter.language import normalize as _normalize_token

# ---------------------------------------------------------------------------
# Vocabularies (closed where honesty depends on them)
# ---------------------------------------------------------------------------

KINDS = ("transfer", "event", "query", "fact", "definition", "calculation")
POLARITIES = ("positive", "negative", "unknown")
CERTAINTIES = ("known", "uncertain", "unknown")
STATUSES = ("verified", "candidate_interpretation", "partial_interpretation",
            "unknown", "retrieved")

# Normalized actions that move money. Only these may become ledger transfers.
MONEY_ACTIONS = ("give", "send", "pay")
MONEY_UNITS = ("dollars", "bucks", "money")


@dataclass
class ConceptFrame:
    """One concept/event, in the single format every module shares.

    WHO / WHAT / WHEN / WHERE / WHY / HOW are the 5W1H slots. ``recipient``,
    ``object``, ``quantity`` and ``units`` are the structured payload that
    v0.3 left trapped inside a text field (e.g. "his sister $50" is now
    recipient="Sister", quantity=50, units="dollars" — structured, so a
    balance question can be answered from it).
    """

    kind: str = "event"                 # transfer|event|query|fact|definition|calculation
    who: str | None = None              # actor / subject
    what: str | None = None             # normalized action/verb
    recipient: str | None = None        # who the action is done to/for
    object: str | None = None           # thing acted on ("bicycle", "dollars")
    quantity: float | int | None = None
    units: str | None = None            # "dollars", "items", ...
    when: str | None = None
    where: str | None = None
    why: str | None = None
    how: str | None = None
    polarity: str = "positive"          # positive|negative|unknown
    certainty: str = "uncertain"        # known|uncertain|unknown
    relationships: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    source_text: str | None = None
    status: str = "candidate_interpretation"

    # -- serialization: the dict form is the wire form --------------------
    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "who": self.who,
            "what": self.what,
            "recipient": self.recipient,
            "object": self.object,
            "quantity": self.quantity,
            "units": self.units,
            "when": self.when,
            "where": self.where,
            "why": self.why,
            "how": self.how,
            "polarity": self.polarity,
            "certainty": self.certainty,
            "relationships": [dict(r) for r in self.relationships],
            "evidence": [dict(e) for e in self.evidence],
            "source_text": self.source_text,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptFrame":
        known = {k: v for k, v in d.items()
                 if k in cls.__dataclass_fields__}
        return cls(**known)

    # -- convenience -------------------------------------------------------
    def known_slots(self) -> list[str]:
        slots = ("who", "what", "recipient", "object", "quantity", "units",
                 "when", "where", "why", "how")
        return [s for s in slots if getattr(self, s) is not None]

    def unknown_slots(self) -> list[str]:
        slots = ("who", "what", "recipient", "object", "quantity", "units",
                 "when", "where", "why", "how")
        return [s for s in slots if getattr(self, s) is None]

    def is_negated(self) -> bool:
        return self.polarity == "negative"

    def is_complete_for_transfer(self) -> bool:
        return (self.what in MONEY_ACTIONS and self.who is not None
                and self.recipient is not None and self.quantity is not None
                and self.units in MONEY_UNITS)


def evidence(source: str, statement: str, kind: str) -> dict:
    """One evidence record, same shape as the adapter's Evidence dataclass."""
    return {"source": source, "statement": statement, "kind": kind}


def normalize_person(name: str | None) -> str | None:
    """One canonical key per person, both sides of a transfer/query.

    Strips possessives/determiners, applies the adapter's synonym map
    ("kid" -> "child"), and title-cases: "his sister" and "sister" both
    become "Sister", and "the kid" and "the child" both become "Child",
    so synonyms join up in the ledger and in the reasoner.
    """
    if name is None:
        return None
    words = [w for w in re.split(r"\s+", name.strip(" .!?"))
             if w.lower() not in
             ("his", "her", "their", "the", "a", "an", "my", "your")]
    if not words:
        return None
    words = [_normalize_token(w.lower()) for w in words]
    return " ".join(w[:1].upper() + w[1:] for w in words)
