"""Stabilization tests: routing, the zero-audit, antonyms, send/give,
copula/has-a facts, the knowledge bridges, rule syllogisms, the
model interface, and the round-trip (item 5's loss metric lives in
test_roundtrip.py; this file covers the behaviour the eval measures).

The zero-audit (item 2) is the load-bearing part: every test here
asserts that an unknown value stays unknown — in the ledger, the
calculator, the renderer, and the API envelope — and never becomes a
zero or a guessed number.
"""

from __future__ import annotations

import unittest

from eval.fixtures import build_knowledge
from nova.adapter.core import calculate
from nova.model_interface import (CallableModel, MockModel, ModelConfig,
                                  coerce_model, get_model, list_models,
                                  register_model)
from nova.semantic import answer_text, process_request
from nova.semantic.facts import extract_rule_frame
from nova.semantic.render import (render_amount_paid_answer,
                                  render_balance_answer,
                                  render_per_unit_answer)
from nova.semantic.roundtrip import roundtrip_loss

KNOWLEDGE = build_knowledge()


def answer(text):
    return answer_text(text, knowledge=KNOWLEDGE)


class TestRouting(unittest.TestCase):
    def test_calculator(self):
        r = answer("What is 15 * 120 * 8?")
        self.assertEqual(r["answer"], 14400)
        self.assertEqual(r["status"], "verified")

    def test_calculator_word_operator(self):
        r = answer("What is 100 divided by 4?")
        self.assertEqual(r["answer"], 25)

    def test_dictionary(self):
        r = answer("What does 'purchase' mean?")
        self.assertIn("obtain", r["answer"]["meaning"])

    def test_define_falls_back_to_encyclopedia(self):
        r = answer("Define thermal expansion.")
        self.assertIn("expand", r["answer"]["meaning"])

    def test_encyclopedia(self):
        r = answer("What happens to most materials when heated?")
        self.assertIn("expand", r["answer"]["meaning"])

    def test_prove_with_rule(self):
        r = answer("If someone is human, they are mortal. "
                   "Socrates is human. Prove Socrates is mortal.")
        self.assertEqual(r["verdict"], "yes")

    def test_prove_without_premises_stays_unknown(self):
        r = answer("Prove Socrates is mortal.")
        self.assertEqual(r["verdict"], "unknown")
        # A yes/no envelope carries the verdict as its answer.
        self.assertEqual(r["answer"], "unknown")

    def test_unroutable_stays_unknown(self):
        r = answer("What is the capital of France?")
        self.assertEqual(r["verdict"], "unknown")
        self.assertIsNone(r["answer"])


class TestZeroAudit(unittest.TestCase):
    """Item 2: never substitute zero for an unknown value, anywhere."""

    def test_undetermined_balance_is_not_zero(self):
        r = answer("Zoe gave Omar some money. "
                   "How much money does Omar have?")
        self.assertIsNone(r["answer"])
        self.assertEqual(r["verdict"], "unknown")
        self.assertNotIn("$0", r["answer_text"])
        self.assertIn("unknown", r["answer_text"].lower())

    def test_person_never_mentioned_is_not_zero(self):
        r = answer("Marcus gave John $20. "
                   "How much money does Sarah have?")
        self.assertIsNone(r["answer"])
        self.assertEqual(r["verdict"], "unknown")

    def test_unmentioned_transfer_stays_unknown(self):
        r = answer("Did Omar pay Cleo $45?")
        self.assertEqual(r["verdict"], "unknown")
        self.assertEqual(r["answer"], "unknown")

    def test_per_unit_without_fact_is_not_zero(self):
        # No has-a fact in the text, but the knowledge store has the
        # spider entry, so this one IS answerable via the bridge (24).
        r = answer("How many legs do three spiders have?")
        self.assertEqual(r["answer"], 24)
        # A thing with no fact anywhere stays unknown, never zero.
        r2 = answer("How many horns do two zibbles have?")
        self.assertIsNone(r2["answer"])
        self.assertEqual(r2["verdict"], "unknown")
        self.assertNotIn(" 0 ", r2["answer_text"].split("\n")[0])

    def test_calculator_rejects_bad_input(self):
        for bad in ("abc", "", "12 *", "import os", "12 / 0"):
            with self.assertRaises((ValueError, SyntaxError,
                                    ZeroDivisionError), msg=bad):
                calculate(bad)

    def test_render_never_prints_zero_for_unknown(self):
        from nova.semantic import ConceptFrame
        q = ConceptFrame(kind="query", who="Omar", what="balance")
        out = render_balance_answer(q, None, [])
        self.assertNotIn("$0", out)
        self.assertIn("unknown", out.lower())
        out2 = render_per_unit_answer(
            ConceptFrame(kind="query", what="per_unit_total",
                         object="legs", quantity=3,
                         relationships=[{"rel": "per_unit_of",
                                         "target": "spiders"}]),
            None, [])
        self.assertNotIn(" 0 ", out2.split("\n")[0])
        self.assertIn("don't know", out2.lower())

    def test_api_envelope_unknown_is_null_not_zero(self):
        result = process_request(
            {"text": "Zoe gave Omar some money. "
                     "How much money does Omar have?"})
        self.assertIsNone(result["answer"])
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["status"], "unknown")

    def test_api_unparseable_raises(self):
        with self.assertRaises(ValueError):
            process_request({"text": "flibberty gibbet wozzle."})


class TestAntonyms(unittest.TestCase):
    def test_light_on_off(self):
        r = answer("The light is on. Is the light off?")
        self.assertEqual(r["verdict"], "no")

    def test_store_open_closed(self):
        r = answer("The store is open. Is the store closed?")
        self.assertEqual(r["verdict"], "no")

    def test_soup_hot_cold(self):
        r = answer("The soup is hot. Is the soup cold?")
        self.assertEqual(r["verdict"], "no")

    def test_stated_state_is_yes(self):
        r = answer("The light is on. Is the light on?")
        self.assertEqual(r["verdict"], "yes")

    def test_absent_state_stays_unknown(self):
        # "Not on" does not prove "off": absence of evidence for one
        # state is not evidence for the opposite.
        r = answer("The light is not on. Is the light off?")
        self.assertEqual(r["verdict"], "unknown")


class TestSendGiveAndReceive(unittest.TestCase):
    def test_send_is_give(self):
        r = answer("Amir sent Omar $90. Did Amir give Omar $90?")
        self.assertEqual(r["verdict"], "yes")

    def test_pay_is_give(self):
        r = answer("Yusuf paid Felix $18. Did Yusuf give Felix $18?")
        self.assertEqual(r["verdict"], "yes")

    def test_receive_is_give(self):
        r = answer("Omar received $40 from Lena. "
                   "How much money does Omar have?")
        self.assertEqual(r["answer"], 40)

    def test_negated_receive_is_no(self):
        r = answer("Omar did not receive $40 from Lena. "
                   "Did Omar receive $40 from Lena?")
        self.assertEqual(r["verdict"], "no")

    def test_buying_is_not_selling(self):
        r = answer("John bought a bicycle. Did John sell a bicycle?")
        self.assertEqual(r["verdict"], "unknown")


class TestCopulaHasAndPerUnit(unittest.TestCase):
    def test_is_a(self):
        r = answer("Jupiter is the largest planet. "
                   "Is Jupiter the largest planet?")
        self.assertEqual(r["verdict"], "yes")

    def test_known_as(self):
        r = answer("Mars is known as the Red Planet. "
                   "Is Mars the Red Planet?")
        self.assertEqual(r["verdict"], "yes")

    def test_bees_produce(self):
        r = answer("Bees produce honey. Do bees produce honey?")
        self.assertEqual(r["verdict"], "yes")

    def test_cannot(self):
        r = answer("A penguin cannot fly. Can a penguin fly?")
        self.assertEqual(r["verdict"], "no")

    def test_has_a(self):
        r = answer("A hexagon has six sides. "
                   "Does a hexagon have six sides?")
        self.assertEqual(r["verdict"], "yes")

    def test_per_unit_spider(self):
        r = answer("A spider has eight legs. "
                   "How many legs do two spiders have?")
        self.assertEqual(r["answer"], 16)

    def test_per_unit_bicycle(self):
        r = answer("A bicycle has two wheels. "
                   "How many wheels do three bicycles have?")
        self.assertEqual(r["answer"], 6)

    def test_per_unit_hour(self):
        r = answer("An hour has 60 minutes. "
                   "How many minutes are in three hours?")
        self.assertEqual(r["answer"], 180)

    def test_per_unit_octopus_plural(self):
        r = answer("An octopus has eight arms. "
                   "How many arms do two octopuses have?")
        self.assertEqual(r["answer"], 16)

    def test_per_unit_from_knowledge_only(self):
        r = answer("How many legs do five spiders have?")
        self.assertEqual(r["answer"], 40)

    def test_amount_paid(self):
        r = answer("Yusuf purchased a bicycle for $120. "
                   "How much money did Yusuf pay?")
        self.assertEqual(r["answer"], 120)


class TestRules(unittest.TestCase):
    def test_socrates(self):
        r = answer("If someone is human, they are mortal. "
                   "Socrates is human. Is Socrates mortal?")
        self.assertEqual(r["verdict"], "yes")
        self.assertIn("is(socrates,human) -> is(socrates,mortal)",
                      r["answer_text"])

    def test_rex(self):
        r = answer("If something is a dog, it is an animal. "
                   "Rex is a dog. Is Rex an animal?")
        self.assertEqual(r["verdict"], "yes")

    def test_rule_frame_is_not_a_garbage_fact(self):
        frame = extract_rule_frame(
            "If someone is human, they are mortal.")
        self.assertIsNotNone(frame)
        self.assertEqual(frame.kind, "rule")
        self.assertEqual(frame.object, "human")
        self.assertEqual(frame.relationships[0]["target"], "mortal")

    def test_adjective_rule_consequent(self):
        # The rule concludes is(iron,strong); the question asks
        # state(iron,strong). Same thing for an adjective.
        r = answer("If something is metal, it is strong. "
                   "Iron is metal. Is iron strong?")
        self.assertEqual(r["verdict"], "yes")

    def test_conditional_without_rule_form_stays_unknown(self):
        # A modal consequent ("can fly") is outside the rule parser:
        # the sentence must not become a garbage fact, and the answer
        # must stay unknown rather than a guessed yes.
        r = answer("If someone is a bird, they can fly. "
                   "A penguin is a bird. Can a penguin fly?")
        self.assertEqual(r["verdict"], "unknown")


class TestModelInterface(unittest.TestCase):
    def test_registry_lists_meta_and_mock(self):
        self.assertIn("meta", list_models())
        self.assertIn("mock", list_models())

    def test_mock_model_flows_through(self):
        r = answer_text("Marcus gave John $20. "
                        "How much money does John have?",
                        model=MockModel("the model guesses $99"))
        self.assertEqual(r["answer"], 20)
        self.assertEqual(r["model_output"]["text"],
                         "the model guesses $99")
        self.assertEqual(r["model_output"]["status"],
                         "unverified_model_output")

    def test_callable_model_flows_through(self):
        r = answer_text("Marcus gave John $20. "
                        "How much money does John have?",
                        model=lambda p: "plain callable")
        self.assertEqual(r["answer"], 20)
        self.assertEqual(r["model_output"]["model_id"], "callable")

    def test_bad_model_type_is_reported_not_fatal(self):
        r = answer_text("Marcus gave John $20. "
                        "How much money does John have?", model=42)
        self.assertEqual(r["answer"], 20)
        self.assertIn("error", r["model_output"])

    def test_unknown_model_name(self):
        with self.assertRaises(ValueError):
            get_model("qwen")

    def test_meta_unconfigured_raises_clearly(self):
        # Contract change (Phase 4, Req 6): the Meta adapter is now
        # connector-backed and serves muse-spark-1.3 by default, so
        # there is no "unconfigured" state for it any more — an
        # empty model_id resolves to the connector's model instead
        # of raising. The "fail clearly, never silently degrade"
        # contract now lives where configuration is actually
        # required: a non-Spark model id, and the generic
        # openai-compatible backend with no endpoint.
        import os
        from unittest import mock
        from nova.model_interface import MetaModelAdapter
        with mock.patch.dict(os.environ, {}, clear=True):
            model = get_model("meta", ModelConfig(model_id="",
                                                  endpoint=None))
            self.assertEqual(model.model_id, "muse-spark-1.3")
            with self.assertRaises(ValueError):
                MetaModelAdapter(ModelConfig(model_id="gpt-4"))
            with self.assertRaises(ValueError):
                get_model("openai-compatible",
                          ModelConfig(model_id="", endpoint=None))

    def test_register_custom_model(self):
        register_model("test-dummy",
                       lambda cfg: MockModel("dummy",
                                             model_id="test-dummy"))
        self.assertEqual(get_model("test-dummy").complete("x").text,
                         "dummy")

    def test_coerce_none(self):
        self.assertIsNone(coerce_model(None))
        self.assertIsInstance(coerce_model(lambda p: "x"),
                              CallableModel)


class TestRoundTripLossMetric(unittest.TestCase):
    def test_no_loss_on_probe_sentences(self):
        sentences = [
            "Marcus gave John $20.",
            "John gave Sarah $10.",
            "The light is on.",
            "A spider has eight legs.",
            "Jupiter is the largest planet.",
            "Omar did not receive $40 from Lena.",
            "If someone is human, they are mortal.",
        ]
        loss = roundtrip_loss(sentences)
        self.assertEqual(loss["lost_slots"], [])
        self.assertEqual(loss["invented_slots"], [])
        self.assertEqual(loss["polarity_flips"], 0)
        self.assertEqual(loss["negation_lost"], 0)
        self.assertEqual(loss["frames_lost"], 0)
        self.assertEqual(loss["preserved_slots"], loss["known_slots"])
        self.assertEqual(loss["preservation_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
