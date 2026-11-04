"""Tests for Req 4: multiple simplified interpretations, agreement and
contradiction checks (nova/semantic/interpret.py).

No live model calls here: model behaviour is covered with the mock
model (nova.model_interface.MockModel) and a raising double.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.model_interface import MockModel
from nova.semantic import (compare_concept_frames, interpret,
                           parse_text_to_frames)
from nova.semantic.interpret import (_adjudicate,
                                     deterministic_simplifications)


class _RaisingModel:
    model_id = "raising"

    def complete(self, prompt, *, max_tokens=128, temperature=0.0):
        raise RuntimeError("boom")


def _result(verdict, answer, status="verified", complete=True):
    return {"verdict": verdict, "answer": answer, "proof": ["p"],
            "complete": complete, "status": status, "missing": [],
            "unusable_frames": [], "frames": []}


class TestDeterministicSimplifications(unittest.TestCase):
    def test_canonical_verbs(self):
        vs = deterministic_simplifications(
            "John wired Sarah $10.")
        texts = [v["text"] for v in vs]
        self.assertIn("John sent Sarah $10.", texts)

    def test_strip_clauses(self):
        vs = deterministic_simplifications(
            "Marcus gave John $20 because he asked.")
        texts = [v["text"] for v in vs]
        self.assertIn("Marcus gave John $20.", texts)

    def test_split_compound(self):
        vs = deterministic_simplifications(
            "Marcus gave John $20 and Sarah $10.")
        texts = [v["text"] for v in vs]
        self.assertIn("Marcus gave John $20. Marcus gave Sarah $10.",
                      texts)

    def test_pronoun_resolution(self):
        vs = deterministic_simplifications(
            "John gave Tom $20. He gave Sarah $10.")
        methods = [v["method"] for v in vs]
        self.assertIn("pronoun-resolution", methods)
        texts = [v["text"] for v in vs]
        self.assertIn("John gave Tom $20. John gave Sarah $10.", texts)
        self.assertIn("John gave Tom $20. Tom gave Sarah $10.", texts)

    def test_no_variant_when_nothing_applies(self):
        # A plain deterministic sentence has no template variant
        # except the deterministic-only re-read.
        vs = deterministic_simplifications(
            "Marcus gave John $20.")
        methods = [v["method"] for v in vs]
        self.assertEqual(methods, ["deterministic-only"])

    def test_dedupe(self):
        vs = deterministic_simplifications(
            "John handed Sarah $10 yesterday because she asked.")
        texts = [v["text"] for v in vs]
        self.assertEqual(len(texts), len(set(texts)))


class TestAdjudicate(unittest.TestCase):
    def test_all_agree(self):
        d = _adjudicate([_result("yes", 10), _result("yes", 10)])
        self.assertEqual(d["verdict"], "yes")
        self.assertEqual(d["answer"], 10)
        self.assertEqual(d["agreement_rate"], 1.0)
        self.assertFalse(d["contradiction"])

    def test_contradiction_abstains(self):
        d = _adjudicate([_result("yes", 20), _result("yes", 10)])
        self.assertTrue(d["contradiction"])
        self.assertEqual(d["status"], "contradiction")
        self.assertEqual(d["verdict"], "unknown")
        self.assertIsNone(d["answer"])
        self.assertEqual(len(d["contradicting_pairs"]), 1)

    def test_unknown_is_not_a_vote(self):
        # One reading settles it, two cannot parse: the settled
        # reading carries the answer (partial agreement), it is not
        # outvoted by the unknowns.
        d = _adjudicate([_result("yes", 10),
                         _result("unknown", None),
                         _result("unknown", None)])
        self.assertEqual(d["verdict"], "yes")
        self.assertEqual(d["answer"], 10)
        self.assertEqual(d["status"], "partial_agreement")
        self.assertAlmostEqual(d["agreement_rate"], 1 / 3)

    def test_all_unknown(self):
        d = _adjudicate([_result("unknown", None),
                         _result("unknown", None)])
        self.assertEqual(d["verdict"], "unknown")
        self.assertEqual(d["agreement_rate"], 1.0)
        self.assertFalse(d["contradiction"])

    def test_no_readings(self):
        d = _adjudicate([])
        self.assertEqual(d["verdict"], "unknown")
        self.assertEqual(d["agreement_rate"], 0.0)

    def test_majority_tie_breaks_to_original(self):
        # Two readings, two different definitive answers: that is a
        # contradiction, not a tie to break.
        d = _adjudicate([_result("yes", 10), _result("no", "no")])
        self.assertTrue(d["contradiction"])


class TestInterpret(unittest.TestCase):
    def test_clear_question_agrees(self):
        r = interpret("Marcus gave John $20. John gave Sarah $10. "
                      "How much money does John have left?")
        self.assertEqual(r["answer"], 10)
        self.assertEqual(r["agreement_rate"], 1.0)
        self.assertFalse(r["contradiction"])
        self.assertTrue(r["confidence"]["certified"])

    def test_pronoun_ambiguity_contradicts(self):
        r = interpret("John gave Tom $20. He gave Sarah $10. "
                      "How much money does Tom have?")
        self.assertTrue(r["contradiction"])
        self.assertEqual(r["status"], "contradiction")
        self.assertIsNone(r["answer"])
        self.assertIn("disagree", r["answer_text"])
        self.assertFalse(r["confidence"]["certified"])

    def test_uncovered_verb_partial_agreement(self):
        # "wired" is unreadable to the deterministic tiers; the
        # canonical-verbs reading settles it, the others cannot.
        r = interpret("John wired Sarah $10. "
                      "How much money does Sarah have?")
        self.assertEqual(r["answer"], 10)
        self.assertEqual(r["status"], "partial_agreement")
        self.assertFalse(r["confidence"]["certified"])

    def test_unknown_stays_unknown(self):
        r = interpret("How much money does Zoe have?")
        self.assertEqual(r["verdict"], "unknown")
        self.assertIsNone(r["answer"])
        self.assertEqual(r["agreement_rate"], 1.0)

    def test_mock_model_variants_do_not_crash(self):
        # The mock returns the same text for every prompt; the
        # restatements dedupe to the original reading.
        r = interpret("Marcus gave John $20. How much money does "
                      "John have?",
                      model=MockModel("Marcus gave John $20."))
        self.assertEqual(r["answer"], 20)
        self.assertEqual(r["n_failed_variants"], 0)

    def test_raising_model_records_failure(self):
        r = interpret("Marcus gave John $20. How much money does "
                      "John have?",
                      model=_RaisingModel())
        self.assertEqual(r["answer"], 20)
        self.assertEqual(r["n_failed_variants"], 2)
        self.assertEqual(r["n_interpretations"], 1)

    def test_duplicate_readings_deduped(self):
        r = interpret("Marcus gave John $20. How much money does "
                      "John have?")
        # deterministic-only re-read parses identically: deduped.
        self.assertGreaterEqual(r["n_duplicate_variants"], 1)

    def test_each_interpretation_carries_proof(self):
        r = interpret("John gave Tom $20. He gave Sarah $10. "
                      "How much money does Tom have?")
        for interp in r["interpretations"]:
            self.assertIn("proof", interp)
            self.assertIn("frames", interp)
            self.assertIn("method", interp)


class TestCompareCertification(unittest.TestCase):
    def test_deterministic_match_certifies(self):
        a = parse_text_to_frames("Marcus gave John $20.")[0]
        b = parse_text_to_frames("Marcus gave John $20.")[0]
        self.assertEqual(a.status, "verified")
        rel = compare_concept_frames(a, b)
        self.assertEqual(rel["relation"], "candidate_equivalent")
        self.assertTrue(rel["certified"])

    def test_heuristic_match_does_not_certify(self):
        a = parse_text_to_frames("John bought a bike.")[0]
        b = parse_text_to_frames("John bought a bike.")[0]
        self.assertNotEqual(a.status, "verified")
        rel = compare_concept_frames(a, b)
        self.assertEqual(rel["relation"], "candidate_equivalent")
        self.assertFalse(rel["certified"])

    def test_deterministic_contradiction_certifies(self):
        a = parse_text_to_frames("Marcus gave John $20.")[0]
        b = parse_text_to_frames("Marcus gave John $20.")[0]
        b.polarity = "negative"
        rel = compare_concept_frames(a, b)
        self.assertEqual(rel["relation"], "possible_contradiction")
        self.assertTrue(rel["certified"])

    def test_undetermined_never_certifies(self):
        a = parse_text_to_frames("Marcus gave John $20.")[0]
        b = parse_text_to_frames("Marcus gave Sarah $30.")[0]
        rel = compare_concept_frames(a, b)
        self.assertEqual(rel["relation"], "undetermined")
        self.assertFalse(rel["certified"])


if __name__ == "__main__":
    unittest.main()
