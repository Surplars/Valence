# BSCAN phase-separated payload/reset candidate (historical contract)

**Historical prephase evidence:** The immediate-revocation requirement below
was superseded by [the bounded phased fault contract](bscan-fault-phase.md).
The original source, bench, mutator and nine-control receipt are preserved in
`simulator/jtag/evidence/bscan-prephase`; the old P3–F3 expectation is still a
counterexample and is not counted as a new-contract PASS.

Status: logical production-RTL checks passed on 2026-10-12. No changed-candidate
Vivado, AMD primitive, synthesis, placement, routed STA or board run is claimed.
This is a structural candidate for the measured UPDATE payload hold and raw
hard_reset removal paths, not evidence that their slack is fixed.

The rising-UPDATE bank still owns the complete 64-bit frame, length and toggle.
Its capacity test compares the live local toggle with the sampled ACK bit; an
unacknowledged duplicate preserves the first frame and sets sticky overrun.
A positive-TCK bank copies frame/length/toggle before the existing two-stage
negative-TCK notification and consumer. All consumer decodes and bridge payload
now use this bank. Immediate BUSY still compares the UPDATE-local toggle with
consumption ACK, so the prior DONE cannot appear complete during ingress.

For UPDATE F0, the complete bundle reaches handoff at P1, notification advances
at F1/F2, consumption and update_seen occur at F3, and P4 samples ACK before the
shortest legal next UPDATE F4. The four-TCK turnover and third-falling-edge
consumer latency remain. The handoff is a related-clock bank, not per-bit CDC.

Keep live update_overrun at final DMI acceptance: a malformed duplicate between
P3 and F3 must block the pending operation. A positive-edge-only overrun sample
would miss it. This residual UPDATE control path and immediate status paths stay
timed. The candidate does not claim all related-clock ingress paths are removed.
Legal TAP sequencing guarantees a four-TCK minimum turnover. The explicit
malformed-pin tests additionally require fail-closed behavior for duplicate
UPDATE without TCK, including the P3-to-F3 window. Those digital tests do not
specify a realizable arbitrarily small analog setup/hold margin for illegal
pin events. If the retained raw-overrun path still dominates physical hold,
continue structural analysis and state that protocol/physical boundary; do not
waive the path or treat zero-delay simulation as physical evidence.

A separate positive-TCK three-stage hard_release fence is driven only by raw
external reset. It resets the negative-TCK hard_reset functional register.
Using work_reset or either work-derived fence here would feed hard_reset into its
own CLR and truncate the intended full-period assertion. Work reset still
clears all ingress epochs asynchronously, including stopped TCK at either level.
DRCK shift storage now uses the existing negative-TCK source_release fence for
functional reset, preserving the first capture without requiring extra DRCK
release clocks. Its actual primitive recovery/removal remains to be measured.

Source-level added storage is 69 FF (66 handoff + 3 hard release); synthesis can
change the mapped count. ValenceDmiCdc, JtagRamLoader, host protocol, held-owner
and late-drain logic are unchanged.

The clock model remains INTERNAL_TCK 50 ns, waveform {0 25}, DRCK divide-by-one,
UPDATE edges {2 3 4}, with 0.100 ns related setup/hold uncertainty. No payload
false path, multicycle, clock group or new datapath-only exception is introduced.
Only the three structurally checked hard_release CLR pins join the prior twelve
release-bank CLR exceptions. All functional CLR recovery/removal stays timed.
The four existing 8 ns mailbox max delays and two held-bundle skew limits remain
scoped to the true debug-clock bridge.

The companion Tcl reconstructs reported local Vivado compatibility corrections:
C-pin IS_INVERTED queries, get_cells collections for assembled banks, and final
release-stage C pins in all_fanin startpoint checks. It is not a byte-identical
copy of the local patch. Added checks bind handoff inputs, clock polarity,
notification source, bridge ingress and functional reset sources and reject
hard-reset self-feedback. Actual DCP collection remains required.

Executed small Icarus checks: production qualification including 16 shortest
turnovers, full BSCAN transport, 101-request CDC; nine behavioral negative
controls all reached their exact intended oracle. New tests observe P1/F1/F2,
stopped positive-phase handoff, the P3/F3 duplicate window and full hard-reset
pulse. Existing malformed lengths, stop/resume, selection, backpressure, overlap
and reset tests remain. These checks prove logical pin-event behavior only.

Reproduction uses the existing restored Icarus toolchain and these serial entry
points; each RTL compile/run is capped at 1 GiB and 60 seconds:

- python3 simulator/jtag/bscan_qualification_run.py --output FRESH_OUTPUT
- python3 simulator/jtag/bscan_qualification_mutations.py --output FRESH_MUTATIONS
- python3 simulator/jtag/bscan_check.py
- python3 simulator/jtag/test_bscan_qualification.py
- tclsh simulator/jtag/test_bscan_timing.tcl
- tclsh simulator/jtag/test_bscan_netlist_audit.tcl

Later authorized combined physical review must inspect full-expanded min/max
for UPDATE to positive handoff and handoff to negative consumer, raw overrun and
immediate status, DRCK to UPDATE, all functional reset recovery/removal, exception
coverage, mapped bank shapes and final routed resources. Added registers and
logical PASS alone do not close the measured hold/removal failures.
