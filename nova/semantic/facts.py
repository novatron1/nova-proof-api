"""Is-a / has-a / state fact extraction (stabilization, items 3-4).

The heuristic 5W1H tier only reads action sentences ("X gave Y $N").
These forms read the sentences it cannot:

* copula / is-a — "Jupiter is the largest planet.", "Mars is known as
  the Red Planet." -> ``is`` fact frames.
* adjective states — "The light is on.", "The store is open." -> ``state``
  fact frames, so the antonym relation can answer "Is the light off?"
  with a proven "no".
* has-a — "A spider has eight legs.", "A bicycle has two wheels." ->
  ``has`` fact frames carrying the per-unit count, which the
  knowledge-to-calculation bridge multiplies out.
* inability — "A penguin cannot fly." -> a negated action fact.
* has-a / per-unit / amount-paid questions — the question forms that
  read these facts back ("Does a hexagon have six sides?", "How many
  legs do two spiders have?", "How much money did Yusuf pay?").

Nothing is ever invented: a fact frame is only built from a sentence
that states it, and a question with no matching fact stays unknown.
"""

from __future__ import annotations

import re

from .frame import ConceptFrame, evidence as ev, normalize_person

# Adjective antonym pairs. The map is symmetric by construction: each
# key maps to its opposite, and the opposite maps back.
ANTONYM_ADJECTIVES = {
    "open": "closed", "closed": "open",
    "hot": "cold", "cold": "hot",
    "full": "empty", "empty": "full",
    "on": "off", "off": "on",
    "big": "small", "small": "big",
    "tall": "short", "short": "tall",
    "fast": "slow", "slow": "fast",
    "light": "dark", "dark": "light",
    "high": "low", "low": "high",
    "long": "short",
    "wide": "narrow", "narrow": "wide",
    "strong": "weak", "weak": "strong",
    "rich": "poor", "poor": "rich",
    "happy": "sad", "sad": "happy",
    "early": "late", "late": "early",
    "new": "old", "old": "new",
    "clean": "dirty", "dirty": "clean",
    "safe": "dangerous", "dangerous": "safe",
    "loud": "quiet", "quiet": "loud",
    "hard": "soft", "soft": "hard",
    "deep": "shallow", "shallow": "deep",
}

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "twenty": 20, "thirty": 30, "sixty": 60,
    "a": 1, "an": 1,
}

_ARTICLE = r"(?:a|an|the)\s+"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_number(token: str) -> float | int | None:
    """A digit or a number word -> a number, or None."""
    t = token.strip().lower()
    if t in NUMBER_WORDS:
        return NUMBER_WORDS[t]
    try:
        v = float(t)
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


def singular(noun: str | None) -> str | None:
    """A rough singular for matching ("legs" -> "leg", "bicycles" ->
    "bicycle", "octopuses" -> "octopus"). Strips "-es" after s/x/z/ch/sh
    ("octopuses", "glasses", "buses"), else a single trailing "s"
    (never "ss"). It is a matcher, not a stemmer: "horses" -> "hors"
    is wrong, but no such noun is in the data, and a missed match
    stays unknown rather than becoming a wrong answer."""
    if noun is None:
        return None
    w = noun.strip().lower()
    if w.endswith("ss"):
        return w
    if len(w) > 3 and w.endswith(("ses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    # Singulars ending in -us ("octopus", "bus", "cactus") are not
    # plurals: stripping the "s" would make "octopu" and break the
    # match against the plural ("octopuses" -> "octopus").
    if w.endswith("us"):
        return w
    if w.endswith("s") and len(w) > 2:
        return w[:-1]
    return w


def _same_word(a: str | None, b: str | None) -> bool:
    """Two nouns match if they are equal up to articles, case, and a
    trailing plural "s" ("spider" == "spiders", "leg" == "legs")."""
    if a is None or b is None:
        return False
    def norm(w: str) -> str:
        w = w.strip().lower()
        w = re.sub(r"^(a|an|the)\s+", "", w)
        return singular(w) or w
    return norm(a) == norm(b)


def _thing_matches(who: str | None, thing: str | None) -> bool:
    """A frame subject matches a question noun, allowing the
    normalize_person alias map as well ("bicycle" and "bicycles" both
    normalize to "Bike", so the has-a frame's who matches the
    question's plural noun)."""
    if _same_word(who, thing):
        return True
    return _same_word(normalize_person(who), normalize_person(thing))


def _clean_complement(text: str) -> str:
    return re.sub(r"^(a|an|the)\s+", "", text.strip(" .!?"),
                  flags=re.IGNORECASE).strip().lower() or None


# ---------------------------------------------------------------------------
# Statement forms -> fact frames
# ---------------------------------------------------------------------------

_HAS_A_RE = re.compile(
    # The article is optional: the renderer writes "A spider has 8
    # legs." but also "Spider has 8 legs." must parse.
    r"^(?:(?:a|an|the)\s+)?(.+?)\s+has\s+"
    r"(\d+(?:\.\d{1,2})?|one|two|three|four|five|six|seven|eight|nine|"
    r"ten|eleven|twelve|twenty|thirty|sixty)\s+(.+?)[.?!]?$",
    re.IGNORECASE)
_IS_NOT_RE = re.compile(
    r"^(.+?)\s+is\s+not\s+(?:the\s+|a\s+|an\s+)?(.+?)[.?!]?$",
    re.IGNORECASE)
_KNOWN_AS_RE = re.compile(
    r"^(.+?)\s+is\s+known\s+as\s+(?:the\s+|a\s+|an\s+)?(.+?)[.?!]?$",
    re.IGNORECASE)
_IS_RE = re.compile(
    r"^(.+?)\s+is\s+(?:the\s+|a\s+|an\s+)?(.+?)[.?!]?$",
    re.IGNORECASE)
_CANNOT_RE = re.compile(
    r"^(.+?)\s+can\s*not\s+(\w+)(?:\s+(.+?))?[.?!]?$",
    re.IGNORECASE)
_CANNOT2_RE = re.compile(
    r"^(.+?)\s+cannot\s+(\w+)(?:\s+(.+?))?[.?!]?$",
    re.IGNORECASE)
# "If someone is human, they are mortal." / "If something is a dog,
# it is an animal." — a universal rule, not a fact about "If someone".
_RULE_RE = re.compile(
    r"^if\s+(?:someone|something|anyone|anything)\s+is\s+"
    r"(?:a\s+|an\s+|the\s+)?(.+?),\s*(?:they|it|he|she)\s+"
    r"(?:is|are)\s+(?:a\s+|an\s+|the\s+)?(.+?)[.?!]?$",
    re.IGNORECASE)


def _fact_frame(kind_what: str, who, obj=None, quantity=None, units=None,
                rels=None, source_text=None, status="verified") -> ConceptFrame:
    return ConceptFrame(
        kind="fact", who=who, what=kind_what, object=obj,
        quantity=quantity, units=units, relationships=rels or [],
        polarity="positive", certainty="known", status=status,
        source_text=source_text,
        evidence=[ev("fact-extractor", source_text or "", "fact")])


def extract_rule_frame(sentence: str) -> ConceptFrame | None:
    """An "If someone/something is A, they/it is B" sentence -> a
    rule frame (kind "rule"), or None.

    The rule frame carries the antecedent class in ``object`` and the
    consequent in an ``implies`` relationship. It becomes NO fact —
    frame_to_fact only reads kind "fact" — so it can never pollute
    the premises with a garbage "is(if_someone, ...)" fact. The
    reasoner instantiates it against matching is(...) facts
    (universal instantiation, sound and deterministic).
    """
    m = _RULE_RE.match(sentence.strip())
    if not m:
        return None
    antecedent = _clean_complement(m.group(1))
    consequent = _clean_complement(m.group(2))
    if not antecedent or not consequent:
        return None
    return ConceptFrame(
        kind="rule", who=None, what="is", object=antecedent,
        relationships=[{"rel": "implies", "target": consequent}],
        polarity="positive", certainty="known", status="verified",
        source_text=sentence.strip(),
        evidence=[ev("fact-extractor", sentence.strip(), "rule")])


def extract_fact_frame(sentence: str) -> ConceptFrame | None:
    """A copula / has-a / cannot statement -> a fact frame, or None."""
    s = sentence.strip()
    # A conditional is not a fact: "If someone is a bird, they can
    # fly." must never become a garbage is-fact about "If someone".
    # Rule sentences are read by extract_rule_frame; anything the
    # rule parser cannot read stays unparsed, never mis-parsed.
    if s.lower().startswith("if "):
        return None
    # "A penguin cannot fly." / "A penguin can not fly."
    for rx in (_CANNOT_RE, _CANNOT2_RE):
        m = rx.match(s)
        if m:
            who = normalize_person(m.group(1))
            if who is None:
                return None
            obj = _clean_complement(m.group(3)) if m.group(3) else None
            return ConceptFrame(
                kind="fact", who=who, what=m.group(2).lower(),
                object=obj, polarity="negative", certainty="known",
                status="verified", source_text=s,
                evidence=[ev("fact-extractor", s, "fact")])
    # "A spider has eight legs." / "An hour has 60 minutes."
    m = _HAS_A_RE.match(s)
    if m:
        who = normalize_person(m.group(1))
        amount = parse_number(m.group(2))
        part = m.group(3).strip().lower()
        if who is None or amount is None or not part:
            return None
        return _fact_frame(
            "has", who, obj=part, quantity=amount, units=part,
            rels=[{"rel": "has_a", "target": part, "per_unit": amount}],
            source_text=s)
    # "Mars is known as the Red Planet."
    m = _KNOWN_AS_RE.match(s)
    if m:
        who = normalize_person(m.group(1))
        target = _clean_complement(m.group(2))
        if who is None or not target:
            return None
        return _fact_frame(
            "is", who, obj=target,
            rels=[{"rel": "is_a", "target": target}], source_text=s)
    # "The light is not on." — tried BEFORE the plain "is" form,
    # which would otherwise read the complement as "not on".
    m = _IS_NOT_RE.match(s)
    if m:
        who = normalize_person(m.group(1))
        complement = _clean_complement(m.group(2))
        if who is None or not complement:
            return None
        first = complement.split()[0]
        frame = _fact_frame(
            "state" if first in ANTONYM_ADJECTIVES else "is",
            who, obj=first if first in ANTONYM_ADJECTIVES else complement,
            rels=[{"rel": "state" if first in ANTONYM_ADJECTIVES
                   else "is_a",
                   "target": first if first in ANTONYM_ADJECTIVES
                   else complement}],
            source_text=s)
        frame.polarity = "negative"
        return frame
    # "Jupiter is the largest planet." / "The light is on."
    m = _IS_RE.match(s)
    if m:
        who = normalize_person(m.group(1))
        complement = _clean_complement(m.group(2))
        if who is None or not complement:
            return None
        first = complement.split()[0]
        if first in ANTONYM_ADJECTIVES:
            return _fact_frame(
                "state", who, obj=first,
                rels=[{"rel": "state", "target": first}], source_text=s)
        return _fact_frame(
            "is", who, obj=complement,
            rels=[{"rel": "is_a", "target": complement}], source_text=s)
    return None


# ---------------------------------------------------------------------------
# Question forms -> query frames
# ---------------------------------------------------------------------------

_COPULA_Q_RE = re.compile(
    # The leading article belongs to the subject ("Is the store
    # closed?" -> who="store"), not to the complement, so it is
    # consumed before the lazy subject — a lazy subject after the
    # article stops at the first split, which is the right one.
    r"^(is|are|was|were)\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+(.+?)[.?!]?$",
    re.IGNORECASE)
_HAS_Q_RE = re.compile(
    r"^(does|do|did)\s+(.+?)\s+have\s+"
    r"(\d+(?:\.\d{1,2})?|one|two|three|four|five|six|seven|eight|nine|"
    r"ten|eleven|twelve|twenty|thirty|sixty)\s+(.+?)[.?!]?$",
    re.IGNORECASE)
_PER_UNIT_DO_RE = re.compile(
    r"^How many\s+(.+?)\s+do\s+"
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|twenty|thirty|sixty)\s+(.+?)\s+have[.?!]?\s*$",
    re.IGNORECASE)
_PER_UNIT_IN_RE = re.compile(
    r"^How many\s+(.+?)\s+are\s+in\s+"
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|twenty|thirty|sixty)\s+(.+?)[.?!]?\s*$",
    re.IGNORECASE)
_AMOUNT_PAID_RE = re.compile(
    r"^How much money did\s+(.+?)\s+(pay|spend|give|send)[.?!]?$",
    re.IGNORECASE)
_MODAL_Q_RE = re.compile(
    # Greedy subject: a lazy (.+?) stops at the article ("Can a
    # penguin fly?" -> who="a", verb="penguin").
    r"^(can|could)\s+(.+)\s+(\w+)(?:\s+(.+?))?[.?!]?$",
    re.IGNORECASE)


def _query_frame(who, what, source_text, obj=None, quantity=None,
                 units=None, rels=None) -> ConceptFrame:
    return ConceptFrame(
        kind="query", who=who, what=what, object=obj, quantity=quantity,
        units=units, relationships=rels or [],
        polarity="positive", certainty="known", status="verified",
        source_text=source_text,
        evidence=[ev("fact-extractor", source_text, "query")])


def extract_copula_question(sentence: str) -> ConceptFrame | None:
    """'Is X Y?' -> a yes/no goal frame (is_a or state)."""
    m = _COPULA_Q_RE.match(sentence.strip())
    if not m:
        return None
    who = normalize_person(m.group(2))
    complement = _clean_complement(m.group(3))
    if who is None or not complement:
        return None
    first = complement.split()[0]
    if first in ANTONYM_ADJECTIVES:
        return _query_frame(
            who, "state", sentence.strip(), obj=first,
            rels=[{"rel": "asks_whether", "target": "state"},
                  {"rel": "state", "target": first}])
    return _query_frame(
        who, "is", sentence.strip(), obj=complement,
        rels=[{"rel": "asks_whether", "target": "is"},
              {"rel": "is_a", "target": complement}])


def extract_has_question(sentence: str) -> ConceptFrame | None:
    """'Does X have N <part>?' -> a yes/no goal frame."""
    m = _HAS_Q_RE.match(sentence.strip())
    if not m:
        return None
    who = normalize_person(m.group(2))
    amount = parse_number(m.group(3))
    part = m.group(4).strip().lower()
    if who is None or amount is None or not part:
        return None
    return _query_frame(
        who, "has", sentence.strip(), obj=part, quantity=amount,
        units=part,
        rels=[{"rel": "asks_whether", "target": "has"},
              {"rel": "has_a", "target": part, "amount": amount}])


def extract_per_unit_question(sentence: str) -> ConceptFrame | None:
    """'How many <part> do N <things> have?' / '... are in N <things>?'
    -> a per-unit-total query frame."""
    for rx in (_PER_UNIT_DO_RE, _PER_UNIT_IN_RE):
        m = rx.match(sentence.strip())
        if m:
            part = m.group(1).strip().lower()
            count = parse_number(m.group(2))
            thing = m.group(3).strip().lower()
            if not part or count is None or not thing:
                return None
            return _query_frame(
                None, "per_unit_total", sentence.strip(), obj=part,
                quantity=count, units=part,
                rels=[{"rel": "asks_whether", "target": "per_unit_total"},
                      {"rel": "per_unit_of", "target": thing}])
    return None


def extract_amount_paid_question(sentence: str) -> ConceptFrame | None:
    """'How much money did X pay?' -> an amount-paid query frame."""
    m = _AMOUNT_PAID_RE.match(sentence.strip())
    if not m:
        return None
    who = normalize_person(m.group(1))
    if who is None:
        return None
    return _query_frame(
        who, "amount_paid", sentence.strip(),
        rels=[{"rel": "asks_whether", "target": "amount_paid"}])


def extract_modal_question(sentence: str) -> ConceptFrame | None:
    """'Can X <verb>?' -> a yes/no goal frame."""
    m = _MODAL_Q_RE.match(sentence.strip())
    if not m:
        return None
    who = normalize_person(m.group(2))
    verb = m.group(3).lower()
    obj = _clean_complement(m.group(4)) if m.group(4) else None
    if who is None:
        return None
    return _query_frame(
        who, verb, sentence.strip(), obj=obj,
        rels=[{"rel": "asks_whether", "target": verb}])


# ---------------------------------------------------------------------------
# Knowledge-to-calculation bridge
# ---------------------------------------------------------------------------

def find_per_unit_fact(frames: list[ConceptFrame], knowledge,
                       thing: str | None, part: str | None
                       ) -> tuple[float | int, list[dict]] | None:
    """Find "one <thing> has N <part>" — first in the statement frames,
    then in the knowledge store (whose meanings are parsed with the
    same has-a extractor). Returns (per_unit, evidence) or None."""
    if thing is None or part is None:
        return None
    for f in frames:
        if f.kind != "fact" or f.what != "has":
            continue
        if f.quantity is None:
            continue
        if _thing_matches(f.who, thing) and _same_word(f.object, part):
            return f.quantity, list(f.evidence)
    if knowledge is None:
        return None
    try:
        entries = knowledge.db.execute(
            "SELECT kind, term, meaning, source FROM entries").fetchall()
    except Exception:
        return None
    for _kind, term, meaning, source in entries:
        if not _same_word(term, thing):
            continue
        fact = extract_fact_frame(meaning)
        if fact is not None and fact.what == "has" \
                and _same_word(fact.object, part) \
                and fact.quantity is not None:
            return fact.quantity, [ev(source, meaning, "retrieval")]
    return None
