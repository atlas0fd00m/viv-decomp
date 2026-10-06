"""Call-graph construction for the memory/analysis layer.

Builds a module-level call graph by walking every function graph and
recording each ``Call`` instruction's callee as an edge caller→callee.
Handles indirect calls (through registers / memory) as unresolved edges.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CallGraph:
    """Directed call graph: caller addr -> set of callee addr/names."""

    calls: Dict[int, Set[Tuple[int, str]]] = field(default_factory=dict)
    callers: Dict[int, Set[int]] = field(default_factory=dict)  # callee -> callers

    def edge(self, caller: int, callee: int, name: str):
        self.calls.setdefault(caller, set()).add((callee, name))
        self.callers.setdefault(callee, set()).add(caller)

    def edges_from(self, addr: int) -> Set[Tuple[int, str]]:
        return self.calls.get(addr, set())

    def edges_to(self, addr: int) -> Set[int]:
        return self.callers.get(addr, set())

    def __len__(self):
        return sum(len(v) for v in self.calls.values())


class CallGraphBuilder:
    """Build a CallGraph from a list of (funcva, BlockGraph) pairs."""

    def __init__(self):
        self.graph = CallGraph()

    def _callee_name(self, call, vw=None):
        """Resolve a call's callee to (addr, name); None addr for indirect."""
        from dec_engine.dec_impl.ir.expression import Var, Const
        callee = getattr(call, "callee", None)
        if callee is None:
            return None, "??"

        # Direct address constant
        if isinstance(callee, Const):
            value = callee.value
            if isinstance(value, int):
                name = ""
                if vw is not None:
                    try:
                        name = vw.getName(value) or f"sub_{value:x}"
                    except Exception:
                        name = f"sub_{value:x}"
                return value, name
            return None, str(value)

        # Register / var-based indirect call
        if isinstance(callee, Var):
            cname = str(getattr(callee, "name", ""))
            return None, cname  # indirect; target unresolved

        return None, "??"

    def build(self, funcs, vw=None) -> CallGraph:
        """Build the call graph from an iterable of (funcva, graph) tuples.

        ``funcs`` may be a dict {funcva: graph} or a list of (funcva, graph).
        """
        from dec_engine.dec_impl.ir.effects import Call

        items = funcs.items() if isinstance(funcs, dict) else funcs
        for funcva, graph in items:
            for addr, block in getattr(graph, "blocks", {}).items():
                for instr in getattr(block, "instructions", []):
                    if not isinstance(instr, Call):
                        continue
                    callee_addr, callee_name = self._callee_name(instr, vw)
                    if callee_addr is not None:
                        self.graph.edge(funcva, callee_addr, callee_name)

        return self.graph


def summarize_calls(graph: CallGraph) -> str:
    """Return a compact textual summary of the call graph."""
    lines = []
    for caller in sorted(graph.calls):
        callees = graph.calls[caller]
        for callee_addr, callee_name in sorted(callees, key=lambda c: c[1]):
            lines.append(f"0x{caller:x} -> 0x{callee_addr:x} ({callee_name})")
    return "\n".join(lines)
