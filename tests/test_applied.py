"""Tests for the SymbolikEmulator applied-effects pass (S8)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from dec_engine.dec_impl.ml.applied import (
    SymbolikEmulatorPass, AppliedEffectEvidence, VarApplied,
)


class _FakeEmu:
    """Mimics vivisect SymbolikEmulator.getSymVariables()."""

    def __init__(self, vars_):
        self._vars = vars_  # list of (name, symval)

    def getSymVariables(self):
        return list(self._vars)


class _FakeCtx:
    """Mimics SymbolikAnalysisContext.getSymbolikPaths(fva)."""

    def __init__(self, paths):
        self._paths = paths  # list of list-of-(name,symval)

    def getSymbolikPaths(self, fva):
        for pathvars in self._paths:
            yield _FakeEmu(pathvars), []


class _FakeVW:
    def __init__(self, arch="amd64"):
        self.meta = {"Architecture": arch}

    def getMeta(self, k):
        return self.meta.get(k)


class TestAppliedEffectEvidence:
    def test_empty(self):
        ev = AppliedEffectEvidence()
        assert ev.has_evidence is False
        assert ev.concrete_count == 0
        assert ev.path_count == 0

    def test_merge_across_paths(self):
        ev = AppliedEffectEvidence()
        # path 1 sets rax = 0x10, rbp
        v1 = VarApplied(symval=0x10, paths=1)
        v2 = VarApplied(symval=None, paths=0)
        ev.vars["rax"] = v1
        ev.vars["rbp"] = v2
        # simulate a second path hitting rax again
        ev.vars["rax"].paths += 1
        assert ev.vars["rax"].paths == 2
        assert ev.vars["rax"].symval == 0x10


class TestSymbolikEmulatorPassCollect:
    def _pass(self, paths, arch="amd64"):
        vw = _FakeVW(arch)
        p = SymbolikEmulatorPass(vw)
        # substitute the fake context so no real vivisect instantiation happens
        fake_ctx = _FakeCtx(paths)
        p._symbolik_context = lambda: fake_ctx
        return p

    def test_no_workspace_raises(self):
        p = SymbolikEmulatorPass()
        with pytest.raises(RuntimeError):
            p.collect(0x1000)

    def test_collect_merges_vars(self):
        p = self._pass([
            [("rax", 0x10), ("rdi", 0x400)] ,  # path 1
            [("rax", 0), ("rsi", 0x500)],       # path 2
        ])
        ev = p.collect(0x1000)
        assert ev.path_count == 2
        assert ev.concrete_count == 3
        assert "rax" in ev.vars
        assert ev.vars["rax"].paths == 2   # set on both paths
        assert ev.vars["rdi"].paths == 1
        assert ev.vars["rsi"].paths == 1
        assert ev.has_evidence is True

    def test_context_none_returns_empty(self):
        p = self._pass([[]])
        p._symbolik_context = lambda: None
        ev = p.collect(0x1000)
        assert ev.has_evidence is False
        assert ev.concrete_count == 0

    def test_analyze_attaches_metadata(self):
        from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
        p = self._pass([[("rax", 1)]])
        g = BlockGraph(entry_block=BasicBlock(addr=0x1000, is_entry=True),
                       blocks={})
        g.blocks[0x1000] = g.entry_block
        out = p.analyze(g)
        assert "applied_effects" in out.metadata
        ev = out.metadata["applied_effects"]
        assert ev.has_evidence is True
        assert ev.concrete_count == 1


class TestAppliedFeedsFeatures:
    def test_applied_evidence_adds_features(self):
        """Applied-effect metadata flows into feature idx 8/9."""
        from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
        from dec_engine.dec_impl.ml.features import extract
        from dec_engine.dec_impl.ir.expression import Var, Size, Const, BinOp, OpType
        from dec_engine.dec_impl.ir.effects import Branch

        # graph with variable "reg1" used in a binop (size 64)
        g = BlockGraph(entry_block=BasicBlock(addr=0x1000, is_entry=True),
                       blocks={})
        g.blocks[0x1000] = g.entry_block
        v = Var("reg1", Size.SIZE_64)
        g.entry_block.instructions = [
            Branch(condition=BinOp(OpType.LT, v, Const(10)), true_target=None)
        ]

        # no applied evidence -> idx 8/9 are 0
        feat_no = next(e.features for e in extract(g) if e.var == "reg1")
        assert feat_no[8] == 0.0
        assert feat_no[9] == 0.0

        # attach applied evidence: reg1 resolved on 4 paths, concrete symval
        ev = AppliedEffectEvidence()
        ev.vars["reg1"] = VarApplied(symval=0x400, paths=4)
        g.metadata["applied_effects"] = ev
        feat_yes = next(e.features for e in extract(g) if e.var == "reg1")
        # 4/8 = 0.5 path strength, concrete flag 1
        assert feat_yes[8] == pytest.approx(0.5)
        assert feat_yes[9] == 1.0
