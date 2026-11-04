"""Round-trip concept preservation: NL -> frames -> NL -> frames.

Measures semantic information loss. For each sentence: parse to frames,
render the frames back to text, re-parse, and compare. Loss types:

* ``lost_slot`` — a slot known in the first parse is None in the second.
* ``invented_slot`` — a slot None in the first parse has a value in the
  second (the renderer invented something the parse never knew).
* ``polarity_flip`` — polarity differs between the two parses.
* ``negation_lost`` — the first frame was negated, the second is not.
* ``frame_lost`` — a frame from the first parse has no counterpart in
  the second (different frame count).

Metric: slot preservation rate = preserved known slots / known slots
in the first parse. A rate of 1.0 means the round trip is lossless for
the slots the first parse knew; anything below it names the loss.
"""

from __future__ import annotations

from .extract import parse_text_to_frames
from .frame import ConceptFrame
from .render import render_frame_sentence

SLOTS = ("who", "what", "recipient", "object", "quantity", "units",
         "when", "where", "why", "how")


def _frame_loss(first: ConceptFrame, second: ConceptFrame) -> dict:
    """Loss between two aligned frames, by type."""
    lost, invented = [], []
    for slot in SLOTS:
        a, b = getattr(first, slot), getattr(second, slot)
        if a is not None and b is None:
            lost.append(slot)
        elif a is None and b is not None:
            invented.append(slot)
        elif a is not None and b is not None and str(a) != str(b):
            # Same slot, different value: counts as both a loss and an
            # invention (the original value did not survive).
            lost.append(slot)
            invented.append(slot)
    polarity_flip = first.polarity != second.polarity
    negation_lost = (first.polarity == "negative"
                     and second.polarity != "negative")
    return {"lost": lost, "invented": invented,
            "polarity_flip": polarity_flip,
            "negation_lost": negation_lost}


def roundtrip_sentence(sentence: str) -> dict:
    """Parse -> render -> re-parse one sentence; return the loss record."""
    first = parse_text_to_frames(sentence)
    rendered = " ".join(render_frame_sentence(f) for f in first)
    second = parse_text_to_frames(rendered)
    record: dict = {"sentence": sentence, "rendered": rendered,
                    "frames_first": len(first), "frames_second": len(second),
                    "known_slots": 0, "preserved_slots": 0,
                    "lost_slots": [], "invented_slots": [],
                    "polarity_flips": 0, "negation_lost": 0,
                    "frames_lost": 0}
    for i, f1 in enumerate(first):
        record["known_slots"] += len(f1.known_slots())
        if i >= len(second):
            record["frames_lost"] += 1
            record["lost_slots"].extend(f1.known_slots())
            continue
        loss = _frame_loss(f1, second[i])
        record["lost_slots"].extend(loss["lost"])
        record["invented_slots"].extend(loss["invented"])
        record["polarity_flips"] += int(loss["polarity_flip"])
        record["negation_lost"] += int(loss["negation_lost"])
        record["preserved_slots"] += (len(f1.known_slots())
                                      - len(loss["lost"]))
    return record


def roundtrip_loss(sentences: list[str]) -> dict:
    """Aggregate loss over a list of sentences."""
    records = [roundtrip_sentence(s) for s in sentences]
    known = sum(r["known_slots"] for r in records)
    preserved = sum(r["preserved_slots"] for r in records)
    return {
        "n_sentences": len(sentences),
        "known_slots": known,
        "preserved_slots": preserved,
        "preservation_rate": (preserved / known) if known else 1.0,
        "lost_slots": [s for r in records for s in r["lost_slots"]],
        "invented_slots": [s for r in records for s in r["invented_slots"]],
        "polarity_flips": sum(r["polarity_flips"] for r in records),
        "negation_lost": sum(r["negation_lost"] for r in records),
        "frames_lost": sum(r["frames_lost"] for r in records),
        "records": records,
    }
