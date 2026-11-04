"""Tests for the genuine-handoff path (NOVA Intelligence Assistance).

Mock-only: no live model calls anywhere in this suite. The mock
proves the plumbing (package built, prompt assembled, response
parsed, scoring recorded); its accuracy numbers mean nothing.

Run:  python3 -m unittest discover -s tests -p test_handoff.py
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.fixtures import build_knowledge  # noqa: E402
from eval.harness import (RunConfig, load_items, run_arm_alone,  # noqa: E402
                          run_arm_handoff, summarize_handoff)
from eval.mock_model import MockModel  # noqa: E402
from eval.normalize import (is_correct, normalize_answer,  # noqa: E402
                            normalize_number)
from nova.semantic.handoff import (  # noqa: E402
    build_explanation_package, build_variant_prompt, coherence_scores)

ROOT = Path(__file__).resolve().parent.parent
FRESH = ROOT / "data" / "eval_uplift_fresh.jsonl"
FROZEN = ROOT / "data" / "eval_uplift.jsonl"


def _money_item():
    items = load_items(FRESH)
    return next(it for it in items if it["category"] == "money")


def _dict_item():
    items = load_items(FRESH)
    return next(it for it in items if it["category"] == "dictionary")


def _oracle_item():
    items = load_items(FRESH)
    return next(it for it in items if it.get("rules"))


class CopyingStubModel:
    """A stub that copies NOVA's verified answer out of the prompt.

    Proves the scoring path: when the model follows the package,
    the handoff arm scores exactly NOVA's accuracy. It is NOT a
    language model and its numbers mean nothing beyond plumbing.
    """
    model_id = "stub-copy-v0"
    checkpoint = "stub-copy-v0"
    temperature = 0
    max_tokens = 2048

    def config(self):
        return {"model_id": self.model_id,
                "checkpoint": self.checkpoint,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens}

    def __call__(self, prompt, item_id="unknown"):
        marker = "NOVA's verified answer: "
        if marker in prompt:
            rest = prompt.split(marker, 1)[1]
            answer = rest.split(" (confidence")[0].strip()
        else:
            answer = "I don't know"
        return f"{answer}\nThat is what NOVA's analysis shows."


class TestNormalizerFix(unittest.TestCase):
    def test_number_words(self):
        self.assertEqual(normalize_number("six"), 6)
        self.assertEqual(normalize_number("twenty-one"), 21)
        self.assertEqual(normalize_number("the answer is six"), 6)
        self.assertEqual(normalize_number("one hundred"), 100)
        self.assertEqual(normalize_number("6"), 6)
        self.assertEqual(normalize_number("$10"), 10)

    def test_number_word_mining_refused(self):
        # A sentence containing two numbers must not be mined.
        self.assertIsNone(
            normalize_number("two spiders have sixteen legs"))
        self.assertIsNone(normalize_number("I don't know"))

    def test_text_keyword_digit_word_equivalence(self):
        self.assertTrue(is_correct(normalize_answer("6", "text"),
                                   "text", {"keywords": ["six"]}))
        self.assertTrue(is_correct(normalize_answer("8", "text"),
                                   "text", {"keywords": ["eight"]}))
        self.assertTrue(is_correct(normalize_answer("sixty", "text"),
                                   "text", {"keywords": ["60"]}))
        self.assertTrue(is_correct(normalize_answer("six", "text"),
                                   "text", {"keywords": ["six"]}))
        self.assertFalse(is_correct(normalize_answer("7", "text"),
                                    "text", {"keywords": ["six"]}))


class TestPackageBuilder(unittest.TestCase):
    def setUp(self):
        self.knowledge = build_knowledge()

    def test_money_package(self):
        item = _money_item()
        pkg = build_explanation_package(
            item["text"], knowledge=self.knowledge,
            rules=item.get("rules"),
            nova_request=item.get("nova_request"),
            ground_truth=item["ground_truth"])
        self.assertEqual(pkg["input_mode"], "text")
        self.assertTrue(pkg["reasoning_steps"],
                        "a money item must carry proof steps")
        self.assertTrue(pkg["graph_lines"],
                        "a money item must carry a concept graph")
        self.assertGreaterEqual(pkg["n_interpretations"], 1)
        self.assertIn("confidence", pkg)
        self.assertEqual(pkg["verified_answer"],
                         f"${item['ground_truth']:g}"
                         if isinstance(item["ground_truth"], (int, float))
                         else str(item["ground_truth"]))

    def test_dictionary_package(self):
        item = _dict_item()
        pkg = build_explanation_package(
            item["text"], knowledge=self.knowledge,
            rules=item.get("rules"),
            nova_request=item.get("nova_request"),
            ground_truth=item["ground_truth"])
        terms = [d["term"] for d in pkg["definitions"]]
        want = (item.get("nova_request") or {}).get("term")
        self.assertIn(want, terms)
        hit = next(d for d in pkg["definitions"]
                   if d["term"] == want)
        for kw in item["ground_truth"]["keywords"]:
            self.assertIn(kw.lower(), hit["meaning"].lower())

    def test_oracle_package(self):
        item = _oracle_item()
        pkg = build_explanation_package(
            item["text"], knowledge=self.knowledge,
            rules=item.get("rules"),
            nova_request=item.get("nova_request"),
            ground_truth=item["ground_truth"])
        self.assertEqual(pkg["input_mode"], "structured_oracle")
        self.assertEqual(pkg["verified_answer"], "yes")

    def test_ground_truth_does_not_leak_into_content(self):
        # Rebuilding with a deliberately WRONG non-unknown ground
        # truth must produce a byte-identical package: the ground
        # truth is used only for the oracle-fallback routing
        # decision, never for content.
        item = _money_item()
        base = build_explanation_package(
            item["text"], knowledge=self.knowledge,
            rules=item.get("rules"),
            nova_request=item.get("nova_request"),
            ground_truth=item["ground_truth"])
        wrong = build_explanation_package(
            item["text"], knowledge=self.knowledge,
            rules=item.get("rules"),
            nova_request=item.get("nova_request"),
            ground_truth=99999)
        self.assertEqual(json.dumps(base, sort_keys=True, default=str),
                         json.dumps(wrong, sort_keys=True, default=str))

    def test_unknown_item_abstains(self):
        items = load_items(FRESH)
        item = next(it for it in items
                    if it["ground_truth"] == "unknown"
                    and it["category"] == "symbolic")
        pkg = build_explanation_package(
            item["text"], knowledge=self.knowledge,
            rules=item.get("rules"),
            nova_request=item.get("nova_request"),
            ground_truth=item["ground_truth"])
        self.assertEqual(pkg["verified_answer"], "cannot be determined")


class TestPromptVariants(unittest.TestCase):
    def setUp(self):
        self.knowledge = build_knowledge()
        item = _money_item()
        self.pkg = build_explanation_package(
            item["text"], knowledge=self.knowledge,
            rules=item.get("rules"),
            nova_request=item.get("nova_request"),
            ground_truth=item["ground_truth"])
        self.text = item["text"]

    def test_full_contains_verified_answer(self):
        prompt = build_variant_prompt(self.pkg, "full", text=self.text)
        self.assertIn("NOVA's verified answer:", prompt)
        self.assertIn("NOVA's reasoning:", prompt)
        self.assertIn("How NOVA reads the question:", prompt)

    def test_no_answer_omits_verified_answer(self):
        prompt = build_variant_prompt(self.pkg, "no_answer",
                                      text=self.text)
        self.assertNotIn("NOVA's verified answer:", prompt)
        self.assertIn("NOVA's reasoning:", prompt)

    def test_context_has_no_reasoning(self):
        prompt = build_variant_prompt(self.pkg, "context",
                                      text=self.text)
        self.assertNotIn("NOVA's reasoning:", prompt)
        self.assertNotIn("NOVA's verified answer:", prompt)
        self.assertNotIn("How NOVA reads the question:", prompt)
        self.assertIn("The facts in the question:", prompt)
        self.assertIn("NOVA's understanding of the words:", prompt)

    def test_translation_only_interpretations(self):
        prompt = build_variant_prompt(self.pkg, "translation",
                                      text=self.text)
        self.assertIn("How NOVA reads the question:", prompt)
        self.assertNotIn("NOVA's reasoning:", prompt)
        self.assertNotIn("NOVA's verified answer:", prompt)
        self.assertNotIn("NOVA's understanding of the words:", prompt)

    def test_reasoning_no_answer_no_lexicon(self):
        prompt = build_variant_prompt(self.pkg, "reasoning",
                                      text=self.text)
        self.assertIn("NOVA's reasoning:", prompt)
        self.assertIn("The concepts and their relationships:", prompt)
        self.assertNotIn("NOVA's verified answer:", prompt)
        self.assertNotIn("NOVA's understanding of the words:", prompt)


class TestCoherenceRubric(unittest.TestCase):
    def setUp(self):
        self.knowledge = build_knowledge()
        item = _money_item()
        self.pkg = build_explanation_package(
            item["text"], knowledge=self.knowledge,
            rules=item.get("rules"),
            nova_request=item.get("nova_request"),
            ground_truth=item["ground_truth"])
        self.kind = item["answer_kind"]

    def test_answer_only(self):
        ans = self.pkg["verified_answer"]
        scores = coherence_scores(ans, self.pkg, self.kind)
        self.assertEqual(scores["c1_answer_present"], 1)
        self.assertEqual(scores["c2_grounded_explanation"], 0)
        self.assertTrue(scores["copied_without_reasoning"])

    def test_grounded_explanation(self):
        ans = self.pkg["verified_answer"]
        raw = (f"{ans}\nMarcus gave John the money, so the "
               f"balance is {ans}.")
        scores = coherence_scores(raw, self.pkg, self.kind)
        self.assertEqual(scores["coherence"], 3)

    def test_empty_response(self):
        scores = coherence_scores("", self.pkg, self.kind)
        self.assertEqual(scores["coherence"], 0)


class TestHandoffRunner(unittest.TestCase):
    def test_mock_run_all_variants(self):
        items = load_items(FRESH)[:10]
        model = MockModel()
        for variant in ("full", "no_answer", "context", "translation",
                        "reasoning"):
            cfg = RunConfig(model_id=model.model_id,
                            checkpoint=model.checkpoint,
                            temperature=model.temperature,
                            max_tokens=model.max_tokens,
                            arm="handoff", set_name="fresh", mock=True,
                            run_id=f"test-{variant}")
            recs = run_arm_handoff(items, model, cfg, variant=variant)
            self.assertEqual(len(recs), 10)
            for r in recs:
                self.assertIn("prompt", r)
                self.assertIsNotNone(r["prompt"])
                self.assertIn("trace", r)
                self.assertEqual(r["trace"]["variant"], variant)
                self.assertIn("nova_correct", r["trace"])
                self.assertIn("coherence", r["trace"])
                self.assertIn("prompt_chars", r["trace"])
                self.assertGreater(r["trace"]["nova_ms"], 0)

    def test_copying_stub_scores_nova_accuracy(self):
        items = load_items(FRESH)[:20]
        model = CopyingStubModel()
        cfg = RunConfig(model_id=model.model_id,
                        checkpoint=model.checkpoint,
                        temperature=model.temperature,
                        max_tokens=model.max_tokens,
                        arm="handoff", set_name="fresh", mock=True,
                        run_id="test-copy")
        recs = run_arm_handoff(items, model, cfg, variant="full")
        # The stub copies the verified answer, so handoff accuracy
        # must equal NOVA's own accuracy on these items, with zero
        # overrides and no answer-only responses.
        nova_acc = sum(1 for r in recs
                       if r["trace"]["nova_correct"]) / len(recs)
        hand_acc = sum(1 for r in recs if r["correct"]) / len(recs)
        self.assertEqual(hand_acc, nova_acc)
        self.assertEqual(sum(1 for r in recs
                             if r["trace"]["override"]), 0)
        self.assertEqual(sum(1 for r in recs if r["trace"]
                             ["copied_without_reasoning"]), 0)

    def test_first_line_scoring(self):
        # A response whose explanation quotes story numbers must
        # still score from the first line only.
        items = [_money_item()]
        model = CopyingStubModel()
        cfg = RunConfig(model_id=model.model_id,
                        checkpoint=model.checkpoint,
                        temperature=model.temperature,
                        max_tokens=model.max_tokens,
                        arm="handoff", set_name="fresh", mock=True,
                        run_id="test-firstline")
        recs = run_arm_handoff(items, model, cfg, variant="full")
        self.assertTrue(recs[0]["correct"])
        self.assertEqual(recs[0]["trace"]["nova_correct"], True)

    def test_summarize_handoff(self):
        items = load_items(FRESH)[:10]
        mock = MockModel()
        cfg_a = RunConfig(model_id=mock.model_id,
                          checkpoint=mock.checkpoint,
                          temperature=mock.temperature,
                          max_tokens=mock.max_tokens,
                          arm="alone", set_name="fresh", mock=True,
                          run_id="test-sum-alone")
        alone = run_arm_alone(items, mock, cfg_a)
        cfg_h = RunConfig(model_id=mock.model_id,
                          checkpoint=mock.checkpoint,
                          temperature=mock.temperature,
                          max_tokens=mock.max_tokens,
                          arm="handoff", set_name="fresh", mock=True,
                          run_id="test-sum-handoff")
        hand = run_arm_handoff(items, mock, cfg_h, variant="full")
        summary = summarize_handoff(alone, hand)
        self.assertEqual(summary["n"], 10)
        self.assertIn("override_n", summary)
        self.assertIn("ignore_n", summary)
        self.assertIn("mean_coherence", summary)
        self.assertIn("per_category", summary)

    def test_handoff_requires_model(self):
        items = load_items(FRESH)[:2]
        cfg = RunConfig(arm="handoff", set_name="fresh", mock=True,
                        run_id="test-nomodel")
        with self.assertRaises(ValueError):
            run_arm_handoff(items, None, cfg, variant="full")


class TestDevSubset(unittest.TestCase):
    def test_dev_subset_deterministic(self):
        from eval.run_handoff import dev_subset
        items = load_items(FRESH)
        a = dev_subset(items)
        b = dev_subset(items)
        self.assertEqual(len(a), 50)
        self.assertEqual([it["id"] for it in a],
                         [it["id"] for it in b])
        cats = {it["category"] for it in a}
        self.assertEqual(len(cats), 12)


if __name__ == "__main__":
    unittest.main()
