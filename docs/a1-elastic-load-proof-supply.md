# Experimental elastic load-proof supply

Status: focused configuration, tiny-module and four actual-CPU guest checks passed. No frequency, PPA,
board or DDR-bandwidth qualification is implied. Selected, FullCandidate and all existing named
profiles remain unchanged.

## Measured reason for this experiment

The saved prepared-store-row CPU was exercised with separate, independently checked hot and cold
load guests, not the earlier 233-retirement store microbenchmarks. The hot guest retired 256 useful
loads in 784 ROI cycles. Of its 255 admission gaps, 254 were three cycles and the initial raw-head
gap was seven. A passive trace preserved the complete hot metric line and all 292 parsed leaf
values exactly.

Every owner after the first began its first proof query one cycle after the previous actual LSU
issue. The steady sequence was query, translated register, then permission register and issue.
During all 508 steady proof-wait cycles there was a real empty LSU slot, all existing owners were
parallel, and cache response ownership was at most one. The conservative serial gate correctly
blocked a load whose proof still named the previous owner. This identifies a proof-supply limit,
not exhaustion of the four LSU slots or external DDR bandwidth.

The cold guest independently demonstrated two real demand miss owners, tracked by accepted
TileLink source and cache MSHR identity. Its 16 useful ROI loads took 360 cycles under a named
32-cycle data-response service. Neither result uses real DDR: the fixture returns a 512-bit whole
line and does not drive the 64-bit D beat stream. The existing hot/cold guest, service, oracle and
receipts remain separate and unchanged.

Evidence: `build/gsim/independent-load-supply-20261024-r1/manifest.json` and
`build/gsim/hot-load-proof-analysis-20261024-r1/manifest.json`. The reviewed design is retained in
`build/gsim/elastic-load-proof-proposal-20261024-r2/proposal.md`, SHA-256
`47caaf6adc8694235bfc4732da8ad96c160bc906ca3962c724a48bbd564a5b2c`.

## Narrow candidate and declared cost

`elasticLoadProofSupply` defaults to false. The only new explicit profile is
`full-r1-m3-checked-flow-store-row-elastic-proof`, differing from its prepared-store-row control
only by that flag. Its distinct memory policy rejects using old policy names for the new topology.
No runtime or whole-SoC selector is extended in this experiment.

The legacy `VirtualRamLoadPreparation` class is unchanged and remains the disabled branch. A new
typed module uses one registered second-rank descriptor D and retains the existing translated T
and permission-result R stages. It reuses the already computed early planner.second VA rather than
late planner.useSecond. There is no new PRF read, address adder, TLB peek port, result-bank PA mux,
MSHR or bus credit.

At ROB16/tag64, D is token68 + VA64 + size2 + epoch32 + valid1 = 167 declared bits. T is the existing
231-bit certificate plus valid and normal-memory bits, 233 total. R is that certificate plus valid,
232 total. Total declared D/T/R state is 632 bits versus 465, an increment of 167. Token widths are
parameterized; these counts are not synthesized flip-flop or area measurements.

Real added combinational costs are the current-versus-D 64-bit query mux, token/size selection,
three full-key/reservation comparisons, indexed owner-liveness checks, and elastic hold/preemption
control. The original two lookup/PMP register boundaries remain. Current-query minimum latency is
two cycles; D capture to permission minimum is three. Backpressure or advisory preemption may add
cycles. This is not a fixed-latency promise or a 300 MHz result.

## Ownership, credit and progress

- A reservation key is full token, VA, size and authorization epoch. Same token with a differing
  VA/size is an inconsistency to discard, not permission to create a second owner.
- Current missing work has priority; exact current D is promoted. Exact current T/R suppresses
  repeat queries. Positive R is held until actual issue or cancellation. Negative R reserves its
  owner for its full one-cycle publication, then expires, allowing a later same-epoch hit retry.
- The single peek is hit-only and never starts a demand or walk. Misses and denied PMP, PBMT,
  alignment, RAM-range or page-offset checks produce only negative optional certificates.
- R credit is raw pre-edge empty. T may accept while its old owner transfers to already-empty R.
  D only captures while raw pre-edge empty, with no same-edge D transfer/refill. No actual issue,
  cleanup, negative expiration or late recovery is borrowed as current-cycle storage credit.
- D capture excludes both resident tokens and a query actually accepted into T on the same edge.
  A valid response with a stale epoch is not query acceptance and does not consume D.
- Tentative next payloads are chosen before cancellation. Issue/death/stale/preemption cancels
  that exact selected next owner, including transferred copies, not an unrelated replacement of
  the old slot. Wide payload write enables use local empty/advance conditions, not late issue or
  an AGU-through-dedup capture enable.
- A newly ready current owner can clock-discard blocking noncurrent advisory T/R. An exact current
  positive R or inflight T is protected. This is disposable preparation, not accepted ownership.
- Prepared validity and query/credit never depend on actual issue or late kill. Full-token pending
  metadata and stable epoch qualify proofs; the existing late recovery/IRQ/system gate still
  authorizes every real LSU launch. Ready head fallback remains immediate and serial.
- D/T/R never contribute to memoryBusy, ownersIdle or CSR/FENCE/IRQ/park drain. Context operations
  may discard them, while already accepted LSU/cache owners drain under the original contract.

With continuous early first/second candidates and no unrelated stalls, the intended narrow
schedule is A query0/issue2, B query1/issue4, C descriptor3/query4/issue6. The target is II2, not II1.
The unchanged two-rank selector exposes a third owner only after issue. Even independently supplied
proof II1 would face the observed six-cycle LSU residence and four-slot occupancy bound of at most
2/3 useful load per cycle if residence stays unchanged. The measured narrow experiment below reaches predominantly two-cycle hot-load admissions, not one per cycle.

## Focused validation and results

One unified Scala compile and nine focused configuration/elaboration tests passed. One tiny real
module model passed 685 cycles, 59 independent byte-PMP cases, full-owner cancellation/retention
checks, and three exact-marker sampled-observation negative injections. Its 48 distinct warm
owners required exactly 48 queries and had 47 issue gaps of two cycles. Additional witnesses
included 55 no-same-edge-consume credits, 49 no-D-refill opportunities, eight T turnovers, nine
inconsistencies, three epoch cancellations, and a preempted T-to-R copy canceled without erasing
its unrelated replacement. These are standalone contract results, not whole-CPU throughput claims.

A single fresh CPU model was compiled once and linked to two hosts. The old prepared-store host
was used byte-for-byte for its two original guests; a private adapted load host retained the exact
hot/cold programs, independent data/retirement oracle and service laws. Saved control models were
not rerun. All four guest oracles passed, including final GPRs, architectural load readback, precise
terminal traps, full-token/source/sink matching and accepted-owner drain. Two sampled-observation
CPU negative controls also failed with their exact expected markers and diagnostics.

| Same guest and service | Control work cycles | Candidate work cycles | Control ROI | Candidate ROI |
|---|---:|---:|---:|---:|
| VM store stream, 233 retired | 687 | 681 | 519 | 513 |
| VM dependency, 233 retired | 1071 | 1018 | 903 | 850 |
| Hot independent loads, 557 retired, 256 useful ROI loads | 1760 | 1253 | 784 | 531 |
| Delayed cold loads, 79 retired, 16 useful ROI loads | 906 | 906 | 360 | 360 |

The stream saves six cycles, not 48; dependency saves 53. Both preserve 48 actual successful M3
forwards and 49 store requests/replies/completions. Stream still uses 48 prepared-store starts and
one cold fallback; dependency still uses 49 fallbacks and no prepared-store capture. All per-owner
DTA latency categories are unchanged: prechecked two, warm raw store/load two, first cold store 24
cycles. The stream improvement is localized to six successive tail-load timestamp advances in the
recorded owner log; this is not a new claim of faster store replies. The dependency has earlier
load/store admissions, not changed DTA service latency.

The store guests' trap-bounded instruction beat counter changes from 136 to 135 because the trap
arrives earlier; their full drained instruction requests and beats remain 136 each. This difference
is preserved in the receipt, not hidden under an assertion that all non-cycle metrics are identical.

### Hot end-to-end result

- 256 useful loads in 531 rather than 784 ROI cycles: 0.482109 rather than 0.326531 load/cycle.
  This is 32.27% fewer ROI cycles and 47.65% more useful loads per ROI cycle for this fixed guest.
- Actual admission gaps change from 254 gaps of three plus one of seven, to 253 of two, one of
  three and one of seven. Do not describe every gap as two or claim sustained one load/cycle.
- All 256 ROI physical accesses remain actual L1 hits. ROI data A/Grant/E is zero on both sides.
  Whole-work data A/Grant/E remains one each; instruction A/response beats remain 26/187, and
  PTE requests remain three. The gain is internal useful load supply, not external bandwidth.
- Exactly 256 ROI proof queries are accepted, 255 from registered D. There are no ROI negative
  expirations or advisory preemptions. Observed query gaps are one gap of one, 252 of two, one of
  three and one of six cycles. The first raw-head load need not wait for its optional proof.
- LSU live occupancy reaches three instead of two, with three owners live for 504 of 531 ROI
  cycles. Start-to-physical remains three, physical-to-reply one and start-to-completion six for
  all 256 loads. This changes supply spacing and overlap, not that downstream latency chain.
  The ROI also has 28 empty fetch-packet cycles versus seven in the control, so continuous useful
  work is not assumed from the benchmark name. Start-to-retirement does have one local regression: its distribution changes
  from `{6:256}` to `{6:255, 7:1}`. The fourth LSU entry, cache ports and permission registers
  were not removed.

### Cold result and actual concurrency

The delayed-cold ROI remains 360 cycles and 0.0444444 useful load/cycle. Both sides have exactly
16 real misses and 16 accepted data A/Grant/E transactions, with 32-cycle A-to-Grant service and
no prefetch transactions. Two actual demand MSHRs are live for 252 ROI cycles on both sides.
The stronger source-to-MSHR witness, requiring two accepted ungranted non-prefetch demand owners,
increases from 196 to 203 cycles, with longest contiguous span 28 to 29. This small overlap change
does not improve completed useful work per cycle.

Cold admission gaps change from `{3:8, 33:1, 35:5, 43:1}` to `{2:8, 36:6, 43:1}`; full LSU occupancy
increases from 226 to 228 ROI cycles. Local residence does not improve uniformly: start-to-physical
changes from `{3:3, 35:2, 37:11}` to `{3:3, 37:13}` and start-to-completion/retirement changes from
`{42:3, 74:2, 76:11}` to `{42:3, 76:13}`. Physical-to-reply remains 37 for all 16 loads. These are
measured histogram changes, including two samples shifted by two cycles; the available owner log
does not establish a per-PC causal attribution for those particular samples. No additional trace
was run to manufacture that attribution.

The unchanged cold total alongside earlier admission opportunities illustrates the distinction between removing a CPU proof
supply gap and a miss/service-limited end-to-end path. It is not evidence that DDR is saturated or
that increasing bus occupancy alone improves performance. The host retains total A capacity 16;
it does not artificially cap all traffic to two. The true two demand MSHRs are observed internally
and matched to accepted external source owners. The 512-bit whole-line-return limitation remains.

## Evidence, failed attempts and exact reuse scope

- Tiny model: `build/gsim/elastic-load-proof-component-20261024-r1/receipt.json`, SHA-256
  `f51caa70ea052859bd37cd06f9c7b06701ba87be8695209ef78b2a1ff6704c58`.
- Final CPU evidence: `build/gsim/elastic-load-proof-cpu-20261024-r3/receipt.json`, SHA-256
  `c72263ca5bc5df808a7575ff76ce833aaff7d016fe05f782cd915ce782c87421`.
- Complete field comparison: `build/elastic-load-proof-20261024-r1/results-summary.json`.
- CPU r1 strictly refused reuse because the unchanged dispatch-bound assertion's automatic
  diagnostic moved from IntegerBackend.scala:3472 to :3520. Its failure receipt and raw/source-only
  diff remain intact. Root reviewed the complete same assertion, clock, predicate and label and
  approved only that exact diagnostic substitution, once. After excluding source annotations and
  this single approved string, the control FIR hashes both equal
  `616d69ee50d80c50938c46c528b476b1ed943f5e331dfb868b589761fceb68e1`.
  Raw FIR bytes are not equal; no general diagnostic normalization or semantic-equivalence claim
  was substituted for this bounded check.
- CPU r2 executed all four guests and both negative controls successfully, then its summary parser
  rejected the expected name `cold_loads` because the unchanged real guest is `delayed_cold_loads`.
  The FAIL receipt (`3694e4f3e84077dd5ce119d29aa826b0f1453b2f93179506bc5e3e2afed25c62`),
  execution logs, hosts and model remain unchanged. The corrected r3 finalizer bound their hashes
  and re-read the existing outputs with zero new DUT compilations, host compilations or executions.
  This was a reporting-name failure, not a hidden DUT rerun.

All production/host execution inputs stayed frozen through the actual runs. This report was
completed afterward. No full GSIM, Verilator, long Linux, new Vivado implementation or board test
was run. The four bounded guests and tiny oracle do not establish general workload performance or
full architectural verification.

## Next qualification boundary

Keep the new flag default-off and the runtime/SoC selection unchanged. Do not add an independent
proof frontier or another result bank merely to chase a nominal II1: the present experiment already
separates a large hot-supply improvement from no cold end-to-end gain. More representative workload
coverage and structural/physical evidence for the new query mux, full-key/live-owner checks and
hold controls are needed before a broader adoption or frequency claim. The declared +167-bit state
and unmeasured control-path cost are real tradeoffs, not a free speedup.
