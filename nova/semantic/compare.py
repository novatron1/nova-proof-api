"""Semantic comparison over shared ConceptFrames.

The vendored adapter's ``compare_frames`` works on its own heuristic
concepts, where a negated sentence misidentifies the actor ("John did
not buy a bike" -> actor "not"), so opposite-polarity pairs come back
"undetermined". This module compares the semantic layer's frames —
where the actor is corrected and the polarity is a first-class field.

**Certification bar.** A comparison is ``certified`` only when the
conclusion follows from deterministic parses, not heuristic guesses:
both frames must have status ``verified`` (deterministic tier) AND
identical normalized signatures. For ``candidate_equivalent`` the
polarities must also match; for ``possible_contradiction`` they must
differ. ``undetermined`` and ``unknown`` are never certified — there
is nothing to certify. The bar is a stated decision, recorded here
and in the tests; it is not tuned to any run after the fact.
"""

from __future__ import annotations

from .extract import parse_text_to_frames
from .frame import ConceptFrame


def _signature(frame: ConceptFrame) -> tuple:
    return (frame.who, frame.what, frame.recipient, frame.object,
            frame.quantity, frame.units)


def _certified(a: ConceptFrame, b: ConceptFrame) -> bool:
    """The certification bar: both frames deterministic (status
    ``verified``) with identical normalized signatures. A heuristic
    parse can suggest a relation but never certifies one."""
    return (a.status == "verified" and b.status == "verified"
            and _signature(a) == _signature(b))


def compare_concept_frames(a: ConceptFrame, b: ConceptFrame) -> dict:
    """Compare two frames. Certified only under the bar in the module
    docstring; anything else is a candidate, not a semantic proof."""
    if a.what is None or b.what is None:
        return {"relation": "unknown", "certified": False,
                "reason": "missing event parse"}
    if _signature(a) == _signature(b) and a.polarity != b.polarity:
        return {"relation": "possible_contradiction",
                "certified": _certified(a, b),
                "reason": "matching normalized event with opposite "
                          "polarity"
                          + (" (both parses deterministic)"
                             if _certified(a, b) else "")}
    if _signature(a) == _signature(b) and a.polarity == b.polarity:
        return {"relation": "candidate_equivalent",
                "certified": _certified(a, b),
                "reason": "normalized event and polarity match; time, "
                          "reference, and context may differ"
                          + (" (both parses deterministic)"
                             if _certified(a, b) else "")}
    return {"relation": "undetermined", "certified": False,
            "reason": "no safe equivalence or contradiction conclusion"}


def compare_texts(a: str, b: str) -> dict:
    """Compare two sentences via their first frames."""
    fa = parse_text_to_frames(a)
    fb = parse_text_to_frames(b)
    if not fa or not fb:
        return {"relation": "unknown", "certified": False,
                "reason": "missing event parse"}
    return compare_concept_frames(fa[0], fb[0])
