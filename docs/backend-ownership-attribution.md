# Owner-qualified backend attribution, 2026-10-07

## Result and decision

**PASS: observation-only instrumentation preserves the selected RV64IMC run exactly.**
Guest output and every existing counter line are byte-identical to
`build/gsim/frontend-rvc-pair-20261007/combined32.log`; the ordered retired-PC
stream is also byte-identical. Guest ticks remain **486605**, with **486606**
inclusive ROI cycles, **360528** retirements and **276782** zero-retirement cycles.

The dominant owner-qualified unresolved category is **73669 downstream cycles**
(15.14% of ROI, 26.62% of zero-retirement cycles). It remains **unknown downstream
work**, not a cache-wait measurement. No functional optimization is proposed from
this pass. The next useful measurement would extend ownership through actual
StoreBuffer physical requests, translation queues, cache requests/replies and the
return buffer, including stores that retire before physical draining.

The old phase-2 total of **123873** zero-retirement cycles is now exactly:

| Matching head-owner state | Cycles |
|---|---:|
| Accepted by StoreBuffer, downstream not further observed | 73669 |
| LSU response handshake this cycle | 38579 |
| Request-FIFO dequeue / StoreBuffer acceptance this cycle | 11156 |
| FIFO head held because StoreBuffer write slots are full | 469 |
| **Total** | **123873** |

Likewise, only **720** queued-head cycles have no available LSU slot/replacement;
**10931** instead have a slot/replacement available but fail serial-exclusion
conditions. The former `memorySlotAvailable=false` count was not a full-slot
measurement. These new categories are ordered observations, not independent
causal costs or projected speedups.

## Complete primary ROI partition

Commit progress has first priority; zero-commit priority is recovery, empty, done,
queued, then issued. The table sums to **486606** cycles. All rows other than the
two commit-progress rows sum to **276782** zero-retirement cycles.

| Category | Cycles |
|---|---:|
| Two commits | 150704 |
| One commit | 59120 |
| Recovery | 10858 |
| Empty ROB | 15963 |
| Done, awaiting retirement | 24576 |
| Queued memory: actual launch handshake | 22502 |
| Queued memory: preparation or selection | 19956 |
| Queued memory: serial exclusion | 10931 |
| Queued memory: no available LSU slot/replacement | 720 |
| Queued nonmemory: actual eligibility true | 21339 |
| Queued special operation: unresolved | 386 |
| Issued nonmemory | 24679 |
| Issued memory: downstream unknown | 73669 |
| Issued memory: response handshake | 38579 |
| Issued memory: FIFO / StoreBuffer acceptance handshake | 11156 |
| Issued memory: matching FIFO head, StoreBuffer full | 469 |
| Issued memory: completion acceptance | 999 |

Actual memory launch, FIFO acceptance, response acceptance and completion
acceptance account for **73236** zero-retirement cycles that nevertheless perform
that pipeline progress. They are not labeled blocked cycles. Preparation/selection
can also contain useful preparation; this first pass does not separately export
the preparation planner's capture handshake. Eligible queued nonmemory work can
include productive execution preparation; it is not evidence of an operand wait
or a particular issue-resource bottleneck. The exact memory scheduling readiness
predicate found no queued-head memory operand waits in this ROI.

The physical idle-slot histogram over *all* ROI cycles is 111024 cycles with zero
idle slots, 203757 with one, and 171825 with two. This is distinct from issue
availability, which also permits replacing a completing owner and imposes serial
exclusion. It cannot be summed with the primary partition. The percentages are
22.82%, 41.87% and 35.31%, respectively. These probes do not count ready younger
loads blocked by capacity. The 720 head-specific slot waits therefore cannot
rule out additional MLP or useful latency hiding for younger work.

## Ownership method and independent checks

`BoardSocGsimMain.scala` adds optional passive test ports using BoringUtils.
`IntegerBackend.scala` only adds Scala elaboration references to its existing
request Queue and StoreBuffer. No production ports, datapath/control assignments,
configuration defaults or functional behavior change. The observer is explicitly
scoped to the selected two-slot, 16-entry ROB board.

The host records full 64-bit allocation tag **and** ROB index at actual LSU request
acceptance. Its non-flow FIFO shadow consumes the old head before appending a
simultaneous enqueue. A second ordered shadow tracks accepted requests until
actual LSU response consumption. Return ownership is independently checked
against the hardware response-owner slot and that slot's full token. Every live
phase-2 slot must have an accepted request owner; every shadow owner must still
have a physical LSU slot. Completion tokens and request ownership are also
checked against the physical slot or the same-cycle accepted start.

Cancellation and branch rollback never clear either host queue. Cancelled reads
remain owned until their response drains. Forwarded loads that issue no request
do not enter the queues. Local StoreBuffer acknowledgements and forwarded
StoreBuffer reads are distinguished at actual FIFO dequeue, using the dequeued
request's predicates. A local acknowledgement can be consumed on that same cycle.
Retired buffered writes are deliberately **not** tracked after their local LSU
acknowledgement; fast-store acceptance is counted, but its later physical drain is
not assigned to a ROB head.

The observer starts before the harness's initial reset and preserves the original
frontend observer's later attach point. The measured whole run checked:

- 1953690 nonreset cycles and 4 asserted reset samples
- 192584 enqueues, 192584 FIFO dequeues and 192584 LSU responses
- 8029 simultaneous FIFO enqueue/dequeue cycles
- 1587 slot/cycle observations of cancellation while a request remained outstanding
- 18454 local accepts and 174130 direct/downstream accepts
- 668 actual LSU forwarded starts; zero separate fast-store accepts in this run
- Both shadows empty at completion

The 1587 figure counts observations, not necessarily distinct cancelled requests.
The independent host tests cover delayed returns, simultaneous transfers,
cancellation with drain, same-index/different-generation tokens, local same-cycle
acknowledgement, forwarded bypass, slot replacement and reset with pending work.
Three negative tests deliberately corrupt return ownership, enqueue ownership and
FIFO occupancy; each is rejected. Reset discards are included in conservation.
ASan and UBSan remain enabled, with fatal sanitizer recovery disabled. Leak
checking uses the repository's existing `detect_leaks=0` setting.

The legacy request-cause correlation is not used for ownership attribution. In
22502 zero-retirement samples where the current LSU-selected request matched the
ROB head, the request FIFO was either empty or headed by another owner. This
figure does **not** assert that all 22502 samples had a different FIFO token.

## Pinned inputs and reproducibility

- Profile: `staged-fetch-turnover`; instruction cache 32 lines / 2KiB / 2 ways
- Board: two issue, RV64GC/FPU, 100MHz, UART 460800, DDR 2GiB, data cache 2 ways
- Optional registered load-issue forwarding remains false
- Workload: the existing RV64IMC/lp64 binary, never rebuilt or compared as RV64IM
- BIN: `build/gsim/coremark-rvc-20261007/rv64imc/coremark_board.bin`
- BIN SHA256: `05b9a01d74a03389433ef942fef7056827331be18a91e0795f6456cee51fdac5`
- ROI: retirement of `0x80200114` through `0x80200122`, inclusive
- Retired-PC SHA256: `142a5aafefa1eabaa2b76f5d7c42baa1cb31de1c6fd95384652ea4e936aa84fa`
- FIR SHA256: `27a05e99f4762d8518031b5485d6a7dfb0cd3645e6136ba2969c836d02c69920`
- Model C++ SHA256: `f7bfecf44dea0966ccc96f83bf9a7130b080399e1c34dbb232d30ca577012928`
- Model object SHA256: `29c6008e38a360e96b45818f10b7777d2bf9cff908d4c61fb17e339ec8dba605`
- Executable SHA256: `744a42de39204f4025da59d4478855cad11d63c3b4bdf98c472e856358177d5b`

Run receipt: `build/gsim/backend-ownership-20261007-r2/receipt.json`.
It records all hardware/measurement source hashes, toolchain lock, exact generator
flags, all artifact hashes, partitions, ledger totals and equivalence results.
All measured sources were unchanged during the run. Independent review also
rechecked prior output, trace, artifact hashes and input hashes.

```sh
source scripts/cloud/env.sh
python3 simulator/gsim/backend_ownership.py --out build/gsim/backend-ownership-NEW_TAG
```

The driver compiles only the selected instrumented board model and runs one
bounded CoreMark image. It retains all original workload oracles, all existing
telemetry, the exact retired-PC trace and host ownership negatives. No DDR/GC
repeat, NEMU rerun, full GSIM, Verilator, CAD, physical-board test or Linux run is
part of this observation-only pass.

## Generator recovery and limitations

The first emitted model hit a pinned GSIM `graph::resort` assertion before C++
compilation. A reset-output-only isolation did not resolve it. Suppressing the
new backend event vector while retaining token/slot/FIFO probes generated
successfully. Replacing the event vector's dynamic head-indexed vector reads with
equivalent static scalar taps and a one-hot head mux resolved generation with all
intended probes present. The final model uses standard `--threads=1` only.

Diagnostic attempts with `--when-size=0` and `--when-size=1000000` also failed;
the latter disabled when merging but left the same three-node ordering defect.
Neither option is used for the successful result. No vendored generator changes
were made. Original failure and isolation logs are preserved in the successful
run's `diagnostics/` directory. Only the final model was compiled and executed.

This pass does not distinguish translation ingress/check queues, identity hits,
walks, cache admission/hit/miss service, response buffering or final completion
arbitration beyond the observed handshakes. It does not infer ownership from
unrelated global cache activity. The 73669-cycle downstream remainder stays
explicitly unknown. It also does not estimate avoidable latency, routed timing,
resource use or FPGA/CoreMark scores.

## Minimal next observation plan (not run)

1. Carry a host full-token lineage from the existing request FIFO into two
   StoreBuffer ledgers: direct reads and buffered physical writes. Record the
   selected physical request class on its actual handshake (`drainRequest`,
   flow-buffered write, flow-fast write, or direct). Keep buffered-write lineage
   after ROB retirement and local acknowledgement until the matching physical
   write response. Match the StoreBuffer's physical-response owner class and
   check request fingerprints/queue counts independently.
2. Transfer that lineage on the exact DataTranslationAdapter virtual ingress,
   incoming, translated and checked-request handshakes. Keep translation faults
   as ordered placeholder responses that never issue a physical request. Separate
   identity/pass-through, actual TLB hit, waiting translation and walk only when
   the current owner has been proven. Assert integer versus FP/system memory
   ownership at the upstream mux rather than silently assuming every request is
   an integer LSU request.
3. Track physical responses through the mapped and platform register routers,
   explicitly distinguishing local MMIO replies from RAM requests accepted by
   CoherentLineCache. Track cache read-hit response queue, miss/bypass owner and
   upstream reply. Then follow the relocated DataResponseBuffer back to the
   StoreBuffer and existing LSU response owner. Preserve reset, cancellation,
   local acknowledgement and simultaneous-transfer tests at each queue boundary.
4. Report a primary category only for a proven matching head lineage; keep an
   explicit unknown remainder. Retain this exact BIN/ROI, byte-exact prior
   counters/output/retirement stream and negative token-corruption gates.
   Separately add an all-cycle count of ready, otherwise eligible younger loads
   denied only by capacity if deciding whether additional MLP is worthwhile.

This is a bounded proposal for another observation pass, not authority to change
hardware, add slots, alter turnover or remove pipeline stages.
