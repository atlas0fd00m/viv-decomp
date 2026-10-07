"""Quality evaluation & benchmarking for decompiler output.

Provides measurable metrics for decompiled output:
- Readability scoring (based on structured constructs, goto usage, depth)
- Symbol resolution accuracy
- Type inference accuracy
- A quality-gate check that thresholds the metrics for CI enforcement
"""
from dec_engine.dec_impl.quality.metrics import (
    DecompQuality,
    QualityGate,
    analyze_output,
)

__all__ = ["DecompQuality", "QualityGate", "analyze_output"]
