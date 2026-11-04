"""Regression: the vendored adapter (nova/adapter) still behaves exactly
like the user's v0.3 artifact.

Run:  python -m unittest discover -s tests -p "test_adapter_vendored.py" -v
       (from the repo root)

These assertions replicate the v0.3 test suite's coverage against the
vendored copy. The original v0.3 suite is also re-run from its own
directory by tests/run_all.py; both must pass.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.adapter import Knowledge, NovaAdapter, calculate
from nova.adapter.concepts import compare_frames, concept_frame
from nova.adapter.language import compare, extract
from nova.adapter.meta import MetaModelClient


class TestVendoredCore(unittest.TestCase):
    def test_math(self):
        self.assertEqual(calculate("15*120*8"), 14400)

    def test_reject_code(self):
        with self.assertRaises(ValueError):
            calculate('__import__("os").system("echo hi")')

    def test_dictionary(self):
        k = Knowledge()
        k.add("dictionary", "purchase", "obtain in exchange for payment",
              "local-test")
        self.assertEqual(
            NovaAdapter(knowledge=k).process(
                {"task": "dictionary", "term": "purchase"}
            )["answer"]["meaning"], "obtain in exchange for payment")

    def test_reason(self):
        r = NovaAdapter().process(
            {"task": "prove", "facts": ["human(socrates)"],
             "rules": [[["human(socrates)"], "mortal(socrates)"]],
             "goal": "mortal(socrates)"})
        self.assertEqual(r["answer"]["verdict"], "yes")

    def test_unknown(self):
        r = NovaAdapter().process(
            {"task": "prove", "facts": [], "rules": [], "goal": "x"})
        self.assertEqual(r["answer"]["verdict"], "unknown")

    def test_no_model(self):
        self.assertEqual(
            NovaAdapter().process({"task": "language", "text": "hello"})
            ["status"], "model_not_configured")


class TestVendoredLanguage(unittest.TestCase):
    def test_roles(self):
        x = extract("Marcus gave his sister $50 yesterday at the store "
                    "because she needed groceries.")
        self.assertEqual(x["frame"]["who"], "Marcus")
        self.assertEqual(x["frame"]["what"], "give")
        self.assertEqual(x["frame"]["when"], "yesterday")
        self.assertEqual(x["frame"]["where"], "store")
        self.assertIn("groceries", x["frame"]["why"])

    def test_unknown_not_invented(self):
        x = extract("John purchased a bicycle.")
        self.assertIsNone(x["frame"]["how"])
        self.assertIsNone(x["frame"]["when"])

    def test_paraphrase_candidate(self):
        self.assertEqual(
            compare("The kid bought a bicycle.",
                    "The child purchased a bike.")["relation"],
            "candidate_equivalent")

    def test_unknown_sentence(self):
        self.assertIsNone(extract("What is this?")["frame"]["what"])

    def test_adapter(self):
        self.assertEqual(
            NovaAdapter().process(
                {"task": "analyze", "text": "John bought a bike."}
            )["status"], "partial_interpretation")

    def test_model_absent(self):
        self.assertEqual(
            NovaAdapter().process({"task": "augment", "text": "Hello"})
            ["status"], "model_not_configured")

    def test_mock_model(self):
        calls = []

        def fake(p):
            calls.append(p)
            return "mock answer"

        r = NovaAdapter(model=fake).process(
            {"task": "augment", "text": "John bought a bike."})
        self.assertEqual(r["answer"], "mock answer")
        self.assertIn("Original user text", calls[0])

    def test_endpoint_guard(self):
        with self.assertRaises(ValueError):
            MetaModelClient(base_url="http://example.com/api", model="fake")


class TestVendoredConcepts(unittest.TestCase):
    def test_slots(self):
        f = concept_frame("Marcus gave his sister $50 yesterday at the "
                          "store because she needed groceries.")
        self.assertEqual(f["slots"]["who"], "Marcus")
        self.assertIn("how", f["unknown_slots"])

    def test_paraphrase(self):
        r = compare_frames("The kid bought a bicycle.",
                           "The child purchased a bike.")
        self.assertEqual(r["relation"], "candidate_equivalent")
        self.assertFalse(r["certified"])

    def test_negation(self):
        r = compare_frames("John bought a bike.", "John did not buy a bike.")
        self.assertFalse(r["certified"])

    def test_unknown(self):
        self.assertEqual(
            compare_frames("Something happened.", "John bought a bike.")
            ["relation"], "unknown")

    def test_adapter(self):
        self.assertEqual(
            NovaAdapter().process(
                {"task": "concept_frame", "text": "John bought a bike."}
            )["status"], "candidate_interpretation")

    def test_no_false_proof(self):
        self.assertFalse(
            NovaAdapter().process(
                {"task": "concept_compare",
                 "a": "The kid bought a bicycle.",
                 "b": "The child purchased a bike."}
            )["answer"]["certified"])


if __name__ == "__main__":
    unittest.main()
