# viv-decomp — Project State (S1–S7 COMPLETE)

Handoff doc for resuming work on the decompiler. Last updated after S7 benchmark
suite. Phases S1–S7 are done and merged; PR#8 (benchmark) is open.

## Active branch & git state
- **Current branch:** `s7-benchmark` (last work: benchmark suite)
- Test suite: **382/382 passing**
- PR#8 (open): S7 benchmark suite

## Branch map / PRs
| Branch | Contents | PR |
|--------|----------|----|
| `phase0-ir-layer` | IR + symbolik layer | #1 merged |
| `phase2-control-flow` | S2 loop reconstruction + S3 graph-aware type inference | #3 merged |
| `s4-memory-model` | S4 memory: stack-frame + call graph | #4 merged |
| `s5-multi-arch` | S5 arch selection | #5 merged |
| `s5-extended-arch` | S5 ext: arm/mips/ppc + --arch CLI | #7 merged |
| `s7-quality-gate` | S7 quality metrics + gate | #6 merged |
| `s7-benchmark` | S7 benchmark suite | **#8 open** |

## What's done (S1–S7)
- **S0/S1** IR layer, builder, formatter, SSA (merged).
- **S2** Structured control flow: `while(cond){body}` reconstruction in `PrettyPrinter`.
  Fixed a real idom bug (min→max) that blocked loop-header detection.
- **S3** `TypeAnalyzer.analyze_graph()` — graph-aware type propagation over the CFG.
- **S4** `dec_engine/dec_impl/memory/` — `StackFrameAnalyzer` (prologue frame size,
  `[rbp ± offset]` local bucketing) + `CallGraphBuilder` (caller→callee edges).
- **S5** `dec_engine/dec_impl/arch/` — `ArchSelector` maps arch → Vivisect symbolik
  context (amd64/i386 + arm/mips/ppc recognition), auto-detect + `--arch` override.
- **S7** `dec_engine/dec_impl/quality/` — `analyze_output()` (readability, symbol
  resolution, type accuracy), `QualityGate` thresholds, and a benchmark runner over
  a synthetic corpus (loop, diamond, call). CI-usable `run_benchmark.py`.

## Key files
- `dec_engine/dec_impl/output/pretty.py` — structured CFG walker + loop/if-else emission
- `dec_engine/dec_impl/structuring/domtree.py` — Cooper's iterative dominators + back-edges
- `dec_engine/dec_impl/type_inference/analyze.py` — TypeAnalyzer + analyze_graph()
- `dec_engine/dec_impl/memory/stack.py` — StackFrameAnalyzer
- `dec_engine/dec_impl/memory/callgraph.py` — CallGraphBuilder
- `dec_engine/dec_impl/arch/selector.py` — ArchSelector
- `dec_engine/dec_impl/quality/metrics.py`, `quality/benchmark.py` — quality + benchmark
- `viv_decomp/decompiler.py` — pipeline orchestration

## Known quirk (IMPORTANT)
Vivisect's ELF `analyzePLT` raises `Invalid File: None` and aborts real-binary graph
extraction (`/bin/ls`, `/usr/bin/yes`). Benign but prevents validating against real
binaries through the current loader. **Workaround:** validate via synthetic graphs
(see tests/benchmarks). Real-binary validation needs a Vivisect version fix or
workspace-level fallback.

## IR MemRef shapes (for the stack analyzer)
1. `MemRef(base=Var('rbp'|'rsp'), offset=Const(signed), size=...)` — Vivisect style
2. `MemRef(base=BinOp(SUB/ADD, Var(base), Const(k)), offset=Const(0), size=...)` — IR style
`_frame_offset()` in `stack.py` converts both to `(base_reg, signed_offset)`.

## Pipeline entry points
- `VivisectDecompiler.decompile_address(funcva, name)` → `DecompOutput` (includes `quality` verdict)
- `TypeAnalyzer().analyze_graph(graph)` → `TypeEnvironment`
- `StackFrameAnalyzer().analyze(graph)` → `List[StackVariable]`
- `CallGraphBuilder().build(funcs)` → `CallGraph`
- `run_benchmark(gate)` → `List[BenchmarkResult]`; `python tests/benchmarks/run_benchmark.py`

## Remaining phases
- **S6** Qt graph viewer GUI (P3, nice-to-have) — not started.
- **S8** ML/LLVM roadmap — not started.
- Benchmark on real binaries — blocked by Vivisect quirk.

## GitHub workflow convention
Fork → apply to fork branch → PR against upstream `atlas0fd00m/viv-decomp`.
gh CLI unauthenticated: use curl + GITHUB_TOKEN. PR `--head` must be
`<fork-owner>:<branch>`.
