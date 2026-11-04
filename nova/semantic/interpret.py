"""Multiple simplified interpretations, with agreement and contradiction
checks (Req 4).

A difficult question is read several ways, and every reading is run
through the same concept engine and reasoner independently. The system
then compares the readings instead of silently trusting the first one:

* **Simplification sources** — (a) deterministic template
  simplifications the system can already do (verb canonicalization,
  subordinate-clause stripping, compound-sentence splitting); (b)
  model-proposed restatements via any ``LanguageModel`` (the model
  restates, NOVA re-parses and reasons — the frame, not the model's
  words, is the answer input).
* **Agreement** — the share of successful readings whose
  (verdict, answer) equals the modal (verdict, answer).
* **Contradiction** — two readings that both settle the question
  definitively but disagree. A contradiction is surfaced, never
  silently resolved: the adjudicated answer is ``unknown`` and both
  readings are named with their proofs. (Readings with a parse tier
  disabled are *diagnostic*, not rival interpretations: they can
  only lose frames, so they count in agreement but cannot veto or
  carry the answer — see ``_adjudicate``.)
* **Adjudication** — all agree: answer from the agreed reading.
  Majority agrees with no contradiction: answer from the majority,
  status ``partial_agreement``, dissent listed. Contradiction, or no
  reading settles the question: abstain honestly (verdict
  ``unknown``).

Nothing here changes the frozen eval or the single-parse path:
``interpret()`` is a wrapper around ``parse_text_to_frames`` +
``SupervisoryReasoner`` that keeps every candidate reading alive
instead of collapsing to one frame.
"""

from __future__ import annotations

import json
import re

from ..model_interface import coerce_model
from .compare import compare_concept_frames
from .extract import parse_text_to_frames
from .frame import ConceptFrame
from .reason import SupervisoryReasoner

# Verb variants the deterministic tiers cannot read, mapped to the
# canonical form the tiers do read. Narrow on purpose: only verbs
# whose canonical form preserves the transfer ("handed $10" IS "gave
# $10"); "lend"/"borrow" are deliberately NOT mapped, because lending
# is not giving.
_VERB_CANONICAL = {
    "handed": "gave", "hand": "give",
    "wired": "sent", "wire": "send",
    "passed": "gave", "pass": "give",
    "transferred": "sent", "transfer": "send",
    "purchased": "bought", "acquired": "bought",
}

# Subordinate clauses and time adverbs that carry no money facts.
# "because she needed groceries" is a reason, not a transfer; removing
# it must not change the answer — which is exactly what the agreement
# check verifies.
_CLAUSE_CUT = re.compile(
    r"\s+(because|since)\b[^.?!]*", re.IGNORECASE)
_TIME_ADVERB = re.compile(
    r"\s*\b(yesterday|today|tomorrow)\b\s*", re.IGNORECASE)

# "X gave Y $A and Z $B" -> "X gave Y $A. X gave Z $B." (and the
# "gave $A to Y" form). Only fires on the exact pattern; anything else
# is left alone.
_COMPOUND_DIRECT = re.compile(
    r"(\b\w+\b) (gave|sent|paid) (\b\w+\b) "
    r"(\$\d+(?:\.\d{1,2})?) and (\b\w+\b) "
    r"(\$\d+(?:\.\d{1,2})?)", re.IGNORECASE)
_COMPOUND_TO = re.compile(
    r"(\b\w+\b) (gave|sent|paid) (\$\d+(?:\.\d{1,2})?) to (\b\w+\b) "
    r"and (\$\d+(?:\.\d{1,2})?) to (\b\w+\b)", re.IGNORECASE)


def _canonicalize_verbs(text: str) -> str:
    """Replace uncovered verb variants with their canonical form."""
    def _sub(m: re.Match) -> str:
        word = m.group(0)
        canon = _VERB_CANONICAL[word.lower()]
        if word[:1].isupper():
            canon = canon[:1].upper() + canon[1:]
        return canon

    pattern = re.compile(
        r"\b(" + "|".join(sorted(_VERB_CANONICAL)) + r")\b",
        re.IGNORECASE)
    return pattern.sub(_sub, text)


def _strip_clauses(text: str) -> str:
    """Remove subordinate because/since clauses and time adverbs."""
    out = _CLAUSE_CUT.sub("", text)
    out = _TIME_ADVERB.sub(" ", out)
    out = re.sub(r"\s+([.?!])", r"\1", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def _split_compound(text: str) -> str | None:
    """Split a two-recipient transfer into two sentences, or None."""
    m = _COMPOUND_DIRECT.search(text)
    if m:
        first = (f"{m.group(1)} {m.group(2)} {m.group(3)} "
                 f"{m.group(4)}.")
        rest = text[m.end():]
        second = (f"{m.group(1)} {m.group(2)} {m.group(5)} "
                  f"{m.group(6)}")
        if not rest.startswith("."):
            second += "."
        return text[:m.start()] + first + " " + second + rest
    m = _COMPOUND_TO.search(text)
    if m:
        first = (f"{m.group(1)} {m.group(2)} {m.group(3)} to "
                 f"{m.group(4)}.")
        rest = text[m.end():]
        second = (f"{m.group(1)} {m.group(2)} {m.group(5)} to "
                  f"{m.group(6)}")
        if not rest.startswith("."):
            second += "."
        return text[:m.start()] + first + " " + second + rest
    return None


def _person_candidates(text: str) -> list[str]:
    """People mentioned in ``text`` (frame actors/recipients plus
    capitalized tokens), for pronoun-resolution variants. Question
    words and the pronouns themselves are excluded."""
    persons: list[str] = []
    for f in parse_text_to_frames(text):
        for name in (f.who, f.recipient):
            if name and name not in persons:
                persons.append(name)
    stop = {"He", "She", "They", "It", "The", "How", "What", "Did",
            "Does", "Do", "Is", "Are", "Was", "Were", "Can", "Could",
            "Would", "Should", "Who", "Why", "When", "Where"}
    for tok in re.findall(r"\b[A-Z][a-z]+\b", text):
        if tok not in stop and tok not in persons:
            persons.append(tok)
    return persons


_PRONOUN_SENTENCE = re.compile(
    r"^(He|She|They|It)\b(.*)$", re.IGNORECASE)


def _pronoun_variants(text: str) -> list[str]:
    """Resolve a sentence-initial pronoun to each person mentioned.

    "John gave Tom $20. He gave Sarah $10." is genuinely two
    questions: He = John (Tom keeps $20) or He = Tom (Tom keeps
    $10). Each resolution is a separate variant; the agreement check
    decides whether they agree. No gender tracking exists, so every
    mentioned person is a candidate — a wrong resolution is still a
    reading the system must weigh, not a reading it may silently
    discard.
    """
    persons = _person_candidates(text)
    if not persons:
        return []
    variants = []
    for sentence in re.split(r"(?<=[.?!])\s+", text.strip()):
        m = _PRONOUN_SENTENCE.match(sentence.strip())
        if not m:
            continue
        pronoun = m.group(1)
        rest = m.group(2)
        for person in persons:
            if person.lower() == pronoun.lower():
                continue
            variants.append(text.replace(
                sentence.strip(),
                f"{person}{rest}", 1))
    return variants


def deterministic_simplifications(text: str) -> list[dict]:
    """Template simplifications of ``text`` (no model calls).

    Returns ``[{text, source, method}]`` — only variants that differ
    from the original and from each other (compared case-insensitively
    on whitespace-normalized text). ``allow_heuristic`` False on a
    variant means "re-read with the deterministic tier only".
    """
    seen = {" ".join(text.lower().split())}
    variants = []

    def _add(candidate: str, method: str,
             allow_heuristic: bool = True) -> None:
        key = " ".join(candidate.lower().split())
        if key and key not in seen:
            seen.add(key)
            variants.append({"text": candidate, "source": "deterministic",
                             "method": method,
                             "allow_heuristic": allow_heuristic})

    _add(_canonicalize_verbs(text), "canonical-verbs")
    _add(_strip_clauses(text), "strip-clauses")
    split = _split_compound(text)
    if split is not None:
        _add(split, "split-compound")
    for pv in _pronoun_variants(text):
        _add(pv, "pronoun-resolution")
    # Deterministic-only re-read: same text, heuristic tier disabled.
    # A question the heuristic tier reads differently from the
    # deterministic tier is a question with two readings. (Appended
    # directly: its text is identical to the original, only the parse
    # mode differs, so the text dedupe above would drop it.)
    variants.append({"text": text, "source": "deterministic",
                     "method": "deterministic-only",
                     "allow_heuristic": False})
    return variants


# Two restatement prompts. Temperature is 0 in the live model, so the
# prompts — not sampling — are what make the readings differ.
_RESTATE_PROMPTS = [
    ("restate-simple",
     "Restate this question in the simplest possible words, keeping "
     "exactly the same meaning and all names and numbers. Return only "
     "the restated question.\n\n{text}"),
    ("restate-facts",
     "Rewrite this as a short list of simple facts, one per line, "
     "followed by the question on its own line. Keep all names and "
     "numbers exactly. Do not add anything.\n\n{text}"),
]


def model_simplifications(text: str, model) -> list[dict]:
    """Model-proposed restatements of ``text``.

    Each restatement is returned as a variant with its source and
    method. A failed model call is recorded as a failed variant
    (``failed: True``) instead of crashing the run; failed variants
    never vote in the agreement check.
    """
    lm = coerce_model(model)
    variants = []
    seen = {" ".join(text.lower().split())}
    for method, template in _RESTATE_PROMPTS:
        try:
            response = lm.complete(template.format(text=text))
            restated = (response.text or "").strip()
        except Exception as e:  # noqa: BLE001 - record, don't crash
            variants.append({"text": None, "source": "model",
                             "method": method, "failed": True,
                             "error": str(e)})
            continue
        key = " ".join(restated.lower().split())
        if not restated or key in seen:
            continue
        seen.add(key)
        variants.append({"text": restated, "source": "model",
                         "method": method})
    return variants


def _answer_key(answer) -> str:
    """A stable, comparable key for an answer value.

    Numbers compare by value (10 == 10.0); dicts by sorted JSON;
    everything else by its string form. ``None`` and the string
    ``"unknown"`` are the same key: the reasoner returns
    ``answer == verdict`` for yes/no goals, so an unresolved goal
    carries the string "unknown" where other paths carry None —
    both mean "no answer". Two readings agree iff their keys match.
    """
    if answer is None or answer == "unknown":
        return "none"
    if isinstance(answer, bool):
        return f"bool:{answer}"
    if isinstance(answer, (int, float)):
        return f"num:{float(answer):g}"
    if isinstance(answer, dict):
        return "dict:" + json.dumps(answer, sort_keys=True, default=str)
    return f"str:{answer}"


def _is_definitive(verdict: str, answer) -> bool:
    """Does this reading settle the question? A yes/no/both verdict
    settles it; so does any non-None answer other than the string
    "unknown" (an unresolved yes/no goal carries answer == verdict,
    i.e. the string "unknown" — that settles nothing)."""
    if verdict in ("yes", "no", "both"):
        return True
    if answer is None or answer == "unknown":
        return False
    return True


def _frame_signature(frame: dict) -> tuple:
    """A reading's identity: everything about a frame except where it
    came from (source_text/evidence differ across variants of the same
    reading and must not split it)."""
    return (frame.get("kind"), frame.get("who"), frame.get("what"),
            frame.get("recipient"), frame.get("object"),
            frame.get("quantity"), frame.get("units"),
            frame.get("when"), frame.get("where"), frame.get("why"),
            frame.get("how"), frame.get("polarity"),
            frame.get("certainty"), frame.get("status"),
            json.dumps(frame.get("relationships") or [],
                       sort_keys=True, default=str))


def _reason_variant(text: str, knowledge=None,
                    rules: list | None = None,
                    allow_heuristic: bool = True) -> dict:
    """Parse one variant and reason over it. Never raises: a variant
    that parses to nothing returns an honest unknown."""
    frames = parse_text_to_frames(text, knowledge=knowledge,
                                  allow_heuristic=allow_heuristic)
    if not frames:
        return {"verdict": "unknown", "answer": None, "proof": [],
                "complete": False, "status": "unknown",
                "missing": ["no sentence matched any parser tier"],
                "evidence": [], "unusable_frames": [],
                "frames": []}
    reasoner = SupervisoryReasoner(knowledge=knowledge)
    result = reasoner.reason(frames, rules=rules)
    result["frames"] = [f.to_dict() for f in frames]
    return result


def _adjudicate(results: list[dict]) -> dict:
    """Decide the answer from per-reading results.

    ``results`` are the successful (non-failed) interpretation records.
    The rule is deliberately asymmetric: a reading that cannot parse
    (verdict unknown) is an absence of evidence, not a vote against
    the readings that could. Only *definitive* readings — a yes/no/
    both verdict, or a non-None answer — can contradict each other
    or carry the answer.

    A second asymmetry: readings marked ``peer: False`` are
    *diagnostic*, not rival interpretations. The deterministic-only
    re-read (heuristic tier disabled) can only lose frames the full
    parse has, so it can disagree by incapacity, not by meaning —
    "sent"/"paid" transfers vanish from it and a balance goes
    negative. Diagnostic readings are listed, count in the agreement
    denominator (the answer's dependence on the heuristic tier is
    real signal), but they cannot veto and cannot carry the answer:
    contradiction pairs and the definitive set are computed over
    peer readings only.

    Returns the adjudicated ``{status, verdict, answer, complete,
    missing, unusable_frames, agreement_rate, agreement_n,
    contradiction, contradicting_pairs, modal_key, modal_index}``.
    ``agreement_rate`` is the share of readings behind the
    adjudicated outcome (the answer, when one is given; the modal
    key otherwise).
    """
    n = len(results)
    if n == 0:
        return {"status": "unknown", "verdict": "unknown", "answer": None,
                "complete": False, "missing": ["no readings produced"],
                "unusable_frames": [], "agreement_rate": 0.0,
                "agreement_n": 0, "contradiction": False,
                "contradicting_pairs": [], "modal_key": None,
                "modal_index": None}
    keys = [(_r["verdict"], _answer_key(_r["answer"])) for _r in results]
    counts: dict[tuple, int] = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    # Modal key: most common; ties break toward the original reading
    # (index 0), so the adjudication is deterministic.
    modal_key = max(counts, key=lambda k: (counts[k], -keys.index(k)))
    modal_n = counts[modal_key]
    modal_idx = keys.index(modal_key)
    modal = results[modal_idx]

    peers = [i for i, r in enumerate(results) if r.get("peer", True)]
    definitive = [i for i in peers
                  if _is_definitive(results[i]["verdict"],
                                    results[i]["answer"])]
    contradicting_pairs = []
    for a_pos in range(len(definitive)):
        for b_pos in range(a_pos + 1, len(definitive)):
            i, j = definitive[a_pos], definitive[b_pos]
            if keys[i] != keys[j]:
                contradicting_pairs.append({
                    "a": i, "b": j,
                    "a_verdict": results[i]["verdict"],
                    "a_answer": results[i]["answer"],
                    "b_verdict": results[j]["verdict"],
                    "b_answer": results[j]["answer"],
                })
    contradiction = bool(contradicting_pairs)

    if contradiction:
        # Two readings settle the question differently. Say so and
        # abstain — never silently pick one. The answer is the modal
        # reading's answer only when the modal reading itself
        # abstained (verdict unknown): that keeps the abstention in
        # the reasoner's own representation ("unknown" for yes/no
        # goals, None for number goals). A definitive modal answer
        # is dropped, because the adjudicated verdict is unknown.
        return {"status": "contradiction", "verdict": "unknown",
                "answer": (modal["answer"]
                           if modal["verdict"] == "unknown" else None),
                "complete": False,
                "missing": ["readings contradict each other; see "
                            "contradicting_pairs"],
                "unusable_frames": [], "agreement_rate": modal_n / n,
                "agreement_n": modal_n, "contradiction": True,
                "contradicting_pairs": contradicting_pairs,
                "modal_key": f"{modal_key[0]}:{modal_key[1]}",
                "modal_index": modal_idx}
    if not definitive:
        # No reading settled the question. All readings agree there
        # is no answer — that is agreement, not a split. The answer
        # is the modal reading's own abstention representation.
        return {"status": "unknown", "verdict": "unknown",
                "answer": modal["answer"],
                "complete": False,
                "missing": list(modal["missing"]),
                "unusable_frames": list(modal["unusable_frames"]),
                "agreement_rate": modal_n / n, "agreement_n": modal_n,
                "contradiction": False, "contradicting_pairs": [],
                "modal_key": f"{modal_key[0]}:{modal_key[1]}",
                "modal_index": modal_idx}
    # Every definitive peer reading agrees. The answer is theirs; the
    # status records whether every reading agreed (all definitive)
    # or only some could read the question at all.
    def_key = keys[definitive[0]]
    def_n = sum(1 for i in range(n) if keys[i] == def_key)
    def_idx = definitive[0]
    def_modal = results[def_idx]
    agreement_rate = def_n / n
    if agreement_rate == 1.0:
        status = def_modal["status"]
        missing = list(def_modal["missing"])
    else:
        status = "partial_agreement"
        missing = list(def_modal["missing"]) + [
            f"{n - def_n} of {n} readings did not reach this answer; "
            "see interpretations"]
    return {"status": status, "verdict": def_modal["verdict"],
            "answer": def_modal["answer"],
            "complete": def_modal["complete"], "missing": missing,
            "unusable_frames": list(def_modal["unusable_frames"]),
            "agreement_rate": agreement_rate,
            "agreement_n": def_n, "contradiction": False,
            "contradicting_pairs": [],
            "modal_key": f"{def_key[0]}:{def_key[1]}",
            "modal_index": def_idx}


def render_interpretation(result: dict) -> str:
    """Human-readable rendering of a multi-interpretation result."""
    n = result["n_interpretations"]
    if result["status"] == "contradiction":
        lines = [f"I read this {n} ways, and they disagree:"]
        # Show each distinct disagreement once (several pairs can
        # name the same two answers).
        shown: set = set()
        for pair in result["contradicting_pairs"]:
            key = tuple(sorted([
                (pair["a_verdict"], str(pair["a_answer"])),
                (pair["b_verdict"], str(pair["b_answer"]))]))
            if key in shown:
                continue
            shown.add(key)
            a = result["interpretations"][pair["a"]]
            b = result["interpretations"][pair["b"]]
            lines.append(
                f"- Reading {pair['a'] + 1} ({a['method']}): "
                f"{a['verdict']}"
                + (f" — {a['answer']}" if a["answer"] is not None
                   else "")
                + f". Proof: {'; '.join(a['proof'][:2])}")
            lines.append(
                f"- Reading {pair['b'] + 1} ({b['method']}): "
                f"{b['verdict']}"
                + (f" — {b['answer']}" if b["answer"] is not None
                   else "")
                + f". Proof: {'; '.join(b['proof'][:2])}")
        lines.append("I cannot settle which reading is right, so I "
                     "abstain rather than guess.")
        return " ".join(lines)
    if result["verdict"] == "unknown":
        return (f"{n} readings, no settled answer "
                f"(agreement {result['agreement_rate']:.2f}). "
                f"Missing: {'; '.join(result['missing'][:2])}")
    answer = result["answer"]
    answer_s = f"${answer:g}" if isinstance(answer, (int, float)) \
        else str(answer)
    if result["agreement_rate"] == 1.0:
        head = f"All readings agree: {answer_s} "
    else:
        head = (f"Most readings agree ({result['agreement_n']} of "
                f"{n}): {answer_s} ")
    return (head + f"(agreement {result['agreement_rate']:.2f}). "
            f"Proof: {'; '.join(result['proof'][:2])}")


def interpret(text: str, model=None, knowledge=None,
              rules: list | None = None, use_model: bool = True,
              advisor_text: str | None = None) -> dict:
    """Read ``text`` several ways and adjudicate the readings.

    Returns an envelope with the adjudicated answer plus, for every
    reading, its text, source, verdict, answer, proof and frames —
    and a confidence score (see ``nova.semantic.confidence``) with a
    computed ``certified`` flag.

    ``model`` (optional) supplies model-proposed restatements.
    ``advisor_text`` (optional) is the model's direct answer to the
    question, used only for the model-agreement component of the
    confidence score — it is never the answer.
    """
    from .confidence import score as confidence_score

    variants = [{"text": text, "source": "original",
                 "method": "as-given"}]
    variants.extend(deterministic_simplifications(text))
    model_calls = 0
    if model is not None and use_model:
        model_variants = model_simplifications(text, model)
        model_calls = sum(1 for v in model_variants
                          if not v.get("failed"))
        variants.extend(model_variants)

    interpretations = []
    seen_signatures: set = set()
    n_duplicate_variants = 0
    for v in variants:
        if v.get("failed"):
            interpretations.append({
                "source": v["source"], "method": v["method"],
                "text": None, "failed": True,
                "error": v.get("error"),
                "verdict": "unknown", "answer": None, "proof": [],
                "complete": False, "status": "unknown", "missing": [],
                "evidence": [], "unusable_frames": [], "frames": []})
            continue
        r = _reason_variant(v["text"], knowledge=knowledge, rules=rules,
                            allow_heuristic=v.get("allow_heuristic",
                                                  True))
        # Two variants that parse to identical frames are the same
        # reading, not two agreeing readings: dedupe by frame
        # signature so the agreement denominator counts distinct
        # readings only.
        sig = tuple(_frame_signature(f) for f in r["frames"])
        if sig in seen_signatures:
            n_duplicate_variants += 1
            continue
        seen_signatures.add(sig)
        interpretations.append({
            "source": v["source"], "method": v["method"],
            "text": v["text"], "verdict": r["verdict"],
            "answer": r["answer"], "proof": r["proof"],
            "complete": r["complete"], "status": r["status"],
            "missing": r["missing"], "evidence": r["evidence"],
            "unusable_frames": r["unusable_frames"],
            "frames": r["frames"],
            # Peer readings (full parse tiers) can veto and carry
            # the answer; diagnostic readings (a tier disabled) are
            # recorded and count in agreement, but cannot do either.
            "peer": v.get("allow_heuristic", True)})

    successful = [r for r in interpretations if not r.get("failed")]
    decision = _adjudicate(successful)

    # Frame-level agreement between readings (pairwise, over the
    # first frame of each successful reading that has one).
    frame_relations = []
    framed_idx = [i for i, r in enumerate(successful) if r["frames"]]
    for a_pos in range(len(framed_idx)):
        for b_pos in range(a_pos + 1, len(framed_idx)):
            i, j = framed_idx[a_pos], framed_idx[b_pos]
            fa = ConceptFrame.from_dict(successful[i]["frames"][0])
            fb = ConceptFrame.from_dict(successful[j]["frames"][0])
            rel = compare_concept_frames(fa, fb)
            rel["a"] = i
            rel["b"] = j
            frame_relations.append(rel)

    all_frames = [f for r in successful for f in r["frames"]]
    frame_objs = [ConceptFrame.from_dict(f) for f in all_frames]
    conf = confidence_score(
        parse_certainty=_parse_certainty(frame_objs),
        agreement_rate=decision["agreement_rate"],
        proof_completeness=_proof_completeness(decision),
        model_agreement=_model_agreement(
            advisor_text, decision["answer"], decision["verdict"]))

    result = {
        "status": decision["status"],
        "verdict": decision["verdict"],
        "answer": decision["answer"],
        "proof": (successful[decision["modal_index"]]["proof"]
                  if decision["modal_index"] is not None
                  and decision["verdict"] != "unknown"
                  else []),
        "complete": decision["complete"],
        "missing": decision["missing"],
        "unusable_frames": decision["unusable_frames"],
        "interpretations": interpretations,
        "n_interpretations": len(successful),
        "n_duplicate_variants": n_duplicate_variants,
        "n_failed_variants": len(interpretations) - len(successful),
        "agreement_rate": decision["agreement_rate"],
        "agreement_n": decision["agreement_n"],
        "contradiction": decision["contradiction"],
        "contradicting_pairs": decision["contradicting_pairs"],
        "frame_relations": frame_relations,
        "confidence": conf,
        "model_calls": model_calls,
    }
    result["answer_text"] = render_interpretation(result)
    return result


# -- confidence inputs (kept here so interpret() stays self-contained;
#    the scoring itself lives in nova.semantic.confidence) -----------

def _parse_certainty(frames: list[ConceptFrame]) -> float:
    """Share of frames parsed deterministically (certainty known)."""
    if not frames:
        return 0.0
    known = sum(1 for f in frames if f.certainty == "known")
    return known / len(frames)


def _proof_completeness(decision: dict) -> float:
    """1.0: complete proof, nothing missing, nothing unusable.
    0.5: complete but with missing/unusable caveats. 0.0: not
    complete."""
    if not decision["complete"]:
        return 0.0
    if decision["missing"] or decision["unusable_frames"]:
        return 0.5
    return 1.0


def _model_agreement(advisor_text: str | None, answer,
                     verdict: str) -> float | None:
    """1.0 if the advisor's direct answer matches the adjudicated
    answer, 0.0 if it contradicts it, None if it cannot be compared
    (no advisor text, unparseable, or a definition answer)."""
    from .confidence import model_agreement_factor
    return model_agreement_factor(advisor_text, answer, verdict)
