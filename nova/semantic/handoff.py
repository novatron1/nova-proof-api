"""NOVA Intelligence Assistance: the genuine handoff package.

PERMANENT ARCHITECTURE DECISION (user, 2026-10-27): NOVA keeps BOTH
capabilities. (1) Independent reasoning — the symbolic reasoner,
concept engine, knowledge retrieval, calculator and specialized
modules solving supported problems on their own — is RETAINED in
full. (2) Intelligence Assistance — NOVA as an adapter for existing
language models — is a SECOND capability, not a replacement. The
handoff work in this module is purely additive: it reads the
deterministic pipeline's envelopes and renders them for a language
model. It changes no pipeline behavior, no parser, no reasoner, no
scoring of the independent arm. The deterministic pipeline's
behavior stays exactly as it is.

What this module does:

* ``build_explanation_package`` — for one question, run the SAME
  deterministic pipeline the independent NOVA arm runs (text path,
  with the same structured-oracle fallback the harness uses) plus the
  Req 4 multi-interpretation pass, and assemble everything a
  language model needs into one package: definitions,
  synonyms/antonyms, 2-3 simplified interpretations with
  agreement/contradiction flags, a concept graph, reasoning steps
  (the proof trace), the verified answer, and a confidence score.
* ``render_*`` — turn a package into prompt blocks. The section
  order is FIXED and documented (see ``render_package``): lexical
  understanding first, then readings, then the graph, then the
  reasoning, then the verified answer. Five prompt variants exist,
  one per experiment arm; each is built from the same package so the
  arms differ only in which sections the model sees:
  ``full`` (H — everything, verified answer included),
  ``no_answer`` (H' — everything except the stated answer),
  ``context`` (B — lexical block + raw fact list, no NOVA reasoning),
  ``translation`` (D — interpretations only),
  ``reasoning`` (E — graph + proof steps, no answer, no lexicon).
* ``coherence_scores`` — the deterministic 0-3 coherence rubric
  for a model response (see there).

Hard rules, enforced here:

* The package NEVER contains the item's ground truth. The verified
  answer comes from the deterministic pipeline's envelope, never
  from the item. The builder reads ``ground_truth`` ONLY for the
  oracle-fallback routing decision — the exact same decision the
  recorded NOVA arm makes (an item whose ground truth is "unknown"
  must abstain, never fall through to the oracle) — and it never
  enters package content.
* The deterministic pipeline is never asked to answer through the
  model in this module: ``model=None`` everywhere. The model
  receives the package and generates the final response; that call
  happens in the harness, not here.
* A package whose envelope is unknown says so plainly
  ("cannot be determined") with the missing reasons listed. It
  never invents a definition, a reading, or an answer.
"""

from __future__ import annotations

import re

from ..adapter.core import Knowledge
from .confidence import CERTIFICATION_BAR
from .extract import (parse_sentence_to_frame, parse_text_to_frames,
                      split_sentences)
from .frame import ConceptFrame
from .graph import ConceptGraph
from .interpret import interpret
from .lexicon import default_lexicon
from .pipeline import answer_text, process_request
from .router import route_sentence
from .translate import list_knowledge_entries

# ---------------------------------------------------------------------------
# Prompt text (fixed; recorded in the design doc and the run config)
# ---------------------------------------------------------------------------

ANSWER_INSTRUCTION = (
    "Put your final answer alone on the first line: a number, yes, "
    "no, a short definition, or \"I don't know\". You may add at most "
    "one short sentence after it explaining your reasoning in your "
    "own words."
)

HANDOFF_PREAMBLE = (
    "You are answering a question. NOVA, a concept-reasoning system, "
    "has already analysed it. Read NOVA's analysis, then give your "
    "own final answer. If NOVA's analysis contradicts itself, or "
    "says the answer cannot be determined, answer \"I don't know\" "
    "rather than guessing."
)

CONTEXT_PREAMBLE = (
    "You are answering a question. Some background facts about the "
    "words in it are given below. Read them, then give your own "
    "final answer."
)

TRANSLATION_PREAMBLE = (
    "You are answering a question. NOVA, a concept-reasoning system, "
    "has read it in more than one way; the readings are given below. "
    "Read them, then give your own final answer. If the readings "
    "disagree, answer \"I don't know\" rather than guessing."
)

REASONING_PREAMBLE = (
    "You are answering a question. NOVA, a concept-reasoning system, "
    "has mapped its concepts and worked through the reasoning steps; "
    "both are given below. Read them, then give your own final "
    "answer. Work out the final answer yourself from the steps."
)

# ---------------------------------------------------------------------------
# Package construction
# ---------------------------------------------------------------------------

_QUOTED_TERM_RE = re.compile(r"['\"]([^'\"]+)['\"]")


def _nova_envelope(text: str, knowledge, rules, nova_request,
                   ground_truth) -> tuple[dict, str, dict | None]:
    """The pipeline envelope for one question, exactly as the
    recorded NOVA arm computes it (see eval/harness._nova_answer).

    Text path first; the structured-oracle fallback fires only when
    the text path yields no answer AND the item carries a structured
    request AND the ground truth is not itself "unknown" (an unknown
    must abstain, never fall through to the oracle). ``ground_truth``
    is used ONLY for that routing decision. Returns
    (envelope, input_mode, text_path_diag).
    """
    result = answer_text(text, model=None, knowledge=knowledge,
                         rules=rules)
    text_diag = {
        "frames_n": len(result.get("frames") or []),
        "status": result.get("status"),
        "verdict": result.get("verdict"),
        "answer": result.get("answer"),
    }
    no_answer = (result.get("answer") is None
                 and result.get("verdict") == "unknown")
    if nova_request and ground_truth != "unknown" \
            and (not result.get("frames") or no_answer):
        result = process_request(nova_request, model=None,
                                 knowledge=knowledge)
        return result, "structured_oracle", text_diag
    return result, "text", None


def _definition_entries(text: str, knowledge) -> list[dict]:
    """Definition/encyclopedia entries the router finds in ``text``.

    Per-sentence routing through the same router the pipeline uses
    (see eval/harness.retrieve_knowledge). Never consults the item's
    structured request.
    """
    found, seen = [], set()
    if knowledge is None:
        return found
    for sentence in split_sentences(text):
        try:
            frame = route_sentence(sentence, knowledge=knowledge)
        except Exception:  # noqa: BLE001 - a routing error is no hit
            continue
        if frame is None or frame.kind != "definition":
            continue
        if frame.status != "retrieved" or not frame.object:
            continue
        term = frame.object
        meaning = frame.why or ""
        if term.lower() in seen or not meaning:
            continue
        kind = ("dictionary"
                if knowledge.lookup("dictionary", term) is not None
                else "encyclopedia")
        found.append({"term": term, "kind": kind, "meaning": meaning,
                      "source": "fixture-store"})
        seen.add(term.lower())
    return found


def _lexical_terms(text: str, frames: list[dict],
                   definitions: list[dict]) -> list[str]:
    """Terms worth a synonym/antonym lookup: definition terms, frame
    objects, quoted terms in the question, and store terms named in
    the question. Capped at 3, first-seen order, deduped."""
    terms: list[str] = []

    def _add(term):
        if term and term.lower() not in [t.lower() for t in terms]:
            terms.append(term)

    for d in definitions:
        _add(d["term"])
    for f in frames:
        _add(f.get("object"))
    for m in _QUOTED_TERM_RE.finditer(text):
        _add(m.group(1).strip())
    return terms[:3]


_LEXICON_CACHE: dict = {"lexicon": None, "attempted": False}


def _get_lexicon():
    """The production lexicon, opened once per process and reused.
    A failed open is remembered (no repeated attempts); the caller
    treats a missing lexicon as empty relations, never an error."""
    if not _LEXICON_CACHE["attempted"]:
        _LEXICON_CACHE["attempted"] = True
        try:
            _LEXICON_CACHE["lexicon"] = default_lexicon()
        except Exception:  # noqa: BLE001 - no lexicon, no relations
            _LEXICON_CACHE["lexicon"] = None
    return _LEXICON_CACHE["lexicon"]


def _lexicon_block(terms: list[str], context: str) -> dict:
    """Synonyms/antonyms (+ WSD sense) per term from the licensed
    production lexicon. An absent or unreadable lexicon yields empty
    lists, never an exception — the package stays honest about what
    it could not look up."""
    block: dict[str, dict] = {}
    lex = _get_lexicon()
    if lex is None:
        return block
    for term in terms:
        try:
            syns = lex.synonyms(term)[:5]
            ants = lex.antonyms(term)[:5]
            sense = lex.disambiguate(term, context=context)
        except Exception:  # noqa: BLE001 - per-term failure is empty
            syns, ants, sense = [], [], None
        block[term] = {
            "synonyms": syns,
            "antonyms": ants,
            "sense": (sense.get("sense_no")
                      if isinstance(sense, dict) else None),
            "sense_definition": (sense.get("definition")
                                 if isinstance(sense, dict) else None),
        }
    return block


def _graph_lines(frames: list[dict]) -> list[str]:
    """A compact rendering of the concept graph: actors, actions,
    objects, and the edges between them (max 12 lines)."""
    try:
        objs = [ConceptFrame.from_dict(f) for f in frames]
        graph = ConceptGraph.from_frames(objs)
    except Exception:  # noqa: BLE001 - a broken graph is no graph
        return []
    lines = []
    actors = [n.label for n in graph.actors()]
    actions = [n.label for n in graph.actions()]
    objects = [n.label for n in graph.objects()]
    if actors:
        lines.append("Actors: " + ", ".join(actors))
    if actions:
        lines.append("Actions: " + ", ".join(actions))
    if objects:
        lines.append("Objects: " + ", ".join(objects))
    edges = []
    for edge in graph.edges:
        src = graph.nodes.get(edge.source)
        dst = graph.nodes.get(edge.target)
        if src is None or dst is None:
            continue
        edges.append(f"{src.label} --{edge.rel}--> {dst.label}")
    lines.extend(edges[:12])
    return lines


def _render_verified_answer(envelope: dict) -> str:
    """The envelope's answer as plain text for the prompt."""
    answer = envelope.get("answer")
    verdict = envelope.get("verdict")
    if (verdict == "unknown"
            and (answer is None or answer == "unknown")):
        return "cannot be determined"
    if isinstance(answer, dict):
        return answer.get("meaning") or str(answer)
    if isinstance(answer, (int, float)):
        return f"${answer:g}" if float(answer).is_integer() \
            and abs(answer) < 10000 else str(answer)
    if verdict in ("yes", "no", "both") and answer is None:
        return verdict
    if answer is not None:
        return str(answer)
    return str(verdict)


def _sense_graph_block(terms: list[str], context: str) -> dict:
    """The v1.2 sense graph for the package's lexical terms, built
    from the production lexicon. Failure degrades to an empty graph,
    never an exception (same honesty contract as _lexicon_block)."""
    try:
        from .sense_graph import sense_graph_for_terms
        return sense_graph_for_terms(terms, lexicon=_get_lexicon(),
                                     context=context)
    except Exception:  # noqa: BLE001 - no graph, not an error
        return {"nodes": [], "edges": [], "note": "unavailable"}


def _coverage(text: str, frames: list[dict], envelope: dict,
              missing: list) -> dict:
    """Parser coverage, merged from NOVA v1.2 (2026-11-02): what the
    parser did NOT cover stays visible in the package instead of
    disappearing. Per-sentence: a sentence that yields no frame is
    listed as unparsed. A scoped balance question whose scope amount
    matches two or more identical incoming transfers is flagged as
    duplicate-scope ambiguity (since v1.4 the core engine also
    abstains on it; the flag keeps the ambiguity visible in the
    package either way). Any failure here degrades to counts only —
    coverage must never break package building."""
    cov: dict = {
        "sentences_n": len(split_sentences(text)),
        "frames_n": len(frames),
        "unparsed_sentences": [],
        "unusable_frames_n": len(envelope.get("unusable_frames")
                                 or []),
        "missing": list(missing or []),
        "duplicate_scope_ambiguity": False,
    }
    try:
        for sentence in split_sentences(text):
            try:
                frame = parse_sentence_to_frame(sentence)
            except Exception:  # noqa: BLE001 - unparsed, not fatal
                frame = None
            if frame is None:
                cov["unparsed_sentences"].append(sentence)
        queries = [f for f in frames if f.get("kind") == "query"
                   and f.get("quantity") is not None]
        for q in queries:
            # Inflows only: a refund frame also has the scoped
            # person as recipient, but money coming back is not a
            # second lot the scope could mean (v1.4).
            dupes = [f for f in frames
                     if f.get("kind") == "transfer"
                     and f.get("what") != "refund"
                     and f.get("polarity") == "positive"
                     and f.get("recipient") == q.get("who")
                     and f.get("quantity") == q.get("quantity")]
            if len(dupes) > 1:
                cov["duplicate_scope_ambiguity"] = True
    except Exception:  # noqa: BLE001 - counts-only coverage
        pass
    return cov


def build_explanation_package(text: str, knowledge=None,
                              rules: list | None = None,
                              nova_request: dict | None = None,
                              ground_truth=None) -> dict:
    """Build the handoff package for one question.

    Runs the deterministic pipeline (text path + oracle fallback,
    same routing as the recorded NOVA arm) and the Req 4
    multi-interpretation pass (deterministic simplifications only;
    no model calls anywhere). ``ground_truth`` is used ONLY for the
    oracle-fallback routing decision (see _nova_envelope) and never
    appears in the package.
    """
    if knowledge is None:
        knowledge = Knowledge()
    envelope, input_mode, text_diag = _nova_envelope(
        text, knowledge, rules, nova_request, ground_truth)
    frames = envelope.get("frames") or []
    interp = interpret(text, model=None, knowledge=knowledge,
                       rules=rules)
    definitions = _definition_entries(text, knowledge)
    # An oracle dictionary/encyclopedia answer is a definition the
    # router never saw: include it with its source named.
    if input_mode == "structured_oracle" \
            and isinstance(envelope.get("answer"), dict):
        ans = envelope["answer"]
        term = ans.get("term")
        meaning = ans.get("meaning")
        if term and meaning and term.lower() not in [
                d["term"].lower() for d in definitions]:
            definitions.append({"term": term, "kind": "oracle",
                                "meaning": meaning,
                                "source": "structured-oracle"})
    terms = _lexical_terms(text, frames, definitions)
    lexicon = _lexicon_block(terms, context=text)
    # Provenance: the evidence sources behind the frames, verbatim.
    sources = set()
    for f in frames:
        for e in f.get("evidence", []):
            sources.add(e.get("source"))
    for e in envelope.get("evidence") or []:
        sources.add(e.get("source"))
    package = {
        "question": text,
        "definitions": definitions,
        "lexicon": lexicon,
        "interpretations": [
            {"text": r.get("text"), "method": r.get("method"),
             "source": r.get("source"),
             "verdict": r.get("verdict"), "answer": r.get("answer"),
             "proof": (r.get("proof") or [])[:2],
             "failed": bool(r.get("failed"))}
            for r in interp.get("interpretations", [])
            if not r.get("failed")][:3],
        "n_interpretations": interp.get("n_interpretations", 0),
        "agreement_rate": interp.get("agreement_rate", 0.0),
        "contradiction": bool(interp.get("contradiction")),
        "contradicting_pairs": interp.get("contradicting_pairs", []),
        "graph_lines": _graph_lines(frames),
        "reasoning_steps": list(envelope.get("proof") or []),
        "verified_answer": _render_verified_answer(envelope),
        "verdict": envelope.get("verdict"),
        "answer_value": envelope.get("answer"),
        "confidence": (interp.get("confidence") or {}).get("confidence"),
        "certified": (interp.get("confidence") or {}).get("certified"),
        "certification_bar": CERTIFICATION_BAR,
        "provenance": sorted(s for s in sources if s),
        "input_mode": input_mode,
        "text_path": text_diag,
        "missing": list(envelope.get("missing") or []),
        "status": envelope.get("status"),
        # Merged from NOVA v1.2 (2026-11-02, additive — no existing
        # key changed): explicit parser coverage, the sense graph
        # with has_sense/synonym/antonym kept distinct, and NOVA's
        # authority limit stated as data.
        "coverage": _coverage(text, frames, envelope,
                              envelope.get("missing")),
        "sense_graph": _sense_graph_block(terms, text),
        "nova_authority": (
            "limited-domain evidence; an unknown/unsupported state "
            "means NOVA lacks a proof, not that the question is "
            "unanswerable"),
    }
    return package


# ---------------------------------------------------------------------------
# Rendering: one fixed section order, five arm variants
# ---------------------------------------------------------------------------

def _section_lexical(package: dict) -> str:
    lines = ["NOVA's understanding of the words:"]
    if not package["definitions"] and not package["lexicon"]:
        lines.append("- (no definitions found for the words in this "
                     "question)")
    for d in package["definitions"]:
        lines.append(f"- {d['term']} ({d['kind']}): {d['meaning']}")
    for term, rels in package["lexicon"].items():
        if rels["synonyms"]:
            lines.append(f"- {term} — synonyms: "
                         + ", ".join(rels["synonyms"]))
        if rels["antonyms"]:
            lines.append(f"- {term} — antonyms: "
                         + ", ".join(rels["antonyms"]))
        if rels.get("sense_definition"):
            lines.append(f"- {term} (sense {rels.get('sense')}): "
                         + rels["sense_definition"])
    return "\n".join(lines)


def _section_interpretations(package: dict) -> str:
    lines = ["How NOVA reads the question:"]
    for i, r in enumerate(package["interpretations"]):
        ans = r["answer"]
        ans_s = (f"${ans:g}" if isinstance(ans, (int, float))
                 else str(ans) if ans is not None else "—")
        lines.append(f"- Reading {i + 1} ({r['method']}): "
                     f"{r['verdict']}"
                     + (f" — {ans_s}" if ans is not None else ""))
    if package["contradiction"]:
        lines.append("These readings DISAGREE with each other.")
    else:
        lines.append(
            f"Agreement across readings: "
            f"{package['agreement_rate']:.2f}.")
    return "\n".join(lines)


def _section_graph(package: dict) -> str:
    lines = ["The concepts and their relationships:"]
    if not package["graph_lines"]:
        lines.append("- (no concept graph could be built)")
    else:
        lines.extend("- " + ln for ln in package["graph_lines"])
    return "\n".join(lines)


def _section_reasoning(package: dict) -> str:
    lines = ["NOVA's reasoning:"]
    steps = package["reasoning_steps"]
    if not steps:
        lines.append("- (no reasoning steps; NOVA could not derive "
                     "the answer)")
    else:
        lines.extend(f"- {s}" for s in steps)
    return "\n".join(lines)


def _section_verified_answer(package: dict) -> str:
    conf = package["confidence"]
    conf_s = f"{conf:.3f}" if isinstance(conf, (int, float)) else "n/a"
    cert = ("certified" if package["certified"]
            else "not certified")
    return (
        "NOVA's verified answer: "
        f"{package['verified_answer']} "
        f"(confidence {conf_s} against a bar of "
        f"{package['certification_bar']}, {cert}; "
        f"provenance: {', '.join(package['provenance']) or 'none'})"
    )


def render_package(package: dict, include_answer: bool = True) -> str:
    """The full package block, fixed section order:

    1. lexical understanding (definitions, synonyms, antonyms)
    2. interpretations (2-3 readings + agreement/contradiction)
    3. concept graph
    4. reasoning steps (proof trace)
    5. verified answer (omitted when include_answer is False)
    """
    parts = [
        _section_lexical(package),
        _section_interpretations(package),
        _section_graph(package),
        _section_reasoning(package),
    ]
    if include_answer:
        parts.append(_section_verified_answer(package))
    elif package["missing"]:
        parts.append("What NOVA could not determine: "
                     + "; ".join(package["missing"][:2]))
    return "\n\n".join(parts)


def build_handoff_prompt(package: dict, include_answer: bool = True
                         ) -> str:
    """Arm H (include_answer=True) / H' (False): the full package
    plus the question and the answer instruction."""
    return (HANDOFF_PREAMBLE + "\n\n"
            + render_package(package, include_answer=include_answer)
            + "\n\nQuestion: " + package["question"]
            + "\n" + ANSWER_INSTRUCTION)


def build_context_prompt(package: dict, text: str) -> str:
    """Arm B (the "more context" control): the lexical block plus
    the question's own sentences listed as plain facts. No
    interpretations, no graph, no proof, no verified answer — the
    same facts NOVA's frames were built from, with none of NOVA's
    computation."""
    facts = [s.strip() for s in split_sentences(text)
             if s.strip()]
    fact_lines = "\n".join(f"- {s}" for s in facts)
    return (CONTEXT_PREAMBLE + "\n\n"
            + _section_lexical(package)
            + "\n\nThe facts in the question:\n" + fact_lines
            + "\n\nQuestion: " + text
            + "\n" + ANSWER_INSTRUCTION)


def build_translation_prompt(package: dict) -> str:
    """Arm D (concept-translation only): interpretations alone."""
    return (TRANSLATION_PREAMBLE + "\n\n"
            + _section_interpretations(package)
            + "\n\nQuestion: " + package["question"]
            + "\n" + ANSWER_INSTRUCTION)


def build_reasoning_prompt(package: dict) -> str:
    """Arm E (symbolic-reasoning only): graph + proof steps. The
    model must work out the final answer itself from the steps; the
    verified answer is never stated."""
    return (REASONING_PREAMBLE + "\n\n"
            + _section_graph(package)
            + "\n\n" + _section_reasoning(package)
            + "\n\nQuestion: " + package["question"]
            + "\n" + ANSWER_INSTRUCTION)


VARIANTS = ("full", "no_answer", "context", "translation",
            "reasoning")


def build_variant_prompt(package: dict, variant: str,
                         text: str | None = None) -> str:
    """One prompt per arm variant, from the same package."""
    if variant == "full":
        return build_handoff_prompt(package, include_answer=True)
    if variant == "no_answer":
        return build_handoff_prompt(package, include_answer=False)
    if variant == "context":
        return build_context_prompt(package, text or
                                    package["question"])
    if variant == "translation":
        return build_translation_prompt(package)
    if variant == "reasoning":
        return build_reasoning_prompt(package)
    raise ValueError(f"unknown handoff variant: {variant}")


# ---------------------------------------------------------------------------
# Coherence rubric (deterministic, 0-3 per item) + failure-mode flags
# ---------------------------------------------------------------------------

def _first_line_answer(raw: str | None, answer_kind: str):
    """The response's first line, normalized — the scored answer."""
    from eval.normalize import normalize_answer
    if raw is None:
        return None
    first = raw.strip().splitlines()[0] if raw.strip() else ""
    return normalize_answer(first, answer_kind)


def _content_tokens(package: dict) -> set[str]:
    """Lowercase content tokens from the package, for the grounding
    check: definition terms + meaning words, synonyms/antonyms,
    proof numbers, frame words (graph lines), interpretation words."""
    tokens: set[str] = set()
    for d in package["definitions"]:
        tokens.add(d["term"].lower())
        tokens.update(re.findall(r"[a-z]+", d["meaning"].lower()))
    for rels in package["lexicon"].values():
        tokens.update(t.lower() for t in rels["synonyms"])
        tokens.update(t.lower() for t in rels["antonyms"])
    for step in package["reasoning_steps"]:
        tokens.update(re.findall(r"[a-z]+|\d+(?:\.\d+)?",
                                 step.lower()))
    for ln in package["graph_lines"]:
        tokens.update(re.findall(r"[a-z]+|\d+(?:\.\d+)?",
                                 ln.lower()))
    for r in package["interpretations"]:
        if r.get("text"):
            tokens.update(re.findall(r"[a-z]+", r["text"].lower()))
    return {t for t in tokens if len(t) > 2}


def coherence_scores(raw: str | None, package: dict,
                     answer_kind: str) -> dict:
    """Deterministic coherence, 0-3:

    * C1 answer present — the first line normalizes to an answer.
    * C2 grounded explanation — there is an explanation line after
      the first, and it shares at least one content token with the
      NOVA package. Answer-only responses score 0 here (they are
      flagged separately as copied-without-reasoning).
    * C3 answer restated/supported — no explanation (answer-only),
      or the explanation contains the first-line answer's value
      (number: the value or its word form; yes/no: the word; text:
      a word from the first-line answer). An explanation that never
      mentions the stated answer scores 0 by design: it does not
      support the answer it follows.

    A human-read sample (20 items per arm, fluency 0-2) is scored
    separately by the run operator and recorded in the run summary;
    it is not computed here.
    """
    from eval.normalize import normalize_answer
    first_answer = _first_line_answer(raw, answer_kind)
    c1 = 1 if first_answer is not None else 0
    lines = (raw or "").strip().splitlines()
    explanation = " ".join(lines[1:]).strip()
    if not explanation:
        return {"c1_answer_present": c1,
                "c2_grounded_explanation": 0,
                "c3_answer_supported": 1 if c1 else 0,
                "coherence": c1 + (1 if c1 else 0),
                "copied_without_reasoning": True}
    expl_tokens = set(re.findall(r"[a-z]+|\d+(?:\.\d+)?",
                                 explanation.lower()))
    c2 = 1 if expl_tokens & _content_tokens(package) else 0
    # C3: does the explanation contain the stated answer's value?
    if first_answer is None:
        c3 = 0
    elif answer_kind == "number":
        val = str(first_answer)
        c3 = 1 if (val in expl_tokens
                   or f"${val}" in explanation
                   or str(first_answer) in explanation) else 0
    elif answer_kind == "yes_no":
        c3 = 1 if str(first_answer) in expl_tokens else 0
    else:  # text: a word from the first-line answer itself
        ans_words = set(re.findall(r"[a-z]+|\d+(?:\.\d+)?",
                                   str(first_answer).lower()))
        c3 = 1 if ans_words & expl_tokens else 0
    return {"c1_answer_present": c1,
            "c2_grounded_explanation": c2,
            "c3_answer_supported": c3,
            "coherence": c1 + c2 + c3,
            "copied_without_reasoning": False}
