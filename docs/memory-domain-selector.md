# Three-domain memory-selector preparation

This stage prepares one production routing surface for integer, explicit-H and
FP memory. It does **not** enable an H+FP core. Both `MachineSystemUnit` and
`IntegerBackend` admission guards, all public defaults, two-issue width and ISA
and firmware declarations remain unchanged. The component fixture is not an
executing guest F/D CPU, a trap handler or a software context-isolation proof.

## Production contract

`ProtectedSystemOwner` captures the full ROB token and protected SYSTEM memory
classification at accepted `unit.io.start.fire`. `MemoryDomainSelector` uses
that captured classification, not live request valid, privilege, CSR context or
the next instruction's decode. Protected explicit-H memory selects H; protected
FP memory selects FP; otherwise integer remains selected. FP arithmetic does not
claim the FP memory domain. Simultaneous protected H and FP memory ownership is
invalid and asserted, not silently resolved by fixed priority.

One domain selects the entire native request, its return ready, response valid,
response ready, native data/error/page-fault fields and complete guest metadata.
An unselected client cannot accept a request or response. The existing integer
reservation queue remains the integer slot owner. The selector creates no new
queue, return credit, transaction identity or scheduling policy.

Successful SYSTEM ownership lasts through the matching retirement, including
commit stalls after native response acceptance. Native response consumption
alone does not release the protected epoch. Existing accepted exceptional
completion handling remains separate from successful retirement; this stage
does not introduce cancellation or interrupt behavior.

Memory-drain status includes integer memory, H LSU and FP memory-pipeline busy,
plus the previously supported posted/prefetch contributors. Architectural FP
state busy is not memory-pipeline busy: a faulted architectural owner can remain
live pending a precise trap after the memory queues have drained. Substituting
architectural busy here would block trap admission.

The H path remains untagged. Existing host-only FP return handles cross payload
conversions explicitly and remain a reservation namespace, distinct from the
full ROB token. No tagged H profile is admitted. The default no-H/no-FP wiring
remains direct.

## Latency, capacity and qualification target

Routing is combinational and adds no mandatory request or response cycle, state,
queue capacity or credit. Its target is one selected transfer per cycle when
the existing owner and both endpoints permit it. A held request or response
must keep its full payload and selected domain stable. Existing FP buffer
latencies, two-credit capacity and full-queue no-refill behavior are unchanged.
One executing protected memory owner remains the conservative baseline; this
is not a new concurrent or fair arbiter.

The focused fixture uses one clock, real production owner/selector logic and
independent native expectations. Its domain sequence exercises integer, H and
FP handoffs in both H/FP orders, delayed request acceptance, delayed response,
consumer stalls and successful post-response retirement stalls. Metadata cases
include zero, successful guest-address provenance, explicit guest faults and
implicit VS-PTE guest faults. A host-only tagged lane checks return handles
without enabling tagged H. Each lane also accepts an eight-request integer
stream on consecutive cycles, with seven simultaneous response/request
turnovers. This checks the selector’s zero-bubble target at the component
boundary; it is not actual-core throughput. Fixture requests, responses and
retirement inputs are component stimulus, not fetched instructions or actual
CPU trap execution.

## Reproducible focused entry

Use an installed, verified pinned repaired GSIM toolchain and its matching
compiler/dependency cache. The entry calls `common.setup(False)` and does not
download, fall back to another simulator or accept an unverified reuse option.

```sh
python3 -m unittest discover -s simulator/gsim -p test_memory_domain_selector_entry.py -v
mill -i IonSoC.memoryDomainSelector.compile
mill -i IonSoC.memoryDomainSelector.testOnly \
  ooo.MemoryDomainSelectorConfigSpec ooo.FpGuestMemoryConfigSpec \
  ooo.DualFsPreparationConfigSpec
GSIM_CXX=clang++-19 make gsim-memory-domain-selector-test \
  MEMORY_DOMAIN_SELECTOR_ARGS="--output /absolute/fresh/workspace-output/model"
```

The default model destination is `build/gsim/memory-domain-selector`. An existing
destination is rejected, even when empty; preserve it and choose a new path.
`IonSoC.memoryDomainSelector` compiles every production and HardFloat source,
with only the new fixture/configuration test and prior FP memory/dual-FS
configuration tests. The three configuration suites contain 5 + 6 + 6 checks.
It does not compile the broad `IonSoC.test` source set.

Only one new model is generated and compiled. Both deterministic schedules and
all 11 named negative controls execute that same newly built executable within
the run. The baseline and staggered schedules contain exactly 877 and 1,261
cycles, including two initial idle-reset cycles, 32 busy/classification probes,
the nine-cycle continuous stream, 64 matrix cases per lane and two final idle
cycles. Each schedule transfers 72 requests and 72 responses per lane.
ASan/UBSan and fatal sanitizer behavior remain enabled, with bounded
native executions. Raw observations and exact summaries are checked together.
A negative is accepted only for exit status 1 and its exact named diagnostic;
an unexpected pass, sanitizer report, crash or timeout is a failure.

The output contains `MemoryDomainSelectorGsim.h`, the generated native sources,
`run`, generation/compile logs, `test.log`, `staggered.log`,
`raw-baseline.jsonl`, `raw-staggered.jsonl`, all `negative-*.log` files and
`entry-summary.json`. Native success is exactly one
`MEMORY_DOMAIN_SELECTOR_SUMMARY` JSON line. The entry emits
`MEMORY_DOMAIN_SELECTOR_STANDARD_PASS` only after both schedules, both raw
traces and every negative have been checked. Each raw JSONL trace has one
schema/header row, contiguous cycle observations for both lanes and one exact
summary footer. All interface types and widths are validated, and transfer,
owner event, stall and coverage counters are cross-checked against raw rows.

The named controls are `owner`, `classification`, `request_payload`,
`request_exclusion`, `response_payload`, `response_exclusion`, `metadata`,
`handle`, `stall`, `busy` and `retirement`. Each deliberately corrupts a checker
observation, not the driven RTL input or the frozen expected totals. The entry
requires the exact checker name, lane and deterministic baseline cycle, with
exit status 1 and no other output. This establishes checker sensitivity, not
faulted-owner, cancellation or reset recovery coverage.

The 33 Python tests mock every tool build and native execution. Passing those
tests proves orchestration behavior only, not hardware behavior. The commands
above are reproduction instructions, not a claim that this source revision
has passed them. Retain source/tool identities, phase receipts and raw logs
alongside the run when reporting validation.

## Resource and preservation boundaries

Run one supervised heavy phase at a time. Route **new** Mill output, HOME,
XDG cache, compiler temporary output and `TMPDIR` into fresh workspace-local
directories; explicitly route JVM `-Djava.io.tmpdir` too. Reuse only the already
verified tools and dependency cache in place, not stale classes or models.
The supervisor, not this repository entry, owns filesystem measurements and
termination on capacity limits.

The reviewed component envelope is 192 MiB aggregate new workspace output and
16 MiB `/tmp` spill, including failed attempts, reports and archives. Admission
requires 336 MiB workspace free, 128 MiB `/tmp` free and 3.5 GiB MemAvailable.
Preserve hard reserves of 128 MiB workspace, 96 MiB `/tmp` and 1 GiB available
RAM; the sampled process-tree RSS cap is the smaller of 3.5 GiB and launch
MemAvailable minus 1 GiB. The overall supervised wall limit is 1,200 seconds.
These are abort budgets, not proof that a larger model fits. No evidence,
cache, Git alternate store or previous output may be deleted or overwritten
to make room. Preserve partial output if a phase stops.

## What remains unqualified

Actual H+FP admission, dual-FS wiring in the actual system, real guest full-F/D
arithmetic/memory, precise VS/VU-to-HS trap handling and all-32-FPR/fcsr eager
host/guest-A/guest-B/guest-A/host software context round trips remain separate
gates. Component metadata fault inputs are not an actual-core fault program.
The single physical FP register/fcsr bank still needs explicit software
management; FS=Initial does not initialize it.

No IRQ/fault-overlap cancellation, reset while an owner is live, restricted
M-origin guest-page-fault review, independent clocks, Yosys, Verilator, OS boot,
ISA-wide compliance, board, multicore, PPA or speedup work belongs to this stage.
No full-core build is implied by the component capacity envelope. Physical
timing/resources and end-to-end actual-core throughput remain unmeasured.
