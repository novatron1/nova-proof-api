"""Fresh v1.6 probe runner (deterministic, model=None, $0).

Runs the FRESH probe set written for the v1.6 advancement
(refund-before-transfer reordering) through the production path and
compares each answer with the hand-derived ground truth stored in
the file. The set was written BEFORE the fix, from the documented
v1.5 skip (ADVANCE_V15.md, 'Stretch — refund ordering'): a refund
stated before its justifying transfer. None of its items is a spent
live item; names/amounts are new.

Usage:
  python3 probes_v16/run_probes.py [--root <repo>] [--label <name>]

--root points the runner at another repo copy (e.g. the v1.5 main
repo) so the same fresh probes measure the BEFORE behaviour. The
default root is this probe directory's own repo.

Exit code 0 iff every probe matches its expected answer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _matches(expected, actual, tolerance) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected
    if actual is None or isinstance(actual, str):
        return False
    return abs(float(actual) - float(expected)) <= (tolerance or 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HERE.parent))
    ap.add_argument("--label", default=None)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))
    # The package must come from --root, not from this script's repo.
    for mod in [m for m in list(sys.modules) if m == "nova"
                or m.startswith("nova.")]:
        del sys.modules[mod]
    from nova.semantic.production import answer_production

    print(f"== probes under root: {root}"
          f"{' (' + args.label + ')' if args.label else ''}")
    items = json.loads((HERE / "refund_reorder_probes.json").read_text())
    passed = 0
    for item in items:
        r = answer_production(item["question"], model=None)
        actual = r.get("answer")
        ok = _matches(item["expected_answer"], actual,
                      item.get("tolerance"))
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {item['id']}  "
              f"expected={item['expected_answer']}  "
              f"actual={actual}  status={r.get('status')}  "
              f"[{item['class']}]")
    print(f"REFUND-REORDER TOTAL: {passed}/{len(items)}")
    return 0 if passed == len(items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
