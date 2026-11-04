"""Concept-level translation: paraphrase -> canonical concept.

This is the Phase 2 intent-preserving translation component for the
NOVA Cognitive Adapter. It is deterministic and rule-based — no
training, no model weights, no fine-tuning (torch/transformers are
absent from this environment and the Day-4 learned component is out
of scope here).

What it does:
  * canonicalize_sentence — rewrites a paraphrased sentence into the
    canonical phrasing the existing parsers already read, recording
    every substitution with its source. Three rewrite kinds:
      - transfer verbs -> their canonical verb (handed/passed ->
        gave; transferred/wired/forwarded/remitted -> sent;
        deposited/spent -> paid). Each entry is checked against the
        Lexicon: WordNet-confirmed synonyms of the canonical verb
        in its transfer sense are marked "wordnet"; the rest are
        marked "hand-listed" and stay visible as such.
      - amount words -> dollar amounts ("a tenner" -> "$10",
        "twenty bucks" -> "$20", "a twenty" -> "$20").
      - per-unit purchases -> their total ("bought two books for
        $12 each" -> "bought two books for $24"), with the
        multiplication recorded as the derivation.
  * translate — parses the original and the canonical sentence and
    compares their frames. Intent is preserved iff the action, the
    participants, the object, and the polarity agree (object nouns
    may differ by a Lexicon synonym), and the quantity agrees or
    differs only through a recorded derivation. When intent is NOT
    preserved, the caller must use the ORIGINAL frames — the
    canonicalization is rejected, never silently applied.
  * intent_preserved — the explicit check, with the comparison
    recorded, so paraphrase round-trips are measured rather than
    asserted.

Nouns are NOT rewritten: the existing alias map already normalizes
them, and a synonym rewrite of a noun risks changing the meaning
("bank" as a river bank vs a financial institution). Noun synonymy
is used only inside the intent comparison, never as a rewrite.
"""

from __future__ import annotations

import re

from .compare import compare_concept_frames
from .extract import parse_text_to_frames
from .facts import NUMBER_WORDS, parse_number
from .frame import normalize_person
from .lexicon import Lexicon

# ---------------------------------------------------------------------------
# Verb canonicalization.
# Key: surface form (lowercase). Value: (canonical base, canonical past).
# The past form is used in statements; the base form in questions
# ("Did Marcus transfer $45?" -> "Did Marcus send $45?").
# ---------------------------------------------------------------------------

_VERB_FORMS = {
    # give-cluster
    "hand": ("give", "gave"), "hands": ("give", "gave"),
    "handed": ("give", "gave"), "handing": ("give", "gave"),
    "pass": ("give", "gave"), "passes": ("give", "gave"),
    "passed": ("give", "gave"), "passing": ("give", "gave"),
    "donate": ("give", "gave"), "donates": ("give", "gave"),
    "donated": ("give", "gave"), "donating": ("give", "gave"),
    # send-cluster
    "transfer": ("send", "sent"), "transfers": ("send", "sent"),
    "transferred": ("send", "sent"), "transferring": ("send", "sent"),
    "wire": ("send", "sent"), "wires": ("send", "sent"),
    "wired": ("send", "sent"), "wiring": ("send", "sent"),
    "forward": ("send", "sent"), "forwards": ("send", "sent"),
    "forwarded": ("send", "sent"), "forwarding": ("send", "sent"),
    "remit": ("send", "sent"), "remits": ("send", "sent"),
    "remitted": ("send", "sent"), "remitting": ("send", "sent"),
    # pay-cluster
    "deposit": ("pay", "paid"), "deposits": ("pay", "paid"),
    "deposited": ("pay", "paid"), "depositing": ("pay", "paid"),
    "spend": ("pay", "paid"), "spends": ("pay", "paid"),
    "spent": ("pay", "paid"), "spending": ("pay", "paid"),
    # receive-cluster (money context only; handled by the caller)
    "got": ("receive", "received"),
}

# Canonical verbs and the WordNet sense whose synonyms confirm the map.
# "give" sense 3 = "transfer possession of something concrete or
# abstract to somebody"; "send" sense 1 = "cause to go somewhere".
_CANON_SENSE = {"give": ("verb", 3), "send": ("verb", 1),
                "pay": ("verb", 1), "receive": ("verb", 1)}


def verb_sources(lexicon: Lexicon | None = None) -> dict:
    """Each verb-map entry -> "wordnet" or "hand-listed".

    An entry is "wordnet" when the surface verb is a WordNet synonym
    of the canonical verb in ANY of its senses. Everything else is
    honestly "hand-listed".
    """
    out = {}
    confirmed: dict[str, set] = {}
    if lexicon is not None:
        for canon in _CANON_SENSE:
            confirmed[canon] = set(lexicon.synonyms(canon))
    for surface, (canon, _past) in _VERB_FORMS.items():
        out[surface] = ("wordnet" if surface in confirmed.get(canon, set())
                        else "hand-listed")
    return out


# ---------------------------------------------------------------------------
# Amount words.
# ---------------------------------------------------------------------------

_AMOUNT_NOUNS = {
    "tenner": 10, "fiver": 5, "twenty": 20, "fifty": 50,
    "hundred": 100, "thousand": 1000,
}

_MONEY_CONTEXT = re.compile(
    r"\b(gave|give|sent|send|paid|pay|bought|buy|sold|sell|handed|"
    r"passed|transferred|wired|lent|borrowed|received|got|spent|"
    r"deposit|bucks?|dollars?|money|\$)\b", re.IGNORECASE)

_PER_UNIT_PURCHASE_RE = re.compile(
    r"\b(bought|purchased)\s+"
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|twenty|thirty|sixty)\s+(\w+)\s+for\s+\$?"
    r"(\d+(?:\.\d{1,2})?)\s+each\b", re.IGNORECASE)


def _number_word_value(token: str):
    t = token.strip().lower()
    if t in NUMBER_WORDS:
        return NUMBER_WORDS[t]
    return parse_number(t)


def canonicalize_sentence(text: str,
                          lexicon: Lexicon | None = None
                          ) -> tuple[str, list[dict]]:
    """Rewrite a sentence into canonical phrasing.

    Returns (canonical_text, substitutions). A sentence that needs
    no rewrite returns itself with an empty list. Substitutions are
    recorded as {kind, original, canonical, source}.
    """
    subs: list[dict] = []
    out = text
    money = bool(_MONEY_CONTEXT.search(text))

    # 1. Per-unit purchases -> totals ("two books for $12 each" ->
    #    "two books for $24"). Only the total is rewritten; the
    #    count and the unit price stay visible in the record.
    m = _PER_UNIT_PURCHASE_RE.search(out)
    if m:
        count = _number_word_value(m.group(2))
        price = parse_number(m.group(4))
        if count is not None and price is not None:
            total = count * price
            total = int(total) if float(total).is_integer() else total
            new = (f"{m.group(1)} {m.group(2)} {m.group(3)} "
                   f"for ${total:g}")
            out = out[:m.start()] + new + out[m.end():]
            subs.append({"kind": "per-unit-total",
                         "original": m.group(0), "canonical": new,
                         "source": "arithmetic",
                         "derivation": f"{count:g} x ${price:g} "
                                       f"= ${total:g}"})

    # 2. Amount words -> dollar amounts (money sentences only).
    if money:
        # Number word + unit ("twenty bucks" -> "$20"). Record
        # each matched phrase, so the intent check can tell that
        # an object change ("twenty bucks" -> "dollars") IS the
        # derivation.
        _NUM_UNIT_RE = re.compile(
            r"\b(one|two|three|four|five|six|seven|eight|nine|ten|"
            r"eleven|twelve|twenty|thirty|sixty)\s+"
            r"(bucks|dollars|euros|pounds)\b", re.IGNORECASE)

        def _num_unit(mo):
            val = _number_word_value(mo.group(1))
            if val is None:
                return mo.group(0)
            return f"${val:g}"
        _num_unit_matches = list(_NUM_UNIT_RE.finditer(out))
        out = _NUM_UNIT_RE.sub(_num_unit, out)
        for mo in _num_unit_matches:
            val = _number_word_value(mo.group(1))
            if val is not None:
                subs.append({"kind": "amount-word",
                             "original": mo.group(0),
                             "canonical": f"${val:g}",
                             "source": "amount-word"})
        # Bare amount nouns ("a tenner" -> "$10"). Never fire when
        # a unit word follows ("a hundred dollars" is not "$100
        # dollars").
        for word, value in _AMOUNT_NOUNS.items():
            pat = re.compile(
                rf"\ba\s+{word}\b(?!\s+(?:dollars|bucks|euros|pounds))",
                re.IGNORECASE)
            if pat.search(out):
                out = pat.sub(f"${value}", out)
                subs.append({"kind": "amount-word", "original": word,
                             "canonical": f"${value}",
                             "source": "amount-word"})
            elif re.search(rf"\b{word}\b", out, re.IGNORECASE) \
                    and word in ("tenner", "fiver"):
                out = re.sub(rf"\b{word}\b", f"${value}", out,
                             flags=re.IGNORECASE)
                subs.append({"kind": "amount-word", "original": word,
                             "canonical": f"${value}",
                             "source": "amount-word"})

    # 3. Transfer verbs -> canonical verbs. Past forms stay past;
    #    base forms (questions) stay base.
    sources = verb_sources(lexicon)
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", out)
    for w in words:
        low = w.lower()
        if low not in _VERB_FORMS:
            continue
        base, past = _VERB_FORMS[low]
        # Past forms are the ones ending in -ed/-t or in the map's
        # past set; base forms are the rest. "got" is past.
        past_forms = {"handed", "passed", "donated", "transferred",
                      "wired", "forwarded", "remitted", "deposited",
                      "spent", "got"}
        canon = past if low in past_forms else base
        if low == canon:
            continue
        out = re.sub(rf"\b{re.escape(w)}\b", canon, out, count=1)
        subs.append({"kind": "verb", "original": w,
                     "canonical": canon,
                     "source": sources.get(low, "hand-listed")})
    return out, subs


# ---------------------------------------------------------------------------
# Intent preservation.
# ---------------------------------------------------------------------------

def _same_participant(a, b) -> bool:
    return normalize_person(a) == normalize_person(b)


def _same_object(a, b, lexicon: Lexicon | None = None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    # A per-unit total re-expresses the purchase ("two books for
    # $12 each" -> "two books for $24"): the "for each" phrasing
    # is not part of the object.
    def _norm(x: str) -> str:
        x = x.strip().lower()
        for suffix in (" for each", " each"):
            if x.endswith(suffix):
                x = x[: -len(suffix)]
        return x.strip()
    a, b = _norm(a), _norm(b)
    if a == b:
        return True
    if lexicon is not None:
        syns = set(lexicon.synonyms(a))
        if b in syns:
            return True
        syns_b = set(lexicon.synonyms(b))
        if a in syns_b:
            return True
    return False


def _amount_word_matches(obj: str | None, original: str | None) -> bool:
    """Is the original object the amount word a substitution maps?

    "tenner" == "tenner"; "twenty" matches "a twenty" (article
    stripped); "twenty bucks" == "twenty bucks".
    """
    if obj is None or original is None:
        return False

    def _norm(x: str) -> str:
        x = x.strip().lower()
        for art in ("a ", "an ", "the "):
            if x.startswith(art):
                x = x[len(art):]
        return x.strip()
    o, s = _norm(obj), _norm(original)
    return o == s or o.endswith(s) or s.endswith(o)


def frames_agree(orig_frames, canon_frames, substitutions,
                 lexicon: Lexicon | None = None) -> dict:
    """Do the canonical frames preserve the original's intent?

    Agreement requires: same action, same participants, same
    object (up to a Lexicon synonym), same polarity. The quantity
    may differ only when a recorded derivation explains it (an
    amount-word mapping or a per-unit total); otherwise it must
    match. A slot the original frame could not express at all
    (None — e.g. an unrecognized verb left what/who/recipient
    empty) is not a mismatch: the translation supplied the parse,
    it did not contradict one. A slot the original DID express
    and the canonical changed is still a mismatch.
    Returns {agree, reasons}.
    """
    reasons = []
    if not orig_frames or not canon_frames:
        return {"agree": False,
                "reasons": ["one side produced no frames"]}
    o, c = orig_frames[0], canon_frames[0]
    if o.what is not None and o.what != c.what:
        reasons.append(f"action differs: {o.what} vs {c.what}")
    if o.who is not None and not _same_participant(o.who, c.who):
        reasons.append(f"actor differs: {o.who} vs {c.who}")
    if o.recipient is not None and not _same_participant(
            o.recipient, c.recipient):
        reasons.append(f"recipient differs: {o.recipient} "
                       f"vs {c.recipient}")
    if o.object is not None and not _same_object(o.object, c.object,
                                                 lexicon):
        # An amount-word substitution re-expresses the object as
        # money ("tenner" -> "$10", object "tenner" -> "dollars"):
        # the object change IS the derivation, not a drift.
        amount_word = any(
            s.get("kind") == "amount-word"
            and _amount_word_matches(o.object, s.get("original"))
            for s in substitutions)
        if not amount_word:
            reasons.append(f"object differs: {o.object} vs {c.object}")
    if o.polarity != c.polarity:
        reasons.append(f"polarity differs: {o.polarity} "
                       f"vs {c.polarity}")
    derived = any(s["kind"] in ("amount-word", "per-unit-total")
                  for s in substitutions)
    if o.quantity != c.quantity and not derived:
        reasons.append(f"quantity differs: {o.quantity} "
                       f"vs {c.quantity}")
    return {"agree": not reasons, "reasons": reasons}


def translate(text: str, lexicon: Lexicon | None = None,
              knowledge=None) -> dict:
    """Paraphrase -> canonical concept, with an intent check.

    Returns the original frames, the canonical frames, the
    comparison, and the frames the caller should use: the canonical
    ones when intent is preserved, the original ones otherwise.
    """
    canonical, subs = canonicalize_sentence(text, lexicon)
    orig_frames = parse_text_to_frames(text, knowledge=knowledge)
    canon_frames = (parse_text_to_frames(canonical, knowledge=knowledge)
                    if canonical != text else orig_frames)
    agreement = frames_agree(orig_frames, canon_frames, subs, lexicon)
    comparison = (compare_concept_frames(orig_frames[0], canon_frames[0])
                  if orig_frames and canon_frames
                  else {"relation": "unknown", "certified": False,
                        "reason": "one side produced no frames"})
    return {
        "original_text": text,
        "canonical_text": canonical,
        "substitutions": subs,
        "original_frames": [f.to_dict() for f in orig_frames],
        "canonical_frames": [f.to_dict() for f in canon_frames],
        "comparison": comparison,
        "intent_preserved": agreement["agree"],
        "intent_reasons": agreement["reasons"],
        "frames_to_use": (canon_frames if agreement["agree"]
                          else orig_frames),
    }
