# Timing and resource batch results

**Default52 improves inclusive COPY throughput by 2.56% in Sv39 and 1.84% in Bare versus fresh `1e90af9`.** Later cleanups and optional53 preserve these cycles exactly. FPGA timing and mapped resource changes remain unmeasured.

The default [board_final.py](../fpga/next/board_final.py) selects 52 CPU/native options including tri-speed MAC and JTAG USER2, plus the separate MAC T1 setting. Published final52 and the complete rollback point are commit `b22f10fde916a0c8209d070e282ebd98cf4c0b2f`, tree `a931ea8ec32438b5fe45852509b0b3dc0a782a6b`. `main` is unchanged. Optional53 uses `fpga/next/board_eager_prefix.py`; default52 remains selected because its mask/fanout tradeoff is unmeasured.

Optional53 is separately qualified; this source provides its explicit A/B entry. Final52 remains the default. Qualification source: `75e450562cc5d3f818e264b602966191950b66ac`, tree `5736ae9442acfe05a4ffee1df58726c86e7d7e69`.

## Measured CPU outcome

Effective COPY payload is **64 KiB × 2 = 128 KiB**, using the same guest, fixed external R32/B32 and READY laws, and capacities. Cycles include final flush. MiB/s assumes **nominal 100 MHz**; it is neither R+W bus-byte throughput nor measured board frequency/bandwidth. These cases add no DMA/MAC concurrency qualification.

| Mode | Fresh baseline ROI + tail | Default52 ROI + tail | Baseline → default52 MiB/s | Gain |
|---|---:|---:|---:|---:|
| Sv39 | 188,286 + 8,238 = 196,524 | 183,380 + 8,238 = 191,618 | 63.605463 → 65.233955 | 2.5603% |
| Bare | 189,789 + 7,933 = 197,722 | 186,216 + 7,937 = 194,153 | 63.220077 → 64.382214 | 1.8382% |

The [configured CPU clock](../src/main/scala/core/ooo/FpgaNextConfig.scala) is 100 MHz and the [scalar memory port](../src/main/scala/core/ooo/LoadStoreUnit.scala) carries at most 64 bits per request. One 64-bit beat every cycle is ideally **800 MB/s = 762.94 MiB/s per direction**. A path sharing one aggregate read/write transfer per cycle limits COPY payload to **400 MB/s = 381.47 MiB/s**, because each copied byte must be read and written. This scalar CPU has a [single arbitrated request port](../src/main/scala/core/ooo/ParallelLoadStoreUnit.scala), so ordinary 8-byte load/store COPY also needs at least two request cycles per 8 bytes. Sv39's 65.23 MiB/s is **17.10% of that ideal scalar request-port payload ceiling**, including flush; it is not a DDR bus-utilization measurement. Instruction issue, dependencies and authorization add further limits.

The [AXI bridge](../src/main/scala/core/ooo/TileLinkAxi4OutstandingBridge.scala) has independent R and W channels and can overlap them; its DDR limit cannot simply be divided by two. Shared credits/cache resources, controller scheduling and physical DDR turnaround still constrain service. The 250 MHz MIG UI clock alone does not establish a CPU or COPY ceiling.

Combined ABC established these gains; no individual subchange receives that credit. Later default52 and optional53 preserve all 105 fields, complete stdout, 12 sections, raw AXI/supply bytes and ROI/tail cycles against their qualified predecessor. Read/memory/trap controls reject correctly.

Both pass same-object NEMU at **1,847/958 cycles**, plus PC/GPR/memory controls without resynchronization. Coverage is two short physical integer M-mode inputs, excluding Sv39/CSR/FP/permission/concurrent-DMA. B's 14-taken-jump C.J case still grows **34→48 cycles (+41.2%)**; optional53 does not solve that tradeoff. See [ABC qualification](experiments/timing-batch-r2-qualification.md) and [final52 evidence](../simulator/gsim/owner_row/README.md).

## Structural changes and costs

Native counts describe emitted RTL, not mapped LUT/FF savings or timing margin.

| Change | Verified cost or simplification | Evidence and remaining limit |
|---|---|---|
| Proof maps / one-hot successor | Consumer proof maps reuse producer validity/index; one-hot successor avoids count decoding; no added state | Component/native pass; ownership and occupancy checks remain |
| A: registered pending-proof query | +179 native scalar bits; one selection-to-query cycle, one query/cycle | Actual boundary verified; cancellation/translation/PA cones remain |
| B: aligned fetch permission | +147 native scalar bits; hot II=1 | Component/CPU pass; branch cost above remains |
| C: registered canonical store event | +240 native scalar bits; checked acceptance-to-tracker boundary | Component/backend/CPU pass; owner/epoch/shape checks remain |
| MAC/BSCAN repairs | FIFO collector repair; BSCAN handoff +69 source-FF estimate; later T1 +1 logical bit and fault sample +1, separately | Behavioral/source pass; mapped mode/reset/CDC/PHY timing remains open |
| Lane-1 owner / rank-1 IDs | Shared ROB equality; two PRF address clears removed; zero state/port/cycle delta | Full native/CPU/NEMU parity; owner/range checks remain |
| Execution operands / upper enables | Four 64-bit selections removed; banks 1–7 enables localized; zero state/port/cycle/capacity delta | Component/full parity; bank0/upstream admission remain |
| Canonical consumers / upper rows | 16 comparisons 68→4 bits; seven row pins localized per slot, four slots; zero state/array/port/cycle delta | Final52 passes; producer/LSU full-token ownership remains |
| Optional53 eager prefix | Length-sum/decode, one four-input 64-bit indexed select and four-level conditional chain removed; masks 3→5, OR joins 2→4; zero state/port/cycle delta | Component/full native/CPU/NEMU pass; carries unchanged, physical fanout/cost unmeasured |

ABC totals **+566 native scalar declaration bits versus 1e90**, including one constant-fed bit; arrays are unchanged. Do not combine this with separate BSCAN/T1 source estimates as a mapped total. Later zero-cycle cleanups establish no net LUT saving. Details: [lane-1](experiments/lane1-owner-match-r1-qualification.md), [rank-1](experiments/prf-address-clear-r1-qualification.md), [operand/enable](experiments/zero-cycle-cleanup-r1-qualification.md), [MAC T1](experiments/mac-reset-release-t1.md), [BSCAN](debug/bscan-fault-phase.md).

## Rejected memory preparation experiments

These are distinct from successful canonical-event stage C and are excluded from default52/optional53.

| Candidate | Sv39 / Bare inclusive cycles | Cost and decision |
|---|---:|---|
| Selected ABC/default52 | 191,618 / 194,153 | Retained |
| Memory preparation + cancelled-response drain | 204,914 / 220,220 | +298 native bits; functionally passed, +6.94%/+13.43% cycles, rejected |
| Above + displaced shadow H / lane-1 reuse | 203,720 / 220,220 | H adds 203 native bits; still +6.32%/+13.43%, rejected |

Stage-only first lost 132 cycles in a directed overlap witness. Drain repaired that witness; H recovered only 1,194 Sv39 cycles and none in Bare. H NEMU was not run after performance rejection. Sv39 traffic stayed equal while offers became sparser; Bare also added reads. Single-stage causal attribution remains unproven.

## Physical result and next decision

Historical r5 CPU100 post-place WNS **−2.010 ns**, TNS **−24,819.273 ns**, and **23,899 failing endpoints** describe the old design. Its path rankings and net-delay observations cannot establish current timing. No new physical STA, mapped resources, routed signoff or board acceptance exists.

Before a user-controlled physical run, confirm exact source/profile/part/constraints, preserve the eight local compatibility patches, and verify actual T1/tri-speed/USER2 consumption. Existing DCPs only describe their original design; changed RTL requires source-matched synthesis/place. Stop at post-place to inspect top families, resources, fanout, clocks, setup/hold, recovery/removal and CDC before a long route.

The [16-family read-only collector](../fpga/next/timing-paths/README.md) passed nine Tcl mock cases, not a Vivado run. Verify exact hierarchy roots and actual nonempty endpoint coverage; stale or missing matches are not a pass. An old DCP cannot qualify changed RTL.

Published progression: `12beb29` ABC/initial repairs; `8a9bed8` T1/fault sample; `503f47c` lane-1; `611ab7a` rank-1/final48; `c67a082` operand/enable/final50; `3fcfaf6` fixture/report repair; `b22f10f` owner/row/final52. These identify delivered changes, not independent performance gains.
