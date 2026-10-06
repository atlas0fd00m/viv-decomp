"""Memory model & stack-frame analysis.

Reconstructs stack frame layout from decompiled functions:
- Prologue/epilogue detection (push rbp; mov rbp,rsp; sub rsp,N)
- Stack-frame size computation
- Local-variable bucketing from [rbp ± offset] and [rsp ± offset] MemRefs
- Typed local variable enumeration
"""
from dec_engine.dec_impl.memory.stack import StackFrameAnalyzer, StackVariable

__all__ = ["StackFrameAnalyzer", "StackVariable"]
