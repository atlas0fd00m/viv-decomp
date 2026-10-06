"""Tests for quality/metrics.py — DecompQuality, analyze_output, QualityGate."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from dec_engine.dec_impl.quality.metrics import DecompQuality, analyze_output, QualityGate


def _structured_output():
    return (
        "int\n"
        "main(\n)\n{\n"
        "  // allocate stack frame\n"
        "  while (i < 10) {\n"
        "    i = (i + 1);\n"
        "  }\n"
        "  foo(1);\n"
        "}\n"
    )


def _goto_heavy_output():
    return (
        "int\n"
        "func(\n)\n{\n"
        "  goto L_1000;\n"
        "  sub_4001ab(0);\n"
        "}\n"
    )


class TestAnalyzeOutput:
    def test_structured_gets_high_readability(self):
        q = analyze_output(_structured_output())
        assert q.readability >= 0.7
        assert q.structured_constructs >= 1  # while

    def test_goto_heavy_gets_penalty(self):
        q = analyze_output(_goto_heavy_output())
        # goto + unresolved sub_ call lower readability vs structured output
        q_struct = analyze_output(_structured_output())
        assert q.readability < q_struct.readability
        assert q.goto_count >= 1
        assert q.unresolved_conds >= 0  # no eflags placeholders here; goto is the penalty

    def test_symbol_resolution_resolved(self):
        q = analyze_output(_structured_output())
        # foo(1) resolves; no sub_ calls
        assert q.symbol_resolution > 0.5

    def test_symbol_resolution_unresolved(self):
        q = analyze_output(_goto_heavy_output())
        # sub_4001ab is unresolved -> lower resolution
        assert q.symbol_resolution < 0.5

    def test_empty_output(self):
        q = analyze_output("")
        assert q.readability == 0.0
        assert q.lines == 0

    def test_comment_lines_ignored(self):
        q = analyze_output("// just a comment\nint\nmain()\n{\n}\n")
        # comment ignored; body lines counted
        assert q.lines >= 1

    def test_depth_tracking(self):
        text = "a\n{ b\n{ c\n{ d\n{ e\n}}}"
        q = analyze_output(text)
        assert q.max_depth >= 4


class TestQualityGate:
    def test_default_pass_structured(self):
        q = analyze_output(_structured_output())
        gate = QualityGate()
        assert gate.passes(q)

    def test_default_fail_goto_heavy(self):
        q = analyze_output(_goto_heavy_output())
        gate = QualityGate()
        assert not gate.passes(q)

    def test_failure_list(self):
        q = analyze_output(_goto_heavy_output())
        gate = QualityGate()
        failures = gate.check(q)
        assert "readability" in failures or "symbol_resolution" in failures

    def test_strict_gate_fails_bad_output(self):
        q = analyze_output(_goto_heavy_output())
        gate = QualityGate(readability=0.99, symbol_resolution=0.99, type_accuracy=0.99)
        assert not gate.passes(q)

    def test_perfect_sample_meets_max_threshold(self):
        # Structured sample with resolved calls scores ~1.0 across all metrics
        q = analyze_output(_structured_output())
        gate = QualityGate(readability=1.0, symbol_resolution=1.0, type_accuracy=1.0)
        assert gate.passes(q)

    def test_custom_threshold_pass(self):
        q = analyze_output("int\nf()\n{\n}\n")
        gate = QualityGate(readability=0.0, symbol_resolution=0.0, type_accuracy=0.0)
        assert gate.passes(q)


class TestDecompQuality:
    def test_defaults(self):
        d = DecompQuality()
        assert d.readability == 0.0
        assert d.goto_count == 0
        assert d.type_accuracy == 0.0
