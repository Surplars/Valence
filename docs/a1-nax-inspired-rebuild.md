# A1 microarchitecture rebuild

## Scope and acceptance contract

This development line starts at Valence `47f42fa0d7d5c845053e325928749422de9b350c`.
It preserves the existing bootable profiles and develops an explicitly selected
A1 candidate, rather than silently changing `FpgaNextConfig.Selected`.

The CPU target is **at least 300 MHz** on the actual target FPGA. This is a design
requirement, **not an achieved frequency**. Acceptance requires source-matched
post-route setup, hold, recovery/removal and clock-domain checks. Neither changing
clock metadata, weakening constraints, simulation, nor a synthesis estimate meets
that requirement. Shared-fabric clocks and capacity must be reported separately.

The existing routed board evidence identifies the device as
**`xczu15eg-ffvb1156-2-i`**, speed grade **-2**, with Vivado **2025.2**. This was
verified from the archived exact-125 MHz DRC report and its binding to the R39
boot bit (`6ef3931799c7a746dd14e71162456d9759a264f548e7a13fb209b85db83ecf73`).
It is an existing I1/platform reference, **not an A1 timing result**. Do not use
historical Artix/Kintex assumptions or NaxRiscv results on another device as this
candidate's frequency qualification. The new CPU period target is approximately
3.333 ns; the actual implementation must use the exact device/package/speed grade.

The first candidate remains two-wide: rename, dispatch budget, completion and
retirement must each have explicit capacity contracts. A faster clock obtained by
unnecessarily serializing work is not a successful performance result.

## Frozen baseline

The baseline is `CommonCpuProfile.A1` / `CommonA1CpuTile`, derived from
`FpgaNextConfig.Selected` with the common-platform line-grant capability. It is
not the default `OooParams` instance or a different FPGA-next experiment:

- Two-wide backend; ROB 16, physical integer registers 48, LSU owners 2, store
  buffer entries 2.
- Private data-cache read MSHRs 2, response entries 2 and writeback entries 2.
- Registered execution boundary and owner-local ready tracking already exist.
- Common A1 excludes tagged-return and posted-proof experiments in its current
  extraction contract. Removing these guards alone is not an implementation.
- The ordinary Sv39 load path lacks the virtual RAM precheck needed for safe
  non-head speculative admission. Nominal queue depth is therefore not evidence
  of effective memory-level parallelism.

## First coherent structural batch

1. Give execution-result producers explicit local ownership and backpressure;
   select up to two distinct live results for the existing ROB/PRF write ports.
2. Replace fixed lane reservation with a bounded two-ticket dispatch policy so
   compatible independent execution units need not exclude one another.
3. Preserve accepted-operand/data-promise semantics. Do not introduce speculative
   wakeup merely because an instruction was selected; a stalled producer is not
   a fixed-latency producer.
4. Form an explicit A1 memory candidate with checked virtual-load eligibility,
   translation and response ownership. Preserve non-speculative MMIO, precise
   faults, ordered stores, AMO/LR-SC and DMA coherence.
5. Audit frontend demand ownership before adding outstanding requests. A token
   must identify address, fault, epoch and destination through redirect/cancel;
   increasing a counter is insufficient.

Implementation and review must distinguish completed integration from independent
components, proposed work and unverified physical results.

Detailed contracts and reference mapping:

- [Fixed-source NaxRiscv study](naxriscv-a1-microarchitecture-study.md)
- [Dual-owner backend batch](a1-dual-owner-backend.md)
- [Independent backend source review](a1-dual-owner-independent-review.md)
- [Frontend supply audit](a1-frontend-supply-audit.md)

The four explicit tile controls are `baseline`, `backend`, `memory` and
`combined` in `CommonA1RebuildProfile`. They support attributable comparisons;
the new tile emitter is not a whole-SoC bitstream replacement. The legacy board
factory rejects the new completion topology rather than silently ignoring it.

## Measurement and correctness gates

The user's explicit refinement on 2026-10-24 is to separate the modules and
evaluate **overall throughput and performance after each added pipeline stage**,
with continuous supply as the starting condition. This is a stage-level matched
integration check, not a full regression after every source edit. Each boundary
must document latency, initiation interval, storage capacity, credit ownership
and backpressure. First measure steady-state continuous-supply throughput, then
dependencies, misses, recovery and congestion. Local timing improvement cannot
hide an end-to-end cycle regression.

Use the same instruction streams, memory service law, clock ratios and cache
initial conditions for baseline/candidate comparisons. Record source/configuration
hashes, accepted operations, cycles, retired instructions and correctness results.

- Backend: independent ALU work, dependent ALU chains, mixed ALU/MUL/DIV/load
  contention, completion collisions, bounded starvation and downstream stalls.
- Memory: independent loads, dependent pointer chasing, load/store aliasing,
  faults, MMIO, response stalls and stale-token rejection.
- Recovery: redirects, precise traps, owner reuse, simultaneous completion/kill,
  and quiesce with live execution/cache/translation owners.
- System: preserve the separate A1 DMA/probe, LR/SC, interrupt and runtime-park
  contracts. A component ledger is not a Linux or board qualification.
- Utilization: report accepted requests/beat duty and stall reasons at each
  credit boundary; traffic generated or presented but not accepted is not useful
  bandwidth. Report payload throughput separately from bus beats.

Follow the repository's short affected-test workflow. Do not run Verilator, broad
regressions, long Linux simulations or repeated physical implementations by
default. Batch related changes, compile once when the batch is ready, and reuse
models/checkpoints. Explicitly report unavailable physical validation.

## External reference

Study the official [NaxRiscv source](https://github.com/SpinalHDL/NaxRiscv/tree/9f452d50560d02fb391bc8039f5453c54e0911af)
at fixed commit `9f452d50560d02fb391bc8039f5453c54e0911af`. Reference mechanisms,
not unsupported cross-device frequency claims. Check file licensing before any
source reuse and retain required attribution. Detailed source mapping and
implementation findings are recorded separately as the audit progresses.

## Current qualification

This document establishes the rebuild contract. It does **not** certify a new
executing CPU, 300 MHz timing closure, performance improvement, or board readiness.
