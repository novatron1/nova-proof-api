"""Pure translation between the checkpoints' JSON frames and the
shared ConceptFrame (stdlib only — no model needed).

The checkpoints' frame schema (identical in push1 and push2)::

    {"body": [[word, bool], ...], "head": [word, bool],
     "kind": "rule" | "fact", "subject": name | null}

``body`` is the list of conditions (predicate, polarity);
``head`` is the concluded predicate (predicate, polarity).
The mapping to ConceptFrame:

* fact  -> kind="fact", who=subject, what="is", object=head word,
  polarity=head polarity; body conditions become ``condition``
  relationships.
* rule  -> kind="rule", who=subject (usually null), what="is",
  object=first body word, polarity=first body polarity; the head
  becomes an ``implies`` relationship, the remaining body conditions
  become ``condition`` relationships.

The mapping is exactly invertible — ``concept_to_push_frame`` is its
inverse — which is what the fixture tests verify against the recorded
data (push1 ``test_novel.jsonl.gz``, 2000 rows; push2
``train_v4.jsonl.gz``).

``push1_rule_applies`` is the deterministic semantics of the push1
task, verified against the recorded gold answers 2000/2000: the rule
applies iff every body condition is asserted by the fact with the
same predicate and the same polarity.
"""

from __future__ import annotations

import json
import re

from ..semantic.frame import ConceptFrame, evidence as ev

_PROMPT_RE = re.compile(
    r"Rule: (\{.*?\})\nFact: (\{.*?\})\nDoes the rule apply\?",
    re.S)

_PROMPT_TEMPLATE = (
    "Read the rule and the fact, then answer the question.\n"
    "Answer with ONLY the word Yes or the word No.\n"
    "\n"
    "Rule: {rule}\n"
    "Fact: {fact}\n"
    "Does the rule apply?\n"
    "Answer:"
)


def push1_prompt(rule: dict, fact: dict) -> str:
    """Rebuild the exact push1 prompt for a rule/fact pair."""
    return _PROMPT_TEMPLATE.format(
        rule=json.dumps(rule, sort_keys=True),
        fact=json.dumps(fact, sort_keys=True))


def _condition_rels(frame: dict) -> list[dict]:
    return [{"rel": "condition", "target": word, "polarity": bool(pol)}
            for word, pol in frame.get("body", [])]


def push_frame_to_concept(frame: dict) -> ConceptFrame:
    """A checkpoint JSON frame -> a ConceptFrame. Pure, total on
    well-formed frames; raises KeyError/ValueError on malformed ones
    instead of inventing slots."""
    kind = frame["kind"]
    if kind not in ("fact", "rule"):
        # "unsupported" rows have head null and no frame to translate.
        raise ValueError(f"cannot translate frame kind {kind!r} "
                         f"(no head/body to map)")
    head_word, head_pol = frame["head"]
    body = frame.get("body", [])
    if kind == "fact":
        return ConceptFrame(
            kind="fact", who=frame.get("subject"), what="is",
            object=head_word,
            polarity="positive" if head_pol else "negative",
            certainty="known", status="verified",
            relationships=_condition_rels(frame),
            evidence=[ev("neural-fixture", json.dumps(frame,
                                                       sort_keys=True),
                          "recorded-frame")])
    if kind == "rule":
        first_word, first_pol = body[0] if body else (None, True)
        rels = [{"rel": "implies", "target": head_word,
                 "polarity": bool(head_pol)}]
        rels += [{"rel": "condition", "target": word,
                  "polarity": bool(pol)} for word, pol in body[1:]]
        return ConceptFrame(
            kind="rule", who=frame.get("subject"), what="is",
            object=first_word,
            polarity="positive" if first_pol else "negative",
            certainty="known", status="verified",
            relationships=rels,
            evidence=[ev("neural-fixture", json.dumps(frame,
                                                       sort_keys=True),
                          "recorded-frame")])
    raise ValueError(f"unknown frame kind: {kind!r}")


def concept_to_push_frame(frame: ConceptFrame) -> dict:
    """A ConceptFrame -> a checkpoint JSON frame. The inverse of
    ``push_frame_to_concept`` (verified by round-trip on the recorded
    data)."""
    if frame.kind == "fact":
        return {
            "body": [[r["target"], bool(r.get("polarity", True))]
                     for r in frame.relationships
                     if r.get("rel") == "condition"],
            "head": [frame.object, frame.polarity == "positive"],
            "kind": "fact",
            "subject": frame.who,
        }
    if frame.kind == "rule":
        implies = next((r for r in frame.relationships
                        if r.get("rel") == "implies"), None)
        if implies is None or frame.object is None:
            raise ValueError("rule frame without implies/object")
        body = [[frame.object, frame.polarity == "positive"]]
        body += [[r["target"], bool(r.get("polarity", True))]
                 for r in frame.relationships
                 if r.get("rel") == "condition"]
        return {
            "body": body,
            "head": [implies["target"],
                     bool(implies.get("polarity", True))],
            "kind": "rule",
            "subject": frame.who,
        }
    raise ValueError(f"cannot translate kind {frame.kind!r} to a "
                     f"checkpoint frame")


def push1_input_to_frames(prompt: str
                          ) -> tuple[ConceptFrame, ConceptFrame]:
    """Parse a recorded push1 prompt into (rule frame, fact frame).

    Raises ValueError when the prompt does not match the recorded
    format — a malformed prompt is never silently reinterpreted.
    """
    m = _PROMPT_RE.search(prompt)
    if not m:
        raise ValueError("prompt does not match the push1 rule/fact "
                         "format")
    rule = push_frame_to_concept(json.loads(m.group(1)))
    fact = push_frame_to_concept(json.loads(m.group(2)))
    return rule, fact


def _rule_conditions(rule: ConceptFrame) -> list[tuple[str, bool]]:
    conds = []
    if rule.object is not None:
        conds.append((rule.object, rule.polarity == "positive"))
    conds += [(r["target"], bool(r.get("polarity", True)))
              for r in rule.relationships
              if r.get("rel") == "condition"]
    return conds


def _fact_assertions(fact: ConceptFrame) -> set[tuple[str, bool]]:
    asserted = set()
    if fact.object is not None:
        asserted.add((fact.object, fact.polarity == "positive"))
    asserted |= {(r["target"], bool(r.get("polarity", True)))
                 for r in fact.relationships
                 if r.get("rel") == "condition"}
    return asserted


def push1_rule_applies(rule: ConceptFrame, fact: ConceptFrame) -> str:
    """Does the rule apply to the fact? "yes" iff every body
    condition is asserted by the fact with the same predicate and
    polarity. Verified 2000/2000 against the recorded push1 gold
    answers — this is the deterministic semantics of the task, not a
    guess."""
    if rule.kind != "rule" or fact.kind != "fact":
        raise ValueError("push1_rule_applies needs (rule, fact) frames")
    asserted = _fact_assertions(fact)
    for pred, pol in _rule_conditions(rule):
        if (pred, pol) not in asserted:
            return "no"
    return "yes"


def push1_answer_to_verdict(text: str) -> str:
    """A model "Yes"/"No" output -> a verdict. Anything else is
    "unknown" — a malformed model output is never read as an answer."""
    t = (text or "").strip().lower()
    if t == "yes":
        return "yes"
    if t == "no":
        return "no"
    return "unknown"
