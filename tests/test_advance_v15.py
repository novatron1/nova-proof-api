"""Advance v1.5 tests (2026-11-03).

Covers the four v1.5 advancements over v1.4:
(1) negated transfers — a compound sentence's clauses are parsed
    separately, so a negated clause never creates a transfer and an
    affirmative clause in the same sentence still counts;
(2) refund phrasing expansion — reimbursed / paid back / gave back
    / amount-less "gave the money back" forms parse as refunds with
    the v1.4 validity rules; negated refunds never restore money;
(3) giver-named-scope abstention — the relative-"that" scope form
    resolves its giver correctly, and a scope resolving to no lot
    abstains instead of certifying $0;
(4) fullproof prompt — the question-itself ambiguity carve-out is
    present and the anti-abstention clause is unchanged.

The probe sets in probes_v15/ are FRESH: written for v1.5 from the
failure classes of the spent v1.4 live set; no item is a spent
live item (v14-020/022/025 appear only in spent_diagnostics.json).
Ground truths are hand-derived in the JSON files.
"""

import json
import unittest
from pathlib import Path

from nova.concept.events import BalanceQuery, Transfer, parse_sentence
from nova.concept.ledger import run_story
from nova.semantic.extract import parse_text_to_frames
from nova.semantic.fullproof import (ANSWER_INSTRUCTION, HEADER,
                                     build_fullproof_prompt)
from nova.semantic.handoff import build_explanation_package
from nova.semantic.production import answer_production

PROBES = Path(__file__).resolve().parent.parent / "probes_v15"


def _load(name):
    return json.loads((PROBES / name).read_text())


class NegatedTransferParseTests(unittest.TestCase):
    """(1a) — negated transfer sentences never parse as transfers
    at the deterministic tier (the verb must immediately follow the
    giver's name, so a negator breaks every pattern's anchor)."""

    CASES = [
        "Liam did not give Lena $55.",
        "Liam didn't give Lena $55.",
        "Liam never gave Lena $55.",
        "Liam did not receive $55 from Lena.",
        "Liam never sent Lena $55.",
    ]

    def test_negated_sentences_parse_to_nothing(self):
        for text in self.CASES:
            self.assertIsNone(parse_sentence(text), text)


class ClauseSplitTests(unittest.TestCase):
    """(1b) — the compound sentence from the v14-020 failure class:
    one negated clause + one affirmative clause yields the real
    transfer, and the negated clause stays a negative frame."""

    TEXT = ("Petra gave Liam $90. Liam didn't give Lena $55, "
            "but Liam gave Samir $30. "
            "How much money does Liam have left from the $90?")

    def test_affirmative_clause_transfer_survives(self):
        frames = parse_text_to_frames(self.TEXT)
        transfers = [(f.who, f.recipient, f.quantity)
                     for f in frames
                     if f.kind == "transfer" and f.polarity == "positive"]
        self.assertIn(("Liam", "Samir", 30), transfers)

    def test_negated_clause_never_a_positive_transfer(self):
        frames = parse_text_to_frames(self.TEXT)
        bad = [f for f in frames
               if f.recipient == "Lena" and f.polarity == "positive"]
        self.assertEqual(bad, [])

    def test_compound_story_answers_affirmative_only(self):
        env = answer_production(
            "Liam received $90 from Petra. Liam didn't give Lena "
            "$55, but Liam gave Samir $30. How much money does Liam "
            "have left from the $90?", model=None)
        self.assertEqual(env["answer"], 60)


class RefundPhrasingParseTests(unittest.TestCase):
    """(2a) — every new refund phrasing parses to a refund Transfer
    with the refunder as giver and the refundee as recipient."""

    CASES = [
        ("Noah reimbursed Eli $10.", "Noah", "Eli", 10),
        ("Noah reimbursed Eli for $10.", "Noah", "Eli", 10),
        ("Noah paid Eli back $10.", "Noah", "Eli", 10),
        ("Noah paid $10 back to Eli.", "Noah", "Eli", 10),
        ("Noah gave $10 back to Eli.", "Noah", "Eli", 10),
        ("Noah gave back $10 to Eli.", "Noah", "Eli", 10),
        ("Noah gave the money back to Eli.", "Noah", "Eli", None),
        ("Noah gave it back to Eli.", "Noah", "Eli", None),
        ("Noah returned the money to Eli.", "Noah", "Eli", None),
    ]

    def test_phrasings_parse_as_refunds(self):
        for text, giver, recip, amount in self.CASES:
            ev = parse_sentence(text)
            self.assertIsInstance(ev, Transfer, text)
            self.assertEqual(ev.kind, "refund", text)
            self.assertEqual((ev.giver, ev.recipient), (giver, recip),
                             text)
            self.assertEqual(ev.amount, amount, text)

    def test_negated_refunds_parse_to_nothing(self):
        for text in ("Noah did not reimburse Eli $10.",
                     "Noah never refunded Eli $10.",
                     "Noah refused to refund Eli $10.",
                     "Noah did not give the money back to Eli."):
            self.assertIsNone(parse_sentence(text), text)


class AmountLessRefundLedgerTests(unittest.TestCase):
    """(2b) — an amount-less refund resolves to the pair's full
    outstanding balance; with nothing outstanding it is unmatched
    and the story abstains."""

    def test_amountless_refund_restores_outstanding(self):
        events = [
            Transfer("Ivan", "Hugo", 70),
            Transfer("Hugo", "Jane", 45),
            Transfer("Jane", "Hugo", None, kind="refund"),
        ]
        result = run_story(events, BalanceQuery("Hugo", 70, "Ivan"))
        self.assertEqual(result["answer"], 70)
        self.assertEqual(result["refund_issues"], [])

    def test_amountless_refund_after_partial_refund(self):
        events = [
            Transfer("Tom", "Sara", 140),
            Transfer("Sara", "Uma", 80),
            Transfer("Uma", "Sara", 30, kind="refund"),
            Transfer("Uma", "Sara", None, kind="refund"),
        ]
        result = run_story(events, BalanceQuery("Sara", 140, "Tom"))
        self.assertEqual(result["answer"], 140)

    def test_amountless_refund_from_non_counterparty_abstains(self):
        events = [
            Transfer("Olga", "Nils", 80),
            Transfer("Nils", "Paul", 30),
            Transfer("Rita", "Nils", None, kind="refund"),
        ]
        result = run_story(events, BalanceQuery("Nils", 80, "Olga"))
        self.assertIsNone(result["answer"])
        self.assertTrue(result["refund_issues"])

    def test_over_refund_in_new_phrasing_abstains(self):
        events = [
            Transfer("Noah", "Mona", 100),
            Transfer("Mona", "Omar", 30),
            Transfer("Omar", "Mona", 50, kind="refund"),
        ]
        result = run_story(events, BalanceQuery("Mona", 100, "Noah"))
        self.assertIsNone(result["answer"])
        self.assertTrue(result["refund_issues"])


class GiverScopeTests(unittest.TestCase):
    """(3) — giver-named scopes: the relative-'that' form resolves,
    duplicates abstain whatever the scope names, a scope matching
    no lot abstains, and a fully spent lot still answers $0."""

    def test_that_form_parses_giver(self):
        q = parse_sentence(
            "How much money is left from the $130 that Nils gave "
            "Pavel?")
        self.assertIsInstance(q, BalanceQuery)
        self.assertEqual((q.person, q.scope_giver, q.scope_amount),
                         ("Pavel", "Nils", 130))

    def test_duplicate_that_scope_abstains(self):
        env = answer_production(
            "Nils gave Pavel $130. Nils gave Pavel $130. Pavel "
            "gave Marta $30. How much money is left from the $130 "
            "that Nils gave Pavel?", model=None)
        self.assertIsNone(env["answer"])

    def test_single_lot_that_scope_answers(self):
        env = answer_production(
            "Sara gave Tom $90. Tom gave Uma $25. How much money "
            "is left from the $90 that Sara gave Tom?", model=None)
        self.assertEqual(env["answer"], 65)

    def test_scope_matching_no_lot_abstains(self):
        events = [Transfer("Yara", "Zoe", 80),
                  Transfer("Zoe", "Adam", 20)]
        result = run_story(events, BalanceQuery("Zoe", 80, "Boris"))
        self.assertIsNone(result["answer"])

    def test_fully_spent_lot_scope_still_answers_zero(self):
        events = [Transfer("Yara", "Zoe", 80),
                  Transfer("Zoe", "Adam", 80)]
        result = run_story(events, BalanceQuery("Zoe", 80, "Yara"))
        self.assertEqual(result["answer"], 0)


class FullproofAmbiguityCarveOutTests(unittest.TestCase):
    """(4) — the header/instruction carry the question-itself
    ambiguity carve-out; the anti-abstention clause for
    NOVA-unsupported cases is verbatim; the question stays
    byte-identical in the built prompt (taint rule)."""

    def test_carve_out_present(self):
        self.assertIn("question's own ambiguity", HEADER)
        self.assertIn("matches more than one", HEADER)
        self.assertIn("do not combine the", HEADER)
        self.assertIn("scope is ambiguous", ANSWER_INSTRUCTION)

    def test_anti_abstention_clause_verbatim(self):
        self.assertIn("never merely because NOVA could not "
                      "determine it", ANSWER_INSTRUCTION)
        self.assertIn("does NOT mean the answer is unknowable",
                      HEADER)

    def test_ambiguity_reason_reaches_prompt_and_question_verbatim(
            self):
        text = ("Diego gave Tomas $95. Diego gave Tomas $95. "
                "Tomas gave Dmitri $45. Tomas gave Victor $25. "
                "How much money does Tomas have left from the $95?")
        package = build_explanation_package(text)
        self.assertTrue(package["coverage"]
                        ["duplicate_scope_ambiguity"])
        prompt = build_fullproof_prompt(package, mode="full")
        self.assertIn(text, prompt)
        self.assertIn("does not resolve to exactly one lot", prompt)
        self.assertIn("do not combine the", prompt)


class FreshProbeFilesTests(unittest.TestCase):
    """The fresh probes_v15 sets pass through the production path
    (before-scores against v1.4 are recorded in ADVANCE_V15.md;
    the spent diagnostics file is deliberately NOT asserted here —
    it is diagnostic only)."""

    def _run(self, name):
        items = _load(name)
        for item in items:
            env = answer_production(item["question"], model=None)
            self.assertEqual(env["answer"], item["expected_answer"],
                             item["id"])

    def test_negation_probes(self):
        self._run("negation_probes.json")

    def test_refund_phrasing_probes(self):
        self._run("refund_phrasing_probes.json")

    def test_giver_scope_probes(self):
        self._run("giver_scope_probes.json")


if __name__ == "__main__":
    unittest.main()
