"""The integrated pipeline: text -> frames -> reasoning -> words.

One entry point for the whole system. Deterministic paths work with
``model=None``; a model is an optional callable, exactly as in the
adapter, and its output is never the answer — it is returned separately
as ``unverified_model_output``.

Flow:
    natural language
      -> parse_text_to_frames (deterministic money parser, then
         heuristic 5W1H with structured quantity recovery)
      -> SupervisoryReasoner (ledger for balance questions, four-valued
         propositional reasoner for yes/no goals)
      -> render (templates from frame + proof -> natural language)

Every step keeps the shared ConceptFrame format, and every result keeps
the adapter's honest statuses.
"""

from __future__ import annotations

from ..model_interface import coerce_model
from ..adapter.core import Knowledge, NovaAdapter
from .extract import find_query, parse_text_to_frames
from .frame import ConceptFrame
from .memory import FrameMemory
from .reason import SupervisoryReasoner
from .render import (render_amount_paid_answer, render_analysis,
                     render_balance_answer, render_per_unit_answer,
                     render_verdict_answer)
from .translate import goal_frame_to_fact


def answer_text(text: str, model=None, knowledge: Knowledge | None = None,
                memory: FrameMemory | None = None,
                rules: list | None = None,
                ablations: set | None = None,
                advisor_template: str | None = None) -> dict:
    """Answer a question (or analyse a statement) through the full system.

    Returns the shared envelope::

        {status, verdict, answer, answer_text, frames, proof,
         complete, evidence, missing, unusable_frames,
         model_output?}

    ``ablations`` (eval-harness use, default none): a set drawn from
    ``{"heuristic", "reasoner", "memory"}``. ``"heuristic"`` disables
    the tier-2 5W1H extractor (deterministic tier only); ``"reasoner"``
    disables the propositional yes/no path; ``"memory"`` skips frame
    memory. "calculator" and "dictionary" ablations apply to the
    ``process_request`` task passthrough, not here. Default behaviour
    is unchanged.

    ``advisor_template`` (eval-harness use, default none): when set,
    the model advisor receives ``advisor_template.format(text=text)``
    instead of the raw text — the same prompt the alone arm gets, so
    the comparison is a same-prompt ablation. When None (the API
    default) the advisor receives the raw text, as before. The
    pipeline's answer never comes from the advisor either way.
    """
    ablations = ablations or set()
    frames = parse_text_to_frames(
        text, allow_heuristic="heuristic" not in ablations,
        knowledge=knowledge)
    if not frames:
        return {
            "status": "unknown", "verdict": "unknown", "answer": None,
            "answer_text": "I could not parse that into concept frames.",
            "frames": [], "proof": [], "complete": False,
            "evidence": [],
            "missing": ["no sentence matched any parser tier"],
            "unusable_frames": [],
        }
    if memory is not None and "memory" not in ablations:
        memory.remember_all(frames)

    reasoner = SupervisoryReasoner(knowledge=knowledge)
    result = reasoner.reason(frames, rules=rules, ablations=ablations)
    query = find_query(frames)

    if query is not None and query.what == "per_unit_total":
        answer_text_out = render_per_unit_answer(
            query, result["answer"], result["proof"])
    elif query is not None and query.what == "amount_paid":
        answer_text_out = render_amount_paid_answer(
            query, result["answer"], result["proof"])
    elif query is not None and query.what == "balance" and any(
            r.get("rel") == "asks_whether"
            for r in query.relationships):
        # Balance yes/no ("Does X have $N?"): a verdict answer, not
        # a balance amount.
        answer_text_out = render_verdict_answer(
            result["verdict"], query.source_text or "?",
            result["proof"], result["missing"])
    elif query is not None and query.what == "balance":
        answer_text_out = render_balance_answer(
            query, result["answer"], result["proof"])
    elif query is not None and any(
            r.get("rel") == "asks_whether"
            for r in query.relationships):
        answer_text_out = render_verdict_answer(
            result["verdict"],
            goal_frame_to_fact(query) or query.source_text or "?",
            result["proof"], result["missing"])
    elif result["verdict"] == "unknown" and not result["complete"]:
        answer_text_out = render_analysis(frames)
    else:
        answer_text_out = render_verdict_answer(
            result["verdict"], "?", result["proof"], result["missing"])

    envelope = {
        "status": result["status"],
        "verdict": result["verdict"],
        "answer": result["answer"],
        "answer_text": answer_text_out,
        "frames": [f.to_dict() for f in frames],
        "proof": result["proof"],
        "complete": result["complete"],
        "evidence": result["evidence"],
        "missing": result["missing"],
        "unusable_frames": result["unusable_frames"],
    }

    if model is not None:
        # The model is an optional advisor. Its words are labeled
        # unverified and are never substituted for the proven answer.
        # ``model`` may be a LanguageModel, a plain callable, or None;
        # coerce_model normalizes it (a bad model type is a caller
        # error and is reported, not swallowed). With advisor_template
        # set (eval harness), the advisor gets the templated prompt;
        # otherwise it gets the raw text, as before.
        try:
            lm = coerce_model(model)
            advisor_prompt = (advisor_template.format(text=text)
                              if advisor_template else text)
            response = lm.complete(advisor_prompt)
            envelope["model_output"] = {
                "status": "unverified_model_output",
                "text": response.text, "model_id": response.model_id}
        except Exception as e:  # noqa: BLE001 - report, don't crash
            envelope["model_output"] = {
                "status": "unverified_model_output",
                "text": None, "error": str(e)}
    return envelope


def process_request(request: dict, model=None,
                    knowledge: Knowledge | None = None,
                    ablations: set | None = None,
                    advisor_template: str | None = None) -> dict:
    """The /concept endpoint's dispatcher, mirroring the adapter's
    ``NovaAdapter.process`` request/response shape.

    Accepted requests:
      {"text": "..."}            natural language in
      {"question": "..."}        alias for text
      {"frames": [{...}, ...]}   structured frames in (external LMs)
      {"task": "calculate"|"dictionary"|"encyclopedia"|"prove"|...}
                                 passthrough to the vendored adapter

    ``ablations`` (eval-harness use, default none): ``{"calculator"}``
    disables the calculate task, ``{"dictionary"}`` disables the
    dictionary/encyclopedia tasks, ``{"heuristic", "reasoner",
    "memory"}`` are forwarded to ``answer_text`` / the reasoner.
    An ablated module returns an honest ``unknown`` envelope, never a
    fabricated answer.

    ``advisor_template`` is forwarded to ``answer_text`` for the
    text branch (see there); the frames and task branches never
    call the model as advisor.
    """
    ablations = ablations or set()
    if "frames" in request:
        try:
            frames = [ConceptFrame.from_dict(f)
                      for f in request["frames"]]
        except Exception as e:  # noqa: BLE001 - honest 422 upstream
            raise ValueError(f"invalid frames: {e}") from e
        if not frames:
            raise ValueError("empty frames list")
        reasoner = SupervisoryReasoner(knowledge=knowledge)
        result = reasoner.reason(frames, goal=request.get("goal"),
                                 rules=request.get("rules"),
                                 ablations=ablations)
        query = find_query(frames)
        if query is not None and query.what == "per_unit_total":
            text_out = render_per_unit_answer(
                query, result["answer"], result["proof"])
        elif query is not None and query.what == "amount_paid":
            text_out = render_amount_paid_answer(
                query, result["answer"], result["proof"])
        elif query is not None and query.what == "balance" and not any(
                r.get("rel") == "asks_whether"
                for r in query.relationships):
            text_out = render_balance_answer(
                query, result["answer"], result["proof"])
        elif result["verdict"] == "unknown" and not result["complete"]:
            text_out = render_analysis(frames)
        else:
            goal = (query.source_text if query is not None else None)
            text_out = render_verdict_answer(
                result["verdict"],
                goal or request.get("goal") or "?", result["proof"],
                result["missing"])
        return {
            "status": result["status"], "verdict": result["verdict"],
            "answer": result["answer"], "answer_text": text_out,
            "frames": [f.to_dict() for f in frames],
            "proof": result["proof"], "complete": result["complete"],
            "evidence": result["evidence"], "missing": result["missing"],
            "unusable_frames": result["unusable_frames"],
        }
    text = request.get("text") or request.get("question")
    if isinstance(text, str) and text.strip():
        result = answer_text(text, model=model, knowledge=knowledge,
                             rules=request.get("rules"),
                             ablations=ablations,
                             advisor_template=advisor_template)
        if not result["frames"]:
            # Nothing parsed into frames at all: honest failure, not a
            # 200 with an empty answer. Matches /reason's 422 contract.
            raise ValueError("no sentence matched any parser tier")
        return result
    if "task" in request:
        task = request["task"]
        if task == "calculate" and "calculator" in ablations:
            return {"status": "unknown", "answer": None, "evidence": [],
                    "missing": ["calculator disabled by ablation"]}
        if task in ("dictionary", "encyclopedia") and \
                "dictionary" in ablations:
            return {"status": "unknown", "answer": None, "evidence": [],
                    "missing": ["knowledge store disabled by ablation"]}
        # Passthrough to the vendored adapter (calculator, dictionary,
        # encyclopedia, prove, analyze, concept_frame, ...). The shared
        # envelope is preserved; the adapter's own statuses are kept.
        # The vendored adapter calls the model as a plain callable, so
        # a LanguageModel is wrapped — the vendored file is untouched.
        lm = coerce_model(model)
        adapter_model = (None if lm is None else
                         (lambda prompt, _lm=lm:
                          _lm.complete(prompt).text))
        adapter = NovaAdapter(model=adapter_model,
                              knowledge=knowledge or Knowledge())
        return adapter.process(request)
    raise ValueError("request needs 'text', 'frames', or 'task'")
