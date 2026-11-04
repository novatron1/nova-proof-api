"""Phase 2 tests (Reqs 1-3): licensed store, Lexicon, translation,
production path.

Run separately (the Phase 2 brief keeps ``tests/run_all.py``
untouched)::

    python3 -m unittest discover -s tests -p "test_phase2.py" -v

These are component tests, not benchmark runs: they pin the
behaviour the probe sets measure (``data/paraphrase_probes.jsonl``,
``data/new_terms_probes.jsonl``) and the runners in ``eval/``.
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "knowledge.db"

from nova.semantic.lexicon import Lexicon, default_lexicon  # noqa: E402
from nova.semantic.production import answer_production  # noqa: E402
from nova.semantic.translate_paraphrase import (  # noqa: E402
    canonicalize_sentence, frames_agree, translate, verb_sources)


class StoreTest(unittest.TestCase):
    """The seeded production store: licensed data, not fixtures."""

    def setUp(self):
        self.conn = sqlite3.connect(DB)

    def tearDown(self):
        self.conn.close()

    def test_counts(self):
        n_entries = self.conn.execute(
            "SELECT COUNT(*) FROM entries").fetchone()[0]
        n_senses = self.conn.execute(
            "SELECT COUNT(*) FROM senses").fetchone()[0]
        n_relations = self.conn.execute(
            "SELECT COUNT(*) FROM relations").fetchone()[0]
        self.assertGreaterEqual(n_entries, 280)
        self.assertGreaterEqual(n_senses, 3300)
        self.assertGreaterEqual(n_relations, 12000)

    def test_provenance_recorded(self):
        rows = self.conn.execute(
            "SELECT source, licence FROM provenance").fetchall()
        sources = {r[0] for r in rows}
        self.assertIn("wordnet-3.0", sources)
        self.assertIn("wiktionary", sources)
        licences = dict(rows)
        self.assertIn("WordNet License", licences["wordnet-3.0"])
        self.assertIn("CC BY-SA 4.0", licences["wiktionary"])

    def test_entries_carry_source(self):
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM entries WHERE source IS NULL "
            "OR source = ''").fetchone()[0]
        self.assertEqual(rows, 0)


class LexiconTest(unittest.TestCase):
    def setUp(self):
        self.lex = default_lexicon()

    def test_lookup_morph(self):
        # "gave" resolves to "give" through the morph table.
        # ("bought" is itself a Wiktionary entry — "simple past and
        # past participle of buy" — so it resolves directly, not
        # through the morph table.)
        hit = self.lex.lookup("gave")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["term"], "give")
        self.assertIn("cause to have", hit["meaning"])

    def test_lookup_synonym_reverse(self):
        # "auto" is not an entry; it resolves through the synonym
        # graph to "automobile".
        hit = self.lex.lookup("auto")
        self.assertIsNotNone(hit)
        self.assertIn("motor vehicle", hit["meaning"])

    def test_lookup_missing_is_none(self):
        self.assertIsNone(self.lex.lookup("flibberty"))

    def test_synonyms_transfer_sense(self):
        syns = self.lex.synonyms("give")
        self.assertIn("hand", syns)
        self.assertIn("pass", syns)

    def test_antonyms_buy_sell(self):
        self.assertIn("sell", self.lex.antonyms("buy", pos="verb",
                                                sense_no=1))

    def test_parts_bicycle(self):
        parts = self.lex.parts("bicycle", pos="noun", sense_no=1)
        self.assertIn("chain", parts)
        self.assertIn("handlebar", parts)

    def test_wsd_bank_river_vs_money(self):
        river = self.lex.disambiguate(
            "bank", "he sat on the bank of the river and watched "
            "the currents")
        money = self.lex.disambiguate(
            "bank", "he cashed a check at the bank and deposited "
            "money")
        self.assertIn("river", river["gloss"].lower())
        self.assertIn("financial institution", money["gloss"])

    def test_wsd_tenner_money(self):
        d = self.lex.disambiguate("tenner", "John handed Sarah a tenner")
        self.assertIn("bill", d["gloss"])
        self.assertIn("10 dollars", d["gloss"])

    def test_wsd_buck_money(self):
        d = self.lex.disambiguate("buck", "he paid three bucks for "
                                  "the coffee")
        self.assertIn("one dollar", d["gloss"])

    def test_wsd_bare_bank_is_primary(self):
        d = self.lex.disambiguate("bank", "What does 'bank' mean?")
        self.assertIn("sloping land", d["gloss"])

    def test_decompose_bicycle(self):
        tree = self.lex.decompose("bicycle", depth=2)
        self.assertIsNotNone(tree)
        terms = [c["term"] for c in tree.get("components", [])]
        self.assertIn("vehicle", terms)
        self.assertIn("wheels", terms)
        frame = tree["frames"][0]
        self.assertEqual(frame["quantity"], 2)
        self.assertEqual(frame["object"], "wheels")

    def test_decompose_spider_has_a(self):
        tree = self.lex.decompose("spider", depth=1)
        self.assertTrue(tree["frames"])
        self.assertEqual(tree["frames"][0]["quantity"], 8)
        self.assertEqual(tree["frames"][0]["object"], "legs")

    def test_decompose_octagon_sides(self):
        tree = self.lex.decompose("octagon", depth=1)
        self.assertEqual(tree["frames"][0]["quantity"], 8)
        self.assertEqual(tree["frames"][0]["units"], "sides")

    def test_per_unit(self):
        self.assertEqual(self.lex.per_unit_from_definition("dozen")[0], 12)
        self.assertEqual(
            self.lex.per_unit_from_definition("octagon")[0], 8)
        self.assertEqual(
            self.lex.per_unit_from_definition("spider")[0], 8)
        self.assertEqual(
            self.lex.per_unit_from_definition("square", "sides")[0], 4)
        self.assertIsNone(
            self.lex.per_unit_from_definition("square", "wheels"))
        self.assertIsNone(
            self.lex.per_unit_from_definition("flibberty"))

    def test_multiword_and_search(self):
        self.assertIn("boiling point", self.lex.multiword_terms())
        hits = self.lex.search_meaning("the largest planet")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["term"], "jupiter")


class TranslateTest(unittest.TestCase):
    def setUp(self):
        self.lex = default_lexicon()

    def test_canonicalize_transfer_verbs(self):
        for text, want in [
                ("Mira handed Dario $25.", "Mira gave Dario $25."),
                ("Wren passed Leo $15.", "Wren gave Leo $15."),
                ("Ana transferred $45 to Sam.",
                 "Ana sent $45 to Sam."),
                ("Tomas wired Ines $60.", "Tomas sent Ines $60."),
                ("Elena donated $30 to Omar.",
                 "Elena gave $30 to Omar."),
                ("Kai spent $40 on a book.", "Kai paid $40 on a book."),
        ]:
            canon, _subs = canonicalize_sentence(text, self.lex)
            self.assertEqual(canon, want, text)

    def test_canonicalize_amount_words(self):
        canon, subs = canonicalize_sentence(
            "John handed Sarah a tenner.", self.lex)
        self.assertEqual(canon, "John gave Sarah $10.")
        kinds = {s["kind"] for s in subs}
        self.assertIn("amount-word", kinds)

    def test_canonicalize_per_unit_total(self):
        canon, subs = canonicalize_sentence(
            "Ines bought two books for $12 each.", self.lex)
        self.assertEqual(canon, "Ines bought two books for $24.")
        self.assertTrue(any(s["kind"] == "per-unit-total"
                            for s in subs))

    def test_verb_sources_honest(self):
        src = verb_sources(self.lex)
        self.assertEqual(src["hand"], "wordnet")
        self.assertEqual(src["pass"], "wordnet")
        self.assertEqual(src["transferred"], "hand-listed")
        self.assertEqual(src["wired"], "hand-listed")

    def test_translate_intent_preserved(self):
        for text in [
                "Mira handed Dario $25. How much money does "
                "Dario have?",
                "Ana transferred $45 to Sam. Did Ana transfer $45 "
                "to Sam?",
                "John handed Sarah a tenner. How much money does "
                "Sarah have?",
                "Ines bought two books for $12 each. How much did "
                "Ines pay?",
                "Ana gave Sam twenty bucks. How much money does "
                "Sam have?",
        ]:
            tr = translate(text, lexicon=self.lex)
            self.assertTrue(tr["intent_preserved"], text)

    def test_translate_intent_not_preserved_on_drift(self):
        # A canonicalization that changed the actor is caught.
        from nova.semantic.extract import parse_text_to_frames
        o = parse_text_to_frames("Mira gave Dario $25.")
        c = parse_text_to_frames("Sam gave Dario $25.")
        self.assertFalse(frames_agree(o, c, [], self.lex)["agree"])


class ProductionTest(unittest.TestCase):
    def test_handed(self):
        r = answer_production(
            "Mira handed Dario $25. How much money does Dario have?")
        self.assertEqual(r["answer"], 25)

    def test_tenner(self):
        r = answer_production(
            "John handed Sarah a tenner. How much money does "
            "Sarah have?")
        self.assertEqual(r["answer"], 10)

    def test_wired(self):
        r = answer_production(
            "Tomas wired Ines $60. How much money does Ines have?")
        self.assertEqual(r["answer"], 60)

    def test_per_unit_purchase(self):
        r = answer_production(
            "Ines bought two books for $12 each. How much did "
            "Ines pay?")
        self.assertEqual(r["answer"], 24)

    def test_octagon(self):
        r = answer_production("How many sides does an octagon have?")
        self.assertEqual(r["answer"], 8)

    def test_boiling_point(self):
        r = answer_production("What is the boiling point of water?")
        self.assertIn("temperature", str(r["answer"]))
        self.assertIn("boils", str(r["answer"]))

    def test_largest_planet(self):
        r = answer_production("What is the largest planet?")
        self.assertIn("Jupiter", str(r["answer"]))

    def test_dictionary_wsd_tenner(self):
        r = answer_production("What does 'tenner' mean?")
        self.assertIn("bill", str(r["answer"]))
        self.assertIn("10 dollars", str(r["answer"]))

    def test_dictionary_bare_bank_is_primary(self):
        r = answer_production("What does 'bank' mean?")
        self.assertIn("sloping land", str(r["answer"]))

    def test_sell_receive(self):
        r = answer_production(
            "Leo sold his bike for $90. How much money did Leo "
            "receive?")
        self.assertEqual(r["answer"], 90)

    def test_negated_balance_is_zero_closed_world(self):
        # The frozen eval's closed-world semantics: a negated
        # transfer leaves the recipient at $0 (eval-146/189/233).
        r = answer_production(
            "John did not hand Sarah $10. How much money does "
            "Sarah have?")
        self.assertEqual(r["answer"], 0)

    def test_unknown_stays_unknown(self):
        r = answer_production("What does 'flibberty' mean?")
        self.assertIsNone(r["answer"])
        self.assertEqual(r["verdict"], "unknown")


if __name__ == "__main__":
    unittest.main()
