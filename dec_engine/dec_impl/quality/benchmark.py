"""Benchmark suite for decompiler quality (S7).

Runs a corpus of synthetic function graphs through the full pipeline
(graph → SSA → type inference → structured output → quality metrics) and
scores each one. The runner can be used as a CI quality gate: any case whose
score falls below thresholds is reported as a regression.

The corpus uses synthetic graphs because the Vivisect ELF loader's
``analyzePLT`` crash prevents real-binary graph extraction in this env (see
project state doc). Synthetic graphs still exercise the full pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
from dec_engine.dec_impl.ir.expression import Var, Const, BinOp, OpType, Size
from dec_engine.dec_impl.ir.effects import Assignment, Branch, Call
from dec_engine.dec_impl.ssa.construct import SsaState, SsaTransform
from dec_engine.dec_impl.type_inference.analyze import TypeAnalyzer
from dec_engine.dec_impl.output.pretty import PrettyPrinter
from dec_engine.dec_impl.quality.metrics import DecompQuality, QualityGate, analyze_output


@dataclass
class BenchmarkResult:
    """Score for a single benchmark case."""

    name: str
    quality: DecompQuality
    passed: bool
    failures: List[str] = field(default_factory=list)
    output: str = ""


def _make_loop_graph():
    """A counting loop: entry -> header(i<10) -> body(i++) -> back; exit."""
    entry = BasicBlock(addr=0x1000, is_entry=True)
    header = BasicBlock(addr=0x2000)
    body = BasicBlock(addr=0x3000)
    exitb = BasicBlock(addr=0x4000)
    vi = Var("i", Size.SIZE_32)
    entry.instructions = [Assignment(destination=vi, source=Const(0, Size.SIZE_32))]
    cond = BinOp(OpType.LT, vi, Const(10))
    header.instructions = [Branch(condition=cond, true_target=body, false_target=exitb)]
    inc = BinOp(OpType.ADD, vi, Const(1))
    body.instructions = [Assignment(destination=vi, source=inc)]
    body.instructions.append(Branch(condition=None, true_target=header))
    entry.successors = [header]
    header.successors = [body, exitb]
    body.successors = [header]
    entry.predecessors = []
    header.predecessors = [entry, body]
    body.predecessors = [header]
    exitb.predecessors = [header]
    return BlockGraph(entry_block=entry,
                      blocks={0x1000: entry, 0x2000: header, 0x3000: body, 0x4000: exitb})


def _make_if_else_graph():
    """A diamond (if/else merge) graph."""
    entry = BasicBlock(addr=0x1000, is_entry=True)
    thenb = BasicBlock(addr=0x2000)
    elseb = BasicBlock(addr=0x3000)
    merge = BasicBlock(addr=0x4000)
    vi = Var("x", Size.SIZE_32)
    entry.instructions = [Assignment(destination=vi, source=Const(1, Size.SIZE_32))]
    cond = BinOp(OpType.EQ, vi, Const(0))
    entry.instructions.append(Branch(condition=cond, true_target=thenb, false_target=elseb))
    thenb.instructions = [Assignment(destination=vi, source=Const(2, Size.SIZE_32))]
    thenb.instructions.append(Branch(condition=None, true_target=merge))
    elseb.instructions = [Assignment(destination=vi, source=Const(3, Size.SIZE_32))]
    elseb.instructions.append(Branch(condition=None, true_target=merge))
    entry.successors = [thenb, elseb]
    thenb.successors = [merge]
    elseb.successors = [merge]
    merge.successors = []
    # predecessors (diamond merge has both then/else as preds)
    entry.predecessors = []
    thenb.predecessors = [entry]
    elseb.predecessors = [entry]
    merge.predecessors = [thenb, elseb]
    return BlockGraph(entry_block=entry,
                      blocks={0x1000: entry, 0x2000: thenb, 0x3000: elseb, 0x4000: merge})


def _make_call_graph():
    """Single block with a resolved-address call."""
    entry = BasicBlock(addr=0x1000, is_entry=True)
    entry.instructions = [Call(callee=Var("printf", Size.SIZE_64), args=[])]
    return BlockGraph(entry_block=entry,
                      blocks={0x1000: entry})


# Corpus: name -> graph builder. Expected to produce structured, readable output.
CORPUS: Dict[str, Callable[[], BlockGraph]] = {
    "loop": _make_loop_graph,
    "if_else": _make_if_else_graph,
    "call": _make_call_graph,
}


def _full_pipeline(graph: BlockGraph) -> str:
    """Run graph -> (SSA) -> types -> structured output."""
    graph = SsaTransform(graph).analyze_graph()
    TypeAnalyzer().analyze_graph(graph)
    pp = PrettyPrinter(graph.name or "bench", graph, SsaState())
    return pp.generate()


def run_benchmark(gate: Optional[QualityGate] = None) -> List[BenchmarkResult]:
    """Run every corpus case through the pipeline and score it."""
    gate = gate or QualityGate()
    results: List[BenchmarkResult] = []
    for name, builder in CORPUS.items():
        graph = builder()
        graph.name = name
        output_text = _full_pipeline(graph)
        q = analyze_output(output_text)
        results.append(BenchmarkResult(
            name=name,
            quality=q,
            passed=gate.passes(q),
            failures=gate.check(q),
            output=output_text,
        ))
    return results


def summarize(results: List[BenchmarkResult]) -> str:
    """Human-readable report of benchmark results."""
    lines = []
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        q = r.quality
        lines.append(
            f"[{status}] {r.name}: "
            f"read={q.readability:.2f} sym={q.symbol_resolution:.2f} "
            f"type={q.type_accuracy:.2f} gotos={q.goto_count} "
            f"failures={','.join(r.failures) or '-'}"
        )
    passed_all = all(r.passed for r in results)
    lines.append(f"\nPassed {sum(r.passed for r in results)}/{len(results)} cases")
    return "\n".join(lines)
