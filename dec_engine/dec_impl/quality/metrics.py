"""Quality metrics for decompiler output (S7).

Scores decompiled C-like output on:
- Readability: structured constructs (if/while/switch) reward, bare ``goto`` and
  unresolved placeholders (``/* ...: flags */``, ``?`)``) penalize.
- Complexity: nesting depth and line count are bounded rewards.
- Symbol resolution: fraction of call targets resolved to names vs raw addresses.
- Type inference: fraction of declared locals whose type is not ``unknown``.

A ``QualityGate`` enforces minimum thresholds for CI regression enforcement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DecompQuality:
    """Aggregated quality metrics for a single decompiled output."""

    readability: float = 0.0          # 0..1
    symbol_resolution: float = 1.0    # 0..1 (% resolved)
    type_accuracy: float = 0.0        # 0..1
    goto_count: int = 0
    unresolved_conds: int = 0
    lines: int = 0
    max_depth: int = 0
    structured_constructs: int = 0    # if/while/switch count


_STRUCTURED_RE = re.compile(r"\b(if|while|for|switch|do)\b")
_GOTO_RE = re.compile(r"\bgoto\b")
_UNRESOLVED_COND_RE = re.compile(r"/\*\s*eflags_|if \(\*\)|/\* ind:")
_RESOLVED_CALL_RE = re.compile(r"(\b\w+)\([^)]*\)\s*;")


class _LineScanner:
    """Compute max nesting depth and line stats."""

    def __init__(self, lines: List[str]):
        self.lines = lines
        self.max_depth = 0
        self.depth = 0
        self.structured = 0
        self.gotos = 0
        self.unresolved = 0
        self.scan()

    def scan(self):
        depth = 0
        for raw in self.lines:
            line = raw.strip()
            opens = line.count("{")
            closes = line.count("}")
            depth += opens - closes
            if depth > self.max_depth:
                self.max_depth = depth
            if _STRUCTURED_RE.search(line):
                self.structured += 1
            if _GOTO_RE.search(line):
                self.gotos += 1
            if _UNRESOLVED_COND_RE.search(line):
                self.unresolved += 1
        self.depth = depth


def analyze_output(text: str) -> DecompQuality:
    """Score a decompiled output string into DecompQuality metrics."""
    lines = [l for l in text.splitlines()
             if l.strip() and not l.strip().startswith("//")]
    if not lines:
        return DecompQuality()

    scanner = _LineScanner(lines)

    # Symbol resolution: fraction of function calls with a resolved name.
    # A call like `sub_4001ab(...)` is unresolved (raw addr); `foo(...)` resolved.
    call_lines = [l for l in lines if "(" in l and ")" in l and ";" in l]
    resolved_calls = 0
    total_calls = len(call_lines)
    for l in call_lines:
        if re.search(r"\b(?:sub|func|plt)_[0-9a-f]{2,}\(", l):
            continue  # unresolved raw target
        resolved_calls += 1
    symbol_resolution = (resolved_calls / total_calls) if total_calls else 1.0

    # Type inference: fraction of local declarations typed, not `unknown`.
    # No declarations -> nothing to type -> treat as fully accurate.
    decl_lines = [l for l in text.splitlines() if re.match(r"^\s*(uint\d+_t|int|char|void|long)\s+\w+\s*;", l)]
    typed_decls = 0
    for l in decl_lines:
        if re.search(r"\bunknown\b", l):
            continue
        typed_decls += 1
    type_accuracy = (typed_decls / len(decl_lines)) if decl_lines else 1.0

    # Readability: reward structured constructs, penalize gotos/unresolved.
    readability = 1.0
    readability -= scanner.gotos * 0.15
    readability -= scanner.unresolved * 0.10
    # Depth penalty above 4
    if scanner.max_depth > 4:
        readability -= (scanner.max_depth - 4) * 0.05
    readability = max(0.0, min(1.0, readability))

    return DecompQuality(
        readability=readability,
        symbol_resolution=symbol_resolution,
        type_accuracy=type_accuracy,
        goto_count=scanner.gotos,
        unresolved_conds=scanner.unresolved,
        lines=len(lines),
        max_depth=scanner.max_depth,
        structured_constructs=scanner.structured,
    )


class QualityGate:
    """Enforce minimum quality thresholds; used for CI regression gates."""

    def __init__(
        self,
        readability: float = 0.5,
        symbol_resolution: float = 0.5,
        type_accuracy: float = 0.3,
    ):
        self.thresholds = {
            "readability": readability,
            "symbol_resolution": symbol_resolution,
            "type_accuracy": type_accuracy,
        }

    def check(self, q: DecompQuality) -> List[str]:
        """Return list of failing metric names; empty list = pass."""
        failures = []
        if q.readability < self.thresholds["readability"]:
            failures.append("readability")
        if q.symbol_resolution < self.thresholds["symbol_resolution"]:
            failures.append("symbol_resolution")
        if q.type_accuracy < self.thresholds["type_accuracy"]:
            failures.append("type_accuracy")
        return failures

    def passes(self, q: DecompQuality) -> bool:
        return not self.check(q)
