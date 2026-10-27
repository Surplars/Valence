# Optional buffered return flow and fixed-row issue identity

This is a private, default-off experiment on the qualified buffered-third-rank
control at `7daf1190db48b37214f73a2fdd68a9fd0dbff3aa`. It is not a new public
default or a board/Fmax qualification.

- Capability: `bufferedReturnFlow` in `FpgaNextConfig` and `OooParams`.
- Profile: `CommonA1RebuildProfile.FullR1M3BufferedReturnFlow`.
- Exact name:
  `full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp-split-tag-buffered-third-rank-return-flow-index`.
- Separate memory policy: `CommonA1MemoryProfile.ExperimentalBufferedReturnFlow`
  (`experimental-buffered-return-flow`). Old policies still reject this recipe;
  the legacy managed-board factory does not accept it.

The exact control-to-candidate parameter delta is three booleans, representing
**two existing behavioral options plus their explicit permission capability**:

| Flag | Control | Candidate | Meaning |
|---|---|---|---|
| `bufferedReturnFlow` | false | true | Named configuration contract, not another data path |
| `translatedResponseEmptyFlow` | false | true | Empty response-buffer bypass with original storage/credits |
| `reconstructIssueTokenIndex` | false | true | Derive issue-row token index from its fixed slot |

Production changes are limited to four configuration/profile files. The existing
LSU, StoreBuffer, DataResponseBuffer and issue-index algorithms were not rewritten.
The exact fresh disabled CPU FIR equals the saved 7daf119 FIR after removing only
source-location annotations. PRF, banked issue payload, third-rank selector and
buffered proof modules are unchanged in the emitted comparison.

## Storage, ownership and timing contract

The translated response buffer still has **two storage slots**, maximum II=1,
old-head priority and occupancy-only enqueue credit:

- Empty and consumer ready: consume the arriving response without allocating a
  storage row. Data, error and pageFault follow the same accepted owner.
- Empty and consumer blocked: capture that response once; later present the saved
  head, without duplicate consumption.
- Nonempty: the old head wins over an arriving response.
- Full: no enqueue credit is borrowed from a same-cycle dequeue. This is not a
  three-slot queue or a zero-capacity wire.

The registered outer request FIFO, DTA request/checked-permission stages and
registered StoreBuffer response owners remain. The ParallelLSU ordered owner
queue remains **flow=true**; it must not be described as a registered owner cut.
Local StoreBuffer ACK/forwarding is still possible. Its saved direct/drain owners
must remain distinct from local replies. Four integer execution owners and the
LSU **result/done register** remain; live replies do not create current-cycle
completion or replacement start readiness. Early load completion, registered
load-result readiness, fast head-load retirement and fast buffered-store
retirement remain disabled.

FP retains its own registered-start LSU, non-flow response buffer and completion
queue. The exclusive FP epoch and complete integer drain requirement remain.
Cancellation suppresses architectural completion, not responsibility to drain an
already accepted memory response. Buffer idle alone is not global owner drain.

ROB16, PRF48, full64 generation tags, two-wide rename/completion/commit, four LSU
entries, two StoreBuffer entries, two demand MSHRs and existing cache/bus credits
are unchanged. This batch adds no issue/PRF port, execution slot or request credit.

The opportunity is a conditional one-cycle shorter empty return path. It is not
permission to predict 4/5 CPU throughput from an isolated four-owner model: the
unchanged three-rank proof supplier and other stages still constrain supply.
The real forward cone now includes DTA owner/fault selection, empty/head selection,
StoreBuffer and ParallelLSU owner selection, and load formatting before the
existing result register. That longer cone can cost timing even when cycles fall.

## Fixed-row index: valid-domain relation, not arbitrary-state equality

The backend allocation loop is the sole raw issue-queue writer. Its write address
is the accepted token index; rows do not move. After allocation, the OFF row's
stored index equals its slot. ON stores zero in that redundant raw field and
reconstructs the static slot in `issueEntries` **before every dynamic/one-hot
consumer**. Full64 generation tags, captured producer tokens and external token
indexes are unchanged; stale external indexes are never normalized.

The raw queue is not reset. `pending` and `memoryLive` are reset authorities, and
pending-false but issued/unretired rows can remain live. Thus the relation requires
written/allocation provenance for authorized uses. Unwritten invalid payload bits
need not agree across OFF/ON; controls and valid payloads, including stalled-valid
payloads, retain their defined behavior. The nominal redundant declaration is
16 x 4 = 64 bits; that declaration alone is **not evidence of a 64-FF saving**.
The actual combined mapped result is reported separately below.

Candidate observers distinguish packed raw stored indexes from reconstructed
consumer indexes. Their ABI is explicitly ON + ROB16 + full64-tag + LSU4. There
is no generic missing-field fallback. All observed pending-or-memoryLive rows
compare raw full64 tags and sources against an independent accepted-allocation
ledger. This observer is not a standalone proof of every protected/replay domain
or of rename correctness.

## Independent models and bounded initial-state evidence

`build/return-flow-contract-model-20261025-r1/` contains the independent queue
model and token induction: 33,068 response traces, 140,731 accepted transactions,
10 detected observation mutations, three complete-64-bit symbolic token proofs,
three symbolic negative cases and 1,048,576 finite token transition combinations.

The accompanying `REVIEW-ADDENDUM.md` is part of the qualification, not an optional
footnote. Cancellation decision sets are shared between the model's two sides;
completion cause/data formatting uses a shared helper. Those checks calibrate
policy/observation mutations, **not independent RTL cancellation or formatter
implementations**. The phase model's 6-to-5 residence and 2/3-to-4/5 examples are
ideal capacity examples, not CPU measurements. Actual component checks below use
independent external operations/cancellation and independent cause/tval/data rules.

The cached OFF CPU was also tested with four initial raw-index patterns: zero,
slot, 15-minus-slot, and slot XOR 10. Each guest constructs a fresh DUT object and
performs the original two reset steps. Before any allocation, CURRENT and NEXT
index arrays are changed once, only after checking that allocation, pending,
memoryLive, protected/head/replay/staged owners, ledger count and execution owners
are empty. Written rows are never subsequently perturbed. Generated code, original
hosts and cached DUT objects are not edited.

Four unchanged guests under all four patterns produced byte-identical normalized
cycle traces: **477 scalar fields/cycle**, 138 unconditional fields, and defined
valid payload fields including stalls. The 16 binary traces total 58,476,384 bytes;
comparison is byte-for-byte, not merely equality of FNV digests. Original functional
logs also agree. Per-pattern live-row fulltag/source checks are 6,303, 12,819,
10,320 and 7,833 for stream, dependency, hot and cold respectively. There were zero
new DUT builds and two new host builds. This is bounded evidence for selected
unreset initial fields and guest traces, not whole-CPU arbitrary-state equivalence.

Later slot-event instrumentation extended the observer header. The exact prior
header preimage was preserved and verified against its executed SHA in
`build/buffered-return-flow-observer-20261025-r2-slot-events/prior-source-binding.json`;
old receipts were not rewritten to pretend they used the new header.

## Actual validation and preserved failed attempts

All runs use GSIM's fixed corrected initialization epoch, receipt
`build/gsim-init-bytefix-20261025-r1/receipt.json`. No Verilator, legacy ChiselSim,
local-machine synthesis or public Git operation was used.

1. The first unified Scala compile passed, and 11 focused suites/32 tests passed.
   Component r1 passed the local OFF queue but rejected the new chain fixture at
   elaboration: its test-only `startSlots` tap directly accessed grandchildren.
   The repair bores each original valid/ready leaf separately and combines them
   in the wrapper. No functional module was changed.
2. A second unified compile and the same 11 suites/32 tests passed. Component r2
   passed elaboration/GSIM generation but failed the real-header C++ syntax gate:
   the host tried to read a generated getter for request-ready, a host input with
   only a setter. No chain DUT object was compiled in that failed attempt.
3. Component r3 uses the same driven `requestReady` variable for drive and handshake
   accounting, and restricts parallel authorization to legal integer RAM loads,
   excluding stores/FP/local-forward cases. No oracle predicate was weakened;
   no third Scala compile was needed. r1/r2 failed directories are retained,
   together with the SHA-checked r2 host preimage and exact r2-to-r3 diff.

The focused suites are `platform.BufferedReturnFlowSpec`,
`platform.BufferedThirdRankLoadProofSpec`, `platform.SplitLowTagAdvanceSpec`,
`ooo.SplitLowTagAdvanceSpec`, `platform.ElasticLoadProofSpec`,
`platform.GuardedNaturalDataPmpSpec`, `platform.FactoredDataPmpSpec`,
`platform.RegisteredRawCertifiedFlowSpec`, `platform.PreparedHeadStoreSpec`,
`platform.CommonA1RebuildSpec` and `ooo.TranslatedResponseFlowSpec`.

Actual component r3 passes local OFF/ON queue tests (six cases, 656 transactions
per mode) and seven composed consumer-chain scenarios per mode. The chain contains
actual ParallelLSU, registered request FIFO, registered-owner StoreBuffer, outer
response buffer and actual FP memory pipeline. Cases cover integer byte/sign/data
and fault metadata under completion stalls, cancel before and on a physical reply,
write-error/pagefault ACK, local store ACK plus forwarding and delayed external
drain, and FP load/store faults with completion backpressure. Accepted-start,
request-owner and consumer-reply ledgers retain full64 owners; cause, original
address/tval and valid held payloads are independently checked. All **22** sampled
negative controls fail their intended signatures. These are observation mutants,
not rebuilt RTL mutants. This fixture does **not** contain DTA permission logic,
AMO or canonical forwarding, and is not called a full-CPU proof.

The passive return/index observer additionally passed 16 synthetic negatives,
including unowned/duplicate slot reply, overwritten live slot, early completion
and bit63 owner corruption. Its four-guest slot ledger permits forwarded no-reply
completion. It is not a general local-misalignment/accessDenied/atomic-fault
observer; such future coverage requires an independently derived accepted-start
local-fault rule, not an ad hoc exemption after a failure.

## Complete emitted tile structural gate

The independent parser traverses the entire production `CommonA1CpuTile` and all
196 descendant instances, including caches, DTA, StoreBuffer, integer and FP
return paths. External Home/DDR managers are outside that tile. Fresh control and
candidate both have **zero combinational SCCs**; the candidate graph has 185,840
vertices and 1,365,865 conservative edges.

Generic last-connect handling is calibrated with 14 microchecks, and memory/invalid
handling with six more. Unknown/unsupported statements are not silently skipped;
static invalidation is an unknown source, not zero. Synchronous memory control
paths are conservatively over-approximated. No named false-path exemption or
Boolean mutual-exclusion waiver is used.

The source-bound actual FIR gates pass: no live reply reaches current integer/FP
completion or admission readiness; no consumer response-ready reaches raw DTA
physical response-ready; all raw queue indexes are disconnected from authoritative
issue index views, clocked NEXT sinks and backend functional IO. Positive controls
retain reply-to-result NEXT, occupancy-to-physical-ready and old-completion-to-
replacement-ready paths. This proves the stated graph cuts, not arbitrary-state
OFF/ON CPU equivalence, sensitized timing, or routed Fmax.

## One new CPU, then zero-new-DUT Bare

The control reuses the sealed 7daf119 corrected-epoch model. Exactly **one** new
combined candidate CPU was generated and compiled. The original guest bytes,
functional host predicates, within-run full-token conservation, source-lifetime
observer and independent checked-PA negative remain. Cross-run numeric token
values and scheduling routes are not architectural invariants; committed load
PC/occurrence/VA identity is retained.

| Workload | Control | Candidate | Cycle saving |
|---|---:|---:|---:|
| VM store stream, whole work | 677 | 625 | 52 |
| VM dependency, whole work | 967 | 867 | 100 |
| Hot loads, measured 256-load ROI | 402 | 359 | 43 |
| Hot loads, whole work including warmup | 1118 | 1074 | 44 |
| Delayed cold loads, ROI | 360 | 358 | 2 |
| Delayed cold loads, whole work | 906 | 902 | 4 |
| Bare, whole work | 7192 | 6729 | 463 |

All 256 measured hot loads retain start-to-physical acceptance = 3 cycles and
physical acceptance-to-reply = 1 cycle. Start-to-completion changes **6 to 5**.
The candidate-only slot event joins accepted start to **LSU slot response.fire**
at +4 for all 256, coinciding with outer reply acceptance. This is explicitly
**slot reply acceptance**, not an unconditional result-register write event:
cancel, local-forward and FP ownership have different semantics. The +5 completion
measurement remains a separate original-host observation. Retirement is not
uniformly +5: 255 measured hot loads retire at +5 and one at +6. Do not describe
all loads as retiring five cycles after start.

Hot start-gap counts change from `{1:128, 2:126, 7:1}` to
`{1:169, 2:85, 6:1}`. Whole-hot translation requests rise 11 to 15, DTLB-hit
observations 10 to 14 and prechecked starts fall 501 to 497; actual PTE requests
and replies remain 3/3. This is a route/scheduling tradeoff, not four extra walks.
Hot drain rises 10 to 11 cycles. Cold drain remains 7 and translation requests 2.
The measured work/ROI comparisons show no cycle regression, but do not imply
unchanged traffic duty everywhere or a guaranteed clock-rate gain.

The four CPU guests observe 708 outer responses: **all are empty bypasses**.
Queued captures, full-pop, faults, FP and cancellation witnesses are zero in these
CPU traces. Their corner coverage is supplied by the actual components, not
invented from absent CPU events. Slot starts/completions total 106/106, 154/154,
512/512 and 32/32; slot response acceptances are 58, 106, 512 and 32, with the
expected forwarded no-memory-reply operations and no release-without-completion.
In aggregate, 804 starts/completions minus 708 slot response acceptances equals
96 forwarded operations: exactly 48 in each VM guest. This reconciles separate
execution and outer-response ledgers without pretending forwarded loads used an
external response credit.

Bare links one additional immutable host against the same candidate objects;
there is no second DUT generation/compile or guest rebuild. Its six ROI cycle
pairs are 409->399, 1344->1281, 1765->1692, 502->488, 1183->1120 and 1694->1617.
Only `work_cycles` changes in the final Bare summary. Per-ROI fetch/dual-retire/
zero-retire/occupancy timing differences are retained in the receipt. This fixed
M-mode/Bare guest forbids virtualized/prechecked requests: proof-query offer and
accept remain strict cross-run equality **and explicitly 0/0**. A proposed generic
route-counter relaxation was rejected before this run; no such exemption remains.

## Evidence inventory

Paths are relative to the source workspace. Historical receipts retain their
original source/HEAD identities; a later commit must bind the validated bytes
rather than rewrite those receipts.

| Gate | Receipt |
|---|---|
| Independent response/token models plus limitation addendum | `build/return-flow-contract-model-20261025-r1/receipt.json` |
| First compile (before test-tap repair) | `build/buffered-return-flow-20261025-r1/scala/compile-receipt.json` |
| Accepted second compile | `build/buffered-return-flow-20261025-r2/scala/compile-receipt.json` |
| Actual components | `build/gsim/buffered-return-flow-components-20261025-r3/receipt.json` |
| Exact initial-index traces | `build/buffered-index-initial-state-20261025-r2-exact-traces/receipt.json` |
| Initial observer calibration, preserved | `build/buffered-return-flow-observer-20261025-r1/receipt.json` |
| Final observer/slot-event calibration | `build/buffered-return-flow-observer-20261025-r2-slot-events/receipt.json` |
| Fresh disabled/candidate FIR and prerequisite bindings | `build/gsim/buffered-return-flow-cpu-20261025-r1/emit-receipt.json` |
| Complete-tile structural gate | `build/return-flow-independent-design-review-20261025-r1/structure-receipt.json` |
| One-new-CPU comparison | `build/gsim/buffered-return-flow-cpu-20261025-r1/receipt.json` |
| Zero-new-DUT Bare comparison | `build/gsim/buffered-return-flow-bare-rom-20261025-r1/receipt.json` |
| Full-token slot-event/ROI joins and cycle summary | `build/buffered-return-flow-validation-results-20261025-r1/summary.json` |
| One full untapped candidate resource map | `build/return-flow-full-cpu-mapping-20261025-r1/receipt.json` |
| Matched conservative connectivity depth | `build/return-flow-full-cpu-mapping-20261025-r1/depth/receipt.json` |
| Sealed mapping/depth artifact inventory | `build/return-flow-full-cpu-mapping-20261025-r1/manifest.json` |

Primary result SHA256 values:

- Actual components: `1aa2eb035e5b0deb5f68080fb80d44eccdcf51658701547dac0aa965837ecd87`.
- Initial-index traces: `8b47198e5984878c62a522503071d34a18852f1ec4cf449ede6a1cb1a72af140`.
- Final observer: `98db8a8f0f890c63e679027dc732cf44cc36abc76d986becf66dd7f9dac089d0`.
- Full-tile structure: `3b3b527a448bde0e2ba0b1052b67696835ba98759e55e9c138d1b5cd9773a27e`.
- CPU: `a816fa84eac57ab3f64d576a998b85db3ed31cc4f031c7c8d882c7604174ff9c`.
- Bare: `1e6690a5f5026af7d6dcca40858b872076f3e97ea88b3f65dbd97e9e034da234`.

## Closed cloud resource prescreen; physical qualification still unverified

One fresh full **untapped** candidate map completed under the exact saved pinned
Yosys xcup no-SAT-sharing policy. The qualified 7daf119 buffered-supply baseline
was reused, not resynthesized; a fresh disabled export matched all 178 saved SV
files byte-for-byte. All 1,078 historical compile inputs were checked against the
pinned 7daf119 Git contents, with the original precommit-to-final source binding.
Current candidate compile/CPU inputs were checked before and after mapping.

The policy is `begin:coarse`, manual coarse passes omitting generic SAT sharing
and using `memory -nomap -nosat`, then `map_memory:edif`. This is not the default
synthesis policy. Baseline/candidate warnings are exactly matched (32/32).

| Mapped resource proxy | 7daf119 control | Candidate | Delta |
|---|---:|---:|---:|
| Logic LUT | 192606 | 192486 | -120 |
| FF | 59361 | 59297 | -64 |
| LUTRAM primitive instances | 627 | 627 | 0 |
| BRAM36 | 16 | 16 | 0 |
| BRAM18 | 0 | 0 | 0 |
| DSP | 30 | 30 | 0 |
| CARRY | 5951 | 5951 | 0 |
| MUXF | 26538 | 27925 | **+1387** |

Logic LUT decreases about 0.062% and FF about 0.108%, while MUXF increases about
5.226%. **This is not a claim of lower total physical area.** LUTRAM counts are
primitive instances, not LUT-equivalent area. The combined recipe changes two
behaviors; its whole-design resource delta is not an isolated attribution of each
change. The untapped candidate has 179 emitted modules, the same 256 top ports /
4,482 bits, unchanged 15 logical PRF reads / 30 bank reads and all 23 memory-array
module geometries unchanged. Removed redundant scalar index storage is included
in the mapped totals rather than hidden by the array-geometry comparison.

The pinned xcup arithmetic flow uses the common **CARRY4** mapper. These counts
are Yosys resource proxies, not Vivado/device-native carry utilization, placement
or routed area. The exact qualified DSP/BRAM modes were checked using the same
finite primitive model as the baseline.

### Conservative path result: 60 to 61, not a timing improvement

The matched unweighted sequential-cut connectivity depth changes **60 -> 61**.
The new maximum witness starts at
`backend.bufferedLoadPreparation.prepared_0_token_index[1]`, passes
`backend.memoryIssued` (alias `bufferedLoadPreparation.io_issued_valid`) at
primitive step 50, and ends at `core.responses.responses_responses.headValid.D`.
These are aliases on one graph witness, not a combinational feedback claim. The
old `queue_0_renamed_token_index[2]` no longer starts this maximum witness, but
its removal does not prove the old path unsensitizable or a faster clock.

No witness was sensitized. This is a conservative connectivity bound, **not
physical delay, STA, Fmax, a proven physical timing regression, or timing
improvement**. The extra MUXF instances and +1 graph depth are disclosed alongside
the lower logic-LUT/FF counts. The separately measured CPU/Bare cycle gains must
not be advertised as combined area-and-timing improvement. Physical implementation
and board qualification remain unverified and require their own authorization
and evidence.

The one candidate map took 2,223.3 seconds, with sampled owned-process-group peak
4,433.9 MiB (about 4.33 GiB). Owned descendants were verified absent after completion;
all 401 files in the final manifest were reverified. No source, HEAD or compiled
class changes, second full candidate map, local/Vivado/bitstream run or public Git
operation was used to obtain this result.

Final mapping evidence:

- Resource receipt SHA256:
  `08effce658dad9998ec7af73d7f9f2b8b01501f3dbfb95a0d7360c7df30d102b`.
- Depth receipt SHA256:
  `e988ab9eb3dbc967bf012843202f27406137220e242bf8373335c08eb72a4587`.
- Final 401-file manifest SHA256:
  `2c128537cc6d116e668362aff5b96b145b6ebe6de57c3ec1448e9005382d2f8d`.
