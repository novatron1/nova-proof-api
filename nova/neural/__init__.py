"""Neural fixtures: the trained FLAN-T5-small checkpoints as OPTIONAL
components (stabilization, item 6).

Two checkpoints, both FLAN-T5-small (``T5ForConditionalGeneration``,
d_model 512, 8 layers, vocab 32128, ~308 MB each):

* **learned reasoner** (push1) — ``runs/reasoner-fast/``. Input is a
  rule+fact JSON prompt ("Read the rule and the fact... Does the rule
  apply? Answer:"), output is "Yes" or "No". Recorded: 2000/2000 on
  the novel-word test (``test_novel.jsonl.gz``).
* **neural parser** (push2) — ``models/p2-augH/checkpoint-500/``.
  Input is a raw sentence, output is a JSON frame
  ``{kind, head, body, subject}``. Recorded limitation: checkpoint-500
  COLLAPSED on the held-out cell (0.2872) — it is a fixture for
  translation verification, not a trusted parser.

**Loading is blocked in this environment**: ``torch``,
``transformers``, and ``sentencepiece`` are not installed (system
python AND ``~/workspace/audio-tools-venv``), and no pip installs are
allowed. ``FlanT5Component.load()`` therefore raises
``NeuralUnavailable`` naming the missing module, and every other path
degrades gracefully — the deterministic path never touches these
files. Do NOT fake a connection: a fixture that cannot load reports
exactly why.

What IS verified here (no model needed): the **schema translation**
between the checkpoints' JSON frames and the shared ``ConceptFrame``.
``translate.py`` is pure stdlib and is verified against the recorded
data — the push1 prompt format parses on all 2000 recorded test rows,
the frame round-trip is lossless, and the deterministic
``rule_applies`` semantics reproduces the recorded gold answers
2000/2000.
"""

from __future__ import annotations

from .components import FlanT5Component, NeuralUnavailable
from .fixtures import (FIXTURES, availability, fixture_status,
                       locate_fixtures)
from .translate import (concept_to_push_frame, push_frame_to_concept,
                        push1_input_to_frames, push1_prompt,
                        push1_rule_applies)

__all__ = [
    "FIXTURES", "FlanT5Component", "NeuralUnavailable",
    "availability", "fixture_status", "locate_fixtures",
    "concept_to_push_frame", "push_frame_to_concept",
    "push1_input_to_frames", "push1_prompt", "push1_rule_applies",
]
