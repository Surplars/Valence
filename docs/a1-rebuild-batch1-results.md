# A1 rebuild: first structural checkpoint

Date: 2026-10-24. Baseline source: `47f42fa0d7d5c845053e325928749422de9b350c`.
Status: **bounded functional checks passed; a measured per-case regression is
disclosed; no frequency or board qualification**. The default bootable profiles
have not been promoted to this candidate.

## What changed

- Six existing producer owners can use two completion ports instead of funneling
  LSU/MUL/DIV/SYS through one fixed port. The implementation reuses the existing
  held state; it does not add a result pipeline stage or expand PRF write ports.
- Class-local dispatch admits compatible memory and multiply/divide work within
  the same two-ticket budget. ALU physical lanes are distinct from writeback
  ports; full tokens authorize architectural effects.
- An explicit Common A1 memory profile connects checked virtual-load admission,
  four LSU owners and sixteen DTLB entries. Cache MSHRs, response slots and
  writeback entries remain two each. CPU return ordering and native ABI stay
  unchanged; tagged and posted protocols are not silently enabled.
- A held LSU completion no longer conceals genuinely empty admission slots in
  the new topology. Live-slot turnover still requires that owner's actual
  completion handshake.

## Matched CPU cycle comparison

The existing bare-core NEMU matrix uses the same programs, continuous instruction
supply and memory service law. It is not a complete Common SoC/DDR/Linux model.

| Workload | Baseline cycles | Candidate cycles | Observation |
|---|---:|---:|---|
| 1,024 independent ALU instructions | 515 | 515 | No loss of dual-issue throughput |
| 1,024 dependent ALU instructions | 1,027 | 1,027 | No extra dependency-cycle penalty |
| Two independent dependency chains | 515 | 515 | Unchanged |
| Compiled sum, memory latency 1 | 1,458 | 1,462 | **0.2743% more cycles** |
| Compiled sum, memory latency 12 | 1,848 | 1,848 | Unchanged |

The twelve throughput cases contain eleven equal-cycle results and the one
regression above. All six additional memory cases have equal cycles. The sum
case's regression accompanies one additional branch misprediction and one fewer
forwarded load. A passive trace using the same generated models identifies the
critical arbitration difference: a ready load, an older ALU result and a younger
branch contend; the old fixed lane gives the branch a writeback port, whereas
age-ordered selection holds it for one cycle. Redirect timing, later forwarding
and retirement-time predictor training then differ. Do not average the resulting
four cycles away or label this checkpoint a performance improvement.

The separate decoded-input backend fixture uses actual Selected A1 parameters,
including FP and system state. Its first ten programs retire 742 instructions
and take 2,657 work cycles in both topologies. Inspection cycles are excluded.
It exercises floating-point enabled/disabled behavior, CSR, FENCE.I and recovery,
but it is not fetch/decode/MMU/ISA-compliance qualification. Actual new side-unit
dispatch/completion overlaps occur; some exchange/held-forwarding witnesses did
not fire in this initial matrix and must not be claimed as covered by it.

Three additional deterministic contention programs, run on the same existing
models, subsequently exercise operand exchange (1), held ALU capture (2), held
load capture (1), and simultaneous system/other completion (6). Their matched
baseline/candidate work cycles are 54/53, 71/71 and 88/88. The original ten
programs' results remain unchanged; the thirteen-program total is 2,870/2,869.
That one-cycle improvement in a separate matrix does not cancel the compiled-sum
regression. Multiple simultaneous M-unit cancellation remains unhit in this
fixture and is not claimed as covered.

## Memory and frontend evidence

- Held-completion tests accept three independent requests in three consecutive
  cycles with four LSU slots, and one in one cycle with two slots. Serial MMIO
  and atomic admission remain blocked where required.
- The Combined backend/translation fixture demonstrates four checked physical
  owners and their complete return. Its deliberately delayed responses make it
  an ownership test, not a steady-state bandwidth measurement.
- The two-MSHR cache handles sixteen reverse-order GrantData beats while keeping
  CPU replies ordered and preserving reply credits, dirty data, denied replies
  and probes. Four LSU entries do not mean four external cache misses.
- Nine frontend supply scenarios and four negative controls pass. The same
  128-instruction 32-bit stream requires 580 work cycles from ROM and 332 from
  RAM in that supply fixture. This compares memory placement in the current
  frontend, **not old versus newly pipelined frontend performance**. Demand
  outstanding remains one. The fixture retains the actual translation chain
  but reduces the I-cache from 512 to 8 lines; it is not core IPC.

## Verification and remaining gates

The batch compiled once after its Scala inputs were frozen. Eight focused
configuration tests passed, and the complete Combined A1 tile was lowered to
SystemVerilog. Static and park-enabled structure checks confirm the selected
LSU/DTLB capacities and ownership connections. Neither elaboration nor structure
inspection demonstrates runtime CDC behavior.

The functional runs include NEMU checks, deliberate incorrect-result controls,
memory cancellation/permission cases, and frontend fault/redirect/backpressure
oracles. Local evidence entry points are:

- `build/a1-candidate-20261024-r1/batch-receipt.json`
- `build/a1-candidate-20261024-r1/stage-comparison.csv`
- `build/gsim/a1-memory-parallel-20261024-r2/receipt.json`
- `build/gsim/a1-fetch-supply-20261024-r1/receipt.json`

These generated paths identify reproducible run outputs, not tracked build
binaries. Subsequent targeted witnesses/diagnostics retain the first matrix
rather than rewriting its observed counters.

No source-matched synthesis, placement/routing, new bitstream, full SoC runtime,
Linux boot or board performance result exists for this candidate. **300 MHz
remains the required design target, not a result.** Each subsequent module/stage
must retain a matched continuous-supply end-to-end cycle comparison, followed by
dependencies, misses, stalls and recovery checks.
