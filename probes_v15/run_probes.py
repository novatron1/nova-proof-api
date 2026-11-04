"""Fresh v1.5 probe runner (deterministic, model=None, $0).

Runs the FRESH probe sets written for the v1.5 advancement
(negation, refund-phrasing, giver-scope) through the production
path and compares each answer with the hand-derived ground truth
stored in the file. The sets were written AFTER the fixes, from
the failure CLASSES of the spent v1.4 live set — none of their
items is a spent live item. `spent_diagnostics.json` holds the
three spent live items (v14-020/022/025); it is reported
separately and never counted in the fresh totals.

Usage:
  python3 probes_v15/run_probes.py [--root <repo>] [--label <name>]

--root points the runner at another repo copy (e.g. the v1.4 copy)
so the same fresh probes measure the BEFORE behaviour. The default
root is this probe directory's own repo.

Exit code 0 iff every fresh probe matches its expected answer.
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
    total_pass = total = 0
    for name in ("negation_probes.json",
                 "refund_phrasing_probes.json",
                 "giver_scope_probes.json"):
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
        total_pass += passed
        total += len(items)
    print(f"FRESH TOTAL: {total_pass}/{total}")

    diag = json.loads((HERE / "spent_diagnostics.json").read_text())
    dpass = 0
    for item in diag:
        r = answer_production(item["question"], model=None)
        actual = r.get("answer")
        ok = _matches(item["expected_answer"], actual,
                      item.get("tolerance"))
        dpass += ok
        print(f"{'PASS' if ok else 'FAIL'}  {item['id']} (SPENT "
              f"diagnostic)  expected={item['expected_answer']}  "
              f"actual={actual}  status={r.get('status')}")
    print(f"SPENT DIAGNOSTICS (not counted): {dpass}/{len(diag)}")
    return 0 if total_pass == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
