"""Fresh v1.4 probe runner (deterministic, model=None, $0).

Runs the two FRESH probe sets written for the v1.4 advancement
(probes_v14/refund_probes.json, probes_v14/duplicate_probes.json)
through the production path and compares each answer with the
hand-derived ground truth stored in the file. These sets were
written AFTER the fixes, from the failure CLASSES of the spent
live-40 set — none of their items is a live-40 item, and the
live-40 set itself is not re-scored here (it is spent as a
benchmark for these fixes).

Usage: python3 probes_v14/run_probes.py
Exit code 0 iff every probe matches its expected answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.semantic.production import answer_production  # noqa: E402

HERE = Path(__file__).resolve().parent


def _matches(expected, actual, tolerance) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected
    if actual is None or isinstance(actual, str):
        return False
    return abs(float(actual) - float(expected)) <= (tolerance or 0)


def run_file(name: str) -> tuple[int, int]:
    items = json.loads((HERE / name).read_text())
    passed = 0
    for item in items:
        r = answer_production(item["question"], model=None)
        actual = r.get("answer")
        ok = _matches(item["expected_answer"], actual,
                      item.get("tolerance"))
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {item['id']}  "
              f"expected={item['expected_answer']}  "
              f"actual={actual}  status={r.get('status')}")
    print(f"-- {name}: {passed}/{len(items)}")
    return passed, len(items)


def main() -> int:
    total_pass = total = 0
    for name in ("refund_probes.json", "duplicate_probes.json"):
        p, n = run_file(name)
        total_pass += p
        total += n
    print(f"TOTAL: {total_pass}/{total}")
    return 0 if total_pass == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
