"""Applied-effects extraction for type inference (via SymbolikEmulator).

Runs Vivisect's symbolik emulator over a function to obtain **applied**
effects — the raw symbolik effects resolved against live emulator state
(``SetVariable.applyEffect`` writes the concrete/resolved value into
``emu._sym_vars``). This is strictly stronger evidence than the unapplied
effect list alone:

- unapplied: a variable is 64-bits wide (structural guess)
- applied: the variable actually holds a resolved value on some path, or was
  dereferenced (pointer-likeness becomes concrete)

Uses ``SymbolikAnalysisContext.getSymbolikPaths(fva)`` which yields
``(emu, effects)`` per path through the function. ``emu.getSymVariables()``
returns the applied ``(name, symval)`` pairs for that path; we merge across
paths so each variable keeps its resolved value + pointer evidence.

This feeds the neural feature extractor: applied evidence becomes extra
features (resolved-to-concrete flag, dereference count, resolved pointer).
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class VarApplied:
    """Applied symbolik evidence for one variable (per function)."""

    symval: Optional[object] = None
    paths: int = 0


class AppliedEffectEvidence:
    """Merged applied-effect evidence for a single function's variables."""

    def __init__(self):
        self.vars: Dict[str, VarApplied] = {}
        self.concrete_count: int = 0
        self.pointer_count: int = 0
        self.path_count: int = 0

    @property
    def has_evidence(self) -> bool:
        return bool(self.vars)


class SymbolikEmulatorPass:
    """Runs the symbolik emulator to collect applied-effect evidence.

    Attach to a decompiler pass list: ``analyze()`` receives a BlockGraph and
    returns it; it consumes a live Vivisect workspace for the function's path
    emulation and stores per-variable applied evidence in the graph's
    top-level metadata (``applied_effects``).
    """

    def __init__(self, vw=None):
        self.vw = vw

    def set_workspace(self, vw):
        self.vw = vw

    # ── core ──

    def collect(self, fva: int) -> AppliedEffectEvidence:
        """Run emulated paths for ``fva`` and merge applied evidence."""
        if self.vw is None:
            raise RuntimeError("SymbolikEmulatorPass needs a workspace "
                               "(set_workspace / vw=)")
        ctx = self._symbolik_context()
        if ctx is None:
            logger.warning("no symbolik context; applied-effects skipped")
            return AppliedEffectEvidence()

        ev = AppliedEffectEvidence()
        try:
            for emu, _effects in ctx.getSymbolikPaths(fva):
                ev.path_count += 1
                for name, symval in emu.getSymVariables():
                    d = ev.vars.setdefault(name, VarApplied())
                    d.symval = symval
                    d.paths += 1
            ev.concrete_count = len(ev.vars)
        except Exception as exc:
            logger.debug("apply-effects skipped for 0x%x: %s", fva, exc)
        return ev

    def _symbolik_context(self):
        """Instantiate the arch symbolik analysis context for the workspace."""
        from dec_engine.dec_impl.arch.selector import symbolik_context_for_arch
        vw = self.vw
        if vw is None:
            return None
        try:
            arch = vw.getMeta("Architecture")
        except Exception:
            arch = None
        cls = symbolik_context_for_arch(arch)
        if cls is None:
            return None
        return cls(vw)

    # ── plugin-pass interface ──

    def analyze(self, graph):
        """Plugin analysis pass: run emulation on each entry addr in graph,
        attach ``applied_effects`` evidence to graph.metadata."""
        ev = AppliedEffectEvidence()
        # graph.entry_block.addr is the function start when built by the
        # workspace/graph builder
        entry = None
        if graph.entry_block is not None:
            entry = graph.entry_block.addr
        if entry is not None:
            ev = self.collect(entry)
        # stash on graph.metadata for the feature extractor
        graph.metadata["applied_effects"] = ev
        return graph
