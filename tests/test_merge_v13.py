"""Merge v1.3 tests — v1.2 hardening ported/adapted (2026-11-02).

Covers MERGE_MAP pieces (a) external lexicon validation, (b) sense
graph, (c) package coverage, (d) no-leak re-verification, (e)
UNSUPPORTED-does-not-force-abstention in the full-proof path,
(f) self-transfer ledger fix, and the TAINT RULE regression:
byte-identical original-question preservation in every model prompt
built by this repo, including a question whose only price ($80) is
stated in the question text itself (the fresh-114 pattern).
"""

import json
import tempfile
import unittest
from pathlib import Path

from nova.concept.events import Transfer, BalanceQuery
from nova.concept.ledger import run_story
from nova.semantic import answer_text
from nova.semantic.fullproof import build_fullproof_prompt
from nova.semantic.handoff import (build_explanation_package,
                                   build_variant_prompt)
from nova.semantic.production import answer_production
from nova.semantic.sense_graph import (build_sense_graph,
                                       lexical_senses,
                                       load_external_lexicon,
                                       sense_graph_for_terms,
                                       to_concept_graph)


class ExternalLexiconTests(unittest.TestCase):
    """(a) — ported from v1.2 test_v12 (custom + invalid lexicon)."""

    def test_custom_lexicon_loads_and_answers_senses(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "words.json"
            p.write_text(json.dumps({"bright": [{
                "meaning": "giving off light",
                "synonyms": ["luminous"], "antonyms": ["dim"],
                "cues": ["lamp"]}]}))
            lex = load_external_lexicon(p)
            entries = lexical_senses("What does bright mean?", lex)
            self.assertEqual(entries[0]["senses"][0]["meaning"],
                             "giving off light")

    def test_invalid_lexicon_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text('{"foo": [{"synonyms": ["bar"]}]}')
            with self.assertRaises(ValueError):
                load_external_lexicon(p)

    def test_non_object_lexicon_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad2.json"
            p.write_text('["not", "an", "object"]')
            with self.assertRaises(ValueError):
                load_external_lexicon(p)


class SenseGraphTests(unittest.TestCase):
    """(b) — ported from v1.2: antonym kept separate from synonym."""

    LEX = {"relinquish": [{
        "meaning": "give up possession or control",
        "synonyms": ["surrender", "yield"],
        "antonyms": ["retain", "keep"], "cues": ["control"]}]}

    def test_graph_keeps_antonym_separate(self):
        entries = lexical_senses("What does relinquish mean?",
                                 self.LEX)
        g = build_sense_graph(entries)
        rels = {(e["to"], e["relation"]) for e in g["edges"]}
        self.assertIn(("word:retain", "antonym"), rels)
        self.assertIn(("word:surrender", "synonym"), rels)
        self.assertIn(("sense:relinquish:0", "has_sense"),
                      {(e["to"], e["relation"]) for e in g["edges"]})

    def test_production_graph_has_all_three_relations(self):
        g = sense_graph_for_terms(["run"],
                                  context="She runs the studio.")
        self.assertEqual({e["relation"] for e in g["edges"]},
                         {"has_sense", "synonym", "antonym"})

    def test_bridge_to_concept_graph_preserves_relations(self):
        entries = lexical_senses("What does relinquish mean?",
                                 self.LEX)
        cg = to_concept_graph(build_sense_graph(entries))
        self.assertEqual({e.rel for e in cg.edges},
                         {"has_sense", "synonym", "antonym"})


class CoverageTests(unittest.TestCase):
    """(c) — package coverage: unparsed stays visible; duplicate
    scope is flagged, not silently certified."""

    def test_package_has_coverage_and_sense_graph(self):
        pkg = build_explanation_package(
            "Marcus gave John $50. John gave Sarah $12. "
            "How much money does John have left from the $50?")
        self.assertIn("coverage", pkg)
        self.assertEqual(pkg["coverage"]["frames_n"], 3)
        self.assertIn("sense_graph", pkg)
        self.assertTrue(pkg["sense_graph"]["nodes"])
        self.assertIn("not that the question is unanswerable",
                      pkg["nova_authority"])

    def test_duplicate_scope_flagged(self):
        pkg = build_explanation_package(
            "Sam gave Eli $100. Sam gave Eli $100. Eli gave Noah "
            "$30. How much money does Eli have left from the $100?")
        self.assertTrue(
            pkg["coverage"]["duplicate_scope_ambiguity"])


class NoLeakTests(unittest.TestCase):
    """(d) — re-verification: concepts-style paths never leak the
    verified answer (here $38, a value absent from the question)."""

    Q = ("Marcus gave John $50. John gave Sarah $12. "
         "How much money does John have left from the $50?")

    def test_fullproof_concepts_withholds_answer(self):
        pkg = build_explanation_package(self.Q)
        prompt = build_fullproof_prompt(pkg, mode="concepts")
        self.assertNotIn("38", prompt)
        self.assertIn("38", build_fullproof_prompt(pkg, mode="full"))

    def test_recorded_no_answer_variants_omit_answer_section(self):
        # The recorded arms omit the verified-answer SECTION (the
        # repo's own contract). They do NOT scrub the value from the
        # interpretations/proof sections — for computation items the
        # final proof step IS the answer, a limitation the Arm D
        # audit already established (calculator/multi-step cannot be
        # de-leaked). The strict no-leak path in this repo is the
        # full-proof concepts mode, tested above.
        pkg = build_explanation_package(self.Q)
        for variant in ("no_answer", "reasoning"):
            self.assertNotIn(
                "NOVA's verified answer:",
                build_variant_prompt(pkg, variant),
                f"{variant} kept the verified-answer section")


class AuthorityTests(unittest.TestCase):
    """(e) — the full-proof path never forces abstention on a NOVA
    unknown, and says so explicitly (v1.2 semantics)."""

    def test_fullproof_prompt_authority_language(self):
        pkg = build_explanation_package(
            "What is the capital of France?")
        prompt = build_fullproof_prompt(pkg, mode="full")
        self.assertIn("does NOT mean the answer is unknowable",
                      prompt)
        self.assertNotIn("rather than guessing", prompt)


class SelfTransferTests(unittest.TestCase):
    """(f) — merged ledger fix: a self-transfer is not spending."""

    def test_ledger_self_transfer_no_movement(self):
        events = [Transfer("Ava", "Mira", 60),
                  Transfer("Mira", "Mira", 20),
                  Transfer("Mira", "Bo", 15)]
        out = run_story(events, BalanceQuery("Mira", 60, "Ava"))
        self.assertEqual(out["answer"], 45)

    def test_production_self_transfer(self):
        r = answer_production(
            "Mira received $60 from Ava. Mira gave Mira $20. "
            "Mira gave Bo $15. How much money does Mira have left "
            "from the $60?", model=None)
        self.assertEqual(r["answer"], 45)


class TaintRuleTests(unittest.TestCase):
    """TAINT RULE: every prompt this repo builds contains the
    original question byte-identical. The $80 sample states its only
    price inside the question text — the fresh-114 pattern, where a
    redacted handoff once made the model answer 'no price'."""

    QUESTIONS = [
        "A jacket costs $80. Tom buys the jacket with a $100 "
        "bill. How much change does Tom get?",
        "Marcus gave John $50. John gave Sarah $12. How much "
        "money does John have left from the $50?",
        "What does 'relinquish' mean?",
        "She runs the studio. What does 'runs' mean here?",
    ]

    def test_all_handoff_variants_preserve_original(self):
        for q in self.QUESTIONS:
            pkg = build_explanation_package(q)
            for variant in ("full", "no_answer", "context",
                            "translation", "reasoning"):
                self.assertIn(q, build_variant_prompt(pkg, variant),
                              f"{variant} distorted the question")

    def test_fullproof_preserves_original_first(self):
        for q in self.QUESTIONS:
            pkg = build_explanation_package(q)
            for mode in ("full", "concepts"):
                prompt = build_fullproof_prompt(pkg, mode=mode)
                self.assertIn(q, prompt)
                self.assertLess(prompt.index(q),
                                prompt.index("Word senses"),
                                "NOVA material precedes the question")

    def test_harness_prompts_preserve_original(self):
        from eval.harness import build_prompt, build_retrieval_prompt
        from eval.fixtures import build_knowledge
        knowledge = build_knowledge()
        for q in self.QUESTIONS:
            item = {"text": q}
            self.assertIn(q, build_prompt(item))
            prompt, _ = build_retrieval_prompt(item, knowledge)
            self.assertIn(q, prompt)


if __name__ == "__main__":
    unittest.main()
