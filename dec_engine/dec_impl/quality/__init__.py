"""Quality evaluation & benchmarking for decompiler output.

Provides measurable metrics for decompiled output:
- Readability scoring (based on structured constructs, goto usage, depth)
- Symbol resolution accuracy
- Type inference accuracy
- A quality-gate check that thresholds the metrics for CI enforcement
- A benchmark runner that scores a corpus of function graphs
"""
from dec_engine.dec_impl.quality.metrics import (
    DecompQuality,
    QualityGate,
    analyze_output,
)
from dec_engine.dec_impl.quality.benchmark import (
    CORPUS,
    BenchmarkResult,
    run_benchmark,
    summarize,
)

__all__ = [
    "DecompQuality",
    "QualityGate",
    "analyze_output",
    "CORPUS",
    "BenchmarkResult",
    "run_benchmark",
    "summarize",
]
