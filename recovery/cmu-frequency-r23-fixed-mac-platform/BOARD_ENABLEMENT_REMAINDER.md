# Dynamic protocol simulation, NOT hardware frequency switching

r23 is a default-off fixed-MAC **functional integration**, not permission to
program a board or a tested legal-frequency whitelist. Finish this bounded
matrix before further functional changes. Do not auto-expand peripheral
performance work after it.

## Shortest dependency order

1. **Complete AON stop-clock qualification and real gate feedback.** Current
   runtime held is a delayed snapshot while old clocks still run, not gate ACK.
   Add actual CPU/fabric gate-close/open and resumed-edge observations to the
   complete ownership join, including UART/CMU request/reply and external-event
   retention. Do not replace these owners with MAC park.
   Sources: `CommonRuntimeEpochBoundary.scala:26–51`,
   `CommonMachinePlatform.scala:148–149,192–240,292–300`,
   `CommonMachineFabric.scala:480–506` (all under `src/main/scala/platform`).
2. **Separate the clock and reset backend correctly.** The current board uses
   one clk_wiz_common for CPU/AON/(optional)fabric and disables dynamic
   reconfiguration. Loss of cpu_locked enters common reset. Simply enabling DRP
   would disturb AON and discard retained owners. Independent fixed AON,
   independently programmable CPU/fabric resources, actual gate feedback,
   validated DRP programming/DRDY, stable LOCKED, retention-preserving reset,
   resumed-edge evidence and safe boot50 fallback/fatal handling remain needed.
   Sources: `fpga/common/synthesize.tcl:22–33`,
   `fpga/common/soc_top_common_ddr.sv:31–50,69–74`,
   `recovery/cmu-frequency-r1.md:9–13`.
3. **Connect existing CMU and epoch machinery to that real backend.** Software
   pages 0x10080800/0x10080880 and ordered replies/consumed receipts exist. But
   CommonMachinePlatform:354–365 still ties endpoint present/drain/gate/lock/
   resume false and disables program/result handshakes. Writes return
   BackendAbsent. The lease-capable controller and CommonClockRateEpochAdapter
   are isolated compositions, not yet the live production chain. Required order:
   actual request/reply consumption -> real epoch drain -> gate/program/resume
   -> terminal delivery/consumption -> final fabric retirement. Local enqueue or
   AON terminal consumption alone is not final completion.
   Sources: `ip/clock/ManagedPeripheralBank.scala:78–94`,
   `ip/clock/ClockRateManagement.scala:20–34,104–106`,
   `platform/CommonClockRateEpochAdapter.scala:7–16,43–91`,
   `ip/clock/ClockRateControl.scala:263–280` under `src/main/scala`.
4. **Qualify frequencies, without relaxing performance targets.** The existing
   exact-rate experiment has 31 CPU50…200 integer points at 5 MHz increments
   from the fixed MIG UI250 source; fabric50…150 is a 21-point candidate subset.
   These are not running-system authorization. physicalLegal, componentTested
   and socSignedOff must all be true before allowed; current points are empty.
   The ~71.43 MHz CDC stress ratio is not an authorized grid point. CPU300 and
   fabric250 timing/performance requirements remain unchanged.
   Sources: `recovery/cmu-frequency-r1-exact-rates.csv`,
   `recovery/cmu-frequency-r1.md:3–15`,
   `src/main/scala/ip/clock/ClockRateControl.scala:6–19`,
   `src/main/scala/platform/CommonMachinePlatform.scala:325–326`,
   `src/main/scala/platform/CommonCpuProfile.scala:13–19`.
5. **Freeze a matching boot50 board package, then perform its physical signoff.**
   boot50-static is already defined as CPU/fabric50, DDR/timer/debug250,
   AON/UART50, without reducing memory geometry or deleting CDC. The production
   exporter does not enable runtime flags and still reports reconfiguration
   false. An enabled test fixture is not the production board top. Required
   matching final RTL/ROM/clock contract, function receipts, generated IP and
   constraints must pass generated-clock audits, setup/hold, CDC/RDC,
   reset/lock recovery and I/O/DRC before bitstream/board tests.
   Sources: `src/main/scala/platform/CommonCpuProfile.scala:15–19,52–57`,
   `src/main/scala/platform/CommonMachinePlatformMain.scala:18–21,55–69`,
   `fpga/common/README.md:37–68`, `fpga/common/board_audit.tcl:63–80`,
   `fpga/common/synthesize.tcl:100–118`.

## Physical evidence is not updated by r23

The locally available full routed r2 evidence is revision dd814d96 at
2026-10-21 07:49 UTC: CPU WNS -1.333 ns, fabric -2.175 ns, global -2.219 ns,
no signoff/bitstream. Its 21 reset CDC Critical and 44 DCIRST warnings describe
that old revision, not a new analysis of current RTL.
`recovery/timing-batch-r2-routed.json` preserves those results.

Current source **does** have native_dci_startup/DCIRESET, and
`recovery/native-validation-366a643/dci-result.json` records real UNISIM positive
and short-pulse negative tests. Do not report DCIRESET as still absent. This
component correction, and the eada605 boot banner/guest native PASS, do not
establish new whole-board mapping/routing closure or board boot. r23 provides
no trustworthy date for completing these remaining hardware dependencies.
