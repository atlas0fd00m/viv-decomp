"""Feature extraction from the IR graph for type inference.

Walks our IR (Built from Vivisect symbolik effects) and produces, per
variable, a numeric feature vector + a type label. This is the "feature
engineering" layer that turns `getSymbolikGraph`'s unapplied effects (via
EffectsBuilder -> IR) into supervised-training examples.

Feature vector (fixed length F):
  idx 0: var size bits (8/16/32/64 -> normalized /64)
  idx 1: 1 if used in a binop (arithmetic/comparison) else 0
  idx 2: 1 if used as a memory address (MemRef base) else 0
  idx 3: 1 if assigned from a pointer-like (MemRef) source else 0
  idx 4: 1 if compared against a constant/address else 0
  idx 5: 1 if used as a call argument else 0
  idx 6: width variance across uses (0..1)
  idx 7: 1 if appears as a load target (ReadMemory) else 0
  idx 8: applied-effect path count (SymbolikEmulator applied evidence, /8)
  idx 9: 1 if variable is concrete-resolved in applied effects (pointer-likeness)

(Applied indices are present only when the graph carries
``metadata["applied_effects"]`` from the SymbolikEmulatorPass; otherwise they
are 0.)

Label: DataType name (e.g. "char", "int", "long", "void*", ...).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import dec_engine.dec_impl.ir.expression as expr
import dec_engine.dec_impl.ir.effects as fx


FEATURE_DIM = 10


def _size_bits(sz) -> int:
    if isinstance(sz, expr.Size):
        return sz.value if sz.value in (8, 16, 32, 64) else 0
    return int(sz) if sz in (8, 16, 32, 64) else 0


def _to_type_label(size_bits: int, is_ptr: bool) -> str:
    if is_ptr:
        return "void*"
    return {8: "char", 16: "short", 32: "int", 64: "long"}.get(size_bits, "unknown")


class TypeExample:
    __slots__ = ("var", "features", "label")

    def __init__(self, var, features: List[float], label: str):
        self.var = var
        self.features = features
        self.label = label


def _collect_use_stats(graph) -> Dict[str, Dict[str, float]]:
    """Per-variable usage statistics over all blocks' instructions."""
    stats = defaultdict(lambda: {
        "sizes": [], "binop": 0, "memaddr": 0, "ptr_src": 0,
        "cmp_const": 0, "call_arg": 0, "load": 0, "uses": 0,
    })
    for bb in graph.blocks.values():
        for instr in bb.instructions:
            _account_instr(instr, stats)
    return stats


def _account_instr(instr, stats: Dict):
    # Assignment dst = src
    if isinstance(instr, fx.Assignment):
        _account_expr(instr.destination, stats, role="dst")
        _account_expr(instr.source, stats, role="src")
        # if src is a MemRef, dst is pointer-like
        if isinstance(instr.source, expr.MemRef):
            nm = _name(instr.destination)
            if nm:
                stats[nm]["ptr_src"] += 1
    elif isinstance(instr, fx.Call):
        _account_expr(instr.callee, stats, role="callee")
        for a in instr.args:
            _account_expr(a, stats, role="arg")
    elif isinstance(instr, fx.Branch):
        if instr.condition is not None:
            _account_expr(instr.condition, stats, role="cond")


def _account_expr(e, stats, role: str, _root=True):
    if e is None:
        return
    nm = _name(e)
    sizes = _size_bits(getattr(e, "size", None))
    if nm:
        st = stats[nm]
        st["uses"] += 1
        if sizes:
            st["sizes"].append(sizes)
        if role in ("arg",):
            st["call_arg"] += 1
        if role == "cond":
            st["cmp_const"] += 1
    # recurse
    if isinstance(e, expr.MemRef):
        # the base of a memref is an address
        bname = _name(e.base)
        if bname:
            stats[bname]["memaddr"] += 1
        _account_expr(e.base, stats, role, _root=False)
        _account_expr(e.offset, stats, role, _root=False)
        return
    if isinstance(e, expr.BinOp):
        if nm is None:
            pass
        # mark operands used in arithmetic
        _mark_binop(stats, e.left)
        _mark_binop(stats, e.right)
        _account_expr(e.left, stats, role, _root=False)
        _account_expr(e.right, stats, role, _root=False)
        return
    if isinstance(e, expr.UnOp):
        _account_expr(e.operand, stats, role, _root=False)
        return
    if isinstance(e, expr.CallExpr):
        _account_expr(e.callee, stats, role, _root=False)
        for a in e.args:
            _account_expr(a, stats, role, _root=False)
        return


def _mark_binop(stats, e):
    nm = _name(e)
    if nm:
        stats[nm]["binop"] += 1


def _name(e) -> Optional[str]:
    if isinstance(e, expr.Var):
        return e.name
    return None


def _applied_lookup(graph):
    """Return the applied_effects evidence dict from graph metadata, or empty."""
    meta = getattr(graph, "metadata", None)
    if not meta:
        return {}
    ev = meta.get("applied_effects")
    if ev is None:
        return {}
    return getattr(ev, "vars", {}) or {}


def extract(graph) -> List[TypeExample]:
    """Extract per-variable feature vectors + labels from the IR graph."""
    stats = _collect_use_stats(graph)
    applied = _applied_lookup(graph)  # name -> VarApplied (applied evidence)
    examples: List[TypeExample] = []
    for var, st in stats.items():
        if not st["sizes"]:
            continue
        size = max(st["sizes"])  # widest use
        f: List[float] = [0.0] * FEATURE_DIM
        f[0] = size / 64.0
        f[1] = 1.0 if st["binop"] else 0.0
        f[2] = 1.0 if st["memaddr"] else 0.0
        f[3] = 1.0 if st["ptr_src"] else 0.0
        f[4] = 1.0 if st["cmp_const"] else 0.0
        f[5] = 1.0 if st["call_arg"] else 0.0
        if len(st["sizes"]) >= 2:
            mn, mx = min(st["sizes"]), max(st["sizes"])
            f[6] = (mx - mn) / 64.0
        f[7] = 1.0 if st["load"] else 0.0

        # Applied-effect evidence (idx 8-9): strength of SymbolikEmulator
        # resolution for this variable (if the pass ran and named it).
        if var in applied:
            applied_v = applied[var]
            paths = int(getattr(applied_v, "paths", 0) or 0)
            f[8] = min(paths, 8) / 8.0
            f[9] = 1.0 if getattr(applied_v, "symval", None) is not None else 0.0

        is_ptr = st["memaddr"] > 0 or st["ptr_src"] > 0
        label = _to_type_label(size if size in (8, 16, 32, 64) else 32, bool(is_ptr))
        examples.append(TypeExample(var=var, features=f, label=label))
    return examples


def labels_of(examples: List[TypeExample]) -> List[str]:
    return [e.label for e in examples]


def features_of(examples: List[TypeExample]) -> List[List[float]]:
    return [e.features for e in examples]
