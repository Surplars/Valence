# Experimental coherent memory-copy line transfers

This page records the phase-one, single-owner design and qualification. The
later optional two/four-owner design and selected next profile are described in
[dma-line-overlap.md](dma-line-overlap.md).

This is a default-off cloud candidate. `--dma-line-transfers` selects it for
FPGA-next; `FpgaNextConfig.Selected` itself is unchanged. It is not a new board
measurement, bitstream, or physical timing qualification. Network/packet DMA,
JTAG loading, MMIO, cache geometry and DDR transaction credits are unchanged.

## Contract and ownership

The existing memory-copy ABI is preserved: positive length, source, and
destination must be 8-byte aligned, their full nonwrapping ranges must be in RAM,
and the source/destination intervals must not overlap. Zero length, unaligned,
overlapping, and out-of-aperture descriptors complete with an error and no memory
traffic. There is no STOP, hot-abort, descriptor ring, or generation field in this
memory-copy ABI; reset recovery still requires coordinated interconnect reset.

When both current addresses are 64-byte aligned and at least 64 bytes remain,
the engine drains its scalar owners/data and issues one full-line read followed
by one full-line write. Source/destination with different offsets modulo 64 stay
scalar. An aligned middle uses line transfers; an 8-byte-aligned prefix or tail
uses the existing four-credit scalar path. Every 64-byte operation is naturally
aligned and therefore cannot cross 4 KiB. A descriptor may cross multiple pages
as separately checked lines. No MMIO transfer is eligible.

`DmaLinePort` has one request/response owner, with a 64-bit physical address and a
512-bit payload. It is an internal bounded line interface, not a widening of the
64-bit SoC TileLink/AXI link. The existing TileLink line engines turn each request
into an eight-beat transaction; the DDR bridge retains four shared slots and at
most two writes. A completed DMA write means its actual backing B response has
returned through the line engine and coherent home. Request acceptance, WLAST,
and an unaccepted acknowledgement are never completion.

The line port passes through `AtomicMemory` before the home:

- Admission requires the atomic FSM to be idle and all ordinary response owners
  to drain. A stalled ordinary offer keeps priority until accepted.
- A stalled line offer is locked. Once accepted, exclusive ownership lasts until
  its final response handshake. Neither an AMO read/write gap nor an outstanding
  LR can be crossed by line admission.
- An accepted line write invalidates an LR reservation for that complete line.
  Ordinary CPU/DMA traffic receives an arbitration turn between line operations.
- This does not make an entire copy descriptor atomic. The inherited software
  rule still forbids conflicting CPU access to DMA-owned buffers.

The mixed coherent home then drains acquisitions, releases and direct reads,
probes the matching cache owner if present, and waits for any dirty writeback
before the full-line operation. It blocks new conflicting ownership until the
line response retires. A pending but unaccepted line request does not block
FENCE.I drain completion; already accepted work does. Read/write responses use
separate full tags outside acquire/release tag ranges. The tag width covers all
supported 2/4 acquire and 1/2/4 writeback configurations.

A clean line and a dirty line preserve the same coherence rules. On an already
owned line, the old scalar path usually probes once too, because that first
probe removes cache ownership. The gain should therefore be attributed to
fewer scalar maintenance transactions and burst service, not a presumed eightfold
reduction in observed probes.

## Bounded-yield experiment

`--dma-line-yield-cycles 4` or `16`, together with `--dma-line-transfers`,
adds a bounded quiet interval after each line-operation response. It applies
between the read and write as well as between copied lines. The default is zero. Dynamic correctness/performance evidence covers yields
0, 4 and 16; the additionally accepted values 8, 32 and 64 remain unqualified
experiments despite passing configuration checks.
The counter is three bits for four cycles or five bits for sixteen cycles.
Yield occurs before the next request is first offered; it never withdraws a
stalled VALID or abandons an accepted owner. Scalar requests remain suppressed
while a complete eligible line is waiting. All variants retain the same buffers,
bridge credits, coherence probes and actual-write-response completion rule.

## Resource and timing targets

There is one 512-bit payload register in the DMA and one 512-bit saved write
payload register in the home: 128 bytes of new payload state total. Home read
results reuse the existing maintenance-data register. No new RAM, RAM port,
bridge slot, cache line or MSHR is requested. Existing line-transfer buffers are
reused. Matched CHIRRTL declares 1,034 additional scalar state bits for zero-yield
line mode: 1,024 payload bits and ten control/state bits. Four/sixteen-cycle yield
adds three/five counter bits. This is an IR declaration delta, not a synthesized
FF count. The three changed modules have identical memory declarations and port
counts (the home's eight tag RAM read/write ports are unchanged).

Line ready is selected from registered ownership/credits and request-valid
arbitration, without an address-range or line-data comparison. Address and
aperture checks remain on descriptor qualification and safety assertions.
The request payload adds wide registered data muxing; its mapped area, routing,
setup/hold and Fmax must still be measured. Source-level state counts and emitted
RTL are not LUT/FF/BRAM or physical timing results.

The legacy `MachinePlatform.activity.dmaMemoryFire` event still measures scalar
DMA handshakes only. It can be zero for a completely line-mode copy. Do not treat
it as total DMA payload/traffic; the focused fixture reports scalar requests,
line requests and actual AXI bytes separately. `readsSent`, `writesSent` and
`writesDone` remain progress counters in eight-byte words, advancing by eight
for each full line. The board-menu harness labels these as words, not physical
request counts; its 128 KiB expectation remains 16,384 words.

## Failure scope

Direct line read and write errors propagate to the DMA. It stops admitting new
work, drains accepted ownership, and reports failure; successful earlier writes
are not rolled back. A new descriptor may start only after that drain.

The pre-existing dirty cache writeback policy is unchanged: a denied dirty
probe/release writeback triggers a fail-stop assertion. Successful direct R/B
error-and-restart tests do not establish graceful recovery for that separate
failure. No assertion is weakened to make this candidate pass.

## Reproducible qualification

The focused fixture uses actual memory-copy DMA, 32 KiB two-way cache with two
MSHRs/two responses/two writebacks, AtomicDataMemory, registered request boundary,
mixed coherent home, scalar TileLink bridge, and the four-slot/two-write DDR
bridge. C++ supplies independent byte memory, delayed AXI responses, backpressure
and CPU DataPort traffic. It is not an executing CPU benchmark or MIG/PHY model;
next-line prefetch is disabled because the fixture has no CPU permission context.

Run with the already provisioned GSIM toolchain, without installing another
simulator:

```
source /path/to/verified/Valence/scripts/cloud/env.sh
export VALENCE_GSIM_SOURCE=/path/to/verified/Valence/simulator/build/gsim-src
mill -i IonSoC.test.testOnly ooo.DmaLineSpec ooo.FpgaNextConfigSpec
python3 -B simulator/gsim/dma_coherent_line.py --tag unique-candidate --line
```

A true old-source baseline uses the archived pre-change tree plus the separate
`simulator/gsim/fixtures/dma_coherent_line_baseline.scala` wrapper, and the same
C++ driver/model. Generated models, source inventories, clocks, delays, byte
counts and options must remain bound together. Copy throughput counts each
successfully copied destination payload byte once. CPU DataPort measurements
must not be relabelled CPU instruction execution or board performance.

Qualification results and exact commands are recorded separately after tests
finish. Experimental source-only publication is separate from hardware qualification.
Default enablement and board promotion still require the remaining physical
and timing/resource gates; no board/default promotion is implied here.

## Board baseline kept separate

The user-confirmed `9fceb61` bitstream on 2026-10-09 measured memory DMA
131,072 bytes in 515,418 ticks at 100 MHz, approximately 24.252 MiB/s. CoreMark
remained 197.984274; reported hot read was 245.136 MiB/s, and 128 KiB CPU read,
write and copy kernels were 80.289, 48.004 and 30.111 MiB/s. Those are board
baseline observations supplied by the user. They do not measure this line-DMA
candidate. The cloud-model speedup must not be multiplied onto the board number
as a promised result; routed timing and a matching new board test remain separate.
