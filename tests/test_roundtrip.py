"""Round-trip concept preservation tests (item 5 of the stabilization).

NL -> frames -> NL -> frames must preserve meaning. These tests detect
semantic information loss: dropped slots, flipped polarity, invented
values, lost negation. Run:

    python -m unittest discover -s tests -p "test_roundtrip.py" -v

The metric is printed by test_preservation_rate and recorded in
EVAL_RESULTS.md (before/after the render fixes).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.semantic.roundtrip import roundtrip_loss

# Sentences covering every frame shape the system produces. None of
# these are in the frozen eval set; they are stabilization probes.
SENTENCES = [
    # money transfers, full 5W1H
    "Marcus gave John $20.",
    "John gave Sarah $10.",
    "Marcus gave his sister $50 yesterday at the store because she needed groceries.",
    "Omar paid Felix $45.",
    "Lena sent Rosa $12 by wire.",
    # purchase (quantity + object, non-money units)
    "Nina bought 3 bicycles.",
    "Yusuf purchased a bicycle for $120.",
    # negated events: polarity must survive
    "John did not give Sarah $10.",
    "Noor never paid Owen.",
    "Felix did not buy a bike.",
    # adjective states
    "The light is on.",
    "The store is open.",
    "The soup is hot.",
    "The glass is full.",
    "The light is not on.",
    # has-a / is-a facts
    "A spider has eight legs.",
    "A bicycle has two wheels.",
    "An octopus has eight arms.",
    "Jupiter is the largest planet.",
    "Mars is known as the Red Planet.",
    # modal / negation of ability
    "A penguin cannot fly.",
    # multi-slot event with method
    "Rosa visited the market yesterday.",
    "Hassan carried the box by hand.",
    # give/take and receive
    "Amir sent Omar $90.",
    "Ivy received $70 from Kofi.",
]


class TestRoundTrip(unittest.TestCase):
    def test_no_polarity_flips(self):
        result = roundtrip_loss(SENTENCES)
        self.assertEqual(result["polarity_flips"], 0,
                         f"polarity flips: {result['records']}")

    def test_no_negation_lost(self):
        result = roundtrip_loss(SENTENCES)
        self.assertEqual(result["negation_lost"], 0,
                         f"negation lost: {result['records']}")

    def test_no_frames_lost(self):
        result = roundtrip_loss(SENTENCES)
        self.assertEqual(result["frames_lost"], 0,
                         f"frames lost: {result['records']}")

    def test_preservation_rate(self):
        result = roundtrip_loss(SENTENCES)
        print(f"\nround-trip: {result['preserved_slots']}/"
              f"{result['known_slots']} slots preserved "
              f"({result['preservation_rate']:.3f}); "
              f"lost={result['lost_slots']}, "
              f"invented={result['invented_slots']}")
        self.assertGreaterEqual(result["preservation_rate"], 0.90,
                                f"lost slots: {result['lost_slots']}")


if __name__ == "__main__":
    unittest.main()
