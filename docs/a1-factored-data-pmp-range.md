# A1 factored generic data PMP ranges

Status: bounded component and full-CPU equivalence checks pass, but matched
isolated FPGA mapping shows substantial resource regression. This candidate is
not promoted; the original high-throughput profile remains unchanged. No routed
frequency, whole-CPU area or speedup claim is made. This is a separate, default-disabled
experiment based on the high-throughput elastic-proof profile, not on the
registered-raw profile with its additional raw-request latency.

## Scope and contract

`full-r1-m3-checked-flow-store-row-elastic-proof-factored-pmp` differs from its
elastic control only in `factoredDataPmpRange = true`. The memory policy checks
the final configuration and rejects use of the old policy label. Public and old
named profiles remain unchanged. The flag is wired only to the main, generic
legacy DTA PMP checker. The next-line checker, page walker, precheck, instruction
checkers and registered `DataPhysicalPermissionEvaluator` remain unchanged.

`PmpGenericRangeComparisons` is a separate combinational module with one address
and size input, full 65-bit lower/upper bounds per entry, and overlap/covers
outputs. It has no registers, queue, ownership, credit or handshake. Nominal
cycle latency is unchanged, initiation interval is one, and there are no new
capacity or backpressure conditions. A zero-entry `PmpChecker` still permits
access directly and does not instantiate the module. Aligned-word, natural,
aligned-line, decoded-word and shared-aligned modes cannot combine with the
factored generic constructor option.

## Exact generic arithmetic

All sizes 0..7, arbitrary byte alignment and full unsigned 65-bit bounds are
supported. The 64-bit request address is zero-extended; its final byte is
address + (2^size - 1), including an end above XLEN. Neither region ordering nor
four-byte-granular bounds is assumed. Each request computes one eight-bit sum
of its low seven address bits and the seven-bit last-byte offset. Complete
58-bit high-address comparisons run in parallel. If that low sum carries, an
equality against the nonzero bound's high predecessor selects the exact
adjacent-block result. Each predecessor depends only on its bound and is
computed once per bound inside this checker. `PmpState` is not widened.

The checker retains its original regionActive, permission, lock/M-mode,
first-overlap priority, whole-range coverage, default denial and optional
summary policy. Only overlap/covers predicates change. The unused generic
65-bit endpoint adder is not elaborated in the factored branch. No assumption
about legal cfg encodings or narrower producer-generated PA bounds is needed.

## Risks and required verification

Extra adjacency equalities, muxes and bound-only subtractors may increase LUTs,
fanout or delay. Shortening the request-dependent carry chain is structural
intent, not evidence of better synthesized or routed timing. Both request and
PMP-state cones need inspection. Do not automatically promote the candidate.

Independent validation must compare the direct range module and complete
0/8/16-entry checker against full-width unsigned interval and permission
oracles, with arbitrary/reversed/high bounds, bit-64 carry, sizes 0..7,
TOR/NA4/NAPOT decode, overlap priority, all privilege/access/lock combinations,
and optional summaries. Existing exact source-derived aligned-mode mutants
were regenerated from the changed production checker using the same declared
single mutation per file; source-preflight gates remain strict and the frozen
R6 reference and independent CSR oracle are unchanged. No historical hardware
PASS is silently reinterpreted as validation of this new branch.


## Completed component and structural evidence (2026-10-25)

The fresh GSIM matrix uses actual old and candidate `PmpChecker` instances with
0, 8 and 16 entries and exported decision summaries, plus the direct production
range module. All 346,696 input trials pass the independent full-width interval
and permission oracle. Coverage includes 89,734 low-block carry trials, 19,656
XLEN-carry trials and 52,280 producer-decoded trials. Coverage counters can
combine observations from several checkers; they are not separate benchmarks.
Five exact source-derived RTL mutants are rejected: lost low carry, lost request
bit 63, lost bound bit 64, strict upper comparison and lost whole-range cover.
A separate oracle-observation mutation is also rejected. These negative controls
are not a formal proof for every possible input.

The actual emitted CHIRRTL passes the fail-closed structural checker, independently
repeated. It contains exactly three reachable production range instances in the
matrix (candidate 8, candidate 16 and standalone 16); mutant classes are not
counted as production. Each range module has one shared 7+7-bit addition with an
8-bit result, one state-only 58-bit predecessor subtraction per bound, and no
register, memory or child module. The complete high-bound arithmetic and all
output dependencies are retained. Each factored parent checker has one range
child and no direct endpoint arithmetic outside it. The original request-side
65-bit add is therefore absent in this generated candidate, not merely disabled
by an input assumption. Fifteen synthetic parser tests exercise acceptance and
rejection behavior, but those tests are not substituted for the actual FIR audit.

Component receipt:
`build/gsim/factored-pmp-ranges-20261025-r1/receipt.json`.
SHA-256: `500f923640d734f491a6e109932bb2cadb03014f045c589bc0f016619ad95ada`.

Actual FIR SHA-256:
`3939b92a93146bf56df8800f4425308fc087f86748a14566259d21de7c84373e`.
Structural report SHA-256:
`bc22869573042f2aa37844356a6790fb98495775b245eb9165d2c994772ef85e`.

This establishes bounded functional equivalence and generated arithmetic shape,
not improved PPA. Additional equalities and state-bound predecessor chains can
cost LUTs or delay despite the shorter request-side arithmetic. Full CPU cycle comparison and same-tool mapped resource measurements are reported
separately below. Yosys mapping is a technology-mapped estimate, not routed Vivado
timing, board Fmax or 300 MHz qualification. Defaults and old profiles remain
unchanged; the observed resource tradeoff does not justify promotion.


The separately emitted full CPU candidate also passes the same generated
structural audit. Exactly one production range module is reachable, at
`CommonA1VmPipelineGsim.tile.core.adapter.legacyPmp.factoredRanges`; its parent
checker has no direct endpoint arithmetic. This confirms the intended sole
use site, not complete CPU functional or timing equivalence. CPU FIR SHA-256:
`f2ad0bd763ed66bb30e03ae192191c2cd24729dd14bc4679130e265bba78640f`.
Independent CPU structure report SHA-256:
`2a057132b9e65a86363ca0eea9fd15bd574cd3d89428c532eed3608a2264460b`.


## Full CPU equivalence and failed resource gate

The single newly built candidate ran four immutable guests and exactly matches
the same-tool-epoch control replay: stream 681 cycles, dependency 1,018, hot-load
ROI 531 and cold-load ROI 360. The existing control executable and objects were
content-bound and replayed, not silently presented as a newly built control.
Independent architecture, bytes, physical traffic, forwarding and stage metrics
match. This confirms no measured cycle cost in the tested workloads, not a
speedup or exhaustive CPU equivalence. The first runner attempt failed before
emission on bookkeeping; it remains preserved rather than overwritten.

CPU receipt:
`build/gsim/factored-data-pmp-cpu-20261025-r2/receipt.json`.
SHA-256: `efc6765e640a81d7a0ca841423467074314b6dfa8e63e6414e47c74571beea3f`.

The same lowered component FIR and matching ports were mapped to Yosys `xcup`
primitives under two identical policies per old/candidate pair. Results are for
standalone complete checkers with exported decision summaries and unconstrained
65-bit decoded-state inputs, not the final CPU's correlated PMP producer or
physical implementation. No placement or routing was performed.

| Entries / mapping policy | LUTs, control → candidate | CARRY4, control → candidate | Longest unweighted primitive path |
| --- | ---: | ---: | ---: |
| 8 / default | 1498 → 2113 | 209 → 354 | 31 → 31 |
| 8 / no wide LUT | 1458 → 2095 | 209 → 354 | 26 → 24 |
| 16 / default | 2907 → 4304 | 401 → 706 | 31 → 36 |
| 16 / no wide LUT | 2904 → 4177 | 401 → 706 | 27 → 25 |

The default eight-entry address-input path shortens from 29 to 20 primitive
cells, but the state-bound path grows from 16 to 31. This confirms the risk of
moving the long arithmetic chain onto bound predecessors. Unweighted primitive
counts treat different cell types equally and are not nanoseconds, slack or
Fmax; the alternate mapping policy's shorter cell count cannot offset the
resource regression by itself. LUT growth is about 41–48% in default mapping
and 44% in the alternate policy. Whole-CPU resource deltas remain unknown.

The candidate is retained only as a tested optional experiment and negative
resource result; it must not replace the control without new compelling
physical evidence. A later exact successor-relation experiment may remove the
bound subtractors, but it is a separate, unqualified design and could still
increase area. No change to this frozen candidate is implied.

Mapping receipt: `build/pmp-generic-mapping-20261025-r1/receipt.json`.
SHA-256: `6c856e2574fcff65d1ea3d4c3c827b06adb2b497d379be843138a698229a22b0`.

A separate unconstrained eight-entry combinational SAT miter compared denied
and all exported decision-summary outputs with arbitrary cfg, full 65-bit raw
bounds, active bits, address, size, privilege and access. Its 60-second attempt
timed out after about 61.2 seconds: `UNKNOWN_TIMEOUT_NOT_PROVED`, not a proof and
not a discovered counterexample. The bounded simulation and structural results
above must not be relabeled formal equivalence. Evidence:
`build/pmp-generic-mapping-20261025-r1/formal-receipt.json` and `formal.log`.
