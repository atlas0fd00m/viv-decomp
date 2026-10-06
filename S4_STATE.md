# viv-decomp — Project State (S4)

Handoff doc for resuming work on the decompiler. Last updated after S4 stack-frame
analysis was committed to branch `s4-memory-model`.

## Active branch & git state
- **Current branch:** `s4-memory-model` (pushed to origin fork `percys-team-337/viv-decomp`)
- Latest commit: `a137a5c` "S4: stack-frame analysis in memory model"
- PR #3 (open, from `phase2-control-flow`): S2 loop reconstruction + S3 graph-aware type inference
- Test suite: **333/333 passing**

## Branch map
| Branch | Contents | PR status |
|--------|----------|-----------|
| `main` | merged baseline (S0/S1 + dominator) | — |
| `phase0-ir-layer` | IR + symbolik layer | PR#1 merged |
| `phase2-control-flow` | S2 loop reconstruction + S3 type inference | **PR#3 open** |
| `s4-memory-model` | S4 stack-frame analyzer | new, no PR yet |

## What's done
- **S0/S1** IR layer, builder, formatter, SSA (merged).
- **S2** Structured control flow: dominator computation, natural-loop detection,
  `while(cond){body}` reconstruction in `PrettyPrinter`. Fixed a real idom bug
  (min→max) that blocked loop-header detection.
- **S3** `TypeAnalyzer.analyze_graph()` — graph-aware type propagation over the CFG.
  Wired into `decompiler.py` so the type engine consumes the real graph.
- **S4** `dec_engine/dec_impl/memory/` — `StackFrameAnalyzer` detects prologue frame
  size and buckets `[rbp ± offset]` / `[rsp ± offset]` MemRefs into typed locals.
  Handles both Vivisect signed-Const and IR BinOp-base MemRef shapes.

## Key files
- `dec_engine/dec_impl/output/pretty.py` — structured CFG walker + loop/if-else emission
- `dec_engine/dec_impl/structuring/domtree.py` — Cooper's iterative dominators + back-edges
- `dec_engine/dec_impl/type_inference/analyze.py` — TypeAnalyzer + analyze_graph()
- `dec_engine/dec_impl/memory/stack.py` — StackFrameAnalyzer (S4)
- `dec_engine/dec_impl/ir/expression.py`, `ir/effects.py` — IR node shapes
- `viv_decomp/decompiler.py` — pipeline orchestration

## Known quirk (IMPORTANT)
Vivisect's ELF `analyzePLT` raises `Invalid File: None` and aborts real-binary graph
extraction (`/bin/ls`, `/usr/bin/yes`). This is benign but prevents validating the
decompiler against real binaries through the current loader. **Workaround:** validate
decompiler logic via synthetic graphs (see tests). Real-binary validation may need a
Vivisect version fix or workspace-level fallback.

## IR MemRef shapes (for the stack analyzer)
1. `MemRef(base=Var('rbp'|'rsp'), offset=Const(signed), size=...)` — Vivisect style
2. `MemRef(base=BinOp(SUB/ADD, Var(base), Const(k)), offset=Const(0), size=...)` — IR style
`_frame_offset()` in `stack.py` converts both to `(base_reg, signed_offset)`.

## Next steps (S4 remainder)
- **Call-graph construction** — build module-level call graph from `Call` callees
  (partial in `_resolve_call_target`).
- Heap analysis (`malloc`/`free` patterns), global-symbol typing.
- **Benchmark suite / CI** (S7) — compile-recompile fidelity gate.

## Pipeline entry points
- `VivisectDecompiler.decompile_address(funcva, name)` → `DecompOutput`
- `TypeAnalyzer().analyze_graph(graph)` → `TypeEnvironment`
- `StackFrameAnalyzer().analyze(graph)` → `List[StackVariable]`

## GitHub workflow convention
Fork → apply to fork branch → PR against upstream `atlas0fd00m/viv-decomp`.
gh CLI unauthenticated: use curl + GITHUB_TOKEN. PR `--head` must be
`<fork-owner>:<branch>`.
