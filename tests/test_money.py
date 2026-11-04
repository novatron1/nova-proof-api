"""End-to-end test: money-transfer probes through parser + ledger.

Run:  python -m tests.test_money   (from the repo root)
Exit 0 only if every probe answers exactly, with a proof.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.concept import parse_story, run_story


def main():
    probes = [json.loads(l) for l in
              open("data/money_probes.jsonl") if l.strip()]
    failures = []
    for p in probes:
        text = p["story"] + " " + p["question"]
        try:
            events, query = parse_story(text)
            result = run_story(events, query)
            got = result["answer"]
        except Exception as e:  # noqa: BLE001 - report, don't crash the run
            failures.append((p, f"ERROR: {e}"))
            continue
        if got != p["expected"]:
            failures.append((p, f"got {got}, expected {p['expected']}"))
    print(f"{len(probes) - len(failures)}/{len(probes)} correct")
    for p, why in failures:
        print(f"  FAIL #{p['id']} [{p['type']}]: {p['story']} {p['question']} -> {why}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
