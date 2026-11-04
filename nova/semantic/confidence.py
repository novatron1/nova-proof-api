"""Calibrated confidence (Req 5, confidence half).

A confidence score derived from auditable inputs — never a model
logit, never a guess. Four components, with fixed weights stated in
code:

* **parse certainty** (0.35) — share of frames parsed deterministically
  (certainty ``known``). A heuristic parse is worth less than a
  deterministic one, even when the arithmetic that follows is exact.
* **interpretation agreement** (0.35) — the share of simplified
  readings that reached the same (verdict, answer) (Req 4). Readings
  that disagree lower the score.
* **proof completeness** (0.20) — 1.0 for a complete proof with
  nothing missing and nothing unusable, 0.5 for a complete proof with
  caveats, 0.0 when the derivation did not complete.
* **model-advisor agreement** (0.10) — 1.0 when the model's direct
  answer matches the adjudicated answer, 0.0 when it contradicts it,
  neutral (0.5) when there is no advisor answer to compare.

**No-proof cap.** When no derivation completed (proof completeness
0.0), the score is capped at 0.5 no matter how clean the parse or
how unanimous the readings: without a proof there is no proven
answer to be confident in, and a single reading agreeing with
itself is vacuous agreement. 0.5 is the "no evidence either way"
ceiling. This is a structural rule, not a fitted weight.

**Certification bar.** ``CERTIFICATION_BAR = 0.85``. An answer is
``certified`` only when its confidence meets the bar AND its proof is
complete (proof completeness 1.0). Certification therefore means
"complete proof + high confidence", not "the model sounded sure".
The bar is a stated decision, recorded here and in the tests — it is
not tuned to any run after the fact.
"""

from __future__ import annotations

import re

CERTIFICATION_BAR = 0.85

WEIGHTS = {"parse": 0.35, "agreement": 0.35, "proof": 0.20,
           "model": 0.10}

# Confidence buckets for calibration reporting: (low, high, label).
BUCKETS = [(0.9, 1.01, "0.90-1.00"), (0.7, 0.9, "0.70-0.90"),
           (0.5, 0.7, "0.50-0.70"), (0.0, 0.5, "0.00-0.50")]

_UNKNOWN_PHRASES = (
    "don't know", "do not know", "unknown", "cannot be determined",
    "can't be determined", "can't tell", "cannot tell", "not enough",
    "insufficient", "unclear", "no way to know",
)

_NUMBER_RE = re.compile(r"\$?\s*(-?[\d,]+\.?[\d]*)")


def parse_certainty(frames) -> float:
    """Share of frames parsed deterministically (certainty known)."""
    frames = list(frames)
    if not frames:
        return 0.0
    known = sum(1 for f in frames if f.certainty == "known")
    return known / len(frames)


def proof_completeness(result: dict) -> float:
    """1.0 / 0.5 / 0.0 ladder over a reasoner result dict.

    1.0: complete, nothing missing, nothing unusable. 0.5: complete
    but with missing or unusable caveats. 0.0: not complete.
    """
    if not result.get("complete"):
        return 0.0
    if result.get("missing") or result.get("unusable_frames"):
        return 0.5
    return 1.0


def _advisor_number(text: str) -> float | None:
    m = re.search(r"\$\s*(-?[\d,]+\.?[\d]*)", text)
    if not m:
        m = _NUMBER_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def model_agreement_factor(advisor_text, answer, verdict
                           ) -> float | None:
    """Compare the model's direct answer with the adjudicated answer.

    1.0 agree, 0.0 contradict, None when the comparison cannot be
    made (no advisor text, advisor abstained, unparseable advisor
    text, or a definition answer). An advisor abstention is NOT a
    disagreement — it is an absence of opinion.
    """
    if advisor_text is None:
        return None
    text = str(advisor_text).strip().lower()
    if not text:
        return None
    if any(p in text for p in _UNKNOWN_PHRASES):
        return None  # advisor abstained: no opinion either way
    if verdict == "unknown":
        # The system abstained. The advisor agreeing means it also
        # has no answer — but an abstention was already handled above,
        # so a definite advisor answer here contradicts the abstention.
        return 0.0
    if isinstance(answer, (int, float)):
        n = _advisor_number(text)
        if n is None:
            return None
        return 1.0 if n == float(answer) else 0.0
    if verdict in ("yes", "no"):
        first = text.split(".")[0].strip()
        if first.startswith("yes"):
            return 1.0 if verdict == "yes" else 0.0
        if first.startswith("no"):
            return 1.0 if verdict == "no" else 0.0
        return None
    # Definition answers (dict) and "both" verdicts: no reliable
    # text comparison exists; report None rather than guessing.
    return None


def score(parse_certainty: float, agreement_rate: float,
          proof_completeness: float, model_agreement: float | None = None
          ) -> dict:
    """Combine the four components into a confidence score.

    ``model_agreement`` None means "no advisor answer to compare"
    and contributes neutrally (0.5). Returns the score, its
    components, the certification bar, and whether the answer is
    certified (confidence >= bar AND proof completeness 1.0).
    """
    model_factor = 0.5 if model_agreement is None else model_agreement
    confidence = (WEIGHTS["parse"] * parse_certainty
                  + WEIGHTS["agreement"] * agreement_rate
                  + WEIGHTS["proof"] * proof_completeness
                  + WEIGHTS["model"] * model_factor)
    if proof_completeness == 0.0:
        # No derivation completed: cap at 0.5 (see module docstring).
        confidence = min(confidence, 0.5)
    confidence = round(max(0.0, min(1.0, confidence)), 3)
    certified = (confidence >= CERTIFICATION_BAR
                 and proof_completeness == 1.0)
    reason = ("complete proof and confidence "
              f"{confidence:.3f} >= bar {CERTIFICATION_BAR}"
              if certified else
              ("proof incomplete" if proof_completeness != 1.0
               else f"confidence {confidence:.3f} < bar "
                    f"{CERTIFICATION_BAR}"))
    return {
        "confidence": confidence,
        "components": {
            "parse_certainty": round(parse_certainty, 3),
            "agreement_rate": round(agreement_rate, 3),
            "proof_completeness": round(proof_completeness, 3),
            "model_agreement": model_agreement,
        },
        "certified": certified,
        "certification_bar": CERTIFICATION_BAR,
        "certification_reason": reason,
    }


def calibration_buckets(records: list[dict]) -> list[dict]:
    """Bucket (confidence, correct) pairs and report accuracy per
    bucket. ``records`` are dicts with ``confidence`` (float) and
    ``correct`` (bool). Empty buckets are reported with n=0 and
    accuracy None — never hidden, never filled in."""
    out = []
    for low, high, label in BUCKETS:
        bucket = [r for r in records
                  if low <= r["confidence"] < high]
        n = len(bucket)
        correct = sum(1 for r in bucket if r["correct"])
        mean_conf = (sum(r["confidence"] for r in bucket) / n
                     if n else None)
        out.append({
            "bucket": label, "n": n, "correct": correct,
            "accuracy": (correct / n if n else None),
            "mean_confidence": (round(mean_conf, 3)
                                if mean_conf is not None else None),
        })
    return out
