"""Natural-language routing: questions -> the right module (item 1).

The frame parsers only read event sentences. These question forms
route to the module that can answer them — through the shared
ConceptFrame path, not ad-hoc string matching:

* calculator — "What is 12 * 15?" -> a calculation frame with the
  computed value (strict charset validation; anything else is not
  routed).
* dictionary — "What does 'serene' mean?" -> a definition frame
  from the knowledge store (unknown when the term is absent).
* encyclopedia — "What is the capital of France?" -> the store
  entry whose term/meaning best matches the question (unique best
  match required; a tie is unknown, never a guess).
* prove — "Prove that every cat is a mammal." -> a yes/no goal frame built
  from the goal clause, answered by the existing reasoner from the
  text's own facts.

Unroutable questions return None: the caller falls through to the
normal parse, which fails honestly instead of guessing.
"""

from __future__ import annotations

import re

from ..adapter.core import calculate
from .facts import _query_frame
from .frame import ConceptFrame, evidence as ev
from .translate import knowledge_hit_to_frame, list_knowledge_entries

_CALC_Q_RE = re.compile(
    r"^(?:what is|calculate|compute|work out)\s+(.+?)[.?!]?\s*$",
    re.IGNORECASE)
_ARITHMETIC = re.compile(r"^[0-9\s\+\-\*\/\(\)\.\%]+$")
_WORD_OPS = [
    ("multiplied by", "*"), ("divided by", "/"),
    ("squared", "**2"), ("cubed", "**3"),
    ("plus", "+"), ("minus", "-"), ("times", "*"), ("over", "/"),
]
_DICT_Q_RE = re.compile(
    r"^what does\s+['\"](.+?)['\"]\s+mean[.?!]?\s*$", re.IGNORECASE)
_DICT_Q_RE2 = re.compile(
    r"^what does\s+(.+?)\s+mean[.?!]?\s*$", re.IGNORECASE)
_DEFINE_RE = re.compile(
    r"^define\s+['\"]?(.+?)['\"]?[.?!]?\s*$", re.IGNORECASE)
_PROVE_RE = re.compile(
    r"^(?:prove|show)\s+(?:that\s+)?(.+?)[.?!]?\s*$", re.IGNORECASE)

_STOPWORDS = {
    "what", "which", "who", "whom", "whose", "when", "where", "why",
    "how", "many", "much", "does", "do", "did", "is", "are", "was",
    "were", "has", "have", "had", "can", "could", "the", "a", "an",
    "of", "to", "from", "in", "on", "at", "by", "for", "with", "as",
    "it", "its", "this", "that", "there", "here", "and", "or", "not",
}


def _calc_expression(sentence: str) -> str | None:
    """The arithmetic expression in a calculation question, or None.

    Word operators are translated, then the result must consist only
    of digits and arithmetic symbols — anything else is not a
    calculation and is not routed.
    """
    m = _CALC_Q_RE.match(sentence.strip())
    if not m:
        return None
    expr = m.group(1).strip()
    low = expr.lower()
    for word, op in _WORD_OPS:
        low = low.replace(word, op)
    low = low.replace(" ", "")
    if not low or not _ARITHMETIC.match(low):
        return None
    return low


def _dictionary_term(sentence: str) -> str | None:
    s = sentence.strip()
    for rx in (_DICT_Q_RE, _DICT_Q_RE2, _DEFINE_RE):
        m = rx.match(s)
        if m:
            term = m.group(1).strip(" '\"").strip()
            return term or None
    return None


def _content_words(text: str) -> set[str]:
    words = set(re.findall(r"[a-z]+(?:-[a-z]+)?", text.lower()))
    return {w for w in words if w not in _STOPWORDS}


def _encyclopedia_term(sentence: str, knowledge) -> str | None:
    """The store term a question is asking about, or None.

    Scores each entry by term-in-question plus shared content words
    with the term and its meaning. The best must beat the runner-up
    strictly — a tie means the question is ambiguous and is not
    routed.
    """
    if knowledge is None:
        return None
    entries = list_knowledge_entries(knowledge)
    if not entries:
        return None
    qwords = _content_words(sentence)
    low = sentence.lower()
    scored = []
    for kind, term, meaning, _source in entries:
        score = 0
        if re.search(r"\b" + re.escape(term.lower()) + r"\b", low):
            score += 3
        shared = qwords & _content_words(term + " " + meaning)
        score += len(shared)
        scored.append((score, term))
    scored.sort(key=lambda t: t[0], reverse=True)
    best, second = scored[0], scored[1] if len(scored) > 1 else (0, None)
    if best[0] >= 2 and best[0] > second[0]:
        return best[1]
    return None


def route_sentence(sentence: str, knowledge=None) -> ConceptFrame | None:
    """One question sentence -> a routed frame, or None if unroutable.

    Only question sentences (ending in "?") route to calculator /
    dictionary / encyclopedia; "Prove ..." also accepts a final ".".
    A routed frame carries its answer (calculation value, retrieved
    meaning) or an honest unknown when the lookup finds nothing.
    """
    s = sentence.strip()
    if not s:
        return None
    # Calculator / dictionary / encyclopedia route on "?" questions;
    # "Define X." is a dictionary request that ends with "." instead.
    if s.endswith("?") or s.lower().startswith("define "):
        expr = _calc_expression(s)
        if expr is not None:
            try:
                value = calculate(expr)
            except Exception:
                return None
            return ConceptFrame(
                kind="calculation", what="calculate", object=expr,
                quantity=value, units=None,
                polarity="positive", certainty="known",
                status="verified", source_text=s,
                evidence=[ev("local-calculator", expr, "computation")])
        term = _dictionary_term(s)
        if term is not None:
            hit = None
            if knowledge is not None:
                hit = knowledge.lookup("dictionary", term)
                if hit is None:
                    # "Define X" / "What does 'X' mean?" where X is an
                    # encyclopedia term, not a dictionary word: the
                    # definition is the encyclopedia entry.
                    hit = knowledge.lookup("encyclopedia", term)
                    if hit is not None:
                        return knowledge_hit_to_frame(
                            "encyclopedia", term, hit)
            return knowledge_hit_to_frame("dictionary", term, hit)
        # Encyclopedia lookup only for wh-questions. A yes/no
        # question ("Can a penguin fly?") is a goal for the reasoner,
        # not a lookup — the matcher must never hijack it.
        if re.match(r"^(can|could|did|does|do|is|are|was|were|has|have|"
                    r"had|should|would|will)\b", s, re.IGNORECASE):
            return None
        term = _encyclopedia_term(s, knowledge)
        if term is not None:
            hit = knowledge.lookup("encyclopedia", term)
            return knowledge_hit_to_frame("encyclopedia", term, hit)
    # Prove / show: the goal clause is parsed with the normal tiers
    # (including the fact tier), then wrapped as a yes/no goal frame.
    # The import is local: extract.py imports this module, so a
    # top-level import would be circular.
    m = _PROVE_RE.match(s)
    if m:
        from .extract import parse_text_to_frames
        clause = m.group(1).strip()
        goal_frames = parse_text_to_frames(clause)
        if not goal_frames or goal_frames[0].what is None:
            return None
        goal = goal_frames[0]
        return _query_frame(
            goal.who, goal.what, s, obj=goal.object,
            quantity=goal.quantity, units=goal.units,
            rels=[{"rel": "asks_whether", "target": goal.what}])
    return None
