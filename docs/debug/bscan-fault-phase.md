# BSCAN bounded phased fault contract

This candidate adds one positive-TCK `fault_sample` register to the published
payload/reset handoff. It samples sticky UPDATE-local `update_overrun` using the
existing negative-TCK-released `source_reset_n`. All negative-TCK D/CE logic uses
the sample or existing negative-TCK `protocol_error`, with no raw-overrun fan-in.
Visible ERROR comes only from `protocol_error`; this adds no same-positive-edge
fault path to DRCK capture. It is a related-clock phase register, not an
asynchronous synchronizer or a permission token.

Legal TAP behavior and ingress latency are unchanged. UPDATE captures A at F0;
P1 copies the held bundle; F1/F2 advance notification; F3 consumes/acknowledges
and may admit A once; P4 returns the ACK bit before the earliest legal next
UPDATE at F4. The live local toggle is compared to that sampled ACK bit. A
cached free Boolean or an ACK at handoff is forbidden.

An illegal duplicate within the same unacknowledged epoch preserves A and its
token, even if raw DRCK changed the scan frame to B. A fault stable before Pk
is sampled at Pk, blocks DMI/capability admission at Fk, and sets visible sticky
error at Fk independently of whether another command is consumed. A deliberate
duplicate in P3–F3 may admit A exactly once at F3 when ready; B is never admitted;
P4 samples the fault and F4 sets sticky error. This bounded observation requires
eligible resumed clock edges and a stable observation satisfying the aperture.
Arbitrarily asynchronous illegal pulses have no deterministic metastability
recovery-cycle guarantee. Stopped TCK gives no wall-clock fault deadline.

Fault setting wins over ordinary CLEAR. NOP polling and control hard reset remain
usable. Hard reset clears the whole frame/toggle/ACK/sample/error epoch and
retains its independent raw-reset-only release fence and full-TCK assertion.
Fault alone never cancels a legally admitted mailbox request, held bus request,
accepted write or response. Explicit transport reset retains/drains loader bus
ownership according to the existing production loader contract.

Immediate BUSY remains `source_busy || update_toggle != update_seen`. Pending
BUSY masks old DONE; at F3 admitted work asserts mailbox BUSY while clearing DONE.
This is a settled edge-sampled status guarantee, not a subcycle glitch claim.
The raw UPDATE-toggle to positive-DRCK BUSY/status path is deliberately timed.

## Evidence and reproduction

The original source, bench, mutator and source-bound nine-mutant receipt remain
unchanged under `simulator/jtag/evidence/bscan-prephase`. The original immediate
late-revoke test still fails with the new source at its exact old oracle; its
receipt category is `PRESERVED_OLD_CONTRACT_COUNTEREXAMPLE`, not a regression PASS.
Eight old controls are re-anchored with the same intended behavioral failures.
New controls cover lost independent sticky update, disabled sample, CLEAR
priority, early ACK, stale fault reset, capability bypass, and raw-fault D/CE
reconnection in source/Tcl audits. Compile failures never kill a control.

Run the small serial Icarus suite with an existing reviewed toolchain:

- `python3 simulator/jtag/bscan_fault_phase_run.py --output FRESH_OUTPUT`
- Add `--loader-fixture FIXTURE` for the source-bound production-loader witness.
- `python3 simulator/jtag/test_bscan_qualification.py`
- `tclsh simulator/jtag/test_bscan_timing.tcl`
- `tclsh simulator/jtag/test_bscan_netlist_audit.tcl`

The fixture preparation script verifies the exact previously emitted loader,
its complete source binding and its reviewed Icarus lifetime adaptation. It
keeps the production timeout at 1,000,000 cycles. No full CPU or loader rebuild
is needed. Pin-event tests and manual/mock structure are not vendor simulation
or physical qualification. Consult the accompanying run receipt for actual
executed results; this document does not substitute for a receipt.

## Remaining timing obligations

No clock phase, false path, multicycle, clock group or datapath-only waiver is
added. Preserve INTERNAL_TCK 50 ns waveform `{0 25}`, DRCK divide-by-one, UPDATE
edges `{2 3 4}` and 0.100 ns related setup/hold uncertainty; use actual primitive
clock arcs. Keep all 15 checked release CLR exceptions, four 8 ns true-mailbox
max delays and two skew limits within their existing scope. C-pin inversion,
root object collections and final release-stage C-pin ancestry remain checked.

Uncut paths include UPDATE fault to positive sample; UPDATE frame/length/token
to handoff; positive sample/handoff to negative consumer; ACK/selection/release
to positive qualifiers to UPDATE; DRCK data/count/capture to UPDATE; raw UPDATE
toggle to BUSY to positive DRCK; negative result/error/mailbox status to DRCK;
scan/TDO; every functional reset recovery/removal and pulse-width path.

Source storage rises from +69 to +70 FF versus the original unphased source.
This is not mapped resource evidence. Full-clock-expanded min/max, mapped bank
shapes, exception coverage, recovery/removal, routed timing and board/vendor
primitive checks remain required. Neither +1 FF nor logical PASS proves that
historical physical hold/removal violations are fixed.
