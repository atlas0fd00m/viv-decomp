#!/usr/bin/env python3
"""CI-usable benchmark runner.

Usage:
    python tests/benchmarks/run_benchmark.py [--strict]

Runs the decompiler quality benchmark corpus and enforces the quality gate.
Exit code 0 = all cases pass; 1 = one or more regressions (CI can gate on this).
"""
import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", ".."))
sys.path.insert(0, _ROOT)

from dec_engine.dec_impl.quality.benchmark import run_benchmark, summarize
from dec_engine.dec_impl.quality.metrics import QualityGate


def main(argv=None):
    argv = argv or sys.argv[1:]
    strict = "-strict" in argv or "--strict" in argv
    gate = QualityGate(
        readability=0.8 if strict else 0.5,
        symbol_resolution=0.8 if strict else 0.5,
        type_accuracy=0.3 if strict else 0.3,
    )
    results = run_benchmark(gate)
    print(summarize(results))
    passed = all(r.passed for r in results)
    # Print failures for CI log readability
    for r in results:
        if not r.passed:
            print(f"FAIL: {r.name} -> {','.join(r.failures)}", file=sys.stderr)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
