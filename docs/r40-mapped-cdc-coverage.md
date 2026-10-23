# R40 mapped CDC coverage repair (analysis-only, native pending)

The native R39 195/155 report bundle SHA256
`76a23442fea1b75adf5308e1d065f72275a77dda4b48076f04c5b00da14fa078`
preserves 1,029 nonclock statements before/after changing modes. That establishes
preservation, not complete coverage of the current mapped cells.

Both saved valid-exception reports list rateCmu bridge response data indices
0..32, 49..58, 61..62 plus error. They omit indices 33..48, 59, 60, 63.
Actual timing proves bit33 exists and is timed as an ordinary synchronous path
(requirement0.645 ns, slack-2.661 ns). Other omitted indices may be optimized or
constant: only a fresh mapped census can establish their active set.

All five ddrCrossing FIFOs' writeGraySync stage0 exception lists contain only
bits0..3. Their capturedGraySync lists already contain all five bits. Actual
timing proves live writeGray bit4 paths in FIFO1 and FIFO4, with requirements
0.129 ns. Do not infer all omitted names exist without inspecting the DCP.

Current common_cdc::gray requires exactly five bits and allows only the usual
binary/Gray MSB merge. register_payload enumerates actual retained capture bits;
neither has the observed four-bit/bit32 ceiling. Thus the saved scope lists are
incomplete for this graph, not a justified protocol exclusion. Which earlier
generation/mapped stage produced those lists is not established by this bundle.

## Minimal staged procedure

Load the unchanged original routed DCP in a fresh native process; retain its
external SHA256 receipt. Source common_cdc.tcl and then
dynamic/mapped_cdc_coverage_repair.tcl. No action occurs just from sourcing.

First call `set plan [r40_cdc_repair::inspect]`, print/save `[list $plan]`, and
retain `r40_cdc_repair::timing $plan before 0` output. This is read-only and
bounded to six buses, not a full CDC collection. Have the actual plan reviewed
before calling `r40_cdc_repair::apply $plan` in the same unchanged DCP.
For a later process, load the saved value with lindex/read, not eval; inspect
must reproduce it exactly. Never change the saved plan to force acceptance.

The helper reuses the existing exact FF/clock, retained-bit/direct-wire, and
two-stage Gray/sole-first-stage-fanout proofs. It checks the response toggle
synchronizer as well. The frozen RegisterClockDomainBridge RTL holds the
response until a subsequent request, and admits that request only after the
previous reply is consumed; the two-stage toggle crossing delays capture.
This source protocol is required evidence, not permission to waive other buses.
The current ClockDomainCrossing.scala and HeldResponseCdcDataFifo.scala were
independently byte-compared to frozen R39 commit84a498a and are unchanged:
SHA256 c2668e21c42dcd88a11f80c721ef24fa0fedc7fed3fd3a371d7a2b6c89bd9a52
and2302decf7392cfd64fdec49a4c2b76470f45c98f736644c2ddb64d0cef21d126.

Only the response bus and five writeGray buses receive their original4 ns
datapath-only max delay and4 ns bus-skew bounds. No clocks, routing, hardware,
false paths, reset paths, or existing capturedGray scopes change. Each exact
source/capture path must return finite positive bounded timing with a maxdelay
exception after application. Failure after mutation is uncertain partial state:
close/reopen the original DCP, never retry in the same session.

Afterward retain full both-corner timing, bus-skew, coverage/ignored exceptions,
and constraint deltas. Confirm no new unconstrained endpoints, ordinary
stage0-to-stage1 paths unchanged, all bus-skew checks meet4 ns, and global
setup/hold/recovery/removal/pulse-width results. The helper's local success does
not qualify the entire mode. Save only a separately named analysis checkpoint;
do not overwrite the original bitstream source or reuse old qualification.

Monitor Gray/MMIO paths already have a separate3 ns helper; absence from
common_cdc dynamic_roots is not evidence they lack constraints. Monitor
sourceRelease PRE entry recovery requires a separate six-pin structural/RDC
proof; this helper makes no reset exceptions. All functional resets remain timed.

`tclsh fpga/common/test_mapped_cdc_coverage_repair.tcl` checks mutation ordering,
exact budget/skew commands, nonfinite values, missing/relaxed/negative paths,
plan drift, and re-source one-shot safety. These are mocks, not native topology
or physical qualification.
