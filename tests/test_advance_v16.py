"""Advance v1.6 tests (2026-11-03).

Covers the v1.6 advancement over v1.5: refund-before-transfer
reordering (the v1.5 'Stretch', skipped there as a semantics
change; see ADVANCE_V15.md and ADVANCE_V16.md).

Semantics: a STATED-amount refund narrated before the transfer
that justifies it is parked by the Ledger and applied at the first
later point where the pair's opposite-direction sent total covers
it. No other event is reordered. A refund no later transfer ever
justifies is settled as an unmatched refund (the story abstains —
the pre-v1.6 outcome). Amount-less refunds are never parked: their
amount would have to be resolved against transfers not yet
narrated, and which of them "the money" means is the text's own
ambiguity, so an amount-less refund unjustified at its position
abstains exactly as in v1.5.

The probe set in probes_v16/ is FRESH: written for v1.6 from the
documented skip class; no item is a spent live item. Ground truths
are hand-derived in the JSON file.
"""

import json
import unittest
from pathlib import Path

from nova.concept.events import BalanceQuery, Transfer
from nova.concept.ledger import Ledger, run_story
from nova.semantic.production import answer_production

PROBES = Path(__file__).resolve().parent.parent / "probes_v16"


def _t(giver, recipient, amount, kind="transfer"):
    return Transfer(giver=giver, recipient=recipient,
                    amount=amount, kind=kind)


class PendingRefundLedgerTests(unittest.TestCase):
    """Ledger level: a refund stated before its justifying transfer
    applies once that transfer lands, in place, with nothing else
    reordered."""

    def test_refund_before_transfer_applies_after_it(self):
        events = [
            _t("Ciro", "Aldo", 25, "refund"),      # narrated first
            _t("Berta", "Aldo", 160),
            _t("Aldo", "Ciro", 60),               # justifies it
        ]
        result = run_story(events, BalanceQuery("Aldo", 160, "Berta"))
        self.assertEqual(result["answer"], 125)
        self.assertEqual(result["refund_issues"], [])

    def test_pending_trace_is_honest(self):
        events = [
            _t("Ciro", "Aldo", 25, "refund"),
            _t("Berta", "Aldo", 160),
            _t("Aldo", "Ciro", 60),
        ]
        result = run_story(events, BalanceQuery("Aldo", 160, "Berta"))
        proof = "\n".join(result["proof"])
        self.assertIn("held pending a later transfer", proof)
        self.assertIn("justifies the pending refund", proof)

    def test_two_pending_refunds_apply_in_narration_order(self):
        events = [
            _t("Mina", "Niko", 20, "refund"),
            _t("Mina", "Niko", 30, "refund"),
            _t("Olga", "Niko", 150),
            _t("Niko", "Mina", 80),
        ]
        result = run_story(events, BalanceQuery("Niko", 150, "Olga"))
        self.assertEqual(result["answer"], 120)
        self.assertEqual(result["refund_issues"], [])

    def test_second_pending_refund_beyond_sent_stays_unmatched(self):
        # $50 + $40 claimed back against $80 sent: the first applies,
        # the second never becomes justified -> issue -> abstain.
        events = [
            _t("Mina", "Niko", 50, "refund"),
            _t("Mina", "Niko", 40, "refund"),
            _t("Olga", "Niko", 150),
            _t("Niko", "Mina", 80),
        ]
        result = run_story(events, BalanceQuery("Niko", 150, "Olga"))
        self.assertIsNone(result["answer"])
        self.assertEqual(len(result["refund_issues"]), 1)
        self.assertIn("$40", result["refund_issues"][0])

    def test_partial_justification_across_two_transfers(self):
        # The refund is covered only once BOTH later transfers land
        # ($40 + $40 >= $70); it applies after the second one.
        events = [
            _t("Jana", "Kira", 70, "refund"),
            _t("Ludo", "Kira", 200),
            _t("Kira", "Jana", 40),
            _t("Kira", "Jana", 40),
        ]
        result = run_story(events, BalanceQuery("Kira", 200, "Ludo"))
        self.assertEqual(result["answer"], 200 - 80 + 70)
        self.assertEqual(result["refund_issues"], [])

    def test_intervening_outflow_of_the_pair_is_unchanged(self):
        # Events between the refund sentence and its transfer keep
        # their positions; only the refund moves, to just after the
        # transfer that justifies it.
        events = [
            _t("Jana", "Kira", 40, "refund"),
            _t("Ludo", "Kira", 180),
            _t("Kira", "Jana", 70),               # justifies it
            _t("Kira", "Mina", 60),
        ]
        result = run_story(events, BalanceQuery("Kira", 180, "Ludo"))
        self.assertEqual(result["answer"], 90)


class NeverJustifiedTests(unittest.TestCase):
    """A parked refund no later transfer justifies settles as an
    unmatched refund: the story abstains, as before v1.6."""

    def test_refund_exceeding_the_later_transfer_abstains(self):
        events = [
            _t("Pietro", "Rosa", 90, "refund"),
            _t("Stefan", "Rosa", 200),
            _t("Rosa", "Pietro", 60),
        ]
        result = run_story(events, BalanceQuery("Rosa", 200, "Stefan"))
        self.assertIsNone(result["answer"])
        self.assertEqual(len(result["refund_issues"]), 1)

    def test_refund_with_no_matching_transfer_abstains(self):
        events = [
            _t("Tilda", "Ugo", 30, "refund"),
            _t("Vera", "Ugo", 140),
            _t("Ugo", "Wren", 50),
        ]
        result = run_story(events, BalanceQuery("Ugo", 140, "Vera"))
        self.assertIsNone(result["answer"])
        self.assertEqual(len(result["refund_issues"]), 1)

    def test_ledger_has_no_pending_left_after_run_story(self):
        ledger = Ledger()
        ledger.apply(_t("Tilda", "Ugo", 30, "refund"))
        self.assertEqual(len(ledger.pending_refunds), 1)
        ledger.settle_pending()
        self.assertEqual(ledger.pending_refunds, [])
        self.assertEqual(len(ledger.refund_issues), 1)


class AmountLessCarveOutTests(unittest.TestCase):
    """Amount-less refunds are never parked (v1.6 design decision,
    ADVANCE_V16.md): unjustified at their position they abstain
    exactly as in v1.5; justified at their position they resolve
    exactly as in v1.5."""

    def test_amount_less_refund_before_transfer_abstains(self):
        events = [
            _t("Ciro", "Aldo", None, "refund"),   # narrated first
            _t("Berta", "Aldo", 160),
            _t("Aldo", "Ciro", 60),
        ]
        result = run_story(events, BalanceQuery("Aldo", 160, "Berta"))
        self.assertIsNone(result["answer"])
        self.assertEqual(len(result["refund_issues"]), 1)

    def test_amount_less_refund_in_order_still_resolves(self):
        events = [
            _t("Berta", "Aldo", 160),
            _t("Aldo", "Ciro", 60),
            _t("Ciro", "Aldo", None, "refund"),
        ]
        result = run_story(events, BalanceQuery("Aldo", 160, "Berta"))
        self.assertEqual(result["answer"], 160)
        self.assertEqual(result["refund_issues"], [])


class NormalOrderUnchangedTests(unittest.TestCase):
    """The safety invariant: parking triggers only where the old
    code recorded an issue, so stories v1.5 certifies are
    untouched — including the cross-check that a reordered story
    and its in-order twin give the same answer."""

    def test_reordered_matches_in_order_twin(self):
        reordered = [
            _t("Ciro", "Aldo", 25, "refund"),
            _t("Berta", "Aldo", 160),
            _t("Aldo", "Ciro", 60),
        ]
        in_order = [
            _t("Berta", "Aldo", 160),
            _t("Aldo", "Ciro", 60),
            _t("Ciro", "Aldo", 25, "refund"),
        ]
        q = BalanceQuery("Aldo", 160, "Berta")
        self.assertEqual(run_story(reordered, q)["answer"],
                         run_story(in_order, q)["answer"])

    def test_refund_justified_at_its_position_never_parks(self):
        ledger = Ledger()
        ledger.apply(_t("Berta", "Aldo", 160))
        ledger.apply(_t("Aldo", "Ciro", 60))
        ledger.apply(_t("Ciro", "Aldo", 25, "refund"))
        self.assertEqual(ledger.pending_refunds, [])
        self.assertEqual(ledger.refund_issues, [])


class FreshProbeSetTests(unittest.TestCase):
    """The fresh probes_v16 set, end to end through the production
    path (the runner measures other repos; this pins this one)."""

    def test_all_fresh_probes_pass(self):
        items = json.loads(
            (PROBES / "refund_reorder_probes.json").read_text())
        failures = []
        for item in items:
            actual = answer_production(
                item["question"], model=None).get("answer")
            if item["expected_answer"] is None:
                ok = actual is None
            else:
                ok = (actual is not None
                      and float(actual) == float(item["expected_answer"]))
            if not ok:
                failures.append((item["id"], item["expected_answer"],
                                 actual))
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
