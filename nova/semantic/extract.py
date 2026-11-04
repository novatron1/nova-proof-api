"""Natural language -> shared ConceptFrame.

Two tiers, in order:

1. **Deterministic** — the money engine's own parser (`parse_sentence`).
   Exact, single-name transfers and balance questions. Frames from this
   tier have certainty="known" and status="verified".
2. **Heuristic** — the vendored adapter's 5W1H extractor, plus structured
   quantity/recipient/object recovery. This tier closes the known v0.3 gap:
   in "Marcus gave his sister $50", the amount no longer stays trapped
   inside a text field — it becomes quantity=50, units="dollars", and
   recipient="Sister". Frames from this tier have certainty="uncertain"
   and status="candidate_interpretation", because the parse itself is a
   heuristic even when the arithmetic that follows is exact.

Nothing is ever invented: a slot with no evidence stays ``None``, a
negated statement stays negative, and an unrecognized verb yields no
action (status "unknown") instead of a guessed frame.
"""

from __future__ import annotations

import re

from ..adapter.concepts import NEGATORS, concept_frame as _adapter_frame
from ..adapter.language import VERBS, extract as _heuristic_extract
from ..adapter.language import normalize as _normalize_token
from ..concept.events import BalanceQuery, Transfer, parse_sentence
from .facts import (extract_amount_paid_question,
                    extract_copula_question, extract_fact_frame,
                    extract_has_question, extract_modal_question,
                    extract_per_unit_question, extract_rule_frame)
from .frame import ConceptFrame, evidence as ev
from .frame import normalize_person  # noqa: F401 - re-exported for callers
from .router import route_sentence

# Base-form verbs the vendored extractor's small verb set lacks. These
# are a semantic-layer extension (the vendored file is not modified):
# without them, a question like "Did Marcus pay John?" (base form "pay")
# has no verb at all and yields no frame. The vendored map has the
# inflected forms (paid/pays, sent/sends, ...) but systematically lacks
# the base forms pay, send, purchase, approach, leave, visit, carry.
_EXTRA_VERBS = {"pay": "pay", "send": "send", "purchase": "purchase",
                "approach": "approach", "leave": "leave", "visit": "visit",
                "carry": "carry", "sell": "sell", "sold": "sell",
                "took": "take", "take": "take", "handed": "give",
                "hand": "give", "lent": "lend", "lend": "lend",
                "borrowed": "borrow", "borrow": "borrow",
                "produce": "produce", "produces": "produce",
                "make": "make", "makes": "make",
                "receive": "receive", "receives": "receive"}
_ALL_VERBS = {**VERBS, **_EXTRA_VERBS}

# Negators the vendored set lacks ("cannot" is a negation, not an
# action). Used to keep a negated heuristic sentence negative even
# when the adapter's own polarity check misses the word. "refused"
# (v1.5) negates its complement: "refused to refund" is a refund
# that did NOT happen, and must never restore money.
_EXTRA_NEGATORS = {"cannot", "can't", "cant", "couldnt", "couldn't",
                   "refused"}

# Tokens that must never be mistaken for the actor when picking "who"
# from the words before the verb ("John did not give ..." -> who is John,
# not "not"; "Did Marcus give ...?" -> who is Marcus, not "Did").
_JUNK_WHO = {
    "did", "does", "do", "is", "are", "was", "were", "has", "have", "had",
    "not", "never", "no", "didnt", "didn't", "doesnt", "doesn't",
    "dont", "don't", "the", "a", "an", "his", "her", "their", "my",
    "yesterday", "today", "tomorrow",
}

_AUX_QUESTION = re.compile(
    r"^(did|does|do|is|are|was|were|has|have)\b\s+(.+?)[.?!]?\s*$",
    re.IGNORECASE)

# Balance questions with multi-word persons ("his sister"), which the
# deterministic single-name parser cannot express.
_BALANCE_MULTI = re.compile(
    r"^How much (?:money )?does (.+?) have(?: left)?"
    r"(?: from the \$?(\d+(?:\.\d{1,2})?))?[.?!]?$", re.IGNORECASE)
_BALANCE_FROM_MULTI = re.compile(
    r"^How much (?:money )?is left from the \$?(\d+(?:\.\d{1,2})?) "
    r"(.+?) gave (.+?)[.?!]?$", re.IGNORECASE)

# Balance yes/no questions: "Does Tara have $90?" / "Did Omar have $45?"
# The inner statement ("Tara have $90") has no action verb the
# extractors know ("have" is a state, not an action), so it gets its
# own form: a query frame carrying the asked amount, answered from
# the ledger — never from a guessed fact.
_HAVE_YES_NO = re.compile(
    r"^(does|do|did)\s+(.+?)\s+have\s+\$?(\d+(?:\.\d{1,2})?)"
    r"(?:\s+(?:dollars|bucks|money))?[.?!]?$", re.IGNORECASE)

_MONEY_AMOUNT = re.compile(r"\$(\d+(?:\.\d{1,2})?)")
_NUMBER_UNIT = re.compile(
    r"(\d+(?:\.\d{1,2})?)\s*(dollars|bucks|euros|pounds|bicycles|bikes|"
    r"cars|books|items|apples|tickets|shares)", re.IGNORECASE)
_NUMBER_WORD = re.compile(r"(\d+(?:\.\d{1,2})?)\s+([A-Za-z]+)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s.strip()]


def _negated(sentence: str) -> bool:
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", sentence.lower())
    return any(w in NEGATORS for w in words)


def _quantity_from_text(text: str) -> tuple[float | int | None, str | None]:
    """Structured (quantity, units) from a sentence tail, or (None, None).

    "$50" -> (50, "dollars"). "25 euros" -> (25, "euros").
    A bare number with no unit is NOT claimed as money.
    """
    m = _MONEY_AMOUNT.search(text)
    if m:
        v = float(m.group(1))
        return (int(v) if v.is_integer() else v), "dollars"
    m = _NUMBER_UNIT.search(text)
    if m:
        v = float(m.group(1))
        return (int(v) if v.is_integer() else v), m.group(2).lower()
    return None, None


def _who_from_prefix(sentence: str) -> str | None:
    """Actor = last meaningful word before the first known verb."""
    words = list(re.finditer(r"\b[\w'-]+\b", sentence))
    vi = next((i for i, w in enumerate(words)
               if w.group().lower() in _ALL_VERBS), None)
    if vi is None or vi == 0:
        return None
    prefix = [w.group() for w in words[:vi]
              if w.group().lower() not in _JUNK_WHO]
    return prefix[-1] if prefix else None


def _fallback_verb_slots(sentence: str, raw_frame: dict) -> dict:
    """When the vendored extractor finds no verb, retry with the
    extended verb set. The when/where/why/how slots come from the
    vendored parse (they do not depend on the verb); only who/what/
    to_whom_or_object are recomputed."""
    words = list(re.finditer(r"\b[\w'-]+\b", sentence))
    vi = next((i for i, w in enumerate(words)
               if w.group().lower() in _EXTRA_VERBS), None)
    if vi is None:
        return raw_frame
    tail = sentence[words[vi].end():]
    tail = re.split(r"\b(?:because|since|yesterday|today|tomorrow|at|in|on|using|by)\b",
                    tail, maxsplit=1, flags=re.IGNORECASE)[0].strip(" .,!?")
    frame = dict(raw_frame)
    frame["who"] = _who_from_prefix(sentence)
    frame["what"] = _ALL_VERBS[words[vi].group().lower()]
    frame["to_whom_or_object"] = tail or None
    return frame


# ---------------------------------------------------------------------------
# Tier 1: deterministic money frames
# ---------------------------------------------------------------------------

def _transfer_to_frame(transfer: Transfer, source_text: str) -> ConceptFrame:
    if transfer.kind == "refund":
        amt_txt = ("an unstated amount" if transfer.amount is None
                   else f"${transfer.amount:g}")
        return ConceptFrame(
            kind="transfer", who=transfer.giver, what="refund",
            recipient=transfer.recipient, object="dollars",
            quantity=transfer.amount, units="dollars",
            polarity="positive", certainty="known", status="verified",
            source_text=source_text,
            evidence=[ev("money-parser",
                         f"{transfer.giver} refunded {transfer.recipient} "
                         f"{amt_txt}",
                         "transfer")])
    return ConceptFrame(
        kind="transfer", who=transfer.giver, what="give",
        recipient=transfer.recipient, object="dollars",
        quantity=transfer.amount, units="dollars",
        polarity="positive", certainty="known", status="verified",
        source_text=source_text,
        evidence=[ev("money-parser",
                     f"{transfer.giver} gave {transfer.recipient} "
                     f"${transfer.amount:g}",
                     "transfer")])


def _balance_to_frame(q: BalanceQuery, source_text: str) -> ConceptFrame:
    rels = []
    if q.scope_giver is not None:
        rels.append({"rel": "scoped_from", "target": q.scope_giver})
    return ConceptFrame(
        kind="query", who=q.person, what="balance",
        quantity=q.scope_amount,
        units="dollars" if q.scope_amount is not None else None,
        relationships=rels,
        polarity="positive", certainty="known", status="verified",
        source_text=source_text,
        evidence=[ev("money-parser",
                     f"balance query for {q.person}", "query")])


def _semantic_balance(sentence: str) -> BalanceQuery | None:
    """Balance questions the single-name parser cannot express."""
    m = _BALANCE_FROM_MULTI.match(sentence.strip())
    if m:
        amt = float(m.group(1))
        giver = m.group(2).strip()
        # A relative "that" introduces the clause ("from the $130
        # that Nils gave Pavel"); it is not part of the giver's
        # name. Left in, the scope's giver resolved to no lot and
        # the balance certified $0 (the v14-022 leak, v1.5).
        if giver.lower().startswith("that "):
            giver = giver[5:]
        return BalanceQuery(
            person=normalize_person(m.group(3)),
            scope_amount=int(amt) if amt.is_integer() else amt,
            scope_giver=normalize_person(giver))
    m = _BALANCE_MULTI.match(sentence.strip())
    if m:
        person = normalize_person(m.group(1))
        if person is None:
            return None
        # Only use this tier for multi-word persons; single names are
        # already handled deterministically (and identically).
        if " " not in m.group(1).strip():
            return None
        amt = float(m.group(2)) if m.group(2) else None
        return BalanceQuery(
            person=person,
            scope_amount=int(amt) if amt is not None and amt.is_integer() else amt)
    return None


# ---------------------------------------------------------------------------
# Tier 2: heuristic 5W1H frames with structured quantity recovery
# ---------------------------------------------------------------------------

def _heuristic_to_frame(sentence: str) -> ConceptFrame:
    raw = _heuristic_extract(sentence)
    adapter = _adapter_frame(sentence)
    slots = raw["frame"]
    if slots["what"] is None:
        slots = _fallback_verb_slots(sentence, slots)
    who = _who_from_prefix(sentence) or slots["who"]
    what = slots["what"]
    tail = slots["to_whom_or_object"] or ""
    quantity, units = _quantity_from_text(sentence)

    recipient, obj = None, None
    if tail:
        # Remove the amount text so it cannot masquerade as a person.
        tail_clean = _MONEY_AMOUNT.sub("", tail)
        tail_clean = _NUMBER_UNIT.sub("", tail_clean).strip(" .,!?")
        # A dangling preposition left by the amount removal ("a
        # bicycle for $120" -> "a bicycle for") must not leak into
        # the recipient or object.
        tail_clean = re.sub(
            r"\b(for|to|at|in|on|by|using)\s*$", "",
            tail_clean).strip(" .,!?")
        # "X to Y" -> object X, recipient Y. The split must also match
        # a leading "to": after the amount is stripped, "$7 to Felix"
        # leaves "to Felix", where "\s+to\s+" finds no split (no
        # whitespace before "to") and the recipient was silently lost.
        if " to " in f" {tail_clean.lower()} ":
            parts = re.split(r"(?:^|\s+)to\s+", tail_clean,
                             flags=re.IGNORECASE)
            obj = parts[0].strip(" .,!?") or None
            recipient = normalize_person(parts[-1]) if len(parts) > 1 else None
        elif quantity is not None and units in ("dollars", "bucks", "money"):
            if what in ("give", "send", "pay"):
                recipient = normalize_person(tail_clean)
                obj = units
            else:
                # A purchase tail is the object, not a recipient:
                # "purchased a bicycle for $120" is not a transfer
                # to "Bike For".
                obj = re.sub(r"^(a|an|the)\s+", "", tail_clean,
                             flags=re.IGNORECASE) or None
        elif tail_clean:
            first = tail_clean.split()[0]
            rest = " ".join(tail_clean.split()[1:]).strip()
            if first[:1].isupper() and rest:
                recipient = normalize_person(first)
                obj = re.sub(r"^(a|an|the)\s+", "", rest,
                             flags=re.IGNORECASE) or None
            else:
                obj = re.sub(r"^(a|an|the)\s+", "", tail_clean,
                             flags=re.IGNORECASE) or None
    # Normalize object nouns through the adapter's alias map so synonyms
    # join up ("bicycle" -> "bike", "automobile" -> "car").
    if obj:
        obj = " ".join(_normalize_token(w) for w in obj.split()).lower() or None

    # A negated event is a fact about what did NOT happen. Keep it, but
    # never let it become a positive transfer downstream. The adapter's
    # own negator set misses "cannot"/"can't", so check the extended
    # set here as well.
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", sentence.lower())
    polarity = ("negative"
                if adapter["polarity"] == "negative"
                or any(w in _EXTRA_NEGATORS for w in words)
                else "positive")
    action = what is not None
    return ConceptFrame(
        kind="transfer" if (what in ("give", "send", "pay")
                            and quantity is not None) else "event",
        who=normalize_person(who) if who else None,
        what=what,
        recipient=recipient,
        object=(obj.lower() if obj else
                (units if quantity is not None else None)),
        quantity=quantity,
        units=units,
        when=slots["when"],
        where=slots["where"],
        why=slots["why"],
        how=slots["how"],
        polarity=polarity,
        certainty="uncertain",
        status="candidate_interpretation" if action else "unknown",
        source_text=sentence,
        evidence=[ev("heuristic-5w1h", sentence, "extraction")])


def _have_yes_no_to_frame(sentence: str) -> ConceptFrame | None:
    """'Does X have $N?' -> a balance yes/no query frame, or None.

    The frame carries the asked amount and an ``asks_whether``
    relationship so the reasoner answers it from the ledger instead
    of routing it through the propositional goal path.
    """
    m = _HAVE_YES_NO.match(sentence.strip())
    if not m:
        return None
    person = normalize_person(m.group(2))
    if person is None:
        return None
    amt = float(m.group(3))
    amount = int(amt) if amt.is_integer() else amt
    return ConceptFrame(
        kind="query", who=person, what="balance",
        quantity=amount, units="dollars",
        polarity="positive", certainty="known", status="verified",
        source_text=sentence.strip(),
        relationships=[{"rel": "asks_whether", "target": "balance"},
                       {"rel": "has_amount", "target": amount}],
        evidence=[ev("money-parser",
                     f"balance yes/no: does {person} have ${amount:g}?",
                     "query")])


# ---------------------------------------------------------------------------
# Yes/no questions -> query frames carrying a goal fact
# ---------------------------------------------------------------------------

def _yes_no_to_frame(sentence: str,
                     allow_heuristic: bool = True) -> ConceptFrame | None:
    m = _AUX_QUESTION.match(sentence.strip())
    if not m:
        return None
    inner = m.group(2).strip()
    # Parse the inner statement as if it were asserted, then wrap it as
    # a question. The inner frame's polarity is the statement's own.
    inner_frames = parse_text_to_frames(inner,
                                        allow_heuristic=allow_heuristic)
    if not inner_frames:
        return None
    inner_frame = inner_frames[0]
    if inner_frame.what is None:
        return None
    inner_frame = ConceptFrame(
        **{**inner_frame.to_dict(), "kind": "query",
           "status": "candidate_interpretation"})
    inner_frame.relationships.append(
        {"rel": "asks_whether", "target": inner_frame.what})
    inner_frame.source_text = sentence
    return inner_frame


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_sentence_to_frame(sentence: str,
                             allow_heuristic: bool = True,
                             knowledge=None
                             ) -> ConceptFrame | None:
    """One sentence -> one shared frame, or None if nothing can be read.

    ``allow_heuristic=False`` disables tier 2 (the 5W1H heuristic
    extractor) — the eval harness uses this for module ablation, to
    measure what the deterministic tier alone can do. Default True
    preserves existing behaviour.

    ``knowledge`` is the Knowledge store the router consults for
    dictionary/encyclopedia questions; None means lookups fail
    honestly (unknown), which is what the empty production store
    does. Tier order matters: money forms first (so a balance
    question is never mistaken for a copula or a lookup), then the
    fact/router question forms, then the deterministic money parser,
    then the fact statements, then the heuristic tier.
    """
    s = sentence.strip()
    if not s:
        return None
    # Balance yes/no first: "Does Tara have $90?" — the inner "have"
    # statement has no action verb, so the generic yes/no path below
    # cannot read it.
    have_q = _have_yes_no_to_frame(s)
    if have_q is not None:
        return have_q
    # Fact question forms: per-unit totals, has-a yes/no, copula
    # yes/no, amount-paid, modal ("Can X ...?").
    for form in (extract_per_unit_question, extract_has_question,
                 extract_copula_question, extract_amount_paid_question,
                 extract_modal_question):
        q = form(s)
        if q is not None:
            return q
    # Yes/no questions first: "Did Marcus give John $20?"
    if _AUX_QUESTION.match(s):
        return _yes_no_to_frame(s, allow_heuristic=allow_heuristic)
    # Tier 1: deterministic money parser.
    try:
        parsed = parse_sentence(s)
    except Exception:
        parsed = None
    if isinstance(parsed, Transfer):
        return _transfer_to_frame(parsed, s)
    if isinstance(parsed, BalanceQuery):
        return _balance_to_frame(parsed, s)
    # Tier 1b: multi-word-person balance questions.
    sem_q = _semantic_balance(s)
    if sem_q is not None:
        return _balance_to_frame(sem_q, s)
    # Router: calculator / dictionary / encyclopedia / prove. It runs
    # after the money tiers so a money question is never misrouted,
    # and before the heuristic tier so a routed question is never
    # mangled into a spurious frame ("who: What, what: purchase").
    routed = route_sentence(s, knowledge=knowledge)
    if routed is not None:
        return routed
    # Fact statements: rules first (an "If someone is A, they are B"
    # sentence must become a rule frame, never a garbage is-fact
    # about "If someone"), then copula / is-a, has-a, "cannot".
    rule = extract_rule_frame(s)
    if rule is not None:
        return rule
    fact = extract_fact_frame(s)
    if fact is not None:
        return fact
    # Tier 2: heuristic 5W1H.
    if not allow_heuristic:
        return None
    frame = _heuristic_to_frame(s)
    if frame.what is None and not frame.known_slots():
        return None
    return frame


# Clause boundaries inside one sentence (v1.5): a contrastive
# conjunction or a semicolon joining two clauses. Money stories
# state one event per clause — "Liam didn't give Lena $55, but Liam
# gave Samir $30" is TWO events (one negated, one real). Parsed as
# one sentence, the heuristic tier produced a single negated frame
# with a garbage recipient and the real $30 transfer was lost (the
# v14-020 miss: the story answered the full $90).
_CLAUSE_BOUNDARY = re.compile(
    r"\s*;\s*|,\s*(?:but|yet)\s+|\s+but\s+(?=[A-Z])",
    re.IGNORECASE)


def _split_clauses(sentence: str) -> list[str]:
    parts = _CLAUSE_BOUNDARY.split(sentence.strip())
    return [p.strip() for p in parts if p.strip()]


def _frames_for_sentence(sentence: str,
                         allow_heuristic: bool = True,
                         knowledge=None) -> list[ConceptFrame]:
    """One sentence -> its frames (usually one; several when the
    sentence joins clauses, v1.5).

    The whole sentence is parsed first and a verified (certainty
    "known") frame is kept exactly as before — clause handling only
    fires when the whole sentence did not deterministically parse,
    and even then only when at least one clause DOES parse
    deterministically: a deterministic clause parse is strictly
    more trustworthy than one heuristic frame smeared across both
    clauses. Questions are never split (a question's clauses are
    not independent events). Each clause is parsed on its own, so
    negation stays scoped to its own clause: the negated clause
    yields a negative frame (which never becomes a transfer) and
    the affirmative clause yields its real transfer.
    """
    frame = parse_sentence_to_frame(
        sentence, allow_heuristic=allow_heuristic, knowledge=knowledge)
    if frame is not None and frame.certainty == "known":
        return [frame]
    s = sentence.strip()
    if s.endswith("?") or _AUX_QUESTION.match(s):
        return [frame] if frame is not None else []
    clauses = _split_clauses(s)
    if len(clauses) > 1:
        clause_frames = []
        for clause in clauses:
            cf = parse_sentence_to_frame(
                clause, allow_heuristic=allow_heuristic,
                knowledge=knowledge)
            if cf is not None:
                clause_frames.append(cf)
        if any(cf.certainty == "known" for cf in clause_frames):
            return clause_frames
    return [frame] if frame is not None else []


def parse_text_to_frames(text: str,
                         allow_heuristic: bool = True,
                         knowledge=None) -> list[ConceptFrame]:
    """Full text -> shared frames, one per sentence (a compound
    sentence can contribute one frame per clause, v1.5).

    Sentences that match no tier return no frame; the caller sees the
    gap (fewer frames than sentences) instead of a fabricated parse.
    """
    frames = []
    for sentence in split_sentences(text):
        frames.extend(_frames_for_sentence(
            sentence, allow_heuristic=allow_heuristic,
            knowledge=knowledge))
    return frames


def find_query(frames: list[ConceptFrame]) -> ConceptFrame | None:
    for f in frames:
        if f.kind == "query":
            return f
    return None
