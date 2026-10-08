# Read-MSHR candidate contract (draft, not yet compiled)

## Scope

Preserve default logical readMshrs=1 by selecting the existing blocking cache/home. Candidate values2/4 enable independent read misses. I/D capacity remains32KiB each, D associativity2; issue width2 and LSU2 remain independent. A separate explicit LSU4 experiment is needed to expose four CPU requests. This is a latency-overlap candidate, not evidence of DDR throughput or a write-stream optimization.

The user's32MiB Linux workload exceeds cache capacity. Invalid-line-only concurrency is inadequate: steady-state clean and dirty replacements must preserve overlap too. First implementation therefore includes a single independent release/writeback lane. Dirty writeback is serialized but cannot prevent other fills/GrantAck from draining. Store misses, AMO, uncached/MMIO and flush remain ordered barriers. The existing acceptance-ordered hit-only read/store pipeline is preserved to avoid a store-hit throughput regression; store hits require no live miss/bypass/eviction/probe.

## Cache invariants

1. Every accepted DataPort request reserves exactly one FIFO response-ledger entry. No new transaction IDs are exposed upstream. Completed requests may be stored out of order, but only the FIFO head can respond; held response payload/valid cannot change.
2. A read miss reserves one MSHR, target cache set and physical way. First increment rejects any new request conflicting with that reserved set; no same-line coalescing/replay queue. This conservative rule preserves overlapping-read version order.
3. The acquire engine allocates physical TL sources0..entries-1, entries=max(2,readMshrs). Request tags identify logical MSHRs. A result is matched by tag, never guessed from arrival order.
4. One Release/ReleaseData owner uses the disjoint source ID=entries. Victim address/data/dirty state and full C payload remain stable until ReleaseAck. A replacement Acquire cannot issue before that acknowledgment.
5. One shared eight-bank read port services hits, probe snapshots and victim snapshots. Probe/capture arbitration never creates extra physical SRAM ports. Refills and store hits share one write port per bank. Same-index read/write ambiguity is forbidden by reservations/arbitration.
6. Refills install and capture CPU results using pre-reserved storage independently of CPU response backpressure. No line becomes valid/dirty on denied/corrupt refill. All D beats and E acknowledgments still drain.
7. Probe acceptance has priority over new CPU accesses. A probe for an E-acknowledged but not yet installed transient waits only for bounded refill installation, never CPU response retirement. After installation, probe invalidation is allowed while the earlier CPU result remains stalled; that result is a saved snapshot.
8. C arbitration locks through each complete ReleaseData/ProbeAckData burst and a stalled offer. Probe/release ownership is separate from miss-result ownership. A waiting dirty writeback cannot block the E/result path needed to finish existing acquires.
9. Store misses/AMO/MMIO/uncached requests wait for older cache ledger/MSHR work to drain and block younger admission until their response retires. Flush closes admission, drains accepted transactions, then scans/acks every dirty release. Store hits may pass queued older hit replies only when no MSHR/bypass/eviction/probe is active; partial writes and read snapshots remain in acceptance order. Accepted speculative loads are never silently cancelled: upstream retains discard/retirement ownership.
10. Reset clears request/result/reservation/channel owners under the existing whole-domain/downstream-reset contract; no stale external responses are accepted as new owners.

## Home interface agreement

- Existing TL-C bundle shape; caller supplies sufficient source/sink widths.
- Home retains address/full Acquire source/client/exact directory slot until GrantAck. It reserves that slot at A acceptance, including transient entries, and commits that same slot on E, not a newly recomputed empty slot.
- Grant sink identifies home table entry; require sinkBits>=max(1,log2Ceil(homeEntries)). Acquire engine returns the captured sink on E.
- D burst arbitration is locked for all eight GrantData beats and through stalls. Error aggregation is complete before Grant begins; denied grants drain E without installing ownership.
- Same-line/probe/writeback hazards serialize. Independent fills may coexist. Direct DMA accesses cannot cross a transient Acquire of the same line; maintenance owns its context while other fills and E acknowledgments continue.
- Release/writeback has independently reserved capacity, not capacity borrowed from a full acquire table. ReleaseAck follows backing-write completion; dirty-writeback errors retain the existing explicit unsupported/error assertion contract.
- Initial nonblocking home is single-client; old nClients>1 path remains available only with readMshrs1.

## Configuration legality

Separate parameters: cache lines, ways, line bytes(fixed64), logical read MSHRs1/2/4, CPU response-ledger entries, home acquire entries, release entries(fixed1 initially), line-engine entries, AXI outstanding slots and LSU slots. No parameter silently grows another.

- responseEntries defaults2 independently; M4 requires explicit>=4. Legacy mode uses this for its hit FIFO plus existing dedicated miss result; concurrent mode uses the unified ledger. responseEntries>=readMshrs; every accepted hit/miss has a reserved result credit.
- Logical MSHR2/4 requires matching home table2/4 in initial validated combinations; engine entries>=logical MSHRs.
- sourceBits>=ceil(log2(engineEntries+1)) for disjoint acquire/release IDs; home line-transfer read/write prefix and fabric prefixes must fit their actual widths.
- sinkBits>=max(1,ceil(log2(homeEntries))). Existing sinkBits1 cannot encode four concurrent GrantAck owners.
- maxBurstBeats>=8 for64-byte cache lines; AXI ID/source widths bound AXI slots separately.
- Lines/ways geometry remains power-of-two and legal for current SRAM organization. D ways1/2 supported; I ways2 remains fixed rather than advertising unsupported arbitrary associativity.
- Registered TwoEntryRegisterQueue boundaries stay exactly depth2 unless explicitly redesigned; do not silently replace them with a deeper queue under the same timing claim.

## Prerequisite engine result holding

Acquire/Fill/Write engine complete outputs currently select PriorityEncoder(doneMask). Their Decoupled interface is not intrinsically irrevocable: a newly completed lower slot may replace a stalled candidate. Add a held-selector/skid contract before integrating owner-bound consumers, and test a lower-slot completion during a held higher-slot result. This is a next-candidate interface hardening requirement, not a claim of a current single-miss failure.

## Independent bounded proof plan

- Configuration/elaboration matrix1/2/4 MSHRs, capacities8 and512 lines (require at least one distinct set per MSHR), ways1/2, independent ledger depths; reject illegal source/sink/home/queue combinations.
- Standalone acquire/fill/write engines: out-of-order completion, early/late errors, blocked result with newly completed lower source, E stall, no slot/source reuse before completion.
- Real cache+home+independent backing manager: warm up then stream a working set>=2x cache; demonstrate multiple simultaneously issued line reads after cache is full, not only at cold start. Assert exact returned data and CPU order independently.
- Same line and same set: refuse conflicting admissions while reserved, then make progress. Interleave dirty-victim eviction, unrelated DMA probe, refill, held CPU reply, ReleaseAck and E stalls. Probe-after-E/before-install and simultaneous B/CPU-D edges are directed tests.
- Denied refill across multiple MSHRs: all responses matched, bad line never installed, later retry succeeds. Dirty writeback errors fail loudly as baseline. Misordered tags/sources/sinks and corrupted data are negative oracle cases.
- Mixed stores/loads, AMO/LRSC, MMIO and FENCE: retain ordering and precise error behavior; flush waits for all accepted work; speculative redirect/cancellation still returns/discards each accepted response once.
- Reset under read/refill/release/probe pressure with coordinated downstream reset; clean post-reset request ownership.
- End-to-end CPU microbench: prefaulted dependent pointer chase vs2 independent streams at LSU2, optional explicit4 streams/LSU4, working set32KiB/64KiB/1MiB; matched AXI latency and frozen firmware/retired-PC oracle. Read/copy/store phases and cache-miss/eviction/stall counts reported separately. Linux first-touch data includes page-fault/scheduling cost and is motivation, not raw DDR bandwidth.

Freeze cache/home/config changes before one combined compile and focused acceptance. Schedule resource-intensive compile, GSIM and timing jobs serially.

## Draft implementation status

Cache RTL, shared IO/factory, explicit concurrency type and stable completed-result selection are staged. Engine oracle expectations now retain first offered high-numbered completion under stall instead of silently switching to a lower slot. The standalone cache oracle includes >cache-capacity clean/dirty replacement streams, FIFO/error ownership, held CPU reply with probe, post-E/pre-install probe, absent same-set probe/refill collision, ordered bypass and coordinated reset during read/release. Python dry-run/syntax and C++ port-shape syntax checks pass; no new Scala elaboration, RTL simulation, real-home integration, timing or performance result has been run.
