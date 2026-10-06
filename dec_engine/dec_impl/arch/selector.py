"""Architecture selection for the decompiler.

Provides a registry of known Vivisect symbolik analysis contexts keyed by
architecture name, automatic architecture detection from a loaded
VivWorkspace, and an explicit-override selector.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Type

logger = logging.getLogger(__name__)


# Map Vivisect architecture names -> symbolik analysis context class.
# These are imported lazily to avoid hard dependency on every arch.
_ARCH_CONTEXTS: Dict[str, Optional[Type]] = {
    "amd64": None,  # resolved on first use
    "i386": None,
}


def _load_amd64_context():
    try:
        from vivisect.symboliks.archs.amd64 import Amd64SymbolikAnalysisContext
        _ARCH_CONTEXTS["amd64"] = Amd64SymbolikAnalysisContext
        return Amd64SymbolikAnalysisContext
    except ImportError as exc:  # pragma: no cover
        logger.warning("amd64 symbolik context unavailable: %s", exc)
        return None


def _load_i386_context():
    try:
        from vivisect.symboliks.archs.i386 import i386SymbolikAnalysisContext
        _ARCH_CONTEXTS["i386"] = i386SymbolikAnalysisContext
        return i386SymbolikAnalysisContext
    except ImportError as exc:  # pragma: no cover
        logger.warning("i386 symbolik context unavailable: %s", exc)
        return None


_LOADERS = {
    "amd64": _load_amd64_context,
    "i386": _load_i386_context,
}


def symbolik_context_for_arch(arch: Optional[str]):
    """Return the symbolik analysis context class for an architecture name.

    Returns None if the arch is unknown or its module is missing.
    """
    if not arch:
        return None
    arch = arch.lower()

    # Direct / common aliases
    alias = {
        "x86-64": "amd64",
        "x64": "amd64",
        "amd64": "amd64",
        "x86": "i386",
        "i386": "i386",
        "ia32": "i386",
        "x86_32": "i386",
        "arm": "arm",
        "arm64": "arm64",
        "aarch64": "arm64",
        "mips": "mips",
        "ppc": "ppc",
        "powerpc": "ppc",
    }
    norm = alias.get(arch, arch)

    # Architectures with no bundled Vivisect symbolik context: record as
    # recognized-but-unsupported so the selector reports them instead of
    # treating them as unknown strings (enables graceful fallback).
    for known in ("arm", "arm64", "mips", "ppc"):
        _ARCH_CONTEXTS.setdefault(known, None)

    if _ARCH_CONTEXTS.get(norm) is None and norm in _LOADERS:
        _LOADERS[norm]()
    return _ARCH_CONTEXTS.get(norm)


def arch_name_for_workspace(vw) -> Optional[str]:
    """Detect the architecture name from a loaded VivWorkspace."""
    if vw is None:
        return None
    try:
        arch = vw.getMeta("Architecture")
        if arch:
            return str(arch)
    except Exception as exc:  # pragma: no cover
        logger.debug("Could not read workspace architecture: %s", exc)
    return None


class ArchSelector:
    """Select a symbolik analysis context for a workspace/arch combination.

    Priority: explicit override > workspace detection > default (amd64).
    """

    DEFAULT_ARCH = "amd64"

    def __init__(self, arch: Optional[str] = None):
        self._requested = arch

    def context_class(self, vw=None):
        """Resolve and return the analysis context class."""
        arch = self._requested
        if not arch:
            arch = arch_name_for_workspace(vw) or self.DEFAULT_ARCH
        ctx = symbolik_context_for_arch(arch)
        if ctx is None:
            logger.warning("No symbolik context for arch=%r; falling back to %s",
                           arch, self.DEFAULT_ARCH)
            ctx = symbolik_context_for_arch(self.DEFAULT_ARCH)
        return ctx

    def instantiate(self, vw=None):
        """Instantiate the context for the given workspace."""
        cls = self.context_class(vw)
        if cls is None:
            return None
        try:
            return cls(vw)
        except Exception as exc:  # pragma: no cover
            logger.error("Instantiate %s failed: %s", cls.__name__, exc)
            return None


def detect_from_workspace(vw) -> Optional[str]:
    """Convenience: detect arch name from a workspace."""
    return arch_name_for_workspace(vw)
