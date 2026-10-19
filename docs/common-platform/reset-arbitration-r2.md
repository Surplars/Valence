# Reset-defined shared-platform arbitration candidate

Baseline: `df9821cd8be30898bf289a06350dd49d5ad65b66`.
The previously delivered board bundle is superseded by this reset repair after
affected CPU validation. Its recorded short guest and full-ROM banner passes remain valid
for those exact tests; a new early-DDR workload exposed an uncovered first-owner
sequence. Neither physical implementation nor board qualification has occurred.

## Reproduced cause

The unchanged A1 workload's first data read targets `0x80210000`, source 8,
size 6. The 34-line native trace records router ownership before the response.
On the first bank-1 D beat, the router host sees VALID/READY=1/1 while the bank
sees VALID/READY=1/X: library round-robin `lastGrant` has no reset value.
The host counts an extra beat, releases the source one beat early, and the
unchanged source-owner assertion rejects the remaining response. There was no
invalid testbench ID/address or simulated timeout. This is a demonstrated
four-state initialization/acceptance defect; it is not a claim of measured
silicon failure.

## Bounded repair

`ResetDefinedRRArbiter` uses one reset-defined selection for chosen, VALID,
payload and all READY outputs. Five reachable instances are repaired together:

- two-bank router D replies
- shared outstanding AXI bridge AR selection
- coherent write dispatch
- A1 parallel LSU requests and completions

The reset last-grant is `n-1`, so first simultaneous requests prefer index zero.
After every accepted transfer, the policy is the existing cyclic priority after
that accepted index. Invalid-input READY is only asserted for the selected index;
no valid request's acceptance is changed in a known equivalent priority state.
There is no data pipeline, payload capacity reduction, lock, or added cycle.
Internal LSU offers may still be cancelled before acceptance. Existing ownership,
burst, real-response completion and source checks remain enabled.

## Component validation

One Scala compilation passed. Native four-state fixtures cover n=2/3/4, every
first input after cold reset, all nonempty offered masks from every possible
last-grant state established by actual singleton acceptance, sustained all-input
round robin at one transfer per cycle, stalls, cancellation of unaccepted offers,
and reset while an offer is pending. Separately initialized two-state legacy
references obey the same independent cyclic-selection oracle for all starting
priorities. The original uninitialized n=3 arm fails the first-index-1 negative
control on READY=X, not by timeout. Receipt/log hashes are in the sibling JSON.

The fixed helper is combinational (zero added cycles) and introduces no owner
credits. Parent queues and capacities are unchanged. This component result does
not qualify whole-CPU throughput or physical timing. Original short boot and the new identical no-wait performance guest now pass on
both repaired CPU selections. Full physical gates still apply.

## Affected CPU validation completed

Both full-size CPU profiles passed the unchanged original short guest: exact
`COMMON\r\n`, 11 reads, 9 writes, 9 real B completions, timer and MSI, three
FENCE.I operations, and dirty code replacement returning 9 then 42. New native
and production emissions use identical 307-file source and 4267-file compiled
classpath maps. A1 severity-preserving sv2v retains all 586 `$error` and 586
`$fatal` calls. Source, classes, emitted artifacts and executable test inputs
were independently hash-checked.

The new same-load, no-UART-wait guest that exposed the bug now passes on A1,
including 192 completed reads, 64 real B completions and all 512 copied words.
Its deliberately wrong expected word 31 is rejected by the independent HDL
oracle, without timeout. I1 also passes, with every window field and timestamp
unchanged from its pre-repair reference. A1 observes two simultaneous read owners
in the cold-copy window and two write owners in the separate drain window.
The program executes from ROM; I1 instruction accesses there are uncached. These
figures include fetch/branch/dependency costs and do not establish pure L1
bandwidth or a hardware bottleneck.

## Structural cost, not timing signoff

Ten bounded mappings compare the five actual old/new specialized modules, with
port/instance and emission hashes checked. Sum FF remains 7; LUT 1303→1300;
MUXF remains 102. Overall maximum primitive layers remain 1/3/2/1/1. However,
AXI AR ready[0/1] and input→out_valid locally grow from one to two layers, and
FFQ→out_valid/CE gain two-layer paths. The other four instances have no measured
per-output depth increase. New reset directly reaches six FDPE and one FDCE
previously implemented as seven FDRE; zero reset logic levels does not imply
zero routing or recovery/removal cost. No Fmax or route margin is inferred.

The same full 128KiB ROM image is retained. Its complete banner run belongs to
the prior df9821c baseline and was not repeated for this bounded repair; the
replacement package records that reuse and its exact seven source-map changes
explicitly. It does not convert prior full-ROM or physical results into new
qualification. The optional next-line timing experiment remains disabled.
