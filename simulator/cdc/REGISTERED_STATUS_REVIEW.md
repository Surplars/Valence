# Registered status candidate and routed CDC review

This is an **uninstantiated, opt-in component candidate**. Production and current
performance platform wiring are unchanged. No implementation, metastability MTBF,
reset timing closure, or board qualification is claimed by native simulation.

## Five non-reset findings

* DDR readiness currently originates at `calib_complete & ui_aresetn` in
  `soc_top_common_ddr.sv`, then enters the fabric `CdcLevel`. This is a
  combinational launch, not a registered source. However, calibration loss also
  asynchronously asserts `ui_reset_request`, which asserts `ui_reset_pipe` and
  hence `commonColdReset` without a UI edge. Therefore a functional stale-ready
  bug has **not** been demonstrated merely by the CDC-10 report.
* `RegisteredStatusClockBoundary` provides an explicit source register and two
  local reset-release chains. A fault requiring cancellation with clocks stopped
  must assert `commonColdReset`. A plain status drop without reset is only
  observed as the clocks run. It is not a pulse synchronizer or a clock monitor.
* GMAC `mediaOpen` is source-registered. Its RX/TX level synchronizers can disagree
  transiently, so they cannot represent an atomic cross-domain commit. Current
  consumers use the local synchronized value for local admission/abort. Separate
  drain ownership remains necessary; CDC-11 fanout is not in itself grounds to
  merge the synchronizers or waive the report.
* `rxStop/command` uses the production one-bit held-data mailbox. Source data is
  held until destination consumption and returned acknowledgement. Stop closes
  admission before ACK, and ACK waits for frame and FIFO idle. `drained` also
  requires source drain and no pending dirty command, preventing stale stop ACK
  reuse across release. DMA completion is explicitly outside this barrier.
* `txConfig/mailbox` uses the same production held-data protocol at 52 bits.
  Destination consumption is gated by TX idle; payload ownership persists while
  backpressured. TX and RX commits are deliberately not simultaneous. Physical
  payload max-delay and toggle synchronizer constraints remain mandatory.

These are source-level protocol arguments, not complete routed CDC acceptance.
No media or mailbox RTL is changed solely to reduce report counts. The reset
classifier is separate, read-only, explicit-inventory tooling; unknown endpoints
remain unreviewed, including vendor reset primitives. Existing routed reset
findings cannot be approved by an earlier smaller reset census.

## Native status test

Emit fresh RTL with `soc.ip.RegisteredStatusBoundaryMain <rtl-directory>` using
`IonSoC.test.runMain`, then run:

```
python3 simulator/cdc/test_registered_status.py <rtl-directory> <fresh-results> \
  --iverilog <iverilog-path> --vvp <vvp-path>
```

The event-driven bench uses independent clocks with changing ratios/phases and
an edge-count oracle. It checks normal propagation, asynchronous cancellation
with both clocks stopped, destination-first/source-first restart, and release
latency. Two deliberately corrupted observations must fail the monitor: stale
ready during common reset and premature ready during destination release. These
are monitor negative controls, **not** mutant-DUT coverage or analog CDC proof.
No generated RTL is rewritten. Receipts hash the actual emitted modules and bench.

Before integration, map the new source FF, synchronizer, reset releases, active
clock anchors and all retained endpoints in strict constraints. Source and fabric
clocks may have equal periods but remain distinct physical domains. Preserve all
existing max-delay/bus-skew checks. Do not replace them with blanket false paths.

The existing real RX-stop/mailbox/FIFO fixture can be emitted unchanged with
`soc.ip.RxAdmissionStopIcarusMain`, which requests the standard firtool lowering
without block-local automatic variables. Its pre-existing native SV ledger is
run by `test_rx_stop_iverilog.py` with the same RTL/output/tool arguments as above.
The original Windows emitter and generated RTL are not modified. Frame owners
and CPU status storage in that fixture are surrogates, not complete GMAC/DMA.

## Cloud component results (2026-10-21)

* Registered status: 533 edge/reset checks passed; stale-reset and premature-release
  monitor negative controls both rejected.
* Existing RX-stop fixture: four independent clock ratios passed, including paused
  clocks, frame/FIFO/output/status ownership, coalesced release, accepted release
  followed by re-stop, and coordinated reset. Ledger: 252 accepted equals 244
  delivered plus 8 intentionally discarded by coordinated reset. Payload/drain
  monitor negatives both rejected.
* Standalone reset-locality classifier: 80 mock checks passed. The actual routed
  128 reset-control endpoints have **not** been classified by this new helper.
  Exact native endpoint contracts and recovery/removal analysis remain required.

The first RX-stop export used the original Windows emitter and was rejected by
Icarus for automatic local variables. The compatible test-only emitter then
produced fresh RTL using firtool lowering; no DUT or generated RTL was patched.

## Standalone reset-locality audit usage

In an already opened native design, source `fpga/common/common_cdc.tcl` and then
`fpga/common/reset_locality_audit.tcl`. Neither sourcing operation applies this
new audit automatically. Call:

```
set result [reset_locality::audit $release_specs $local_sources $exact_endpoints]
```

`release_specs` is a Tcl dictionary keyed by the exact final release Q pin. Each
value contains exactly `stages` (three ordered FDPE cell names), `clock` (local
clock name), `assert_source` (registered positive-asserting source Q pin), and
`assert_clock` (that source register's clock). `local_sources` maps each exact
downstream CLR/PRE endpoint to its required final release Q. `exact_endpoints`
is the nonempty, duplicate-free native endpoint inventory supplied by the caller.
Do not derive that inventory from a guessed hierarchy or a summary count.

Inspect the returned `rows`, `releases`, and `unreviewed_count`. A classified row
establishes only the checked topology; the result always carries
`scope EXACT_CALLER_ENDPOINTS_ONLY`, `timing UNCHECKED`, and `waiver NONE`.
Unknown/vendor controls and unsupported qualification logic remain UNREVIEWED.
The helper does not write timing exceptions or claim whole-design coverage.
Mock validation is `tclsh fpga/common/test_reset_locality_audit.tcl`.
