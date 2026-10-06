"""Stack-frame analysis for decompiled functions.

Reconstructs the local stack frame from a function's CFG:
- Detects prologue/epilogue patterns (push rbp; mov rbp,rsp; sub rsp,N)
- Computes the frame size
- Buckets [rbp ± offset] and [rsp ± offset] memory references into typed
  local-variable slots

Works on the IR ``MemRef`` shapes produced by the graph builder:
  - ``MemRef(base=Var('rbp'), offset=Const(-0x10))``  (Vivisect signed-const style)
  - ``MemRef(base=BinOp(SUB, Var('rbp'), Const(0x10)), offset=Const(0))`` (IR style)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class StackVariable:
    """A typed local variable occupying part of the stack frame."""

    offset: int           # signed byte offset relative to frame base (rbp)
    size: int             # byte span of the variable
    name: str             # e.g. var_10
    type_name: str = "uint64_t"
    accesses: int = 0     # how many times this slot is referenced

    def __repr__(self):
        return f"StackVariable(off=0x{self.offset:x}, size={self.size}, {self.name}: {self.type_name})"


def _frame_offset(memref, base_names=("rbp", "rsp")):
    """Extract a signed frame-relative offset from a MemRef.

    Returns ``(base_reg, offset)`` when the memory ref is relative to a frame
    pointer, else ``None``. Handles both signed-Const and BinOp base styles.
    """
    from dec_engine.dec_impl.ir.expression import MemRef, BinOp, Const, Var, OpType

    base = getattr(memref, "base", None)
    offset = getattr(memref, "offset", None)

    # Style 1: base is Var('rbp'|'rsp'), offset is Const (may be negative)
    if isinstance(base, Var) and isinstance(offset, Const):
        bname = str(getattr(base, "name", ""))
        if bname in base_names and isinstance(offset.value, int):
            return bname, offset.value

    # Style 2: base is BinOp(SUB, Var('rbp'), Const(k)), offset is Const(0)
    if isinstance(base, BinOp):
        left = base.left
        right = base.right
        bname = None
        if isinstance(left, Var):
            bname = str(getattr(left, "name", ""))
        elif isinstance(right, Var):
            bname = str(getattr(right, "name", ""))
        if bname in base_names and isinstance(right, Const) and isinstance(right.value, int):
            # determine sign from op: (rbp SUB k) => -k ; (rbp ADD k) => +k
            if getattr(base.op, "name", "") == "SUB":
                return bname, -right.value
            return bname, right.value

    return None


class StackFrameAnalyzer:
    """Detect the stack frame and enumerate typed locals for a function graph."""

    def __init__(self):
        self.frame_size: int = 0
        self.vars: Dict[int, StackVariable] = {}   # offset -> variable
        self.used_temps: set = set()

    def _frame_size_from_prologue(self, block) -> int:
        """Scan the entry block's prologue for ``sub rsp, N`` allocation."""
        from dec_engine.dec_impl.ir.effects import Assignment
        for instr in getattr(block, "instructions", []):
            if not isinstance(instr, Assignment):
                continue
            dst = instr.destination
            src = instr.source
            dname = str(getattr(dst, "name", ""))
            if dname == "rsp" and "SUB" in repr(src):
                # extract N from BinOp(SUB, rsp, Const(N))
                from dec_engine.dec_impl.ir.expression import BinOp, Const, OpType
                if isinstance(src, BinOp) and getattr(src.right, "value", None):
                    n = src.right.value
                    if isinstance(n, int) and n > 0:
                        self.frame_size = n
                        return n
        return 0

    def analyze(self, graph) -> List[StackVariable]:
        """Walk all blocks, bucket frame-relative memrefs, return typed locals."""
        from dec_engine.dec_impl.ir.effects import Assignment, Call
        self.vars = {}

        blocks = getattr(graph, "blocks", {})
        # Frame size from entry block prologue
        entry_addr = getattr(getattr(graph, "entry_block", None), "addr", None)
        if entry_addr is not None and entry_addr in blocks:
            entries = [entry_addr]
        else:
            entries = sorted(blocks.keys())[:1]
        for ea in entries:
            if self._frame_size_from_prologue(blocks.get(ea)):  # noqa: E501
                break

        # Bucket every frame-relative memory access
        for addr, block in blocks.items():
            for instr in getattr(block, "instructions", []):

                def walk_expr(expr):
                    from dec_engine.dec_impl.ir.expression import MemRef
                    if isinstance(expr, MemRef):
                        hit = _frame_offset(expr)
                        if hit is not None:
                            _base_reg, off = hit
                            self._record_access(off, expr)
                    # recurse into operands
                    for attr in ("base", "left", "right", "operand", "from_expr", "callee", "destination", "source"):
                        child = getattr(expr, attr, None)
                        if child is not None:
                            walk_expr(child)
                    for attr in ("args", "operands", "children"):
                        seq = getattr(expr, attr, None) or []
                        for child in (seq if isinstance(seq, (list, tuple)) else []):
                            walk_expr(child)

                if isinstance(instr, (Assignment, Call)):
                    walk_expr(instr)
                else:
                    walk_expr(instr)

        return sorted(self.vars.values(), key=lambda v: v.offset)

    def _size_from_size_attr(self, expr) -> int:
        from dec_engine.dec_impl.ir.expression import Size
        sz = getattr(expr, "size", None)
        m = {Size.SIZE_8: 1, Size.SIZE_16: 2, Size.SIZE_32: 4, Size.SIZE_64: 8}
        return m.get(sz, 8)

    def _record_access(self, offset: int, memref):
        """Record a variable at the given frame offset (positive = above frame base)."""
        # locals live below the frame base; store offset as its negative distance
        key = abs(offset)
        size = self._size_from_size_attr(memref)
        if key in self.vars:
            self.vars[key].accesses += 1
            self.vars[key].size = max(self.vars[key].size, size)
            return
        self.vars[key] = StackVariable(
            offset=offset,
            size=size,
            name=f"var_{key:x}",
            accesses=1,
        )

    def declare_lines(self, indent: int = 4) -> List[str]:
        """Return C-style local declarations for each variable."""
        pad = " " * indent
        lines = []
        for v in sorted(self.vars.values(), key=lambda v: v.offset):
            lines.append(f"{pad}{v.type_name} {v.name};")
        return lines
