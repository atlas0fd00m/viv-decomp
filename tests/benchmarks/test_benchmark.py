"""Regression tests for the benchmark suite (S7 quality gate).

Runs the full corpus through the pipeline and enforces that each case
meets the default quality gate. This doubles as the CI regression detector.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import pytest
from dec_engine.dec_impl.quality.benchmark import CORPUS, run_benchmark, summarize, BenchmarkResult
from dec_engine.dec_impl.quality.metrics import QualityGate


class TestBenchmarkRunner:
    def test_corpus_has_expected_cases(self):
        assert "loop" in CORPUS
        assert "if_else" in CORPUS
        assert "call" in CORPUS

    def test_run_benchmark_returns_all_cases(self):
        results = run_benchmark()
        assert len(results) == len(CORPUS)

    def test_all_cases_pass_default_gate(self):
        results = run_benchmark()
        failures = [r.name for r in results if not r.passed]
        assert failures == [], f"benchmark regressions: {failures}"

    def test_loop_case_structured(self):
        results = run_benchmark()
        loop = next(r for r in results if r.name == "loop")
        # loop reconstruction should yield a while construct (low goto count)
        assert loop.quality.goto_count == 0
        assert loop.quality.structured_constructs >= 1

    def test_quality_score_fields_populated(self):
        results = run_benchmark()
        for r in results:
            assert 0.0 <= r.quality.readability <= 1.0
            assert 0.0 <= r.quality.symbol_resolution <= 1.0
            assert r.output != ""

    def test_gate_detects_regression(self):
        # Feed a deliberately bad output: goto + unresolved call
        from dec_engine.dec_impl.quality.metrics import analyze_output
        bad = "int f() {\n  goto L_1000;\n  sub_4001ab(0);\n}\n"
        q = analyze_output(bad)
        strict = QualityGate(readability=0.9, symbol_resolution=0.9)
        assert not strict.passes(q)  # gate flags the regression
        failures = strict.check(q)
        assert "symbol_resolution" in failures

    def test_summarize_contains_all_names(self):
        results = run_benchmark()
        s = summarize(results)
        for r in results:
            assert r.name in s

    def test_quality_accuracy_bounds(self):
        results = run_benchmark()
        for r in results:
            assert r.quality.readability <= 1.0
            assert r.quality.symbol_resolution >= 0.0
