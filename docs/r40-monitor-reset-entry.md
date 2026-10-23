# Exact monitor source-release RDC entry proof

Status: mock-checked candidate; native inspection/application is pending. No RTL,
clock target, physical placement/routing or existing production gate is changed.
This is an explicitly invoked diagnostic helper, not an automatic flow override.

## Scope and actual structural basis

Only `u_soc/monitor/domain0/sourceRelease` and `domain1/sourceRelease` are eligible.
The existing R38 native report identifies each as three positive-edge FDPEs,
INIT1/ASYNC_REG1/CE1, stage0 D0, shared PRE from `ui_reset_pipe_reg[2]/Q`, and
early-stage Q fanout exclusively to the next D. The source is UI250; destination
clocks are the respective actual managed CPU/fabric clocks. The complete native
`domain0-reset-load-comparison.tcllist` and `domain1-reset-load-comparison.tcllist`
contain519 final loads each: 256 Gray FF CLR,256 binary FF CLR,7 sampled-event FF
CLR. The earlier `monitor-six-reset-ffs.txt` direct collection display truncates
its tail; it is not used as the complete load list.

The new helper re-proves these exact mapped identities, primitive types, pin
polarity, reset initialization, CE/D constants, clock connectivity, early fanout
and all519 loads **on the currently opened graph**. Old reports supply the
expected contract, never a new graph PASS. It accepts no broad CdcResetRelease
class, other hierarchy, early functional fanout, extra/missing consumer or unknown
property. The three-stage local release and all functional reset distributions
remain real hardware and normally timed.

After successful runtime inspection/review, the only mutation is
`set_false_path -to` the exact six sourceRelease PRE pins. This intentionally
removes their **recovery and removal** checks. It is not an assertion-only cut.
No later D, functional CLR, whole cell, clock group or through-path is excepted.

## Invocation on the already-open diagnostic DCP

    source /exact/tools/fpga/common/dynamic/dynamic_clock_constraints.tcl
    source /exact/tools/fpga/common/dynamic/monitor_reset_entry.tcl
    set plan [monitor_reset_entry::inspect]
    # Save/review plan with input DCP/tool hashes before allowing mutation.
    monitor_reset_entry::apply $plan

Source performs no native query or constraint action. `inspect` is read-only.
`apply` repeats inspection and requires an identical plan, then proves retained
paths before and after the six-PRE exception. The mutation is one-shot; even a
partially failing native command cannot be retried by sourcing the helper again.
Open a fresh original checkpoint for any independently authorized retry.

There are24 bounded native timing queries: per bank, two exact interstage pairs
and one exact519-CLR group, max/min, before/after. Grouped queries use nworst1 and
max_paths equal to the endpoint count. Returned count **and exact unique endpoint
set**, startpoint, clocks, finite slack/requirement, normal period/zero requirement,
and no existing exception are checked for every path. Attributes are fetched in
batches with exact cardinality checks, not one native call per attribute/bit.
Every retained result must be unchanged after the cut. Missing/duplicated paths,
path-group truncation or unsupported properties fail closed; coverage is never
reduced to fit a report limit. Negative slack is retained and reported as such,
not converted into timing signoff. Complete scenario STA is still required.

Cell lookup is scoped to the two monitor domains plus the exact source reset
register family, not a whole-chip CDC collect. Query caches exist only during one
inspection/application and are discarded afterward. No cache crosses opt, route,
mode changes or a reopened checkpoint. Actual elapsed native time is pending;
mock runtime and query counts do not establish the600-second native limit.

## Tests and remaining evidence

`tclsh fpga/common/test_monitor_reset_entry.tcl` passes one structural positive
and21 negative cases. They cover FF type/init/ASYNC/polarity, CE/D constant,
early fanout, missing final load, foreign clock/buffer/reset source, extra stage,
missing/duplicate timing endpoint, truncated property vectors, nonfinite timing,
pre-existing functional exception, changed retained timing, changed approved
plan and re-source after partial mutation. These are ordinary helper checks
against perturbed observations, not fake fatal exits inserted into the helper.

Before use for a native diagnostic result, bind the exact helper/dependency hashes
and input DCP, inspect the real plan, preserve the original checkpoint/reports,
measure elapsed time, and archive the full after-cut native STA/coverage result.
This helper alone does not qualify operating modes, produce a bitstream or prove
on-board reset behavior. CPU300/fabric250 performance evidence stays unchanged.
