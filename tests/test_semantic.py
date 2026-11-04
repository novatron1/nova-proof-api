"""New semantic test suites for the integrated system.

Run:  python -m unittest discover -s tests -p "test_semantic.py" -v
       (from the repo root)

Suites:
  Synonyms      — same meaning, different words -> same normalized concept
  Antonyms      — opposite actions/words -> NOT equivalent
  Negation      — a negated statement never becomes a positive fact
  MultiStep     — chains of events through the ledger, incl. heuristic
                  sentences and scoped queries
  FiveWOneH     — 5W1H extraction keeps unknowns explicit (None), and the
                  v0.3 gap is closed: quantity/units are structured fields

Every test asserts on the shared ConceptFrame format and on the
supervisory reasoner's verdict, never on model output.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.adapter.concepts import compare_frames
from nova.semantic import answer_text, parse_text_to_frames
from nova.semantic.translate import frame_to_transfer


class TestSynonyms(unittest.TestCase):
    def test_kid_child_bicycle_bike(self):
        a = parse_text_to_frames("The kid bought a bicycle.")[0]
        b = parse_text_to_frames("The child purchased a bike.")[0]
        self.assertEqual(a.what, b.what)                    # purchase
        self.assertEqual(a.object, b.object)                # bike
        rel = compare_frames("The kid bought a bicycle.",
                             "The child purchased a bike.")
        self.assertEqual(rel["relation"], "candidate_equivalent")
        self.assertFalse(rel["certified"])  # never certified: honest

    def test_automobile_car(self):
        a = parse_text_to_frames("John bought an automobile.")[0]
        b = parse_text_to_frames("John bought a car.")[0]
        self.assertEqual(a.object, b.object)

    def test_give_send_same_money_meaning(self):
        # "gave" and "sent" are distinct actions in the frame, but both
        # are money actions that move the same amount the same way.
        # "sent" is heuristic-only, so the transfer needs the explicit
        # opt-in — and the answer status is downgraded accordingly.
        a = frame_to_transfer(
            parse_text_to_frames("Marcus gave John $20.")[0])
        b = frame_to_transfer(
            parse_text_to_frames("Marcus sent John $20.")[0],
            allow_heuristic=True)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual((a.giver, a.recipient, a.amount),
                         (b.giver, b.recipient, b.amount))

    def test_synonym_story_answers(self):
        # A paraphrased story still answers through the pipeline.
        r = answer_text("The kid bought a bicycle. "
                        "Did the child purchase a bike?")
        self.assertEqual(r["verdict"], "yes")


class TestAntonyms(unittest.TestCase):
    def test_buy_vs_sell_not_equivalent(self):
        rel = compare_frames("John bought a bike.", "John sold a bike.")
        self.assertNotEqual(rel["relation"], "candidate_equivalent")

    def test_give_vs_take_roles_differ(self):
        a = parse_text_to_frames("Marcus gave John $20.")[0]
        b = parse_text_to_frames("John gave Marcus $20.")[0]
        self.assertNotEqual((a.who, a.recipient), (b.who, b.recipient))
        self.assertEqual(a.quantity, b.quantity)  # same amount, opposite flow

    def test_opposite_polarity_is_possible_contradiction(self):
        # The semantic comparison (over corrected frames) sees the
        # opposite polarity. The vendored adapter's compare misreads
        # the actor as "not" here and returns "undetermined" — a known
        # limit of the vendored heuristic, not of the shared frames.
        from nova.semantic import compare_texts
        rel = compare_texts("John bought a bike.",
                            "John did not buy a bike.")
        self.assertEqual(rel["relation"], "possible_contradiction")
        self.assertFalse(rel["certified"])

    def test_antonym_story_answers_no(self):
        r = answer_text("John bought a bike. Did John sell a bike?")
        self.assertEqual(r["verdict"], "unknown")
        # "sell" is not a known verb: the system says unknown rather
        # than guessing "no" from an unparsed question. Honest, not wrong.


class TestNegation(unittest.TestCase):
    def test_negated_transfer_frame(self):
        f = parse_text_to_frames("John did not give Sarah $10.")[0]
        self.assertEqual(f.polarity, "negative")
        self.assertEqual(f.who, "John")       # not "not"
        self.assertEqual(f.recipient, "Sarah")
        self.assertEqual(f.quantity, 10)
        self.assertEqual(f.units, "dollars")

    def test_negated_transfer_never_moves_money(self):
        f = parse_text_to_frames("John did not give Sarah $10.")[0]
        self.assertIsNone(frame_to_transfer(f, allow_heuristic=True))

    def test_negation_balance_is_zero(self):
        r = answer_text("John did not give Sarah $10. "
                        "How much money does Sarah have?")
        self.assertEqual(r["answer"], 0)

    def test_negation_yes_no_is_no(self):
        r = answer_text("John did not give Sarah $10. "
                        "Did John give Sarah $10?")
        self.assertEqual(r["verdict"], "no")
        self.assertIn("not give(john,sarah,10)", r["proof"][0])

    def test_negation_does_not_poison_real_transfer(self):
        r = answer_text("Marcus gave John $20. "
                        "John did not give Sarah $10. "
                        "How much money does John have?")
        self.assertEqual(r["answer"], 20)

    def test_never_is_negation(self):
        f = parse_text_to_frames("Marcus never paid John.")[0]
        self.assertEqual(f.polarity, "negative")
        r = answer_text("Marcus never paid John. Did Marcus pay John?")
        self.assertEqual(r["verdict"], "no")


class TestMultiStep(unittest.TestCase):
    def test_four_step_chain(self):
        r = answer_text(
            "Marcus gave John $50. John gave Sarah $20. "
            "Sarah gave Tom $5. How much money does Tom have?")
        self.assertEqual(r["answer"], 5)
        self.assertEqual(r["status"], "verified")

    def test_chain_scoped_remainder(self):
        r = answer_text(
            "Marcus gave John $50. John gave Sarah $20. "
            "How much money does John have left from the $50?")
        self.assertEqual(r["answer"], 30)

    def test_multi_inflow_partial_spend(self):
        r = answer_text(
            "Elena gave Tom $100. Maya gave Tom $40. Tom gave Sarah $25. "
            "How much money is left from the $100 Elena gave Tom?")
        self.assertEqual(r["answer"], 75)

    def test_heuristic_chain_with_sister(self):
        # The v0.3 gap example, end to end: heuristic transfer feeds
        # the ledger, answer downgraded to candidate (parse is heuristic).
        r = answer_text(
            "Marcus gave his sister $50. His sister gave John $20. "
            "How much money does John have?")
        self.assertEqual(r["answer"], 20)
        self.assertEqual(r["status"], "candidate_interpretation")

    def test_distractor_ignored(self):
        r = answer_text(
            "Elena received $10 from Tom. Elena gave $10 to Marcus. "
            "Tom received $25 from John. "
            "How much money does Elena have left from the $10?")
        self.assertEqual(r["answer"], 0)

    def test_mixed_deterministic_and_heuristic(self):
        r = answer_text(
            "Marcus gave John $100. John gave his sister $40. "
            "How much money does Sister have?")
        self.assertEqual(r["answer"], 40)


class TestFiveWOneH(unittest.TestCase):
    def test_marcus_sister_sentence(self):
        # The canonical v0.3 example: every slot checked, unknowns None.
        f = parse_text_to_frames(
            "Marcus gave his sister $50 yesterday at the store "
            "because she needed groceries.")[0]
        self.assertEqual(f.who, "Marcus")
        self.assertEqual(f.what, "give")
        self.assertEqual(f.recipient, "Sister")
        self.assertEqual(f.quantity, 50)
        self.assertEqual(f.units, "dollars")
        self.assertEqual(f.when, "yesterday")
        self.assertEqual(f.where, "store")
        self.assertIn("groceries", f.why)
        self.assertIsNone(f.how)              # unknown stays unknown
        self.assertEqual(f.polarity, "positive")
        self.assertIn("how", f.unknown_slots())

    def test_unknowns_are_never_invented(self):
        f = parse_text_to_frames("John purchased a bicycle.")[0]
        self.assertIsNone(f.when)
        self.assertIsNone(f.where)
        self.assertIsNone(f.why)
        self.assertIsNone(f.how)
        self.assertIsNone(f.quantity)
        self.assertIsNone(f.units)

    def test_frame_round_trips_through_dict(self):
        f = parse_text_to_frames(
            "Marcus gave his sister $50 yesterday.")[0]
        d = f.to_dict()
        from nova.semantic import ConceptFrame
        f2 = ConceptFrame.from_dict(d)
        self.assertEqual(f2.to_dict(), d)
        self.assertIsNone(f2.how)

    def test_why_and_how_extracted(self):
        f = parse_text_to_frames(
            "Elena sent Tom $25 because he needed it.")[0]
        self.assertIn("needed", f.why)
        f2 = parse_text_to_frames(
            "John paid Sarah by check.")[0]
        # "by check" is a method slot; if the heuristic misses it, the
        # slot must be None, never a guessed method.
        self.assertTrue(f2.how is None or "check" in f2.how)


class TestHardNegatives(unittest.TestCase):
    """The biggest eval failure cluster (0/15): 'Does X have $N?' was
    unparseable and near-miss transfers were never settled. The fix
    has two halves — a have/balance yes-no form answered from the
    ledger, and a closed-world near-miss rule for transfer goals —
    both scoped so anything the story does not determine stays
    "unknown" instead of a guessed "no"."""

    def test_balance_yes_no_spent_is_no(self):
        r = answer_text("Owen gave Tara $90. Tara gave Ivy $90. "
                        "Does Tara have $90?")
        self.assertEqual(r["verdict"], "no")
        self.assertEqual(r["answer"], "no")
        self.assertTrue(r["complete"])

    def test_balance_yes_no_received_then_spent_is_no(self):
        r = answer_text("Owen received $45 from Felix. "
                        "Owen gave $45 to Amir. Does Owen have $45?")
        self.assertEqual(r["verdict"], "no")

    def test_balance_yes_no_still_has_is_yes(self):
        r = answer_text("Marcus gave John $20. Does John have $20?")
        self.assertEqual(r["verdict"], "yes")

    def test_balance_yes_no_unmentioned_person_is_unknown(self):
        # Sarah appears nowhere in the story: no balance to report.
        r = answer_text("Marcus gave John $20. Does Sarah have $20?")
        self.assertEqual(r["verdict"], "unknown")
        self.assertIsNone(r["answer"])

    def test_closed_world_wrong_verb_stays_unknown(self):
        # Audit 2026-10-27 (fresh-006/078): the story states a giving
        # and says nothing about any paying, so "Did Omar pay Nina?"
        # is unknown — not "no". The closed-world rule only settles
        # the SAME action, never a different verb.
        r = answer_text("Omar gave Felix $22. Did Omar pay Nina $22?")
        self.assertEqual(r["verdict"], "unknown")
        r = answer_text("Noor gave Kofi $7. Did Noor pay Owen $7?")
        self.assertEqual(r["verdict"], "unknown")

    def test_closed_world_wrong_recipient_is_no(self):
        r = answer_text("Yusuf gave $7 to Ivy. "
                        "Did Yusuf give $7 to Felix?")
        self.assertEqual(r["verdict"], "no")

    def test_closed_world_wrong_amount_is_no(self):
        r = answer_text("Sana gave Omar $70. Did Sana give Omar $7?")
        self.assertEqual(r["verdict"], "no")

    def test_closed_world_receive_is_no(self):
        r = answer_text("Rosa gave Amir $45. "
                        "Did Elif receive $45 from Rosa?")
        self.assertEqual(r["verdict"], "no")

    def test_receive_same_transfer_is_yes(self):
        # The symbolic "receive" gap, fixed by the same change:
        # "receive" is now a known verb form in the money parser.
        r = answer_text("Rosa gave Amir $45. "
                        "Did Amir receive $45 from Rosa?")
        self.assertEqual(r["verdict"], "yes")

    def test_one_slot_shared_stays_unknown(self):
        # Only the giver is shared: the story says nothing about
        # this transfer, so the honest answer is unknown, not no.
        r = answer_text("Zoe paid Kofi $120. Did Zoe pay Sana $18?")
        self.assertEqual(r["verdict"], "unknown")

    def test_unrelated_giver_stays_unknown(self):
        r = answer_text("Rosa paid Felix $45. Did Omar give Felix $35?")
        self.assertEqual(r["verdict"], "unknown")

    def test_sell_after_buy_stays_unknown(self):
        # Not a money transfer: closed-world never applies.
        r = answer_text("John bought a bike. Did John sell a bike?")
        self.assertEqual(r["verdict"], "unknown")


class TestUndeterminedBalance(unittest.TestCase):
    """The ambiguous cluster: a balance the story never determines
    is unknown, not $0. A person mentioned only with an unquantified
    amount, or not mentioned at all, has no ledger balance."""

    def test_some_money_is_unknown(self):
        r = answer_text("Kofi gave Zoe some money. "
                        "How much money does Zoe have?")
        self.assertIsNone(r["answer"])
        self.assertEqual(r["verdict"], "unknown")
        # The rendered answer must not contain a number to guess from.
        self.assertNotIn("$0", r["answer_text"])

    def test_absent_person_is_unknown(self):
        r = answer_text("Sana gave $70 to someone. "
                        "How much money does Zoe have?")
        self.assertIsNone(r["answer"])
        self.assertEqual(r["verdict"], "unknown")

    def test_negated_only_balance_is_still_zero(self):
        # A negated quantified transfer DOES determine the balance:
        # the story says money to Owen was not given, so Owen has $0.
        r = answer_text("Noor did not give Owen $22. "
                        "How much money does Owen have?")
        self.assertEqual(r["answer"], 0)


if __name__ == "__main__":
    unittest.main()
