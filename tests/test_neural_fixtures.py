"""Neural-fixture tests: the trained checkpoints as OPTIONAL fixtures
(stabilization, item 6).

Loading is BLOCKED in this environment (no torch / transformers /
sentencepiece, and no pip installs allowed), so these tests verify
the honest degradation path — exact blockers, no faked connection —
plus the pure schema translation, verified against the recorded
data:

* push1 ``test_novel.jsonl.gz`` (2000 rows): the prompt format
  parses, the frame round-trip is lossless, and the deterministic
  ``push1_rule_applies`` semantics reproduces the recorded gold
  answers 2000/2000.
* push2 ``train_v4.jsonl.gz`` (sampled): gold frames round-trip
  losslessly through ConceptFrame.

Tests that need the recorded data skip cleanly (with a message) when
the workspace files are absent, so the suite stays green on a
machine without the ARC goal workspace — but the skip itself is
reported, never silent.
"""

from __future__ import annotations

import gzip
import json
import re
import unittest
from pathlib import Path

from nova.neural import (FlanT5Component, NeuralUnavailable,
                         concept_to_push_frame, fixture_status,
                         push1_input_to_frames, push1_prompt,
                         push1_rule_applies, push_frame_to_concept)
from nova.neural.components import component_status
from nova.semantic import answer_text

ARC_ROOT = Path.home() / "workspace" / "goals" / \
    "arc-prize-2026-paper-track-entry"
PUSH1_TEST = ARC_ROOT / "push1-learned-reasoner" / "data" / \
    "test_novel.jsonl.gz"
PUSH2_TRAIN = ARC_ROOT / "push2-template10-fix" / "data" / \
    "train_v4.jsonl.gz"


def _load_gz(path: Path, limit: int | None = None) -> list[dict]:
    rows = []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


class TestFixturePresence(unittest.TestCase):
    def test_both_checkpoints_present_with_configs(self):
        status = fixture_status()
        for name in ("learned_reasoner", "neural_parser"):
            f = status["fixtures"][name]
            self.assertTrue(f["present"], f"{name} files missing: "
                            f"{f['missing_files']}")
            self.assertEqual(f["architecture"],
                             ["T5ForConditionalGeneration"])
            self.assertEqual(f["model_type"], "t5")
            self.assertEqual(f["d_model"], 512)
            self.assertEqual(f["num_layers"], 8)
            self.assertEqual(f["weights_bytes"], 307867048)

    def test_not_loadable_and_blocker_is_exact(self):
        status = fixture_status()
        self.assertFalse(status["loadable"])
        self.assertIn("torch", status["blockers"][0])
        self.assertIn("transformers", status["blockers"][0])
        self.assertIn("sentencepiece", status["blockers"][0])

    def test_component_status_reports_directories(self):
        status = component_status()
        self.assertFalse(status["loadable"])
        for name in ("learned_reasoner", "neural_parser"):
            self.assertIn(name, status["components"])
            self.assertFalse(status["components"][name]["loaded"])


class TestFixtureDegradation(unittest.TestCase):
    def test_load_raises_neural_unavailable_naming_torch(self):
        for name in ("learned_reasoner", "neural_parser"):
            comp = FlanT5Component(name)
            self.assertFalse(comp.loaded)
            with self.assertRaises(NeuralUnavailable) as ctx:
                comp.load()
            self.assertIn("torch", str(ctx.exception))

    def test_generate_without_load_raises(self):
        comp = FlanT5Component("learned_reasoner")
        with self.assertRaises(NeuralUnavailable):
            comp.generate("Read the rule and the fact...")

    def test_unknown_fixture_name(self):
        with self.assertRaises(ValueError):
            FlanT5Component("no-such-fixture")

    def test_deterministic_path_unaffected(self):
        # The neural layer being unloadable must not touch the
        # deterministic path at all.
        r = answer_text("Marcus gave John $20. "
                        "How much money does John have?")
        self.assertEqual(r["answer"], 20)


class TestPush1Translation(unittest.TestCase):
    @unittest.skipUnless(PUSH1_TEST.exists(),
                         f"recorded data absent: {PUSH1_TEST}")
    def test_prompt_parses_and_round_trips_2000_rows(self):
        rows = _load_gz(PUSH1_TEST)
        self.assertEqual(len(rows), 2000)
        for row in rows:
            rule, fact = push1_input_to_frames(row["input"])
            # Frame -> dict -> frame is the identity on the recorded
            # JSON (lossless translation).
            rule_json = json.loads(re.search(
                r"Rule: (\{.*?\})\nFact:", row["input"], re.S).group(1))
            fact_json = json.loads(re.search(
                r"Fact: (\{.*?\})\nDoes", row["input"], re.S).group(1))
            self.assertEqual(concept_to_push_frame(rule), rule_json)
            self.assertEqual(concept_to_push_frame(fact), fact_json)
            # The prompt builder reproduces the recorded prompt.
            self.assertEqual(
                push1_prompt(concept_to_push_frame(rule),
                             concept_to_push_frame(fact)),
                row["input"])

    @unittest.skipUnless(PUSH1_TEST.exists(),
                         f"recorded data absent: {PUSH1_TEST}")
    def test_rule_applies_reproduces_gold_2000_of_2000(self):
        rows = _load_gz(PUSH1_TEST)
        agree = 0
        for row in rows:
            rule, fact = push1_input_to_frames(row["input"])
            verdict = push1_rule_applies(rule, fact)
            gold = "yes" if row["answer"] == "Yes" else "no"
            agree += (verdict == gold)
        self.assertEqual(agree, 2000)


class TestPush2Translation(unittest.TestCase):
    @unittest.skipUnless(PUSH2_TRAIN.exists(),
                         f"recorded data absent: {PUSH2_TRAIN}")
    def test_gold_frames_round_trip(self):
        rows = _load_gz(PUSH2_TRAIN, limit=500)
        # "unsupported" rows have no frame (head null) — they are
        # sentences the parser was trained to reject, not frames to
        # translate. Only fact/rule frames round-trip.
        frames = [r["frame"] for r in rows
                  if r["frame"].get("kind") in ("fact", "rule")]
        self.assertGreater(len(frames), 0)
        for frame in frames:
            back = concept_to_push_frame(
                push_frame_to_concept(frame))
            self.assertEqual(back, frame)


class TestPush1AnswerMapping(unittest.TestCase):
    def test_yes_no_unknown(self):
        from nova.neural.translate import push1_answer_to_verdict
        self.assertEqual(push1_answer_to_verdict("Yes"), "yes")
        self.assertEqual(push1_answer_to_verdict("No"), "no")
        self.assertEqual(push1_answer_to_verdict("Maybe"), "unknown")
        self.assertEqual(push1_answer_to_verdict(""), "unknown")


if __name__ == "__main__":
    unittest.main()
