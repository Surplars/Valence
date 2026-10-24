# A1 dual-owner completion and dispatch contract

This is the first backend structural batch on `47f42fa`, not a 300 MHz timing
qualification. Select it explicitly with `completionTopology = "dual-owner"`.
The default `legacy` topology and the saved `FpgaNextConfig.Selected` remain
unchanged. The accepted configuration domain is checked in `OooParams`.

## Boundaries, capacity and service

- `DualCompletionSelector`: six producer offers, two one-hot owner masks, zero
  storage, zero added cycles, at most two distinct ROB owners per cycle. Only
  registered presence and ROB slot age enter ranking. Both ranks are computed
  independently. Wide payload selection follows the owner decision.
- Physical ALU operand holders: two existing `IssueExecuteStage` instances,
  capacity one each, no empty bypass, minimum one cycle, II one each when granted
  output credit. A consumed old owner can be replaced on the same edge. Cancel
  does not create combinational input credit. This batch adds no result register.
- MUL: existing eight reserved result slots, nonstalling arithmetic, II one until
  reservation capacity is exhausted. The existing registered-operand option adds
  one cycle to the documented two/six-cycle arithmetic. Writeback contention
  retains the local result owner; no arithmetic result may overwrite a reservation.
- DIV: existing single reservation, registered operands, iterative 32/64-bit
  divide, held `done` result. This batch does not improve divider latency or II.
- LSU: existing two slots in the baseline, four in the separate memory candidate.
  Each slot retains a result and full token. The existing internal arbiter offers
  at most one LSU result per cycle to the six-producer selector. A global held
  LSU output is not an irrevocable transaction: the sampled owner/data pair is
  authoritative. Empty capacity is not hidden by an ungranted completed slot.
- SYS/FP: existing protected ROB-head command with a held system completion.
  CSR minimum completion latency remains two cycles; FP/flush/IMSIC service is
  variable. The memory-drain/head-only serialization is unchanged.
- ROB and PRF: exactly two completion ports and two integer PRF write ports.
  Selected full-token completions must pass existing liveness, generation,
  exception and recovery authorization before any wakeup/write/retirement.

## Related changes in this batch

1. Replace fixed side-result priority on writeback lane 0 with six-source,
   age-ordered, distinct-owner selection across both existing ports.
2. Keep full completion payload selection separate from narrow owner selection.
3. Return accepted-completion credit to the actual DIV/MUL/SYS producer, not a
   historical lane number.
4. Give LSU an early output credit computed only from registered owner metadata.
5. Use that credit consistently for LSU strict/candidate/ordinary empty-slot and
   turnover capacity. Never use late ROB acceptance or kill to choose a new slot.
6. Route ALU drain authorization by physical producer identity, independently of
   the selected writeback port.
7. Carry same-cycle retirement class and fault with the selected producer.
8. Keep branch resolution, saved branch result and executing operands in physical
   ALU-lane coordinates, not writeback-lane coordinates.
9. Permit one memory and one MUL/DIV launch on the same edge, consuming both
   dispatch tickets. SYS remains mutually exclusive with these side launches.
10. Bound ordinary ALU/store-preparation rank grants by the remaining tickets.
11. Exchange the two already-read operand packets at the local execution input
    when the oldest ALU's default holder is blocked and the other is available.
    No functional-unit credit chooses a new ROB rank or PRF read address.
12. Preserve both held ordinary-ALU data promises independently of writeback
    credit, so an output collision does not silently add a dependency bubble.
13. Allow a successful retained LSU result to supply operands before its granted
    writeback, preserving full owner and current-capture kill checks.
14. Count actual dispatches separately from completions. Assert at most two
    accepted dispatch tickets and no same-owner duplicate across execution classes.
15. Witness every raw producer offer against the independent full issue-entry
    token and live ROB window, before index reuse can hide an old generation.
16. Change the throughput fixture's load-publication witness from fixed lane 0 to
    either accepted writeback with the exact LSU full token.

One conservative mapping remains: if the oldest rank is store preparation and
ALU0 is blocked while ALU1 is empty, the second-ranked ALU is not yet exchanged.
This is a missed opportunity, not permission to consume a third ticket.

## Directed verification and measurement

`simulator/gsim/a1_dual_completion.py` uses the prebuilt pinned toolchain. It never
installs a simulator, invokes Verilator, performs synthesis, or runs Linux.

- Selector phase: an independent software walk through circular ROB age checks
  all presence masks and heads across deterministic owner layouts, including
  duplicates, wrap and wide-payload selection. A deliberate oracle mutation must
  fail. This does not by itself prove generation safety or executing-CPU behavior.
- Backend phase: one legacy and one candidate model use the actual
  `CommonCpuProfile.A1.fpga.coreParams`, including F/D, Sv39/PMP hardware and full
  tag widths. The stimulus boundary is decoded instructions with continuous
  offers, not a frontend/cache/TLB system. Bare memory service and commit/request
  backpressure follow the same deterministic law for both models.
- The precomputed architectural interpreter never follows DUT register values or
  redirects. Separate memory copies check architectural stores, accepted device
  writes and final memory. Commit token uniqueness, final integer registers,
  precise traps, response conservation and bounded owner drain are checked.
- Ten bounded programs cover independent/dependent ALU, MUL/DIV/load contention,
  subword stores/loads, branches and reuse, CSR/FENCE.I, signed divide edges,
  FS-Off illegal FP, and exact binary64 moves plus `1.5 + 1.5`. This is not broad
  F/D or RV64GC qualification. Non-GPR-writing completion data is unspecified and
  not compared as architectural state.
- Report hardware cycles separately from final register inspection and host
  runtime. Record side-unit concurrent starts/completions, local packet exchange,
  captured held-value forwarding, pending replies at redirect and cancellation.
  Passive counters establish coverage only when their measured values are nonzero.
- The existing short NEMU throughput/load/recovery matrix independently checks
  the bare core. Its older fixed-lane structural witnesses must not be confused
  with an architectural mismatch if the new topology removes that old collision.

Source/configuration/artifact hashes and deliberate-negative results are recorded
in each fresh receipt. Pure elaboration is not an execution or timing result.

### First measured batch, 2026-10-24

- Independent selector: 98,304 cases and the deliberate negative passed; receipt
  `build/gsim/a1-dual-selector-20261024-r1/receipt.json`.
- Real A1 decoded backend: both topologies passed all ten programs, 742 retired
  instructions each, precise terminal traps, final state and negatives. Every
  matched program took the same cycles, total 2,657, plus 320 separately counted
  inspection cycles. Receipt:
  `build/gsim/a1-dual-backend-20261024-r1/receipt.json`.
- The candidate exercised 11 memory-plus-M starts and seven simultaneous side
  completions. The legacy had zero of each. These are structural utilization
  improvements, **not a measured end-to-end speedup** in this workload.
- Operand exchange, captured held-value forwarding, SYS-plus-other completion
  and multi-owner M cancellation were all zero in that first backend batch.
  Consequently it does not establish those directed coverage points. Additional
  bounded host-only contention cases below use the same immutable models.
- Existing short NEMU throughput: eleven of twelve cases had unchanged cycles.
  `compiled_sum`, RAM latency one, regressed from 1,458 to 1,462 cycles (+0.2743%).
  Its conditional-branch mispredictions increased six to seven, forwarded loads
  decreased 127 to 126, and external reads increased 70 to 71. These aggregate
  facts alone do not establish causality; the passive trace below diagnoses the
  scheduling difference. Latency 12 remained 1,848 cycles. The six memory cases
  were unchanged.
- The important continuously supplied ALU guards stayed exact: independent and
  dual-chain 1,024 instructions in 515 cycles, single-chain 1,024 in 1,027.

The optional candidate stays separate from the selected baseline. Neither the
functional passes nor the concurrent side events qualify a performance win or
the 300 MHz goal.

### Fixed contention supplement, same generated models

Three additional programs use legal external response timing and continuous
instruction offers. They do not inject internal owners or change the DUT or
architectural oracle. The first fixed schedules hit their coverage targets;
there was no phase search or additional elaboration.

- `held_load_contention`: legacy 54 cycles, candidate 53, nine retired. Candidate
  captures a retained load value once and a retained ALU promise once.
- `held_alu_exchange`, fixed response phase eight: both 71 cycles, 26 retired.
  Candidate captures one exchanged operand packet and one retained ALU promise,
  with one dual-side completion collision.
- `system_alu_collision`: both 88 cycles, 82 retired, with six SYS-plus-other
  completion events on each topology. SYS still uses its original head-only
  command policy; this proves result collision handling, not out-of-order FP.

Both topologies pass all thirteen programs, 859 retired each, final GPRs/memory,
precise traps, and deliberate data-oracle negatives under ASan/UBSan. Candidate
totals are one exchange, two held-ALU captures, one held-load capture and six SYS
collisions. Every original-ten JSON metric is unchanged. The thirteen-case total
is 2,870 versus 2,869 cycles; the one-cycle gain in a focused collision is not a
general throughput gain and does not cancel the separate four-cycle regression.
Multi-owner M cancellation remains unexercised.

Supplement receipt: `../a1-host-contention/receipt.json` relative to the repository
root (a sibling workspace artifact directory). The original ten-program harness is separately archived there
as `original-ten-a1_dual_backend.cpp`, SHA-256
`6fe19fdfbc45783c84c2414ac0d02759e2fb7678217b4e2da151c263f90fdc13`.
The final thirteen-program harness SHA-256 is
`7206ae75050ef910ec69f2e0741a4f81b3922eac2092970311602186c3d65b39`.
Original model files, logs and receipts were not overwritten.

### Passive diagnosis of the four-cycle regression

`build/a1-dual-trace-r1/receipt.json` and `analysis.json` reuse the two already
generated models. Only a diagnostic host harness was compiled; no RTL,
elaboration, guest instruction, initial memory or service law changed. The
single `compiled_sum`/latency-one execution reproduced **every original IPC
counter exactly** and retained the original independent ISA/NEMU checking.
Trace cycle numbers below start at zero.

1. The first difference, cycle 11, is beneficial: a store completion no longer
   monopolizes the fixed ALU0 writeback path. ALU0 obtains credit, and the candidate
   dispatches two operations instead of one. This transient difference converges.
2. At cycle 38 there are three ready results: LSU tag 23, physical ALU0 tag 35
   (`0x80000090`, `addi s2,s2,8`) and physical ALU1 tag 36 (`0x80000094`, branch).
   Legacy chooses LSU plus ALU1; age-ordered dual-owner chooses LSU plus the older
   ALU0. The branch remains held for one cycle, so its registered redirect moves
   from cycle 39 to 40. There is no added ALU dependency pipeline stage.
3. This changes the memory/start phase: the first `fold` load at `0x80000044`
   starts at cycle 43 in both runs, but the old run forwards from the store whereas
   the candidate performs a RAM read. Its retirement moves from cycle 45 to 46.
   The main first-loop steady state thereafter remains one cycle behind, not one
   extra cycle per iteration.
4. Near the second loop, retirement and the registered predictor-training packet
   shift again. Its first `0x800000ac` retirement is cycle 1258 versus 1260; the
   direction counter first reaches taken at cycle 1260 versus 1262. The candidate
   has already fetched another not-taken-predicted iteration, producing the extra
   redirect at cycle 1264. Baseline warmup redirects are 1241/1251/1257; candidate
   warmup redirects are 1242/1251/1258/1264. Loop-exit redirects are 1440/1444.
5. From architectural retirement ordinal 1066 through completion the candidate is
   four cycles behind. Both execute the same 1,310 architectural instructions and
   have identical single/dual retirement counts. This is a real whole-path cost
   of the changed completion order, not host trace overhead or an ISA mismatch.

Do not erase this checkpoint by tuning global priority to this one workload. A
separate next-stage option is to extract the existing registered branch-resolution
mailbox and let a held branch resolve independently of writeback credit. That
requires per-owner capture-once state, full-token/kill rules, and testing redirect
before branch completion; it is **not implemented in this checkpoint**. Merely
changing `newResolutions.valid` would risk duplicate redirects and deadlock.

## Next-stage acceptance rule

For subsequent scheduler, PRF and retirement separation, add one clear module or
pipeline boundary at a time within a coherent batch. Specify its latency, II,
queue capacity, owner lifetime, credit and backpressure first. Measure the whole
path under continuous supply, then dependencies, congestion and recovery using
matched streams. A local timing improvement cannot conceal total-cycle or IPC
regression. The current batch's six-way comparison and two wide result muxes are
new timing risks; a source-matched routed report is still required for 300 MHz.
