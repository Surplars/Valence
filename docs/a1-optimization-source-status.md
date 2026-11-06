# A1 optimization source and qualification status

Status date: 2026-11-06. This is a source map, not a new performance result or release qualification.
Defaults and production admission guards remain unchanged. A source integration, a component pass,
a historical CPU snapshot result and a current full-platform result are different claims.

## Current production baseline

- `src/main/scala/platform/CommonCpuProfile.scala` selects static A1 at CPU100/fabric250;
  `src/main/scala/core/ooo/config/FpgaNextConfig.scala` resolves the current two-issue
  ROB16/PRF48/LSU2 baseline. Historical CPU optimization runs used ROB32/PRF64.
- `src/main/scala/core/ooo/config/OooParams.scala` still defaults `indirectTargetEntries` to 0.
  A predictor implementation being present does not enable it in the production CPU.

## CPU: maintained source versus historical composition

- W13's historical indirect16 table reduced LLVM 409386→389222 cycles (4.93%). W14 banked
  storage preserved its timed results while saving 2008 LUT/168 MUX/2032 FF, adding 40 RAM32M16.
  Against no-table W12, W14 still costs +3171 LUT/+2427 MUX/+46 FF/+40 RAM32M16.
  These ROB32/PRF64 snapshot results do not qualify current A1 performance or physical timing.
- The W14 source integration is in `src/main/scala/core/ooo/frontend/BranchPredictor.scala`:
  default-false `bankedStorage`, unchanged register-vector fallback, restricted to 16 entries,
  two lookups/two commits, compressed instructions and registered training.
  `src/main/scala/core/ooo/integration/IntegerCore.scala` and
  `src/test/scala/ooo/IntegerCoreGsim.scala` expose default-false `bankedIndirectStorage`.
  This is a test-core source entry, not a CommonMachinePlatform production selection.
  Its new RVC emission flag does not qualify the existing full-core host for RVC execution.
- Fresh qualification: one 352-source compile, four contract tests, and both focused GSIM modes
  passed 40004 random +123 original-directed +81 banked-directed ticks, including one-edge reset.
  Four observation-only controls per mode failed as intended. Independent review passed.
  The 41-module core CHIRRTL pair differs only in the predictor; it was emitted, not executed.
  Qualification used direct pinned stages; the Make entry was dry-run only because Mill was absent.
  Focused assets: `src/test/scala/ooo/BankedIndirectStorageSpec.scala`,
  `src/test/scala/ooo/BankedIndirectStorageGsim.scala`,
  `simulator/gsim/banked_indirect_storage.py`, and `simulator/gsim/harness/banked_indirect_storage.cpp`.
  See [the storage contract, commands and limits](banked-indirect-storage.md).
  No new parameter case-class fields, default identity change, current-CPU runtime/IPC or PPA claim.
- W11/W12 compact signed-immediate storage and owner-guard pruning remain specialized FIR/SV
  snapshot work; live `src/main/scala/core/ooo/issue/BankedIssuePayload.scala` keeps 64-bit payloads.
  W11 is separable, but current ROB16 would save only 512 logical bits; current PPA is unmeasured.
  The historical W11+W12 LUT/MUX saving cannot be attributed to W11 alone. Current unowned
  immediate reads default to enabled, so the old four-reader lifetime proof must be rebound.
- W15 targets the raw-packet sequential-prefix comparisons in `IntegerCore.scala`:
  `lanePcs(lane) === packetPc(laneOffsets(lane))`, not the AUIPC comparison. W15 and W16
  segmented fetch-window comparisons remain component-leaf/CPU grafts. The core and
  `src/main/scala/core/ooo/frontend/RegisteredFetchWindow.scala` still use direct comparisons.
  Defer isolated ports: W15's direct changed-module delta was +51 LUT/-138 MUX, while
  W16 added 259 LUT/767 MUX to the historical whole-CPU map with no cycle benefit.
- W18 rank-guard pruning has a historical whole-CPU saving of 5031 LUT/4657 MUX, but 53 finite-path
  regressions and a different specialized backend. The worst saved declared-row regression was
  backend-head to stagedMemoryToken_tag, 30→36 mapped-cell levels. W12/W18 require current
  selector/metadata/owner and defined-lifetime proofs, not guard deletion in
  `src/main/scala/core/ooo/integration/IntegerBackend.scala`. Rejected W19 remains excluded.

## Bus/cache/DMA: maintained, explicit opt-in

- Accepted completion flow, disjoint DMA-read/Acquire overlap, factored owned-directory updates,
  and dirty-Probe/older-Acquire overlap are already in
  `src/main/scala/core/ooo/cache/MixedCoherentLineHome.scala`, with guarded propagation through
  `src/main/scala/core/ooo/cache/CoherentLineHome.scala` and
  `src/main/scala/platform/CommonMachineFabric.scala`.
- Line DMA/threshold rewrite is in `src/main/scala/ip/dma/MemoryCopyDma.scala`.
  `src/main/scala/platform/CommonFabricDmaExperiment.scala` resolves the matched
  `read-baseline` and `probe-acquire` modes. Both enable completion flow/read overlap;
  only Probe overlap differs. Neither is the default; `singleReadWait` remains off.
- `src/test/scala/platform/CommonMachinePlatformMain.scala` exposes
  `--experimental-fabric-dma=read-baseline|probe-acquire`, requires a source/class-bound
  compile receipt, and passes the selection through
  `src/main/scala/platform/CommonMachinePlatform.scala`.
  The supported experiment is static generic A1 with memory-copy DMA, not a custom/experimental
  CPU, runtime clock profile, I1, or SoC-file configuration.
- Focused source checks are `src/test/scala/platform/CommonFabricDmaExperimentSpec.scala`,
  `src/test/scala/platform/CommonFabricDmaAcquireSpec.scala`, and
  `src/test/scala/platform/CommonFabricDmaProbeAcquireSpec.scala`.
  See [candidate details and evidence scope](dma-probe-acquire-overlap.md), including the rejected
  probe-window extension. Do not revive that extension or bypass legacy board guards.

## Maintained reproduction and assertion checks

- `simulator/qualification/a1_cdc_fabric/export_fixture.py` is an opt-in export/check-only tool.
  It validates complete source/class/identity bindings, supported production startup/reset/empty/
  readiness/direct-AXI wiring, dependency closure, ports and assertion layers. Dependency bodies
  are copied exactly; it does not build, lower or execute hardware.
- Fresh, separately emitted OFF/ON production inputs passed 13 affected platform tests and paired
  projection: 374 copied definitions plus one wrapper, 612 ports, 181 identical CPU definitions,
  and only `MixedCoherentLineHome` differs. This replaces the old Home-substitution method for
  future exports. Fresh ON versus the archived production emission differs only in source locators
  in BranchPredictor/IntegerCore after the default-off W14 port. No runtime was repeated.
  See [export commands, strict controls and limits](../simulator/qualification/a1_cdc_fabric/README.md).
- `src/test/scala/ooo/PmpLifetimeSpec.scala` adds five production-emission contracts for FP ownership,
  walker depths 3/4/5 in both PMP modes, exact predicates, and original decoded-state reset scope.
  A separate tiny four-state fixture passes ten positives and rejects ten active-illegal/unknown
  or malformed-region cases. Its independent checker binds declared stimulus and original
  assertion A/EN/TRG, including owner-vacuity controls. No CPU or full caller state machine runs.
  See [PMP lifetime commands and bounds](../simulator/qualification/pmp_lifetime/README.md).

## What still blocks production usability

- The measured A1+100:250 runtime fixture is not the complete production RawModule/vendor/
  peripheral/MIG assembly. Its historical OFF arm used the pinned earlier OFF Home substitution.
  The fresh export qualification above does not rerun or relabel that runtime.
  The bounded 669→606 CPU-cycle result belongs to its guest, synthetic DDR service and clock phase;
  it is not current banked-predictor performance, sustained DDR bandwidth or board signoff.
- `src/main/scala/platform/CommonCpuClockBoundary.scala` and
  `src/main/scala/ip/bus/HeldResponseCdcDataFifo.scala` are maintained production CDC sources.
  Static A1 connects fabric AXI directly to MIG UI250; it has no DDR AXI clock boundary.
  This coverage does not qualify physical CDC or another clock profile's extra DDR crossing.
- `fpga/common/cpu_identity.py` and `fpga/common/board_inputs.py` currently reject the
  fabric experiment's extra identity fields/qualification/shared-fabric configuration.
  Full-top SystemVerilog and `fpga/common/soc_top_common_ddr.sv` interface qualification remain
  separate gates. Do not remove validation or relabel the experiment as public-qualified.

## Next valuable bounded work

1. Qualify the actual full-top experimental export/identity/shell contract without weakening board
   admission. Any later optimized-CPU+fabric selection is a new matched qualification lineage.
2. Keep the maintained export and short PMP checks separate from full native assertion conversion,
   guest/service/oracle portability and real CPU execution. Extend runtime only when a concrete
   functional change or boundary justifies another slow matched run.
3. If pursuing another source batch, first assess W11's modest current storage value and close
   every current meaningful-read lifetime, preserving arbitrary-64-bit generic APIs. Defer W12/W18
   until exact current authority can prove a real redundant gate; defer isolated W15/W16 work.

No new broad regression, map, routed timing, board result, default promotion or publication follows
from this source map. Use short affected checks and independent oracles before any further gate.
