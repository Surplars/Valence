# Read-MSHR integration candidate

## Explicit selection, no hidden growth

Production constructor/export plumbing appends `cacheConcurrency` after the independent DDR bridge configuration. Default remains logicalMSHR1/responseEntries2 and serialAXI1. Select MSHR2/responseEntries2/AXI4/maxBurstBeats8 explicitly for the first performance candidate, retaining LSU2,32KiBI/32KiBD and2 ways. MSHR4 requires explicit responseEntries>=4 and a separate explicit LSU4 experiment to expose four CPU loads; it is not the default.

The cache/home TL-C bundle derives sinkBits1/2 for MSHR2/4. The noncoherent backing fabric keeps sinkBits1 through an explicit A/D-compatible boundary: unused E is forced0 and asserted inactive, so no live GrantAck sink is truncated. Directory entries follow cache capacity; MSHR and response depths are separate.

CLI tails (after existing DDR slots/burst arguments): BoardSocGsimMain `[read-mshrs] [cache-response-entries]` at16/17, ManagedBoardSocMain13/14, EthernetTimingMain9/10. Omitted arguments retain1/2; requesting MSHR4 without adequate explicit response depth is rejected. Current legal production data requests emit at most eight-beat64-byte lines; scalar DMA operations emit one beat. Burst8 supports those requests. Larger future TL transfers must select a larger supported burst configuration; the bridge asserts on oversize acceptance rather than silently truncating buffers.

## Integration proof scope

The small fixture instantiates real cache, real home, AtomicDataMemory, registered request boundary, ordered scalar TL bridge, TL arbiter and four-ID AXI bridge. The host supplies independent sparse backing memory and FIFO CPU/DMA expectations. No fake cache or home coherence response exists. All1/2/4 cases use identical AXI4/burst8/32-cycle synthetic DDR timing; response depths are explicit2/2/4. The1 case selects legacy cache/home, not a new one-entry approximation.

The test streams1024new lines after populating all512 cache lines; dirty replacement and unrelated DMA probes exercise steady-state ownership. It also checks real dirty-probe byte visibility, same-victim B/ReleaseAck overlap, held CPU/DMA reply stability, byte-strobed RAW order, same-line hit behavior, denied refill/retry, coordinated reset with pending read or writeback, and caller-discarded-but-still-returned response ownership. Caller discard is not a claim of a real CPU redirect/LSU rollback test.

Read/store-hitII1 is checked separately. Request-to-reply measurements are cache-boundary latency and include deliberate response stalls where indicated. They are not full CPU load-use latency. CoreMark may mostly hit in32KiB; MSHRs do not imply CoreMarkIPC>=1. Existing cacheProfile/headProfile counters should be reused for later CPU attribution rather than adding wide internal probes or undoing timing stages.

## Resource-efficiency bounds, not utilization

- Data capacity stays262144 bits per L1; these synchronous banks are intended for block RAM. The single physical read/write-port organization remains explicit.
- L1 D tags:512x50=25600 raw bits; bounded home tags:512x58=29696 raw bits. Indexed tag/valid muxes and comparisons remain a timing/LUT risk; no new associative search across512 lines is introduced. MSHR conflict comparisons scale with2/4 entries.
- Legacy cache AcquireEngine has4x512=2048 bits of line data despite one logical miss. MSHR2 instantiates2x512=1024 bits; MSHR4 retains2048. These are source-level buffer counts, not proven synthesized savings.
- New home retains Mx512 grant-data bits plus512-bit release and512-bit probe/maintenance payloads; the generic line reader/writer engines retain their own buffers. This duplication is explicit and may be optimized in a later independently verified step. Do not alter frozen passing RTL merely to claim savings.
- Choosing AXI burst8 instead of16 reduces four replicated burst-engine read/write/mask buffers from8704 to4352 raw bits. Writes remain exclusive; a future shared write engine could reduce duplicated idle write buffers but requires separate ownership/timing proof.
- Potential follow-up after qualification: size home read engine toM and independently size its write engine to the two real origins, share store-miss payload where barriers guarantee one writer, and evaluate eliminating duplicate home full-line storage. Removing pipeline registers may hurt100MHz even if it saves FFs; benchmark/synthesis evidence must decide.

No LUT/FF/BRAM,Fmax,DDR bandwidth,CPUIPC or physical-board improvement is claimed from raw-bit arithmetic or these protocol tests.

## Integration-discovered scheduling correction

First integration snapshot passed M1 and M2 clean concurrency, but M2 dirty replacement exposed only one live AXI read despite511 overlapping C releases. Trace showed a queued refill overtaking the next victim writeback, forcing that writeback to wait for the refill under the deliberately exclusive AXI write fence. The failure receipt and original RTL are preserved separately.

The corrected home delays only a not-yet-dispatched refill for a currently active or admissibly offered release. It yields to at most one completed release per fill-queue head; after that ReleaseAck, the head gets priority until engine acceptance. An inadmissible same-set release cannot block the fill it depends on. Already-issued reads, returned data, Grants and E are never gated, and no AXI ordering rule changes. Directed home proof requires the first writeback to complete before the queued refill, then requires that refill before a second release acknowledgment. Real integration retains the dirty-concurrency gate and additionally requires actual AXI read peak>=2, not just buffered home Acquires.
