"""Money probes through the INTEGRATED system (not the old path).

Run:  python -m tests.test_integration_money   (from the repo root)
Exit 0 only if every probe answers exactly through the shared-frame
pipeline (text -> ConceptFrames -> supervisory reasoner -> words),
with status "verified" and complete=True.

Also prints timing: total and mean per-probe latency.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.semantic import answer_text


def main():
    probes = [json.loads(l) for l in
              open("data/money_probes.jsonl") if l.strip()]
    failures = []
    times = []
    for p in probes:
        text = p["story"] + " " + p["question"]
        t0 = time.perf_counter()
        try:
            result = answer_text(text)
            got = result["answer"]
        except Exception as e:  # noqa: BLE001 - report, don't crash the run
            failures.append((p, f"ERROR: {e}"))
            times.append(time.perf_counter() - t0)
            continue
        times.append(time.perf_counter() - t0)
        if got != p["expected"]:
            failures.append(
                (p, f"got {got}, expected {p['expected']} "
                    f"[status={result['status']}]"))
        elif result["status"] != "verified" or not result["complete"]:
            failures.append(
                (p, f"answer {got} but status={result['status']}, "
                    f"complete={result['complete']}"))
    total = sum(times)
    print(f"{len(probes) - len(failures)}/{len(probes)} correct "
          f"(integrated pipeline)")
    print(f"latency: total {total * 1000:.1f} ms, "
          f"mean {total / len(times) * 1000:.2f} ms/probe, "
          f"max {max(times) * 1000:.2f} ms")
    for p, why in failures:
        print(f"  FAIL #{p['id']} [{p['type']}]: {p['story']} "
              f"{p['question']} -> {why}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
