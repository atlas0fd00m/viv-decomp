"""
Core decompiler engine — ties the graph builder → SSA → type inference → output pipeline together.

The VivisectDecompiler class is the orchestration layer:
  1. Load binary / get graph source
  2. Build BlockGraph via a GraphBuilder plugin
  3. Run analysis passes (SSA, structural, type inference)
  4. Format output

Graph builders are pluggable: a GraphBuilder is any class that implements
  def build(self, graph): BlockGraph
    Takes a raw graph dict/obj and returns a BlockGraph ready for analysis.
"""
from __future__ import annotations

import logging
import sys
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any

# Ensure the project root is on sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
from dec_engine.dec_impl.ssa.construct import SsaState, SsaTransform
from dec_engine.dec_impl.type_inference.analyze import TypeAnalyzer, TypeEnvironment
from dec_engine.dec_impl.output.pretty import PrettyPrinter

# Imported lazily inside BUILDER_MAP resolution to avoid import cycle.
def _workspace_builder_cls():
    from viv_decomp.workspace_builder import WorkspaceGraphBuilder
    return WorkspaceGraphBuilder

logger = logging.getLogger("viv-decomp")


# ── Plugin interface ──

class GraphBuilder(ABC):
    """Abstract base class for graph source plugins.

    Subclasses are initialized with a binary path and must implement
    ``get_graph(funcva) -> BlockGraph`` which returns the CFG for a function.
    """

    def __init__(self, binary_path: str, arch: Optional[str] = None):
        self.binary_path = binary_path
        self.arch = arch

    @abstractmethod
    def get_graph(self, funcva: int, name: str = "") -> BlockGraph:
        """Return a BlockGraph for the function at the given virtual address."""
        ...

    def load(self) -> None:
        """Optional hook called once before any ``get_graph`` calls."""
        pass


# ── Vivisect graph builder ──

class VivisectGraphBuilder(GraphBuilder):
    """Builds BlockGraph from an existing Vivisect workspace."""

    def __init__(self, binary_path: str, arch: Optional[str] = None,
                 workspace=None):
        super().__init__(binary_path)
        self.vw = workspace
        self.workspace_loaded = workspace is not None
        self.arch = arch  # optional explicit architecture override

    def set_workspace(self, vw):
        """Attach an already-loaded Vivisect workspace (e.g. from a GUI/ext)."""
        self.vw = vw
        self.workspace_loaded = vw is not None

    def load(self) -> None:
        """Import Vivisect, load the binary workspace (if none attached)."""
        if self.workspace_loaded and self.vw is not None:
            return
        try:
            import vivisect  # noqa: F811
        except ImportError:
            raise RuntimeError(
                "vivisect package is not installed. Install it to use the "
                "Vivisect graph builder.\n"
                "  pip install vivisect\n"
                "Or use --graph raw with manual graph construction."
            )
        try:
            vw = vivisect.VivWorkspace()
            vw.loadFromFile(self.binary_path)
            vw.analyze()
            self.vw = vw
            self.workspace_loaded = True
            logger.info(f"Loaded Vivisect workspace: {self.binary_path}")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load {self.binary_path} in Vivisect: {exc}"
            ) from exc

    def get_graph(self, funcva: int, name: str = "") -> BlockGraph:
        """Build a BlockGraph from the Vivisect workspace using the symbolik graph."""
        if not self.workspace_loaded or self.vw is None:
            self.load()
        vw = self.vw
        assert vw is not None, "Vivisect workspace not loaded"

        # Ensure the function has a symbolik graph (analyzed)
        if funcva not in vw.getFunctions():
            # Try to discover it via analysis
            try:
                vw.analyzeFunction(funcva)
            except Exception:
                pass

        if funcva not in vw.getFunctions():
            # No function — build a minimal block graph
            entry = BasicBlock(
                addr=funcva, is_entry=True, label=f"bb_{funcva:x}" if funcva else "bb_entry",
            )
            fallback_name = f"func_{funcva:x}"
            return BlockGraph(
                entry_block=entry, blocks={funcva: entry}, name=fallback_name,
            )

        # Get symbolik graph from architecture-specific analysis context
        # (auto-detected from the workspace, or overridden via self.arch)
        from dec_engine.dec_impl.arch.selector import ArchSelector
        from dec_engine.dec_impl.ir.builder import EffectsBuilder

        selector = ArchSelector(arch=self.arch)
        ctx = selector.instantiate(vw)
        if ctx is None:
            raise RuntimeError(
                "No symbolik analysis context available for arch="
                f"{selector.context_class(vw) and selector._requested or 'default'}"
            )
        sgraph = ctx.getSymbolikGraph(funcva)

        # Validate we have symbolik effects to process
        has_effects = False
        for va_node, ninfo in sgraph.getNodes():
            if isinstance(ninfo, dict) and 'symbolik_effects' in ninfo:
                if ninfo['symbolik_effects']:
                    has_effects = True
                    break

        builder = EffectsBuilder(funcva)
        label = name or (vw.getName(funcva) if vw.getName(funcva) else f"func_{funcva:x}")

        if has_effects:
            return builder.build(sgraph, func_name=label)
        else:
            builder_empty = EffectsBuilder(funcva)
            # Build with empty graph (no symbolik effects)
            blocks_dict = {}
            entry_block = BasicBlock(
                addr=funcva, is_entry=True, label=f"func_{funcva:x}"
            )
            blocks_dict[funcva] = entry_block
            return BlockGraph(
                entry_block=entry_block, blocks=blocks_dict, name=label,
            )


# ── Raw (stub) graph builder for testing ──

class RawGraphBuilder(GraphBuilder):
    """Graph builder that creates a minimal test graph from scratch.

    Useful for testing the pipeline without binaries.
    """

    def get_graph(self, funcva: int, name: str = "") -> BlockGraph:
        """Return a simple test graph with two blocks."""
        bb1 = BasicBlock(addr=funcva, is_entry=True,
                         label=f"{name}_entry" if name else f"entry_{funcva:x}")
        bb2 = BasicBlock(addr=funcva + 0x10,
                         label=f"{name}_body" if name else f"body_{funcva + 0x10:x}")
        bb1.successors = [bb2]
        bb2.predecessors = [bb1]
        return BlockGraph(
            entry_block=bb1,
            blocks={funcva: bb1, funcva + 0x10: bb2},
            name=name or f"func_{funcva:x}",
        )


# ── Analysis result ──

@dataclass
class DecompOutput:
    """Container for decompiler output."""
    text: str
    json: dict  # Structured data (graph, ssa info, types)
    success: bool
    error: Optional[str] = None


# ── Main decompiler class ──

class VivisectDecompiler:
    """Orchestrates the full decompiler pipeline.

    Usage:
        decomp = VivisectDecompiler(binary_path="/bin/ls")
        output = decomp.decompile_address(0x401000)
        print(output.text)
    """

    BUILDER_MAP = {
        "vivisect": VivisectGraphBuilder,
        "workspace": _workspace_builder_cls,  # live-vw path (extension/GUI)
        "ghidra": VivisectGraphBuilder,  # Stub for now
        "raw": RawGraphBuilder,
    }

    def __init__(
        self,
        binary_path: str,
        graph_source: str = "vivisect",
        do_ssa: bool = True,
        analyze_types: bool = True,
        arch: Optional[str] = None,
        plugin_registry=None,
        passes: Optional[list] = None,
        formatter: Optional[str] = None,
    ):
        self.binary_path = binary_path
        self.do_ssa = do_ssa
        self.analyze_types = analyze_types
        self.arch = arch  # optional architecture override (S5)
        self.plugin_registry = plugin_registry
        self.passes = passes
        self.formatter = formatter

        builder_cls = self.BUILDER_MAP.get(graph_source, RawGraphBuilder)
        # "workspace" maps to a factory function; resolve lazily.
        if callable(builder_cls) and not isinstance(builder_cls, type):
            builder_cls = builder_cls()
        self.graph_builder = builder_cls(binary_path, arch=arch)

        # Analysis state
        self.graph: Optional[BlockGraph] = None
        self.ssa_state: Optional[SsaState] = None
        self.type_env: Optional[TypeEnvironment] = None

    @classmethod
    def from_workspace(cls, vw, graph_source: Optional[str] = None,
                       do_ssa: bool = True, analyze_types: bool = True,
                       arch: Optional[str] = None):
        """Create a decompiler from an already-loaded Vivisect workspace.

        This is the path used by the Vivisect extension/GUI: it consumes the
        live ``vw`` instead of re-loading the binary, avoiding the
        ``analyzePLT`` load quirk. The binary path is nominal.
        """
        binary = getattr(vw, "_filename", None) or "<workspace>"
        # Default graph_source to the live-workspace builder, which reads the
        # CFG from vw.getFunctionGraph() instead of re-loading the binary.
        graph_source = graph_source or "workspace"
        decomp = cls(binary_path=binary, graph_source=graph_source,
                     do_ssa=do_ssa, analyze_types=analyze_types, arch=arch)
        builder = decomp.graph_builder
        if hasattr(builder, "set_workspace"):
            builder.set_workspace(vw)
        return decomp

    def decompile_address(self, funcva: int, name: str = "") -> DecompOutput:
        """Run the full decompiler pipeline on a single function.

        Always returns a DecompOutput; on pipeline failure ``success`` is
        False and ``error`` holds the exception text.
        """
        result = DecompOutput(text="", json={}, success=False)
        try:
            # 1. Build graph (this triggers graph_builder.load() → vw.analyze())
            self.graph = self.graph_builder.get_graph(funcva, name)
            logger.debug(f"Built BlockGraph: {len(self.graph.blocks)} blocks")
            
            # S2 Step: Collapse unconditional forward jumps (pre-SSA simplification)
            from dec_engine.dec_impl.structuring import collapse_unconditional_jumps
            old_block_count = len(self.graph.blocks)
            self.graph = collapse_unconditional_jumps(self.graph)
            if old_block_count != len(self.graph.blocks):
                logger.debug("Collapse pass: %d -> %d blocks", old_block_count, len(self.graph.blocks))
            
            # 2. Run SSA construction
            if self.do_ssa:
                self.ssa_state = SsaState()
                ssa = SsaTransform(self.graph)
                self.graph = ssa.analyze_graph()  # returns the graph
                logger.debug("SSA construction complete")
            
            # 3. Run type inference
            if self.analyze_types:
                analyzer = TypeAnalyzer()
                analyzer.analyze_graph(self.graph)  # propagate types over the CFG
                self.type_env = analyzer.env
                logger.debug("Type inference complete")

            # 3b. Run plugin analysis passes
            if self.plugin_registry is not None:
                self.graph = self.plugin_registry.run_passes(self.graph, self.passes)
                logger.debug("Plugin passes complete")

            # 4. Format output — pass workspace for call target resolution via vw.getName()
            pp = PrettyPrinter(
                func_name=name or f"func_{funcva:x}",
                graph=self.graph,
                ssa=self.ssa_state or SsaState(),
                workspace=self.graph_builder.vw if hasattr(self.graph_builder, 'vw') else None,
            )
            c_code = pp.generate()
            # Plugin formatter override
            if self.plugin_registry is not None and self.formatter:
                c_code = self.plugin_registry.format_output(
                    DecompOutput(text=c_code, json={}, success=True), self.formatter
                )
            
            # Build structured JSON snapshot
            from dec_engine.dec_impl.quality.metrics import analyze_output, QualityGate
            quality = analyze_output(c_code)
            gate = QualityGate()
            json_data = {
                "func_name": name or f"func_{funcva:x}",
                "func_address": f"0x{funcva:x}",
                "num_blocks": len(self.graph.blocks) if self.graph else 0,
                "ssa_rounds": self.ssa_state._rounds if self.ssa_state and hasattr(self.ssa_state, "_rounds") else 0,
                "type_env": {
                    "num_types": len(self.type_env.types) if self.type_env and hasattr(self.type_env, "types") else 0,
                } if self.type_env else {},
                "quality": {
                    "readability": quality.readability,
                    "symbol_resolution": quality.symbol_resolution,
                    "type_accuracy": quality.type_accuracy,
                    "goto_count": quality.goto_count,
                    "max_depth": quality.max_depth,
                    "pass": gate.passes(quality),
                    "failures": gate.check(quality),
                },
            }

            result = DecompOutput(
                text=c_code,
                json=json_data,
                success=True,
            )
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            logger.error(f"Pipeline failed: {result.error}")
            result.text = f"// Error: {result.error}"
            result.json = {"success": False, "error": result.error}

        return result


    def export_graph(self, funcva: int, fmt: str, name: str = "") -> str:
        """Build the CFG for a function and export it (json|svg|dot).

        Independent of the decompile pipeline — only the graph builder runs.
        """
        from dec_engine.dec_impl.export.graph import export_json, export_svg, graph_to_dot

        graph = self.graph_builder.get_graph(funcva, name)
        if fmt == "json":
            return export_json(graph)
        if fmt == "svg":
            return export_svg(graph)
        if fmt == "dot":
            return graph_to_dot(graph)
        raise ValueError(f"Unknown export format: {fmt}")


# ── Convenience function ──

def decompile(binary_path: str, funcva: int, name: str = "") -> str:
    """Quick decompile one function to C code string."""
    decomp = VivisectDecompiler(binary_path)
    out = decomp.decompile_address(funcva, name)
    assert out is not None
    return out.text
