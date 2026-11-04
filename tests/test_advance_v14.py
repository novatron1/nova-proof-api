"""Advance v1.4 tests (2026-11-02).

Covers the three v1.4 advancements over the merged v1.3:
(1) refund verb parsing in the core engine (deterministic parser
    -> refund frames -> Ledger validity + lot restoration),
(2) duplicate-scope abstention in the core Ledger (a scoped query
    matching more than one lot returns no certified answer;
    totals and uniquely-resolving scopes are unchanged),
(3) the fullproof prompt's question-missing-info line (answerability
    is judged from the question itself; the anti-abstention clause
    for NOVA-unsupported cases is NOT weakened).

The probe sets in probes_v14/ are FRESH: written for v1.4 from the
failure classes of the (now spent) live-40 set; no item is a
live-40 item. Ground truths are hand-derived in the JSON files.
"""

import json
import unittest
from pathlib import Path

from nova.concept.events import BalanceQuery, Transfer, parse_sentence
from nova.concept.ledger import run_story
from nova.semantic.fullproof import (ANSWER_INSTRUCTION, HEADER,
                                     build_fullproof_prompt)
from nova.semantic.handoff import build_explanation_package
from nova.semantic.production import answer_production

PROBES = Path(__file__).resolve().parent.parent / "probes_v14"


def _load(name):
    return json.loads((PROBES / name).read_text())


class RefundParseTests(unittest.TestCase):
    """(1a) — every refund phrasing parses to a refund Transfer with
    the refunder as giver and the refundee as recipient."""

    CASES = [
        ("Noah refunded Eli $10.", "Noah", "Eli", 10),
        ("Noah repaid Eli $10.", "Noah", "Eli", 10),
        ("Noah refunded $10 to Eli.", "Noah", "Eli", 10),
        ("Noah repaid $10 to Eli.", "Noah", "Eli", 10),
        ("Noah returned $10 to Eli.", "Noah", "Eli", 10),
        ("Eli received a refund of $10 from Noah.", "Noah", "Eli", 10),
        ("Eli got a refund of $10 from Noah.", "Noah", "Eli", 10),
        ("Eli was refunded $10 by Noah.", "Noah", "Eli", 10),
    ]

    def test_refund_phrasings_parse_as_refunds(self):
        for text, giver, recv, amt in self.CASES:
            ev = parse_sentence(text)
            self.assertIsInstance(ev, Transfer, text)
            self.assertEqual(ev.kind, "refund", text)
            self.assertEqual((ev.giver, ev.recipient, ev.amount),
                             (giver, recv, amt), text)

    def test_plain_transfers_still_parse_as_transfers(self):
        ev = parse_sentence("Noah gave Eli $10.")
        self.assertEqual(ev.kind, "transfer")


class RefundLedgerTests(unittest.TestCase):
    """(1b) — ledger semantics: restoration, validity, abstention."""

    def test_refund_restores_scoped_lot(self):
        events = [Transfer("Sam", "Eli", 100),
                  Transfer("Eli", "Noah", 30),
                  Transfer("Noah", "Eli", 10, kind="refund")]
        out = run_story(events, BalanceQuery("Eli", 100, "Sam"))
        self.assertEqual(out["answer"], 80)
        self.assertEqual(out["refund_issues"], [])

    def test_over_refund_abstains(self):
        events = [Transfer("Sam", "Eli", 100),
                  Transfer("Eli", "Noah", 30),
                  Transfer("Noah", "Eli", 40, kind="refund")]
        out = run_story(events, BalanceQuery("Eli", 100, "Sam"))
        self.assertIsNone(out["answer"])
        self.assertEqual(len(out["refund_issues"]), 1)

    def test_cumulative_over_refund_abstains(self):
        events = [Transfer("Sam", "Eli", 100),
                  Transfer("Eli", "Noah", 30),
                  Transfer("Noah", "Eli", 20, kind="refund"),
                  Transfer("Noah", "Eli", 20, kind="refund")]
        out = run_story(events, BalanceQuery("Eli", 100, "Sam"))
        self.assertIsNone(out["answer"])
        self.assertEqual(len(out["refund_issues"]), 1)

    def test_refund_within_sent_amount_is_valid_in_parts(self):
        events = [Transfer("Sam", "Eli", 100),
                  Transfer("Eli", "Noah", 30),
                  Transfer("Noah", "Eli", 20, kind="refund"),
                  Transfer("Noah", "Eli", 10, kind="refund")]
        out = run_story(events, BalanceQuery("Eli", 100, "Sam"))
        self.assertEqual(out["answer"], 100)
        self.assertEqual(out["refund_issues"], [])


class DuplicateScopeTests(unittest.TestCase):
    """(2) — the core Ledger abstains on multi-lot scopes."""

    def test_run_story_duplicate_scope_abstains(self):
        events = [Transfer("Sam", "Eli", 100),
                  Transfer("Sam", "Eli", 100),
                  Transfer("Eli", "Noah", 30)]
        out = run_story(events, BalanceQuery("Eli", 100))
        self.assertIsNone(out["answer"])
        self.assertTrue(out["ambiguous_scope"])

    def test_run_story_total_unaffected_by_duplicate(self):
        events = [Transfer("Sam", "Eli", 100),
                  Transfer("Sam", "Eli", 100),
                  Transfer("Eli", "Noah", 30)]
        out = run_story(events, BalanceQuery("Eli"))
        self.assertEqual(out["answer"], 170)
        self.assertFalse(out["ambiguous_scope"])

    def test_giver_scoped_unique_lot_still_answers(self):
        events = [Transfer("Sam", "Eli", 100),
                  Transfer("Ruth", "Eli", 100),
                  Transfer("Eli", "Noah", 30)]
        out = run_story(events, BalanceQuery("Eli", 100, "Sam"))
        self.assertEqual(out["answer"], 70)


class ProbeSetTests(unittest.TestCase):
    """(1)+(2) — the fresh probe sets through the production path."""

    def _run(self, name):
        for item in _load(name):
            r = answer_production(item["question"], model=None)
            actual = r.get("answer")
            expected = item["expected_answer"]
            if expected is None:
                self.assertIsNone(actual, item["id"])
            elif isinstance(expected, str):
                self.assertEqual(actual, expected, item["id"])
            else:
                self.assertIsNotNone(actual, item["id"])
                self.assertAlmostEqual(
                    float(actual), float(expected),
                    delta=item.get("tolerance") or 0,
                    msg=item["id"])

    def test_refund_probes(self):
        self._run("refund_probes.json")

    def test_duplicate_probes(self):
        self._run("duplicate_probes.json")


class RegressionProbeTests(unittest.TestCase):
    """The MERGE_RESULTS regression probes still pass in v1.4."""

    def test_self_transfer_mira_both_paths(self):
        events = [Transfer("Ava", "Mira", 60),
                  Transfer("Mira", "Mira", 20),
                  Transfer("Mira", "Bo", 15)]
        out = run_story(events, BalanceQuery("Mira", 60, "Ava"))
        self.assertEqual(out["answer"], 45)
        r = answer_production(
            "Mira received $60 from Ava. Mira gave Mira $20. "
            "Mira gave Bo $15. How much money does Mira have left "
            "from the $60?", model=None)
        self.assertEqual(r["answer"], 45)

    def test_fullproof_concepts_value_absence(self):
        pkg = build_explanation_package(
            "Marcus gave John $50. John gave Sarah $12. "
            "How much money does John have left from the $50?")
        self.assertNotIn("38", build_fullproof_prompt(
            pkg, mode="concepts"))
        self.assertIn("38", build_fullproof_prompt(pkg, mode="full"))

    def test_duplicate_scope_coverage_flag_still_set(self):
        pkg = build_explanation_package(
            "Sam gave Eli $100. Sam gave Eli $100. Eli gave Noah "
            "$30. How much money does Eli have left from the $100?")
        self.assertTrue(pkg["coverage"]["duplicate_scope_ambiguity"])
        # And the package's verified answer now agrees with the
        # flag: it can no longer certify the summed 170.
        self.assertIsNone(pkg["answer_value"])


class FullproofPromptTests(unittest.TestCase):
    """(3) — the missing-info line is drawn on the QUESTION, and the
    anti-abstention protection for NOVA-unsupported cases is kept."""

    def test_question_side_test_is_stated(self):
        self.assertIn("Judge answerability from the question itself",
                      HEADER)
        self.assertIn("missing from the question itself", HEADER)
        self.assertIn("not general knowledge", HEADER)

    def test_anti_abstention_clause_not_weakened(self):
        self.assertIn("does NOT mean the answer is unknowable", HEADER)
        self.assertIn(
            "never merely because NOVA could not determine it",
            ANSWER_INSTRUCTION)
        self.assertIn("general knowledge does not supply it",
                      ANSWER_INSTRUCTION)

    def test_taint_rule_still_holds_with_new_wording(self):
        q = ("Tomas received $90 from Ulf. Tomas gave Vera $25. "
             "Vera refunded Tomas $9. How much money does Tomas "
             "have left from the $90?")
        pkg = build_explanation_package(q)
        for mode in ("full", "concepts"):
            prompt = build_fullproof_prompt(pkg, mode=mode)
            self.assertIn(q, prompt)
            self.assertLess(prompt.index(q),
                            prompt.index("Word senses"))


if __name__ == "__main__":
    unittest.main()
