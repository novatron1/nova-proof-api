"""The production lexicon: WordNet (primary) + Wiktionary (secondary).

This is the Phase 2 knowledge layer for the NOVA Cognitive Adapter.
It wraps the seeded SQLite store built by ``data/import_wordnet.py``
and ``data/import_wiktionary.py`` (``data/knowledge.db``) and adds
the operations the vendored ``Knowledge`` store cannot do:

* alias-aware, morph-aware lookup (inflected forms, synonyms of the
  lookup term, singular/plural variants),
* sense-scoped synonym / antonym / hypernym / hyponym / part relations
  from both sources (every relation carries its source),
* word-sense disambiguation (Lesk-style gloss overlap against the
  surrounding context; ties fall back to the most frequent sense),
* recursive definition decomposition — a definition is followed down
  through its component concepts (depth-capped, cycle-safe), and each
  level is also parsed into fact frames with ``defined_as``
  provenance,
* the per-unit bridge: an is-a numeric definition ("A dozen is 12")
  or a set-of-N definition ("a set of twelve") yields a per-unit
  count the knowledge-to-calculation bridge can multiply out.

Source hierarchy (user decision, Oct 26 11:12 PM): WordNet is the
PRIMARY structured semantic foundation; Wiktionary is the SECONDARY
vocabulary-expansion source. Both are subject to their licences
(WordNet License; CC BY-SA 4.0) — every row carries its source, and
``data/PROVENANCE.md`` records the full attribution.

Nothing here invents a fact: a term outside the store stays unknown,
a sense with no evidence for disambiguation returns the most
frequent sense labelled as such, and a decomposition that finds no
component concepts returns the single-level definition only.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..adapter.core import Knowledge
from ..adapter.language import ALIASES
from .facts import (NUMBER_WORDS, extract_fact_frame,
                    extract_rule_frame, parse_number, singular)

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "knowledge.db"

_STOPWORDS = {
    "a", "an", "the", "of", "to", "from", "in", "on", "at", "by",
    "for", "with", "as", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "do", "does", "did", "that", "which",
    "who", "what", "when", "where", "why", "how", "and", "or", "it",
    "its", "this", "that", "one", "two", "three", "some", "any",
    "into", "out", "up", "down",
    # Question-template words, not content: "What does 'orbit'
    # mean?" must not let "mean" match the gloss word "means"
    # ("by means of") and pick the social-media sense of "orbit".
    "mean", "means", "meaning", "define", "definition",
}

# Domain hints for disambiguation: when the context matches a
# domain pattern, its hint words join the context set (stated
# explicitly, not hidden). Money context is what lets "a tenner"
# resolve to the bill sense instead of the number sense.
#
# Each entry is (pattern, hints, term_sensitive): when
# term_sensitive is True, the pattern is matched against the
# context with the term itself removed — a general verb must not
# fire its own domain ("What does 'buy' mean?" must not let
# "buy" pick the bribery sense via the "payments" hint). Money
# nouns are NOT term-sensitive: "tenner" is unambiguously money
# even when it is the word being defined.
_DOMAIN_HINTS = [
    (re.compile(r"\b(tenner|fiver|bucks?|dollars?|money|\$|grand|"
                r"quid|deposit)\b",
                re.IGNORECASE),
     {"money", "dollar", "dollars", "currency", "bill", "payment",
      "price", "cost", "cash", "bank"},
     False),
    (re.compile(r"\b(gave|give|sent|send|paid|pay|bought|buy|sold|"
                r"sell|handed|passed|transferred|wired|lent|borrowed|"
                r"received|got|spent|deposit)\b", re.IGNORECASE),
     {"money", "dollar", "dollars", "currency", "bill", "payment",
      "price", "cost", "cash", "bank"},
     True),
    (re.compile(r"\b(swung|swing|baseball|home run|tennis|"
                r"football|soccer|golf|hit a ball)\b", re.IGNORECASE),
     {"ball", "game", "club", "swing", "sport", "play"},
     True),
    (re.compile(r"\b(light|lamp|room|dim|bright|darkness|"
                r"illuminate)\b", re.IGNORECASE),
     {"electromagnetic", "radiation", "visible", "illumination",
      "lamp", "brightness"},
     True),
]


def _stem(word: str) -> str:
    """A light stem for overlap scoring only (not a lemmatizer):
    strip -ing / -ed / -es / -s so "deposits" and "deposited"
    score as the same word. A doubled consonant is collapsed
    only when a suffix was actually stripped ("hitting" -> "hit",
    "stopped" -> "stop"); a bare word keeps its double ("bill"
    stays "bill", "class" stays "class")."""
    w = word.lower()
    stripped = False
    if len(w) > 4 and w.endswith("ing"):
        w = w[:-3]
        stripped = True
    elif len(w) > 3 and w.endswith("ed"):
        w = w[:-2]
        stripped = True
    elif len(w) > 3 and w.endswith("es"):
        w = w[:-2]
        stripped = True
    elif len(w) > 2 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
        stripped = True
    if stripped and len(w) > 2 and w[-1] == w[-2] \
            and w[-1] not in "aeious":
        w = w[:-1]
    return w

_SET_OF_N = re.compile(
    r"\b(?:a\s+)?(?:set|group|collection)\s+of\s+"
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|twenty|thirty|sixty)\b", re.IGNORECASE)
# "with N <plural noun>" — the has-a phrasing WordNet uses when
# the definition does not say "has": "predatory arachnid with
# eight legs" -> spider has eight legs. The object is one or two
# words ("four equal sides"); the noun is the last word.
# It ends at "and", a comma, or the sentence end.
_WITH_N = re.compile(
    r"\bwith\s+(\w+)\s+([a-z]+(?:\s+[a-z]+)?)"
    r"(?:\s+and\b|,|\.|;|$)", re.IGNORECASE)
# Bare noun-phrase definition: "an eight-sided polygon".
_BARE_NP = re.compile(r"^(?:a|an|the)\s+(.+)$", re.IGNORECASE)
_N_SIDED = re.compile(
    r"^(\w+)-sided\b", re.IGNORECASE)


def _part_matches(units: str, part: str) -> bool:
    """Plural-insensitive part match ("sides" == "side")."""
    u = units.strip().lower().rstrip("s")
    p = part.strip().lower().rstrip("s")
    return u == p and bool(u)


def _content_words(text: str, stem: bool = False) -> set[str]:
    words = set(re.findall(r"[a-z]+(?:-[a-z]+)?", text.lower()))
    out = {w for w in words if w not in _STOPWORDS and len(w) > 1}
    return {_stem(w) for w in out} if stem else out


class Lexicon:
    """WordNet + Wiktionary, read from the seeded store."""

    def __init__(self, db_path: Path | str | None = None,
                 knowledge: Knowledge | None = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        if knowledge is not None:
            self.knowledge = knowledge
            self.db = knowledge.db
        elif self.db_path.exists():
            self.db = sqlite3.connect(self.db_path)
            self.knowledge = Knowledge()
            self.knowledge.db = self.db
        else:
            self.db = sqlite3.connect(":memory:")
            self.knowledge = Knowledge()
            self.knowledge.db = self.db
        self._has_relations = self._table_exists("relations")
        self._has_senses = self._table_exists("senses")
        self._has_morph = self._table_exists("morph")

    def _table_exists(self, name: str) -> bool:
        try:
            return self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name=?", (name,)).fetchone() is not None
        except Exception:
            return False

    # -- lookup ------------------------------------------------------
    def _lemma_candidates(self, term: str) -> list[str]:
        """Base forms for a term: itself, alias map, morph table,
        singular/plural variants — in that order."""
        t = term.strip().lower()
        cands: list[str] = []
        for c in (t, ALIASES.get(t, t)):
            if c and c not in cands:
                cands.append(c)
        if self._has_morph:
            try:
                rows = self.db.execute(
                    "SELECT lemma FROM morph WHERE surface=?",
                    (t,)).fetchall()
                for (lemma,) in rows:
                    if lemma not in cands:
                        cands.append(lemma)
            except Exception:
                pass
        sing = singular(t)
        if sing and sing not in cands:
            cands.append(sing)
        if not t.endswith("s") and t + "s" not in cands:
            cands.append(t + "s")
        return cands

    def lookup(self, term: str, kind: str = "dictionary"
               ) -> dict | None:
        """Alias- and morph-aware lookup; None when absent.

        Falls back to the reverse synonym graph: "auto" is not an
        entry, but it is a synonym of "automobile", so the lookup
        returns the "automobile" entry. The returned dict carries
        the entry's own term, so callers can tell the resolution
        happened.
        """
        for cand in self._lemma_candidates(term):
            hit = self.knowledge.lookup(kind, cand)
            if hit is not None:
                return hit
        rows = self.db.execute(
            "SELECT DISTINCT term FROM relations "
            "WHERE rel='synonym' AND target=?",
            (term.strip().lower(),)).fetchall()
        for (canon,) in rows:
            hit = self.knowledge.lookup(kind, canon)
            if hit is not None:
                return {**hit, "resolved_from": term.strip().lower()}
        return None

    def senses(self, term: str) -> list[dict]:
        """All senses for a term (WordNet first, then Wiktionary)."""
        if not self._has_senses:
            return []
        rows = []
        for cand in self._lemma_candidates(term):
            rows = self.db.execute(
                "SELECT pos, sense_no, gloss, source FROM senses "
                "WHERE term=? ORDER BY "
                "CASE WHEN source='wordnet-3.0' THEN 0 ELSE 1 END, "
                "sense_no",
                (cand,)).fetchall()
            if rows:
                break
        return [{"pos": p, "sense_no": n, "gloss": g, "source": s}
                for p, n, g, s in rows]

    def multiword_terms(self) -> list[str]:
        """Store terms containing a space, longest first.

        Used by the production path's longest-match patch so a
        question about "boiling point" answers from that term
        rather than from "boiling".
        """
        rows = self.db.execute(
            "SELECT DISTINCT term FROM entries WHERE term LIKE '% %'"
            ).fetchall()
        return sorted((r[0] for r in rows), key=len, reverse=True)

    def search_meaning(self, phrase: str) -> list[dict]:
        """Entries whose meaning contains ``phrase`` (case-insensitive).

        Used by the production path's superlative patch: "What is
        the largest planet?" is answered by the entry whose gloss
        says "the largest planet" (Jupiter), not by the entry for
        "planet". Returns entries in no particular order.
        """
        rows = self.db.execute(
            "SELECT term, meaning, source FROM entries "
            "WHERE lower(meaning) LIKE ?",
            ("%" + phrase.strip().lower() + "%",)).fetchall()
        return [{"term": t, "meaning": m, "source": s}
                for t, m, s in rows]

    # -- relations ---------------------------------------------------
    def relations(self, term: str, rel: str | None = None,
                  pos: str | None = None,
                  sense_no: int | None = None) -> list[dict]:
        """Sense-scoped relations for a term, source-tagged."""
        if not self._has_relations:
            return []
        out: list[dict] = []
        for cand in self._lemma_candidates(term):
            q = ("SELECT rel, target, pos, sense_no, source "
                 "FROM relations WHERE term=?")
            args: list = [cand]
            if rel is not None:
                q += " AND rel=?"
                args.append(rel)
            if pos is not None:
                q += " AND pos=?"
                args.append(pos)
            if sense_no is not None:
                q += " AND sense_no=?"
                args.append(sense_no)
            q += " ORDER BY source, sense_no"
            rows = self.db.execute(q, args).fetchall()
            if rows:
                out = [{"rel": r, "target": t, "pos": p, "sense_no": n,
                        "source": s} for r, t, p, n, s in rows]
                break
        return out

    def synonyms(self, term: str, pos: str | None = None,
                 sense_no: int | None = None) -> list[str]:
        return [r["target"] for r in self.relations(
            term, "synonym", pos, sense_no)]

    def antonyms(self, term: str, pos: str | None = None,
                 sense_no: int | None = None) -> list[str]:
        return [r["target"] for r in self.relations(
            term, "antonym", pos, sense_no)]

    def hypernyms(self, term: str, pos: str | None = None,
                  sense_no: int | None = None) -> list[str]:
        return [r["target"] for r in self.relations(
            term, "hypernym", pos, sense_no)]

    def hyponyms(self, term: str, pos: str | None = None,
                 sense_no: int | None = None) -> list[str]:
        return [r["target"] for r in self.relations(
            term, "hyponym", pos, sense_no)]

    def parts(self, term: str, pos: str | None = None,
              sense_no: int | None = None) -> list[str]:
        return [r["target"] for r in self.relations(
            term, "part_meronym", pos, sense_no)]

    # -- word-sense disambiguation -----------------------------------
    def disambiguate(self, term: str, context: str | None = None
                     ) -> dict | None:
        """Pick the sense of ``term`` that fits ``context`` (Lesk).

        Each sense is scored by content-word overlap between its
        gloss and the context; ties go to the lowest sense number
        (most frequent). With no context, sense 1 is returned and
        labelled as the frequency fallback, not as a disambiguation.
        """
        senses = self.senses(term)
        if not senses:
            return None
        if not context:
            best = senses[0]
            return {**best, "score": 0, "runner_up": 0,
                    "method": "frequency-fallback"}
        ctx = _content_words(context, stem=True)
        for pattern, hints, term_sensitive in _DOMAIN_HINTS:
            haystack = context
            if term_sensitive:
                haystack = re.sub(
                    r"\b" + re.escape(term.strip().lower()) + r"\b",
                    " ", context, flags=re.IGNORECASE)
            if pattern.search(haystack):
                ctx |= hints
        term_stem = _stem(term.strip().lower())
        scored = []
        for s in senses:
            gloss_words = _content_words(s["gloss"], stem=True)
            gloss_words.discard(term_stem)
            score = len(gloss_words & ctx)
            scored.append((score, s))
        scored.sort(key=lambda t: (-t[0], t[1]["sense_no"]))
        best_score, best = scored[0]
        runner = scored[1][0] if len(scored) > 1 else 0
        # The score of the frequency-primary sense (senses[0]),
        # so callers can tell whether a non-primary sense has
        # positive evidence over the primary.
        primary_score = next(
            (sc for sc, s in scored if s is senses[0]), 0)
        return {**best, "score": best_score, "runner_up": runner,
                "primary_score": primary_score,
                "method": "lesk-overlap"}

    # -- definition decomposition ------------------------------------
    def decompose_definition(self, meaning: str) -> list[dict]:
        """Parse a definition string into fact/rule frames.

        The fact extractors read is-a / has-a / state / cannot
        sentences; a "set of N" / "group of N" phrasing yields a
        per-unit count frame. Each returned frame carries
        ``defined_as`` provenance. A definition that parses into
        nothing returns an empty list — never a guessed frame.
        """
        frames = []
        if not meaning:
            return frames
        text = meaning.strip()
        for extractor in (extract_rule_frame, extract_fact_frame):
            f = extractor(text)
            if f is not None:
                f.relationships.append(
                    {"rel": "defined_as", "target": text})
                d = f.to_dict()
                # A definition is one sentence; the has-a re-parse
                # can over-grab the rest of the sentence into the
                # object ("wheels and is moved by foot pedals").
                # Trim it, and strip a trailing relative "that"
                # off the subject.
                if d.get("what") == "has" and isinstance(d.get("object"), str) \
                        and " and " in d["object"]:
                    d["object"] = d["object"].split(" and ")[0]
                if isinstance(d.get("who"), str) and d["who"].lower().endswith(" that"):
                    d["who"] = d["who"][:-len(" that")]
                # A "with N <noun>" count inside the same sentence
                # ("a polygon with 10 sides and 10 angles") is a
                # per-unit count the is-a parse does not carry.
                if d.get("quantity") is None:
                    wm = _WITH_N.search(text)
                    if wm:
                        wn = parse_number(wm.group(1))
                        if wn is not None:
                            wobj = wm.group(2).strip().split()[-1]
                            d["quantity"] = wn
                            d["units"] = wobj
                            d["relationships"].append(
                                {"rel": "has_a", "target": wobj,
                                 "per_unit": wn})
                frames.append(d)
                return frames
        m = _WITH_N.search(text)
        if m:
            n = parse_number(m.group(1))
            if n is not None:
                obj = m.group(2).strip().split()[-1]
                frames.append({
                    "kind": "fact", "who": None, "what": "has",
                    "quantity": n, "units": obj, "object": obj,
                    "relationships": [
                        {"rel": "has_a", "target": obj, "per_unit": n},
                        {"rel": "defined_as", "target": text}],
                    "polarity": "positive", "certainty": "known",
                    "status": "verified", "source_text": text})
                return frames
        m = _SET_OF_N.search(text)
        if m:
            n = parse_number(m.group(1))
            if n is not None:
                frames.append({
                    "kind": "fact", "who": None, "what": "set_of",
                    "quantity": n, "units": None,
                    "relationships": [
                        {"rel": "defined_as", "target": text}],
                    "polarity": "positive", "certainty": "known",
                    "status": "verified", "source_text": text})
                return frames
        # Bare noun-phrase definition ("an eight-sided polygon"):
        # the whole phrase is the is-a complement. A leading
        # "<number>-sided" also yields a per-unit count.
        m = _BARE_NP.match(text)
        if m:
            np_text = m.group(1).strip().rstrip(",;")
            n = None
            units = None
            sided = _N_SIDED.match(np_text)
            if sided:
                n = parse_number(sided.group(1))
                units = "sides"
            rels = [{"rel": "is_a", "target": np_text},
                    {"rel": "defined_as", "target": text}]
            if n is not None:
                rels.append({"rel": "has_a", "target": units,
                             "per_unit": n})
            frames.append({
                "kind": "fact", "who": None, "what": "is",
                "quantity": n, "units": units, "object": np_text,
                "relationships": rels,
                "polarity": "positive", "certainty": "known",
                "status": "verified", "source_text": text})
        return frames

    def decompose(self, term: str, context: str | None = None,
                  depth: int = 3, _visited: set | None = None
                  ) -> dict | None:
        """Recursive definition decomposition for one term.

        Follows a definition down through its component concepts:
        the chosen sense's gloss is parsed into frames and its
        content words that are themselves in the lexicon are
        decomposed one level deeper. Depth-capped (default 3) and
        cycle-safe (a visited term is never re-entered). Returns a
        tree, or None when the term is absent.
        """
        if _visited is None:
            _visited = set()
        key = term.strip().lower()
        if key in _visited or depth < 1:
            return None
        _visited.add(key)
        sense = self.disambiguate(term, context)
        if sense is None:
            return None
        gloss = sense["gloss"]
        frames = self.decompose_definition(gloss)
        components = []
        if depth > 1:
            for word in sorted(_content_words(gloss)):
                if word in _visited:
                    continue
                if not self.senses(word):
                    continue
                child = self.decompose(word, context=gloss,
                                       depth=depth - 1,
                                       _visited=_visited)
                if child is not None:
                    components.append(child)
        return {"term": key, "sense_no": sense["sense_no"],
                "pos": sense["pos"], "gloss": gloss,
                "source": sense["source"],
                "disambiguation": sense["method"],
                "score": sense["score"],
                "frames": frames, "components": components}

    def per_unit_from_definition(self, term: str,
                                 part: str | None = None
                                 ) -> tuple[float | int, list[dict]] | None:
        """A per-unit count from a definition of ``term``.

        Accepts an is-a numeric definition ("A dozen is 12" ->
        12) or a set-of-N definition ("a set of twelve" -> 12).
        Checks every sense (WordNet primary first, then Wiktionary
        senses). Returns (per_unit, evidence) or None.
        """
        meanings = []
        for cand in self._lemma_candidates(term):
            hit = self.lookup(cand)
            if hit is not None:
                meanings.append((hit["meaning"], hit["source"]))
            for s in self.senses(cand):
                meanings.append((s["gloss"], s["source"]))
        seen = set()
        for meaning, source in meanings:
            if meaning in seen:
                continue
            seen.add(meaning)
            frames = self.decompose_definition(meaning)
            for f in frames:
                if f.get("what") == "set_of" \
                        and f.get("quantity") is not None:
                    return f["quantity"], [{
                        "source": source,
                        "statement": meaning,
                        "kind": "retrieval"}]
            for f in frames:
                if f.get("what") == "is" and f.get("object"):
                    n = parse_number(str(f["object"]).strip())
                    if n is not None:
                        return n, [{
                            "source": source,
                            "statement": meaning,
                            "kind": "retrieval"}]
            for f in frames:
                # A has-a per-unit count carried on the frame
                # itself ("an eight-sided polygon" -> 8 sides;
                # "a wheeled vehicle that has two wheels" -> 2).
                # When a part is named, the count must be OF that
                # part (plural-insensitive): "How many wheels does
                # a square have?" must not answer 4 from its sides.
                if f.get("quantity") is not None and f.get("units"):
                    if part is None or _part_matches(f["units"], part):
                        return f["quantity"], [{
                            "source": source,
                            "statement": meaning,
                            "kind": "retrieval"}]
                for rel in f.get("relationships", []):
                    if rel.get("rel") == "has_a" \
                            and rel.get("per_unit") is not None:
                        if part is None or _part_matches(
                                str(rel.get("target") or ""), part):
                            return rel["per_unit"], [{
                                "source": source,
                                "statement": meaning,
                                "kind": "retrieval"}]
        return None


def production_knowledge(db_path: Path | str | None = None) -> Knowledge:
    """The seeded production store, or an empty store when the seed
    file is absent (lookups then fail honestly, as before)."""
    lex = Lexicon(db_path)
    return lex.knowledge


def default_lexicon(db_path: Path | str | None = None) -> Lexicon:
    return Lexicon(db_path)
