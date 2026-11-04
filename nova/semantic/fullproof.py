"""Full-proof handoff — merged from NOVA Cognitive Adapter v1.2
(2026-11-02). See MERGE_MAP.md (c)+(e).

This is the production-facing handoff path. It differs from the
recorded experiment arms in ``handoff.py`` in exactly the ways v1.2
differs, and those arm prompts are deliberately NOT changed here —
they are frozen instruments for recorded runs:

1. TAINT RULE: the model receives the original question verbatim,
   first and intact, before any NOVA material. NOVA's senses, graph,
   coverage and proof are an ADDITION alongside the question, never
   a replacement, redaction, summary or rewrite of it.
2. AUTHORITY: a NOVA unknown / UNSUPPORTED state means NOVA lacks a
   proof. It is NOT a verdict that the question is unanswerable, and
   this prompt never instructs the model to abstain because of it —
   the model keeps its own knowledge (the failure mode behind the
   tainted legs, where the model 'failed' questions it never
   cleanly received).
3. MODES: ``concepts`` withholds the verified answer AND the proof
   AND the per-reading answers (no leak, as in v1.2); ``full``
   includes the verified answer and proof for the model to check
   against the question.

No model is called in this module (same contract as handoff.py).
"""

from __future__ import annotations

from .handoff import (_section_graph, _section_lexical,
                      _section_reasoning, _section_verified_answer)

HEADER = (
    "Answer the original question below in your own words. NOVA, a "
    "concept-reasoning system, analysed it and its notes follow the "
    "question. NOVA is an optional assistant, not an authority over "
    "your knowledge: an unknown or unsupported NOVA state means "
    "NOVA lacks a proof — it does NOT mean the answer is "
    "unknowable. Use the valid definitions and relations, ignore "
    "irrelevant senses, preserve negation. If a verified answer is "
    "given, check it against the question before using it. Judge "
    "answerability from the question itself, never from NOVA's "
    "notes: if every fact the answer depends on is stated in the "
    "question, follows from what it states, or is general "
    "knowledge, answer it — even when NOVA has no proof. Say the "
    "answer cannot be determined only when a fact the answer "
    "depends on is missing from the question itself and is not "
    "general knowledge: the question asks about an amount, an "
    "event, or a detail it never gives. One further case is the "
    "question's own ambiguity, not NOVA's limit: when NOVA's notes "
    "say the amount the question scopes to matches more than one "
    "transfer, or the same transfer is described with conflicting "
    "values, the question itself does not pick one — also say the "
    "answer cannot be determined, and do not combine the "
    "conflicting transfers into a single total. Never invent "
    "missing facts."
)

ANSWER_INSTRUCTION = (
    "Put your final answer alone on the first line: a number, yes, "
    "no, a short definition, or \"I don't know\". Say \"I don't "
    "know\" only when the question itself lacks a fact the answer "
    "depends on and general knowledge does not supply it, or when "
    "NOVA's notes state the question's own scope is ambiguous "
    "(the scoped amount matches more than one transfer) — never "
    "merely because NOVA could not determine it. You may add at "
    "most one short sentence after it."
)


def _section_sense_graph(package: dict) -> str:
    graph = package.get("sense_graph") or {}
    lines = ["Word senses and their relationships "
             "(synonym and antonym are different relations):"]
    edges = graph.get("edges") or []
    if not edges:
        lines.append("- (no sense graph could be built)")
    labels = {n["id"]: n["label"] for n in graph.get("nodes", [])}
    for e in edges[:20]:
        lines.append(
            f"- {labels.get(e['from'], e['from'])} "
            f"--{e['relation']}--> {labels.get(e['to'], e['to'])}")
    return "\n".join(lines)


def _section_coverage(package: dict) -> str:
    cov = package.get("coverage") or {}
    lines = ["What NOVA's parser covered:"]
    lines.append(
        f"- {cov.get('frames_n', 0)} frames from "
        f"{cov.get('sentences_n', 0)} sentences")
    unparsed = cov.get("unparsed_sentences") or []
    if unparsed:
        lines.append("- Sentences NOVA could not parse (read them "
                     "from the original question yourself):")
        lines.extend(f"  - {s}" for s in unparsed)
    if cov.get("duplicate_scope_ambiguity"):
        lines.append("- WARNING: the scoped amount matches more "
                     "than one identical incoming transfer; which "
                     "one the question means is ambiguous.")
    if cov.get("missing"):
        lines.append("- NOVA could not determine: "
                     + "; ".join(str(m) for m in cov["missing"][:2]))
    return "\n".join(lines)


def build_fullproof_prompt(package: dict, mode: str = "full") -> str:
    """The taint-safe prompt. ``package`` comes from
    ``handoff.build_explanation_package``. The original question is
    the first substantive block, byte-identical, always."""
    if mode not in ("full", "concepts"):
        raise ValueError(f"unknown fullproof mode: {mode}")
    parts = [
        HEADER,
        "Original question (verbatim):\n" + package["question"],
        _section_lexical(package),
        _section_sense_graph(package),
        _section_coverage(package),
    ]
    if mode == "full":
        parts.append(_section_graph(package))
        parts.append(_section_reasoning(package))
        parts.append(_section_verified_answer(package))
    parts.append(ANSWER_INSTRUCTION)
    return "\n\n".join(parts)
