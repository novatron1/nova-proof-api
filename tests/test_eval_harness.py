"""Harness-mechanics tests for the Capability Uplift Test.

Run:  python3 -m tests.test_eval_harness   (from the repo root)

Covers: normalization, classification, metrics (Wilson + paired
bootstrap), the comparison guard, the holdout guard, ablation
toggles, mock determinism, and eval-set integrity (counts, no
overlap with the development probes or between eval/holdout).
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval import analyze as ev_analyze  # noqa: E402
from eval.fixtures import build_knowledge  # noqa: E402
from eval.gen_eval import EVAL_COUNTS, check_overlap  # noqa: E402
from eval.harness import (COST_BASIS_LIVE, PROMPT_TEMPLATE, RunConfig,  # noqa: E402
                          build_retrieval_prompt, classify, load_items,
                          retrieve_knowledge, run_arm_alone, run_arm_nova,
                          run_arm_retrieval, run_comparison,
                          summarize_three_way)
from eval.metrics import (accuracy_wilson,  # noqa: E402
                          paired_bootstrap_ci)
from eval.mock_model import MockModel  # noqa: E402
from eval.normalize import (is_correct, normalize_answer,  # noqa: E402
                            normalize_number, normalize_yes_no)
from eval.run_eval import _guard_holdout  # noqa: E402
from nova.model_interface import ModelResponse  # noqa: E402
from nova.semantic import answer_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class TestNormalize(unittest.TestCase):
    def test_number(self):
        self.assertEqual(normalize_number("$10"), 10)
        self.assertEqual(normalize_number("John has $10 left."), 10)
        self.assertEqual(normalize_number("42"), 42)
        self.assertIsNone(normalize_number("I don't know."))
        self.assertIsNone(normalize_number(None))

    def test_yes_no(self):
        self.assertEqual(normalize_yes_no("Yes."), "yes")
        self.assertEqual(normalize_yes_no("No, he didn't."), "no")
        self.assertEqual(normalize_yes_no("I don't know."), "unknown")
        self.assertEqual(normalize_yes_no("Yes, John has $10."), "yes")
        self.assertIsNone(normalize_yes_no(""))

    def test_text_keywords(self):
        self.assertTrue(is_correct(
            normalize_answer("obtain something in exchange for payment",
                             "text"),
            "text", {"keywords": ["obtain", "payment"]}))
        self.assertFalse(is_correct(
            normalize_answer("It is a kind of machine.", "text"),
            "text", {"keywords": ["obtain", "payment"]}))
        # Numbers survive text normalization: "an hour has 60 minutes"
        # must satisfy the keyword "60".
        self.assertTrue(is_correct(
            normalize_answer("an hour has 60 minutes", "text"),
            "text", {"keywords": ["60"]}))
        self.assertTrue(is_correct(
            normalize_answer("Mars is known as the Red Planet", "text"),
            "text", {"keywords": ["Mars"]}))

    def test_unknown_ground_truth(self):
        # Abstention is the right answer when the truth is unknown.
        from eval.harness import check_correct
        item = {"ground_truth": "unknown", "answer_kind": "number"}
        self.assertTrue(check_correct(None, item))
        self.assertFalse(check_correct(0, item))
        item = {"ground_truth": "unknown", "answer_kind": "yes_no"}
        self.assertTrue(check_correct("unknown", item))
        self.assertFalse(check_correct("yes", item))


class TestClassifyAndMetrics(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify(False, True), "wrong->correct")
        self.assertEqual(classify(True, False), "correct->wrong")
        self.assertEqual(classify(True, True), "correct->correct")
        self.assertEqual(classify(False, False), "wrong->wrong")

    def test_wilson_contains_truth(self):
        res = accuracy_wilson([True] * 50 + [False] * 50)
        self.assertAlmostEqual(res["accuracy"], 0.5)
        self.assertLess(res["ci95_low"], 0.5)
        self.assertGreater(res["ci95_high"], 0.5)
        self.assertLess(res["ci95_high"] - res["ci95_low"], 0.25)

    def test_bootstrap_identical_arms(self):
        flags = [True, False, True, True, False] * 20
        res = paired_bootstrap_ci(flags, flags, n_boot=200)
        self.assertAlmostEqual(res["diff"], 0.0)
        self.assertLessEqual(res["ci95_low"], 0.0)
        self.assertGreaterEqual(res["ci95_high"], 0.0)

    def test_bootstrap_detects_difference(self):
        alone = [False] * 100
        nova = [True] * 100
        res = paired_bootstrap_ci(alone, nova, n_boot=200)
        self.assertAlmostEqual(res["diff"], 1.0)
        self.assertGreater(res["ci95_low"], 0.9)


class TestGuards(unittest.TestCase):
    def test_holdout_refused_without_final(self):
        with self.assertRaises(SystemExit) as ctx:
            _guard_holdout("holdout", False, "test-run")
        self.assertEqual(ctx.exception.code, 2)

    def test_comparison_refuses_model_none(self):
        items = load_items(ROOT / "data" / "eval_uplift.jsonl")[:3]
        cfg = RunConfig(run_id="t-none", set_name="eval")
        recs = run_arm_nova(items, cfg)
        with self.assertRaises(ValueError):
            run_comparison(recs, recs)

    def test_comparison_refuses_mismatched_config(self):
        items = load_items(ROOT / "data" / "eval_uplift.jsonl")[:3]
        mock = MockModel()
        cfg_a = RunConfig(run_id="t-a", set_name="eval", arm="alone",
                          mock=True, model_id="mock-tiny-lm-v0",
                          checkpoint="mock-v0", temperature=0,
                          max_tokens=128)
        cfg_b = RunConfig(run_id="t-b", set_name="eval", arm="nova",
                          mock=True, model_id="mock-tiny-lm-v0",
                          checkpoint="mock-v0", temperature=1,
                          max_tokens=128)
        a = run_arm_alone(items, mock, cfg_a)
        b = run_arm_nova(items, cfg_b, model=mock)
        with self.assertRaises(ValueError):
            run_comparison(a, b)


class TestAblation(unittest.TestCase):
    def test_heuristic_ablation(self):
        # "his sister" needs the heuristic tier: with it ablated, the
        # transfer sentence yields no frame, so the balance question
        # is undetermined. The honest answer is unknown (None), NOT
        # $0: an empty ledger is not evidence Sister has $0. (This
        # test used to assert 0 — that expectation encoded the
        # zero-for-unknown bug fixed with the hard-negative cluster.)
        text = ("Marcus gave his sister $50 yesterday at the store "
                "because she needed groceries. "
                "How much money does Sister have?")
        full = answer_text(text)
        self.assertEqual(full["answer"], 50)
        self.assertTrue(any(f.get("kind") == "transfer"
                            for f in full["frames"]))
        ablated = answer_text(text, ablations={"heuristic"})
        self.assertFalse(any(f.get("kind") == "transfer"
                             for f in ablated["frames"]))
        self.assertIsNone(ablated["answer"])
        self.assertEqual(ablated["verdict"], "unknown")

    def test_reasoner_ablation(self):
        text = "Marcus paid Elena. Did Marcus pay Elena?"
        full = answer_text(text)
        self.assertEqual(full["verdict"], "yes")
        ablated = answer_text(text, ablations={"reasoner"})
        self.assertEqual(ablated["verdict"], "unknown")


class TestMock(unittest.TestCase):
    def test_deterministic(self):
        mock = MockModel()
        prompt = ("Answer the following question. Give only the answer: "
                  "a number, yes, no, or \"I don't know\" if it cannot "
                  "be determined.\n\nQuestion: Marcus gave John $20. "
                  "John gave Sarah $10. How much money does John have "
                  "left from the $20?\nAnswer:")
        self.assertEqual(mock(prompt, item_id="eval-001"),
                         mock(prompt, item_id="eval-001"))

    def test_mock_money_shape(self):
        mock = MockModel()
        raw = mock("Question: Omar gave Nina $35. Nina gave Rosa $12. "
                   "How much money does Nina have?", item_id="eval-002")
        self.assertEqual(normalize_number(raw), 23)


class TestEvalSets(unittest.TestCase):
    def test_counts(self):
        eval_items = load_items(ROOT / "data" / "eval_uplift.jsonl")
        holdout_items = load_items(
            ROOT / "data" / "eval_uplift_holdout.jsonl")
        self.assertEqual(len(eval_items), 250)
        self.assertEqual(len(holdout_items), 100)
        groups = {it["group"] for it in eval_items}
        self.assertEqual(groups, {"deterministic", "unfamiliar_nl",
                                  "knowledge"})
        kinds = {it["answer_kind"] for it in eval_items}
        self.assertEqual(kinds, {"number", "yes_no", "text"})

    def test_no_overlap_with_dev_probes(self):
        eval_items = load_items(ROOT / "data" / "eval_uplift.jsonl")
        holdout_items = load_items(
            ROOT / "data" / "eval_uplift_holdout.jsonl")
        check_overlap(eval_items, ROOT / "data" / "money_probes.jsonl",
                      "money_probes.jsonl")
        check_overlap(holdout_items, ROOT / "data" / "money_probes.jsonl",
                      "money_probes.jsonl")
        eval_texts = {it["text"] for it in eval_items}
        self.assertFalse(
            any(it["text"] in eval_texts for it in holdout_items))

    def test_manifest_matches_files(self):
        import hashlib
        manifest = json.loads(
            (ROOT / "data" / "eval_manifest.json").read_text())
        for key, fname in (("eval_sha256", "data/eval_uplift.jsonl"),
                           ("holdout_sha256",
                            "data/eval_uplift_holdout.jsonl")):
            digest = hashlib.sha256(
                (ROOT / fname).read_bytes()).hexdigest()
            self.assertEqual(manifest[key], digest)


class TestLiveUsageRecording(unittest.TestCase):
    """Token/cost recording for live models (LiveModel accounting
    shape, no network): per-item usage, cost math, failed calls
    record no usage, models without accounting stay null."""

    class FakeLiveModel:
        """Mimics eval.live_model.LiveModel: __call__ + complete +
        mark_usage/usage_since, fixed fake token counts."""
        model_id = "fake-live"
        checkpoint = "fake-live"
        temperature = 0
        max_tokens = 2048

        def __init__(self):
            self._calls = []
            self.last_usage = None

        def config(self):
            return {"model_id": self.model_id,
                    "checkpoint": self.checkpoint,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens}

        def _record(self, tin, tout):
            self._calls.append({"tokens_in": tin, "tokens_out": tout,
                                "finish_reason": "stop"})
            self.last_usage = {"tokens_in": tin, "tokens_out": tout}

        def mark_usage(self):
            return len(self._calls)

        def usage_since(self, mark):
            mine = self._calls[mark:]
            return {"tokens_in": sum(c["tokens_in"] for c in mine),
                    "tokens_out": sum(c["tokens_out"] for c in mine),
                    "calls": len(mine), "truncated": False}

        def __call__(self, prompt, item_id=None):
            self._record(10, 20)
            return "42"

        def complete(self, prompt, max_tokens=2048, temperature=0.0):
            self._record(30, 40)
            return ModelResponse(text="advisor says 42",
                                 model_id=self.model_id)

    class RaisingModel:
        """Always fails: no usage must be attributed to its items."""
        model_id = "fake-raising"
        checkpoint = "fake-raising"
        temperature = 0
        max_tokens = 2048
        last_usage = None

        def config(self):
            return {"model_id": self.model_id,
                    "checkpoint": self.checkpoint,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens}

        def __call__(self, prompt, item_id=None):
            raise RuntimeError("boom")

    def test_alone_records_live_usage_and_cost(self):
        items = load_items(ROOT / "data" / "eval_uplift.jsonl")[:2]
        model = self.FakeLiveModel()
        cfg = RunConfig(run_id="t-live-alone", set_name="eval",
                        arm="alone", mock=False, **model.config())
        recs = run_arm_alone(items, model, cfg)
        for rec in recs:
            self.assertEqual(rec["tokens_in"], 10)
            self.assertEqual(rec["tokens_out"], 20)
            self.assertEqual(rec["token_source"], "live_api")
            self.assertEqual(rec["cost_basis"], COST_BASIS_LIVE)
            self.assertAlmostEqual(
                rec["cost_usd"],
                10 * 1.25 / 1_000_000 + 20 * 4.25 / 1_000_000)
            self.assertEqual(rec["trace"].get("live_calls"), 1)

    def test_nova_records_advisor_usage_answer_still_proven(self):
        # eval-005 is a plain money text item (no oracle request):
        # exactly one advisor call, and the answer still comes from
        # the pipeline, not the advisor's "42".
        items = [it for it in
                 load_items(ROOT / "data" / "eval_uplift.jsonl")
                 if it["id"] == "eval-005"]
        self.assertEqual(len(items), 1)
        model = self.FakeLiveModel()
        cfg = RunConfig(run_id="t-live-nova", set_name="eval",
                        arm="nova", mock=False, **model.config())
        recs = run_arm_nova(items, cfg, model=model)
        rec = recs[0]
        self.assertEqual(rec["tokens_in"], 30)
        self.assertEqual(rec["tokens_out"], 40)
        self.assertEqual(rec["token_source"], "live_api")
        self.assertEqual(rec["trace"].get("live_calls"), 1)
        self.assertEqual(rec["normalized_answer"], 11)
        self.assertTrue(rec["correct"])

    def test_no_usage_stays_null_for_mock(self):
        items = load_items(ROOT / "data" / "eval_uplift.jsonl")[:2]
        mock = MockModel()
        cfg = RunConfig(run_id="t-mock-null", set_name="eval",
                        arm="alone", mock=True, **mock.config())
        recs = run_arm_alone(items, mock, cfg)
        for rec in recs:
            self.assertIsNone(rec["tokens_in"])
            self.assertIsNone(rec["tokens_out"])
            self.assertEqual(rec["token_source"], "mock_no_counting")
            self.assertEqual(rec["cost_usd"], 0.0)

    def test_failed_call_records_no_usage(self):
        items = load_items(ROOT / "data" / "eval_uplift.jsonl")[:2]
        model = self.RaisingModel()
        cfg = RunConfig(run_id="t-live-fail", set_name="eval",
                        arm="alone", mock=False, **model.config())
        recs = run_arm_alone(items, model, cfg)
        for rec in recs:
            self.assertIsNone(rec["tokens_in"])
            self.assertIsNone(rec["tokens_out"])
            self.assertEqual(rec["token_source"], "unknown")
            self.assertFalse(rec["correct"])
            self.assertIn("boom", rec["trace"]["error"])

    def test_threaded_matches_sequential_for_mock(self):
        items = load_items(ROOT / "data" / "eval_uplift.jsonl")[:12]
        mock = MockModel()
        cfg_a = RunConfig(run_id="t-thr-a", set_name="eval",
                          arm="alone", mock=True, **mock.config())
        cfg_b = RunConfig(run_id="t-thr-b", set_name="eval",
                          arm="nova", mock=True, **mock.config())
        seq_alone = run_arm_alone(items, mock, cfg_a)
        thr_alone = run_arm_alone(items, mock, cfg_a, workers=4)
        self.assertEqual(
            [r["normalized_answer"] for r in seq_alone],
            [r["normalized_answer"] for r in thr_alone])
        self.assertEqual([r["correct"] for r in seq_alone],
                         [r["correct"] for r in thr_alone])
        seq_nova = run_arm_nova(items, cfg_b, model=mock)
        thr_nova = run_arm_nova(items, cfg_b, model=mock, workers=4)
        self.assertEqual(
            [r["normalized_answer"] for r in seq_nova],
            [r["normalized_answer"] for r in thr_nova])
        self.assertEqual([r["correct"] for r in seq_nova],
                         [r["correct"] for r in thr_nova])


class TestRetrievalArm(unittest.TestCase):
    """The model + knowledge-retrieval arm (audit, 2026-10-27):
    template v1 plus store lookups, no NOVA reasoning."""

    def test_dictionary_item_gets_knowledge_block(self):
        items = [it for it in
                 load_items(ROOT / "data" / "eval_uplift.jsonl")
                 if it["category"] == "dictionary"]
        self.assertTrue(items)
        prompt, entries = build_retrieval_prompt(items[0],
                                                 build_knowledge())
        self.assertTrue(entries)
        self.assertIn("Relevant knowledge from the concept store:",
                      prompt)
        self.assertIn(entries[0][1], prompt)  # term in the prompt
        self.assertIn(entries[0][2], prompt)  # meaning in the prompt
        self.assertTrue(prompt.endswith(
            PROMPT_TEMPLATE.format(text=items[0]["text"])))

    def test_money_item_gets_no_block_prompt_is_template_v1(self):
        items = [it for it in
                 load_items(ROOT / "data" / "eval_uplift.jsonl")
                 if it["category"] == "money"]
        prompt, entries = build_retrieval_prompt(items[0],
                                                 build_knowledge())
        self.assertEqual(entries, [])
        self.assertEqual(
            prompt, PROMPT_TEMPLATE.format(text=items[0]["text"]))

    def test_no_money_item_retrieves_receipt(self):
        # The encyclopedia matcher scores whole text, so a naive
        # whole-text lookup returns "receipt" (its meaning shares
        # "money" and "received" with money stories) on 41/60 money
        # items. Per-sentence routing — the same routing the NOVA
        # arm uses — must return nothing for every money item.
        items = [it for it in
                 load_items(ROOT / "data" / "eval_uplift.jsonl")
                 if it["category"] == "money"]
        knowledge = build_knowledge()
        retrieved = [it["id"] for it in items
                     if retrieve_knowledge(it, knowledge)]
        self.assertEqual(retrieved, [])

    def test_retrieval_never_reads_nova_request(self):
        # An item whose question text has no retrievable term but
        # whose nova_request names one must retrieve nothing: the
        # oracle input is not an answer key for this arm.
        item = {"text": "What is 12 * 15?",
                "nova_request": {"task": "dictionary",
                                 "term": "purchase"}}
        self.assertEqual(
            retrieve_knowledge(item, build_knowledge()), [])

    def test_run_arm_retrieval_records_entries(self):
        items = [it for it in
                 load_items(ROOT / "data" / "eval_uplift.jsonl")
                 if it["category"] == "dictionary"][:2]
        mock = MockModel()
        cfg = RunConfig(run_id="t-retr", set_name="eval",
                        arm="retrieval", mock=True, **mock.config())
        recs = run_arm_retrieval(items, mock, cfg)
        self.assertEqual(len(recs), 2)
        for rec in recs:
            self.assertEqual(rec["arm"], "retrieval")
            self.assertTrue(rec["trace"]["retrieved"])
            self.assertEqual(rec["trace"]["retrieved"][0]["kind"],
                             "dictionary")

    def test_three_way_summary_identical_arms(self):
        def _recs(flags):
            return [{"item_id": f"eval-{i:03d}", "correct": f,
                     "latency_ms": 1.0, "cost_usd": 0.0,
                     "run_config": {"model_id": "m", "checkpoint": "m",
                                    "temperature": 0, "max_tokens": 1},
                     "group": "deterministic", "category": "money"}
                    for i, f in enumerate(flags, start=1)]
        flags = [True, False, True, True, False]
        s = summarize_three_way(_recs(flags), _recs(flags),
                                _recs(flags))
        self.assertEqual(s["n"], 5)
        self.assertAlmostEqual(s["alone"]["accuracy"], 0.6)
        self.assertAlmostEqual(
            s["retrieval_minus_alone"]["diff"], 0.0)
        self.assertAlmostEqual(
            s["nova_minus_retrieval"]["diff"], 0.0)
        self.assertAlmostEqual(s["net_improvement"]["diff"], 0.0)
        self.assertEqual(s["classification_alone_vs_nova"],
                         {"wrong->correct": 0, "correct->wrong": 0,
                          "correct->correct": 3, "wrong->wrong": 2})

    def test_three_way_summary_detects_retrieval_gain(self):
        def _recs(flags):
            return [{"item_id": f"eval-{i:03d}", "correct": f,
                     "latency_ms": 1.0, "cost_usd": 0.0,
                     "run_config": {"model_id": "m", "checkpoint": "m",
                                    "temperature": 0, "max_tokens": 1},
                     "group": "deterministic", "category": "money"}
                    for i, f in enumerate(flags, start=1)]
        alone = [False] * 5
        retrieval = [True, True, False, False, False]
        nova = [True] * 5
        s = summarize_three_way(_recs(alone), _recs(retrieval),
                                _recs(nova))
        self.assertAlmostEqual(
            s["retrieval_minus_alone"]["diff"], 0.4)
        self.assertAlmostEqual(
            s["nova_minus_retrieval"]["diff"], 0.6)
        self.assertAlmostEqual(s["net_improvement"]["diff"], 1.0)


class TestFreshSet(unittest.TestCase):
    """The audit fresh set (seed 20261029): same coverage as the
    frozen set, independently generated, disjoint by item text."""

    def test_counts_and_coverage(self):
        items = load_items(ROOT / "data" / "eval_uplift_fresh.jsonl")
        self.assertEqual(len(items), 250)
        cats = {}
        for it in items:
            cats[it["category"]] = cats.get(it["category"], 0) + 1
        self.assertEqual(cats, EVAL_COUNTS)
        self.assertEqual({it["group"] for it in items},
                         {"deterministic", "unfamiliar_nl", "knowledge"})

    def test_disjoint_from_frozen_holdout_probes(self):
        fresh = load_items(ROOT / "data" / "eval_uplift_fresh.jsonl")
        frozen = load_items(ROOT / "data" / "eval_uplift.jsonl")
        holdout = load_items(
            ROOT / "data" / "eval_uplift_holdout.jsonl")
        check_overlap(fresh, ROOT / "data" / "money_probes.jsonl",
                      "money_probes.jsonl")
        frozen_texts = {it["text"] for it in frozen}
        holdout_texts = {it["text"] for it in holdout}
        self.assertFalse(any(it["text"] in frozen_texts
                             for it in fresh))
        self.assertFalse(any(it["text"] in holdout_texts
                             for it in fresh))

    def test_manifest_matches_file(self):
        import hashlib
        manifest = json.loads(
            (ROOT / "data" / "eval_fresh_manifest.json").read_text())
        self.assertEqual(manifest["seed"], 20261029)
        self.assertEqual(manifest["count"], 250)
        self.assertEqual(
            manifest["disjointness"]["overlaps_frozen"], 0)
        self.assertEqual(
            manifest["disjointness"]["overlaps_holdout"], 0)
        self.assertEqual(
            manifest["disjointness"]["overlaps_probes"], 0)
        digest = hashlib.sha256(
            (ROOT / "data" / "eval_uplift_fresh.jsonl")
            .read_bytes()).hexdigest()
        self.assertEqual(manifest["sha256"], digest)


class TestAnalyze(unittest.TestCase):
    def test_failure_clustering(self):
        records = [
            {"correct": False, "item_id": "eval-001",
             "group": "deterministic",
             "category": "calculator", "ground_truth": 42,
             "answer_kind": "number", "normalized_answer": None,
             "trace": {"frames_n": 0, "input_mode": "text"}},
            {"correct": True, "item_id": "eval-002",
             "group": "deterministic",
             "category": "money", "ground_truth": 10,
             "answer_kind": "number", "normalized_answer": 10,
             "trace": {"frames_n": 2, "input_mode": "text"}},
        ]
        result = ev_analyze.analyze_run(records)
        self.assertEqual(result["failures"], 1)
        self.assertEqual(result["clusters"][0]["failure_type"],
                         "unparseable")
        self.assertEqual(result["clusters"][0]["module"], "calculator")
        self.assertTrue(result["clusters"][0]["recommendation"])


if __name__ == "__main__":
    unittest.main()
