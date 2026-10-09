# CPU bandwidth: request supply and bounded queue shortcuts

Opt-in functional/native checkpoint, 2026-10-09. Historical source baseline: `e8520ab23fb31cd03566787056d5e937e1aca7c3`.
The selected profile remains two-issue, two LSU owners, 32 KiB/two-way D-cache,
two read MSHRs, two cache responses and two writeback entries. All new options
are default-off. No measured FPGA timing or physical-board speedup is claimed.

## Separate the ceilings

At 100 MHz, a 64-bit interface transferring every cycle carries 800 MB/s,
or 762.939 MiB/s. This is an interface ceiling, not the executing CPU's current
load-loop throughput. Copy uses at least a read and a write on the shared CPU
DataPort for each eight bytes of useful copied payload, so its local-port ceiling
is at most 381.470 MiB/s before instruction, owner, miss or write-allocate cost.

The current CPU additionally retains each load's LSU owner from accepted start
through registered response/result and completion/replacement. With two owners
and an independently measured residency L, the supply bound is at most
`2 * 8 / L` bytes/cycle, assuming every request is an independent eight-byte load,
completion/start overlap is possible, and no other issue constraint dominates.
This is a bound for the current microarchitecture; reducing L or increasing owner
capacity can move it. It is not a general 100 MHz CPU ceiling.

Existing source-bound Sv39 warm-load measurements show seven cycles from start
to result: one request-FIFO cycle, three cycles to physical acceptance, one
cache service cycle, one response-buffer cycle and one LSU result cycle. With
precheck enabled, 512 loads use 1,809 ROI cycles rather than 4,422, with two
rather than one live LSU owners. Physical service stays one cycle, physical
peak remains one, and response-credit full cycles remain zero. The default
physical path already skips the translated queue. Fresh source-matched selected
GSIM now confirms every one of 4,096 hot 8 KiB loads has exactly six cycles of
start-to-result residency: start-to-request-FIFO acceptance zero, FIFO-to-physical
three, physical service one, registered return one, LSU result one. Full-slot
completion/replacement actually overlaps on 4,084 cycles. Its measured local
two-owner supply roof is therefore 254.313 MiB/s, with 253.262 MiB/s achieved
(99.587% utilization). This is an all-hit read bound for this configuration.

The reported 100 MHz board measurements correspond to these useful-payload costs:

| Board kernel | MiB/s | Bytes/cycle | Cycles per 8 payload bytes |
|---|---:|---:|---:|
| Hot 8 KiB read | 245.136 | 2.5704 | 3.1123 |
| 128 KiB read | 80.289 | 0.8419 | 9.5024 |
| 128 KiB write | 48.004 | 0.5034 | 15.8932 |
| 128 KiB copy | 30.111 | 0.3157 | 25.3376 |

These board values are supplied by the parent task and have not been rerun here.
The source-matched GSIM OFF configuration also measures 8 KiB/4-pass hot write
at 160.018 MiB/s kernel and 128.116 MiB/s including drain/flush; hot copy measures
99.9936 and 86.6539 MiB/s respectively. The copy footprint is 16 KiB. There are
zero timed data misses in these kernels. StoreBuffer peaks at one of two entries
and never fills: store start-to-result is two cycles but launch spacing is mostly
four, exposing head/retire supply rather than capacity. See
`cpu-store-supply-next-plan.md`. 64 KiB stream passes are not all-hit evidence for
a 32 KiB cache.

## Stage and ownership audit

- `IntegerBackend.scala`: a single selected memory operation starts per cycle.
  Two early memory-preparation candidates allow selection past the owner starting
  now; they are not two memory ports. Physical RAM loads may overlap after older
  store and full-token checks. Stores remain exact-head serial owners.
- `ParallelLoadStoreUnit.scala`: two actual operation/result slots, one locked
  request arbiter and an ordered owner FIFO. Completion and replacement can share
  a cycle. Request hold cannot be changed to an unrelated line while stalled.
- `IntegerBackend.scala` / `StoreBuffer.scala`: the request FIFO is registered,
  store data are locally acknowledged only for guaranteed physical RAM, and
  physical store slots remain held until their actual downstream replies.
- `DataTranslationAdapter.scala`: selected physical requests have a registered
  ingress and checked boundary but skip the translated FIFO when it is empty.
  Certified virtual loads carry a PA yet were excluded from that shortcut.
- `DataResponseBuffer.scala` / `LoadStoreUnit.scala`: a registered two-credit
  return boundary precedes the slot's registered completion result.
- `NonBlockingCoherentLineCache.scala`: local hit pipeline can accept one request
  per cycle subject to its credits/hazards, but same-set outstanding miss ownership
  prevents subsequent words in that set from bypassing. Scalar eight-word lines
  therefore often use just one MSHR despite genuine cross-line overlap capability.

The current cache set index is PA[13:6]. A 32 KiB, two-way cache has a 16 KiB
per-way footprint, so PA[13:12] is outside a 4 KiB page offset. This work does
not use VA indexing or assume VA and PA sets match.

## Candidate A: prechecked translated-queue flow

`precheckedDataRequestFlow` / `--prechecked-data-flow` requires explicit
`virtualRamLoadPrecheck` and the registered ingress/checked architecture.
Only when no older translated owner or outstanding translation exists can a
registered prechecked load be selected directly into the original checked
register. The same PMP, epoch, privilege, shape and RAM-range checks run there;
next-line permission is still independently captured. Checked backpressure spills
the accepted request into the translated FIFO exactly once. The normal virtual
translation, identity path, owner order and physical response handling remain.

The opt-in also rejects malformed prechecked alignment or byte masks, which a
legitimate LSU cannot emit. A legal-looking but forged PA is not independently
translated again at this boundary: full-token/VA/size certificate matching and
authoritative TLB/PMP generation remain the upstream contract, tested separately.

The adapter proof measures accepted-to-physical latency three to two cycles for
eligible certified virtual loads. A full executing CPU prechecked-flow speedup
has not been measured here. This is not a prediction of the same improvement
for physical DDR streams. It adds no queue,
owner or cache capacity. A mux now selects two registered sources before the
existing PMP check; the final checked register and ready/occupancy cut remain.
Routed 100 MHz timing is not established by simulation or source inspection.

## Candidate B: physical-only empty-ingress shortcut

`physicalLoadIngressFlow` / `--physical-load-ingress-flow` is implemented default-off.
It retains the checked register, next-line PMP authorization, stable held-request
fallback and all existing capacities, while excluding virtual/prechecked/MMIO/
uncached/store/atomic accesses. It captures an eligible registered upstream
request directly into checked only when ingress/translated/walker owners are
absent and checked has capacity. Otherwise the accepted request spills into the
unchanged ingress queue. Upstream ready remains registered occupancy-only.

The focused adapter RTL proof measures ordinary accepted-ingress-to-physical
latency two to one cycles, dependent 64-load span 256 to 192 cycles and unchanged
48-load issue span 47 cycles. Forty cases pass per side; order, metadata, next-line
PMP and context negatives are independently checked. The upgraded order negative
actually swaps two accepted requests. An independent production source review
found no actionable defect; a separate abstract queue model passed 82,944
transitions and rejected three guard-removal mutants. Abstract modeling is not
RTL or implementation timing coverage.

Fresh executed selected-board OFF/ON qualification passed all six cases.
Every architectural hot read measures six to five cycles. Hot 8 KiB read rises
253.262 to 303.016 MiB/s at assumed 100 MHz; copy rises 99.9936 to 108.927;
write remains 160.018. All read timing and physical traffic include the four
extra canceled guard reads. OFF six cases exactly match historical selected
hot cycles. See `cpu-bandwidth-flow-results.md` for full identities, complete
drain/flush results, independent negative controls and remaining gates.
Joining StoreBuffer selection with next-line permission logic is a timing risk.
No new downstream-ready-to-upstream-ready loop was introduced, but native cone
inspection does not establish routed 100 MHz timing.

The older four-owner experiment is documented in `memory-capacity-experiment.md`.
It changed request FIFO 2 to 4, owner FIFO 2 to 4 and StoreBuffer response credits
3 to 5 as well as the LSU owners. It was on an older 2 KiB I-cache / single-miss
profile without current load-issue forwarding. Its DDR cold read improved
5,684 to 4,883 ticks, write-plus-flush regressed 8,112 to 8,115, copy changed
13,744 to 13,735 and chase stayed 4,012. Those values are not current selected
bandwidth and do not substitute for a new configuration-bound comparison.
