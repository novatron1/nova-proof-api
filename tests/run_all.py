"""Run every suite and print one summary table with timings.

Run:  python3 tests/run_all.py   (from the repo root)

Suites:
  1. money probes, old path            (tests/test_money.py)
  2. money probes, integrated pipeline (tests/test_integration_money.py)
  3. semantic suites                    (tests/test_semantic.py)
  4. vendored adapter                   (tests/test_adapter_vendored.py)
  5. regression (old path + live API)   (tests/test_regression.py)
  6. original v0.3 suite, original dir (read-only source artifact)
  7. round-trip concept preservation (tests/test_roundtrip.py)
  8. stabilization (routing, zero-audit, antonyms, rules, model
     interface)                  (tests/test_stabilization.py)
  9. neural fixtures (checkpoints present but unloadable; schema
     translation verified)       (tests/test_neural_fixtures.py)
 10. multi-interpretation (Req 4) + confidence (Req 5)
     (tests/test_interpret.py, tests/test_confidence.py)

Exit 0 only if every suite passes. Numbers printed here are the numbers
recorded in RESULTS_INTEGRATION.md — no other source.
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V03 = Path.home() / "workspace" / "nova-cognitive-adapter-v03" / \
    "nova_cognitive_adapter"

SUITES = [
    ("money probes — old path (parser+ledger)",
     [sys.executable, "-m", "tests.test_money"], ROOT),
    ("money probes — integrated pipeline",
     [sys.executable, "-m", "tests.test_integration_money"], ROOT),
    ("semantic suites (synonyms/antonyms/negation/multi-step/5W1H)",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests",
      "-p", "test_semantic.py"], ROOT),
    ("vendored adapter v0.3 (in-repo copy)",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests",
      "-p", "test_adapter_vendored.py"], ROOT),
    ("regression (old path + live API)",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests",
      "-p", "test_regression.py"], ROOT),
    ("original adapter v0.3 suite (source artifact, read-only)",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
     V03),
    ("eval harness mechanics (normalization, guards, ablation, mock)",
     [sys.executable, "-m", "tests.test_eval_harness"], ROOT),
    ("round-trip concept preservation (NL -> frames -> NL)",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests",
      "-p", "test_roundtrip.py"], ROOT),
    ("stabilization (routing, zero-audit, antonyms, rules, models)",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests",
      "-p", "test_stabilization.py"], ROOT),
    ("neural fixtures (checkpoints + schema translation)",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests",
      "-p", "test_neural_fixtures.py"], ROOT),
    ("multi-interpretation (Req 4) + confidence (Req 5)",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests",
      "-p", "test_interpret.py"], ROOT),
    ("calibrated confidence (Req 5)",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests",
      "-p", "test_confidence.py"], ROOT),
    ("model-agnostic interface (Req 6: registry, generic transport, "
     "/concept model selection)",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests",
      "-p", "test_model_backends.py"], ROOT),
]


def main():
    print("NOVA integration — full test run")
    print("=" * 70)
    overall_ok = True
    results = []
    for name, cmd, cwd in SUITES:
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=120)
        dt = time.perf_counter() - t0
        ok = proc.returncode == 0
        overall_ok = overall_ok and ok
        # Last meaningful summary line of the suite's output.
        tail = [l for l in (proc.stdout + proc.stderr).splitlines()
                if l.strip()]
        summary = tail[-1] if tail else "(no output)"
        if "OK" in summary or "correct" in summary:
            detail = [l for l in tail if "correct" in l or l.startswith("OK")
                      or l.startswith("Ran ") or "FAILED" in l]
            summary = " | ".join(detail) if detail else summary
        results.append((name, ok, dt, summary))
        print(f"[{'PASS' if ok else 'FAIL'}] {name} ({dt:.2f}s)")
        for line in (proc.stdout + proc.stderr).splitlines():
            if "FAIL" in line or "Error" in line or "correct" in line:
                print(f"         {line}")
        if not ok:
            print("---- stdout ----")
            print(proc.stdout[-2000:])
            print("---- stderr ----")
            print(proc.stderr[-2000:])
    print("=" * 70)
    for name, ok, dt, summary in results:
        print(f"{'PASS' if ok else 'FAIL'}  {dt:6.2f}s  {name}")
        print(f"         {summary}")
    print("=" * 70)
    print("OVERALL:", "PASS" if overall_ok else "FAIL")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
