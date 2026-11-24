"""Tests for the neural type-inference module (S8, dependency-free ML)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from dec_engine.dec_impl.ml.classifier import BinaryLogisticModel, OneVsRestClassifier
from dec_engine.dec_impl.ml.features import extract, FEATURE_DIM, labels_of, features_of
from dec_engine.dec_impl.ml.typing import NeuralTypeInferer, _make_datatype


# ── helpers to build small IR graphs ──

def _g():
    from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
    entry = BasicBlock(addr=0x1000, is_entry=True)
    return BlockGraph(entry_block=entry, blocks={0x1000: entry})


def _var(name, sz):
    from dec_engine.dec_impl.ir.expression import Var, Size
    return Var(name, Size(sz))


def _const(v, sz=32):
    from dec_engine.dec_impl.ir.expression import Const, Size
    return Const(v, Size(sz))


def _assignment(dst, src):
    from dec_engine.dec_impl.ir.effects import Assignment
    return Assignment(destination=dst, source=src, address=0x1000)


def _branch(cond, tgt):
    from dec_engine.dec_impl.ir.effects import Branch
    return Branch(condition=cond, true_target=_var("bb", 64), address=0x1000)


class TestFeatureExtractor:
    def test_dim(self):
        assert FEATURE_DIM == 10

    def test_int_var_features(self):
        from dec_engine.dec_impl.ir.expression import BinOp, OpType, Const
        g = _g()
        bb = next(iter(g.blocks.values()))
        i = _var("i", 32)
        bb.instructions = [_assignment(i, _const(0))]
        # i compared with constant
        bb.instructions.append(
            _branch(BinOp(OpType.LT, i, _const(10)), None))
        examples = extract(g)
        assert len(examples) == 1
        ex = examples[0]
        # size normalized: 32/64 = 0.5
        assert ex.features[0] == pytest.approx(0.5)
        # compared against const
        assert ex.features[4] == 1.0
        assert ex.label == "int"

    def test_pointer_var_features(self):
        from dec_engine.dec_impl.ir.expression import MemRef
        g = _g()
        bb = next(iter(g.blocks.values()))
        p = _var("p", 64)
        # p used as memref base -> pointer
        src = MemRef(base=p, offset=_const(0), size=64)
        bb.instructions = [_assignment(_var("x", 32), src)]
        examples = extract(g)
        p_ex = next(e for e in examples if e.var == "p")
        assert p_ex.features[2] == 1.0  # memaddr
        assert p_ex.label == "void*"

    def test_label_by_size(self):
        assert _make_datatype("long", 64).name == "long"
        assert _make_datatype("char", 8).size.value == 8


class TestClassifier:
    def test_binary_sigmoid(self):
        m = BinaryLogisticModel(2)
        # sigmoid monotonic
        assert m.sigmoid(3.0) > m.sigmoid(-3.0)
        assert 0.5 - 1e-6 < m.sigmoid(0) < 0.5 + 1e-6

    def test_binary_trains_separable(self):
        # feature[0] > 0.5 -> positive class
        X = [[0.0, 0], [0.2, 0], [0.9, 0], [1.0, 0]]
        y = [0, 0, 1, 1]
        m = BinaryLogisticModel(2)
        m.train(X, y, epochs=300, lr=0.2)
        assert m.predict([0.1, 0]) == 0
        assert m.predict([0.95, 0]) == 1

    def test_multiclass(self):
        X = [[0.0, 0], [0.1, 0],   # small -> low
             [0.5, 0], [0.6, 0],   # mid -> int
             [1.0, 0], [0.9, 0]]   # big -> long
        y = ["char", "char", "int", "int", "long", "long"]
        clf = OneVsRestClassifier(2, ["char", "int", "long"])
        clf.train(X, y, epochs=300, lr=0.2)
        assert clf.predict([0.95, 0]) == "long"
        assert clf.accuracy(X, y) >= 0.5


class TestNeuralTypeInferer:
    def _train_graphs(self):
        from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
        graphs = []
        # graph A: 32-bit var, compared -> int
        for label_sz in (32, 64, 8):
            g = BlockGraph(entry_block=BasicBlock(addr=0x1000, is_entry=True),
                           blocks={0x1000: BasicBlock(addr=0x1000, is_entry=True)})
            g.blocks[0x1000] = g.entry_block
            # re-create entry as the same object
            graphs.append(g)
        return graphs

    def test_infer_requires_training(self):
        inf = NeuralTypeInferer()
        with pytest.raises(RuntimeError):
            inf.infer(_g())

    def test_train_then_infer(self):
        from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
        inf = NeuralTypeInferer(classes=["char", "int", "long", "void*"])
        # synthetic examples from graphs with clear size signal
        graphs = []
        for sz, lbl in [(8, "char"), (32, "int"), (64, "long")]:
            g = BlockGraph(entry_block=BasicBlock(addr=0x1000, is_entry=True),
                           blocks={})
            bb = BasicBlock(addr=0x1000, is_entry=True)
            g.blocks[0x1000] = bb
            g.entry_block = bb
            i = _var(f"v{sz}", sz)
            bb.instructions = [_branch(_int_lt(i, 0), None)]
            graphs.append((g, lbl))
        # Build X/y by feature extraction + manual labels
        X, y = [], []
        for g, lbl in graphs:
            exs = extract(g)
            for e in exs:
                X.append(e.features)
                y.append(lbl)
        inf.train_from_examples(X, y, epochs=300)
        assert inf.model is not None
        # infer on a fresh graph with a 64-bit var
        g = _g()
        bb = next(iter(g.blocks.values()))
        longv = _var("L", 64)
        bb.instructions = [_branch(_int_lt(longv, 0), None)]
        preds = inf.infer(g)
        assert "L" in preds
        assert preds["L"].name in ("long", "void*")


def _int_lt(v, c):
    from dec_engine.dec_impl.ir.expression import BinOp, OpType, Const
    return BinOp(OpType.LT, v, Const(c))


class TestNeuralTypePass:
    def test_untrained_pass_skips(self):
        from dec_engine.dec_impl.ml.neural_pass import NeuralTypePass
        p = NeuralTypePass()
        g = _g()
        out = p.analyze(g)
        assert out is g  # no-op, no crash

    def test_trained_pass_annotates(self):
        from dec_engine.dec_impl.ml.neural_pass import NeuralTypePass
        from dec_engine.dec_impl.ml.typing import NeuralTypeInferer
        inf = NeuralTypeInferer(classes=["char", "int", "long", "void*"])
        # train minimally on separable size data (feature0 = size/64)
        def _feat(size):  # FEATURE_DIM-dim feature vector, size at idx 0
            f = [0.0] * FEATURE_DIM
            f[0] = size / 64.0
            return f
        X = [_feat(8), _feat(32), _feat(64)]
        y = ["char", "int", "long"]
        inf.train_from_examples(X, y, epochs=300)
        p = NeuralTypePass(inferer=inf)

        from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
        g = BlockGraph(entry_block=BasicBlock(addr=0x1000, is_entry=True),
                       blocks={})
        g.blocks[0x1000] = g.entry_block
        bb = g.entry_block
        v = _var("bigv", 64)
        bb.instructions = [_branch(_int_lt(v, 0), None)]
        out = p.analyze(g)
        assert "ml_types" in out.entry_block.metadata
        assert "bigv" in out.entry_block.metadata["ml_types"]
