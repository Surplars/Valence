# Two zero-cycle cleanups and the final50 entry

The candidate extends commit `611ab7a602d66aaa5435a9f2a4699e31146e65be` (tree `fe71cf8ee6083503a518314de9dba567d259c007`). Qualified source tree: `b2dfb60cfb55f227d2860160c42c841e57bf8610`. Publication preserves every qualified production hardware byte.

`directRegisteredExecutionOperands` removes four 64-bit operand selections inside the registered execution boundary. `localPayloadWriteEnable` localizes the continued payload event to upper bridge banks 1–7. Both generic options default to false. No new pipeline cycles, PRF ports, state, payload banks, owners or capacities are introduced.

## Previously recorded qualification

Independent component gates passed before a full 239-module native comparison. Only `IntegerBackend.sv` and `TileLinkAxi4BurstBridge.sv` changed; all module ports and declared state remained identical. The actual board used four bridge slots, two write credits, max burst 16, base 0x80200000 and a 2 GiB window. Constructor counts were 157 core, 68 profile, 8 DDR and 22 cache fields.

One fresh 36-translation-unit sanitized CPU model was compiled serially. No OFF model was rebuilt. The same host, guest, oracle and independent DDR service law were retained.

- Sv39: 191618 inclusive cycles; Bare: 194153
- All 105 captured fields and 12 result sections, including raw AXI/supply records, matched the qualified baseline exactly
- Inclusive, ROI and tail deltas were zero
- Original read, memory and trap controls rejected as required
- The same 36 CPU objects passed the original short NEMU inputs: hot 1847 cycles and compressed 958 cycles
- Original PC/GPR/memory controls rejected; no DUT regeneration, object compilation, reference build or reference resynchronization occurred during NEMU reuse

These are recorded full-qualification results. The public receipt pins their source/configuration and references complete external evidence by hash. The local checker does not reproduce the hardware results or claim that external bundles were downloaded or revalidated. Original failures remain summarized and hash-bound; complete logs and inventories are retained externally.

## Current source-only checks

`python3 fpga/next/board_final.py --output <directory>` validates source and configuration without producing hardware. Its `--emit` option separately invokes the existing native export path. The selected CPU vector is exact original48 plus `--direct-registered-execution-operands` and `--local-payload-write-enable`, in that order. MAC T1 is a separate physical option, giving 51 board options including T1. Tri-speed media and JTAG USER2 remain explicit.

`python3 simulator/gsim/zero_cycle_cleanup/check_retained.py` checks the minimal public receipt, necessary source fingerprints, aggregate production-source closure, exact option extension and live Python product preflight. Its mutation tests reject drift in receipt identity/schema, source fingerprints, recorded result scope, options, external hashes and unsafe paths. Final-entry/Tcl tests use mock emitters and a `synth_design` mock.

No actual synthesis consumer, mapped LUT/resource measurement, STA, implementation, PHY or board execution was run for publication. Physical qualification and routed timing remain unmeasured. COPY/NEMU is same-profile non-regression and adds no MAC/network concurrency qualification. Paired simulator initial storage is an experimental comparison condition, not hardware reset-state proof.

## Exact48 rollback

Restore the complete source at `611ab7a602d66aaa5435a9f2a4699e31146e65be`, then use that commit's original `fpga/next/board_final.py`. The earlier 156/66-field audit belongs to that complete source. No historical manifest copy is needed in this publication. The existing `board_t1.py` entry and its physical source contract are unchanged.
