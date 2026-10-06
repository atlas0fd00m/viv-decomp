"""Memory model & call-graph analysis.

Reconstructs stack frame layout from decompiled functions and builds a
module-level call graph:
- StackFrameAnalyzer: prologue/epilogue detection, frame-size computation,
  local-variable bucketing from [rbp ± offset] / [rsp ± offset] MemRefs,
  typed local-variable enumeration.
- CallGraphBuilder: directed caller→callee edges from Call instructions.
"""
from dec_engine.dec_impl.memory.stack import StackFrameAnalyzer, StackVariable
from dec_engine.dec_impl.memory.callgraph import (
    CallGraph,
    CallGraphBuilder,
    summarize_calls,
)

__all__ = [
    "StackFrameAnalyzer",
    "StackVariable",
    "CallGraph",
    "CallGraphBuilder",
    "summarize_calls",
]
