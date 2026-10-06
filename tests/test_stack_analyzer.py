"""Tests for memory/stack.py — StackFrameAnalyzer & StackVariable."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from dec_engine.dec_impl.memory.stack import StackFrameAnalyzer, StackVariable
from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
from dec_engine.dec_impl.ir.effects import Assignment
from dec_engine.dec_impl.ir.expression import Var, Const, BinOp, MemRef, OpType, Size


def _mv(off, size=Size.SIZE_32):
    """Build Vivisect-style memref: [rbp + off]."""
    return MemRef(base=Var("rbp", Size.SIZE_64), offset=Const(off, Size.SIZE_64), size=size)


def _build_graph(instructions_fn):
    entry = BasicBlock(addr=0x1000, is_entry=True)
    entry.instructions = instructions_fn(entry)
    return BlockGraph(entry_block=entry, blocks={0x1000: entry})


class TestFrameOffset:
    def test_constant_offset_style(self):
        assert StackFrameAnalyzer  # import sanity
        m = _mv(-0x10)
        from dec_engine.dec_impl.memory.stack import _frame_offset
        hit = _frame_offset(m)
        assert hit is not None
        assert hit[0] == "rbp"
        assert hit[1] == -0x10

    def test_positive_offset(self):
        from dec_engine.dec_impl.memory.stack import _frame_offset
        m = _mv(0x8)
        hit = _frame_offset(m)
        assert hit is not None
        assert hit[1] == 0x8

    def test_non_frame_base_returns_none(self):
        from dec_engine.dec_impl.memory.stack import _frame_offset
        m = MemRef(base=Var("rax", Size.SIZE_64), offset=Const(0x10), size=Size.SIZE_32)
        assert _frame_offset(m) is None


class TestStackFrameAnalyzer:
    def test_analyze_empty_graph(self):
        ta = StackFrameAnalyzer()
        g = type("Graph", (), {"blocks": {}, "entry_block": None})()
        result = ta.analyze(g)
        assert result == []

    def test_prologue_detects_frame_size(self):
        def mk(entry):
            src = BinOp(OpType.SUB, Var("rsp", Size.SIZE_64), Const(0x20))
            return [Assignment(destination=Var("rsp", Size.SIZE_64), source=src)]
        g = _build_graph(mk)
        ta = StackFrameAnalyzer()
        ta.analyze(g)
        assert ta.frame_size == 0x20

    def test_variable_bucketing_from_memref(self):
        def mk(entry):
            a = Assignment(destination=Var("x", Size.SIZE_32), source=_mv(-0x10))
            return [a]
        g = _build_graph(mk)
        ta = StackFrameAnalyzer()
        vars_ = ta.analyze(g)
        assert any(v.name == "var_10" for v in vars_)
        assert any(v.size == 4 for v in vars_)

    def test_multiple_offsets_bucketed_distinct(self):
        def mk(entry):
            return [
                Assignment(destination=Var("a"), source=_mv(-0x10)),
                Assignment(destination=Var("b"), source=_mv(-0x20)),
            ]
        g = _build_graph(mk)
        ta = StackFrameAnalyzer()
        vars_ = ta.analyze(g)
        names = {v.name for v in vars_}
        assert "var_10" in names
        assert "var_20" in names

    def test_declare_lines(self):
        def mk(entry):
            return [Assignment(destination=Var("a"), source=_mv(-0x10))]
        g = _build_graph(mk)
        ta = StackFrameAnalyzer()
        ta.analyze(g)
        lines = ta.declare_lines(indent=4)
        assert len(lines) == 1
        assert lines[0].startswith("    ")
        assert "var_10" in lines[0]
