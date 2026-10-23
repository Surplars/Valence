# One-shot IDELAY reset locality optimization

Diagnostic helper only; no automatic hook, RTL or constraint changes. Source it
AFTER the combined candidate's place_design, before its normal route. Do not
start a separate native run just for this helper.

```tcl
source fpga/common/idelay_reset_replication.tcl
set reset_result [idelay_reset_replication::apply fresh-idelay-reset-before 450]
# Only returned status is REQUIRES_ROUTE_AND_TIMING_VALIDATION, not closure.
# Continue the existing batch's route flow exactly once.
set reset_reports [idelay_reset_replication::postroute_reports fresh-idelay-reset-after]
```

The explicit second apply argument selects the reviewed candidate: exactly 450
or 475 ps, with 475 retained as the backward-compatible default. R39 uses 450.
The expected value is stored in the same-session baseline and reused by all
postchecks; postroute_reports does not accept a replacement value. Every one of
the ten delay primitives must match, or execution stops.

Run both calls in the same Vivado session. Source/apply never calls route,
unroute, set_property, creates clocks or adds exceptions. apply executes one
phys_opt_design -force_replication_on_nets on the exact guard[63]/Q net. Its
one-shot latch is set before that command; native error or failed postcondition
must stop this candidate, not retry on potentially changed state. Preserve the
pre-optimization checkpoint externally. Resourcing does not reset the latch.

Preconditions fail closed: placed FDPE guard[63], original guard[62]/Q D source,
delay_reset_pipe[2]/Q PRE source, REF500, direct Q reset connections, exactly
three named IDELAYCTRL plus five IDELAYE3 and five ODELAYE3 RST pins, all cascades
the selected exact delay/FIXED/TIME with MASTER/SLAVE_END and ref500. RX CLOCK_ROOT and USER_CLOCK_ROOT
must both remain X3Y2. Unknown names or extra/missing loads stop without mutation.
Afterward every reset driver must have identical INIT/inversion/C/D/PRE/CE and
clock signatures; all 13 reset sink LOC/BEL identities must remain unchanged.
No chosen slice location or clock root is imposed. No change to 128 ns guard.

Before/after reports cover driver D/PRE and all 13 reset destinations, Fast/Slow
max/min. The reporter does not claim signoff or silently waive missing paths.
Acceptance must inspect endpoint coverage, require all timed recovery/removal
and added driver setup/hold paths nonnegative, and compare full global timing.
A missing path requires classification, NOT acceptance based on an empty report.
Also retain the batch's five RX input all-corner/both-edge max/min reports, prove
all five still positive and all ten delays retain the selected exact value, check route completeness
and DRC. A reset-net-only mutation is not proof unrelated timing cannot move.

Cloud check: tclsh fpga/common/test_idelay_reset_replication.tcl. Tests use stub
native objects, not Vivado: 25 invalid baselines cause zero mutations, including
both 450/475 mismatch directions and unsupported selections. Post-change
identity failure and tool error prohibit retry. Explicit 450 and default 475
cases pass; postroute delay drift fails. This parameter-selection change has
not yet been executed in native Vivado.

AMD UG974 2025.2 explicitly requires IDELAYCTRL reset synchronous deassertion to
REFCLK; the measured -66 ps recovery is real, not an asynchronous waiver:
https://docs.amd.com/r/2025.2-English/ug974-vivado-ultrascale-libraries/IDELAYCTRL
Scoped driver replication semantics:
https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/phys_opt_design
