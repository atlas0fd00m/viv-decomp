"""Tests for memory/callgraph.py — CallGraph & CallGraphBuilder."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from dec_engine.dec_impl.memory.callgraph import CallGraph, CallGraphBuilder, summarize_calls
from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
from dec_engine.dec_impl.ir.effects import Call, Assignment
from dec_engine.dec_impl.ir.expression import Var, Const


def _graph_with_call(funcva, callee_addr):
    entry = BasicBlock(addr=funcva, is_entry=True)
    call = Call(callee=Const(callee_addr), args=[])
    entry.instructions = [call]
    return BlockGraph(entry_block=entry, blocks={funcva: entry})


class TestCallGraph:
    def test_empty(self):
        cg = CallGraph()
        assert len(cg) == 0

    def test_edge_add(self):
        cg = CallGraph()
        cg.edge(0x1000, 0x2000, "foo")
        assert cg.edges_from(0x1000) == {(0x2000, "foo")}
        assert cg.edges_to(0x2000) == {0x1000}

    def test_len_counts_edges(self):
        cg = CallGraph()
        cg.edge(0x1000, 0x2000, "foo")
        cg.edge(0x1000, 0x3000, "bar")
        assert len(cg) == 2


class TestCallGraphBuilder:
    def test_build_direct_call(self):
        b = CallGraphBuilder()
        graph = _graph_with_call(0x1000, 0x5000)
        cg = b.build({0x1000: graph})
        # Without vw, addr is recorded; name is empty string
        assert cg.edges_from(0x1000) == {(0x5000, "")}

    def test_build_multiple(self):
        b = CallGraphBuilder()
        g1 = _graph_with_call(0x1000, 0x5000)
        g2 = _graph_with_call(0x2000, 0x6000)
        cg = b.build({0x1000: g1, 0x2000: g2})
        assert len(cg) == 2

    def test_build_skips_indirect(self):
        b = CallGraphBuilder()
        entry = BasicBlock(addr=0x1000, is_entry=True)
        entry.instructions = [Call(callee=Var("rax"), args=[])]
        graph = BlockGraph(entry_block=entry, blocks={0x1000: entry})
        cg = b.build({0x1000: graph})
        assert cg.edges_from(0x1000) == set()  # indirect not recorded as addr

    def test_build_no_calls(self):
        b = CallGraphBuilder()
        entry = BasicBlock(addr=0x1000, is_entry=True)
        entry.instructions = [Assignment(destination=Var("x"), source=Const(1))]
        graph = BlockGraph(entry_block=entry, blocks={0x1000: entry})
        cg = b.build({0x1000: graph})
        assert len(cg) == 0

    def test_summarize(self):
        b = CallGraphBuilder()
        cg = b.build({0x1000: _graph_with_call(0x1000, 0x5000)})
        s = summarize_calls(cg)
        assert "0x1000 -> 0x5000" in s
