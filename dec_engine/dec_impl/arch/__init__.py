"""Architecture abstraction & dispatch.

Maps a target architecture to the appropriate Vivisect symbolik analysis
context (Amd64/i386/...), auto-detects architecture from a loaded workspace,
and allows an explicit override. This decouples the decompiler pipeline from
the hard-coded ``Amd64SymbolikAnalysisContext``.
"""
from dec_engine.dec_impl.arch.selector import (
    ArchSelector,
    arch_name_for_workspace,
    symbolik_context_for_arch,
)

__all__ = [
    "ArchSelector",
    "arch_name_for_workspace",
    "symbolik_context_for_arch",
]
