"""Tests for Req 5 (confidence half): calibrated confidence
(nova/semantic/confidence.py).

The certification bar (0.85) and the weights are stated decisions in
the module, not tuned values: these tests pin them, so any change to
the bar is a deliberate edit with a failing test to explain, not a
silent drift.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.semantic import parse_text_to_frames
from nova.semantic.confidence import (CERTIFICATION_BAR, WEIGHTS,
                                      calibration_buckets,
                                      model_agreement_factor,
                                      parse_certainty,
                                      proof_completeness, score)


class TestParseCertainty(unittest.TestCase):
    def test_all_deterministic(self):
        frames = parse_text_to_frames("Marcus gave John $20.")
        self.assertEqual(parse_certainty(frames), 1.0)

    def test_all_heuristic(self):
        frames = parse_text_to_frames("John bought a bike.")
        self.assertEqual(parse_certainty(frames), 0.0)

    def test_no_frames(self):
        self.assertEqual(parse_certainty([]), 0.0)

    def test_mixed(self):
        frames = (parse_text_to_frames("Marcus gave John $20.")
                  + parse_text_to_frames("John bought a bike."))
        self.assertAlmostEqual(parse_certainty(frames), 0.5)


class TestProofCompleteness(unittest.TestCase):
    def test_complete_clean(self):
        self.assertEqual(proof_completeness(
            {"complete": True, "missing": [],
             "unusable_frames": []}), 1.0)

    def test_complete_with_caveats(self):
        self.assertEqual(proof_completeness(
            {"complete": True, "missing": ["x"],
             "unusable_frames": []}), 0.5)
        self.assertEqual(proof_completeness(
            {"complete": True, "missing": [],
             "unusable_frames": [{"kind": "event"}]}), 0.5)

    def test_incomplete(self):
        self.assertEqual(proof_completeness(
            {"complete": False, "missing": ["x"],
             "unusable_frames": []}), 0.0)


class TestModelAgreement(unittest.TestCase):
    def test_agree_number(self):
        self.assertEqual(
            model_agreement_factor("John has $10 left.", 10, "yes"),
            1.0)

    def test_disagree_number(self):
        self.assertEqual(
            model_agreement_factor("John has $20 left.", 10, "yes"),
            0.0)

    def test_agree_yes_no(self):
        self.assertEqual(
            model_agreement_factor("Yes, she did.", "yes", "yes"), 1.0)
        self.assertEqual(
            model_agreement_factor("No, she did not.", "yes", "yes"),
            0.0)

    def test_advisor_abstention_is_not_disagreement(self):
        self.assertIsNone(
            model_agreement_factor("I don't know.", 10, "yes"))

    def test_no_advisor(self):
        self.assertIsNone(model_agreement_factor(None, 10, "yes"))
        self.assertIsNone(model_agreement_factor("", 10, "yes"))

    def test_unparseable_advisor(self):
        self.assertIsNone(
            model_agreement_factor("Something happened.", 10, "yes"))

    def test_definition_answer_not_compared(self):
        self.assertIsNone(model_agreement_factor(
            "orbit means path.", {"term": "orbit"}, "yes"))


class TestScore(unittest.TestCase):
    def test_perfect_inputs_certify(self):
        s = score(1.0, 1.0, 1.0)
        self.assertAlmostEqual(s["confidence"], 0.95)
        self.assertTrue(s["certified"])
        self.assertEqual(s["certification_bar"], CERTIFICATION_BAR)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0)

    def test_incomplete_proof_never_certifies(self):
        s = score(1.0, 1.0, 0.5)
        self.assertFalse(s["certified"])
        s = score(1.0, 1.0, 0.0)
        self.assertFalse(s["certified"])

    def test_low_confidence_not_certified(self):
        s = score(0.0, 0.33, 0.0)
        self.assertLess(s["confidence"], CERTIFICATION_BAR)
        self.assertFalse(s["certified"])

    def test_no_proof_caps_at_half(self):
        # A clean parse and unanimous (single) reading with no
        # completed derivation cannot score above 0.5.
        s = score(1.0, 1.0, 0.0)
        self.assertEqual(s["confidence"], 0.5)
        self.assertFalse(s["certified"])
        s = score(0.0, 1.0, 0.0)
        self.assertEqual(s["confidence"], 0.4)

    def test_model_disagreement_lowers_score(self):
        agree = score(1.0, 1.0, 1.0, model_agreement=1.0)
        disagree = score(1.0, 1.0, 1.0, model_agreement=0.0)
        self.assertGreater(agree["confidence"],
                           disagree["confidence"])
        self.assertAlmostEqual(agree["confidence"], 1.0)
        self.assertAlmostEqual(disagree["confidence"], 0.90)

    def test_no_advisor_is_neutral(self):
        s = score(1.0, 1.0, 1.0, model_agreement=None)
        self.assertAlmostEqual(s["confidence"], 0.95)

    def test_bar_is_085(self):
        self.assertEqual(CERTIFICATION_BAR, 0.85)


class TestCalibrationBuckets(unittest.TestCase):
    def test_bucketing(self):
        records = [
            {"confidence": 0.95, "correct": True},
            {"confidence": 0.92, "correct": True},
            {"confidence": 0.80, "correct": False},
            {"confidence": 0.60, "correct": True},
            {"confidence": 0.30, "correct": False},
        ]
        buckets = calibration_buckets(records)
        by_label = {b["bucket"]: b for b in buckets}
        self.assertEqual(by_label["0.90-1.00"]["n"], 2)
        self.assertEqual(by_label["0.90-1.00"]["accuracy"], 1.0)
        self.assertEqual(by_label["0.70-0.90"]["n"], 1)
        self.assertEqual(by_label["0.70-0.90"]["accuracy"], 0.0)
        self.assertEqual(by_label["0.50-0.70"]["n"], 1)
        self.assertEqual(by_label["0.50-0.70"]["accuracy"], 1.0)
        self.assertEqual(by_label["0.00-0.50"]["n"], 1)
        self.assertEqual(by_label["0.00-0.50"]["accuracy"], 0.0)

    def test_empty_bucket_reported_not_hidden(self):
        buckets = calibration_buckets(
            [{"confidence": 0.95, "correct": True}])
        by_label = {b["bucket"]: b for b in buckets}
        self.assertEqual(by_label["0.70-0.90"]["n"], 0)
        self.assertIsNone(by_label["0.70-0.90"]["accuracy"])


if __name__ == "__main__":
    unittest.main()
