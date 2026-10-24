# Netboot copy: matched I1 CPU-cycle evidence, 2026-10-23

This is a 128-byte microbenchmark, not a board transfer-rate measurement or an
explanation proven for the user's historical 2 MB/s versus 0.2 MB/s observation.
The passed r6 RAM stager and passed FPGA bitstream were not modified.

## Complete result

All four variants use the same full-capacity frozen I1 RTL, CPU/fabric 50 MHz,
DDR 250 MHz, unchanged bounded AXI service, same source pattern and destination
state. Source alignment is 6 modulo 8 and destination alignment is 4 modulo 8.
This matches a subsequent 1024-byte TFTP DATA packet after a 36-byte VLD header:
Ethernet/IP/UDP/TFTP contributes 46 bytes, and the previous payload contributed
988 bytes. This test uses only 128 bytes, not a complete packet.

| Copy implementation / execution location | CPU cycles | Retired instructions | Simulated window time | AXI AR |
|---|---:|---:|---:|---:|
| Old byte packing, ROM | 5671 | 534 | 113.420 us | 0 |
| New aligned/sliding, ROM | 4025 | 348 | 80.500 us | 0 |
| Old byte packing, RAM, cold instructions | 1317 | 534 | 26.340 us | 4 |
| New aligned/sliding, RAM, cold instructions | 1168 | 348 | 23.360 us | 8 |

Every copy window had zero AXI AW/B. These windows measure completion into the
CPU cache, not completion to external DDR. The final real FENCE.I/drain and DDR
oracle check the actual backing memory separately before PASS.

- Old/new cycle ratios: 1.409 in ROM, 1.128 in RAM (29.0% and 11.3% fewer cycles).
- Same algorithm moved to RAM: 4.306x old, 3.446x new.
- These are ratios of this matched microbenchmark's cycle counts, not network
  bandwidth multipliers. The unchanged retired counts for each ROM/RAM pair
  support code placement, rather than less work, as the large difference here.
- The new routine has a larger instruction footprint. Its cold RAM case incurs
  eight AR transactions versus four for the old routine; do not extrapolate this
  first-call result to warmed instruction-cache steady state.

One fixed, separate production mode-3 CRC stage took 13,942 cycles / 1372 retired
instructions / 278.840 us, with 31 AR transactions. It runs from ROM against the
last copied 128-byte block and a previously unaccessed RAM lookup table. This is
not a comparison of CRC locations or CRC implementations. It demonstrates why
copy-only improvement is not an end-to-end netboot claim.

The full passing guest used 46,211 enabled CPU edges and retired 4155
instructions. Raw simulation finish time was 1,580,310,731 ps, which includes ROM
programming and reset before CPU enable. The enabled edge count corresponds to
924.220 us at 50 MHz. The native simulation took 166.67 seconds wall time; wall
time is simulator cost, not target speed.

## Matching and independent checks

- Snapshot: build/netboot-relocation-target-r1/rtl/emission-profile.json,
  SHA f6a2c8752f5e98416b787815d9c4d1d6af3423e32b2be9ec6a32aba42133525d.
  Full 32 KiB I/D caches, 16 I1 TLB entries, two cache ways, 1024 Home lines,
  four DDR read and two write slots. Every emitted SV hash is checked; no
  generated DUT edits or current-source substitution occur.
- Current working-tree differences after that emission were A1 park, its test
  fixture and A1-only platform branches. This result belongs to the explicitly
  frozen I1 snapshot, not a claimed fresh validation of all current sources.
- The old loop is the byte-packing body before be875ac. Both algorithms exclude
  the common unchanged board-store bounds check. The new body is the actual
  netboot_copy.h. Both compile with the same GCC flags; neither is a host model.
- One linked 680-byte instruction blob is present at ROM 0x80004000 and as
  identical bytes at RAM 0x80204000. Internal relative branches remain unchanged.
  The 2048-byte production CRC table is at RAM 0x80238000.
- The test initializes external DDR with these bytes. A separate independent
  ELF parser verified every byte against the ELF sections, flat ROM LMA image
  and DDR hex input. This removes test initialization cost, not a DUT operation.
  It does not replace the separately passed real stager relocation test.
- Before each case: real FENCE.I, source read prewarm and destination write
  prewarm. Thus data is warm and destination lines writable; RAM instructions
  are cold for each single measured invocation. FENCE.I also invalidates I1 BTB
  metadata. There is no warm-instruction-repeat measurement in the final batch.
- Each measurement begins/ends at the same marker instruction retirement and
  includes the common caller/return overhead. Time/cycles are sampled from real
  CPU retirement and clock edges, not estimated from instruction counts.
- After all cases and a final real FENCE.I, the external DDR oracle checks every
  byte of all four 192-byte source regions and all four destination regions,
  including the untouched prefix/tail. Every B response must have completed.
  The production CRC result also matches an independently computed host zlib
  constant. No register or cache state is forced or poked.

Passing evidence: build/netboot-copy-perf-r5/{receipt.json,run.log,
preload-byte-proof.json,disassembly.txt}. Source runner and guest files are
simulator/gsim/common/netboot_copy_perf*.

## Interpretation and remaining measurements

For this small, warm-data workload, instruction placement has a substantially
larger effect than the copy-loop change. That supports trying the unchanged-bit
RAM stager as a practical experiment. It does not assign a percentage of the
actual netboot stall budget to instruction fetch; no stage-stall instrumentation
was collected.

Not measured here: entire stager networking on hardware, cold packet data/DMA
ownership, ACK/window waiting, PHY behavior, host 100-us pacing or OS sleep,
CRC execution after relocation, warmed instruction steady state, other
alignment performance or a full-size DATA packet. Existing exhaustive host
alignment tests establish copy correctness, not performance at those alignments.
Paired host TFTP STATS and board NB totals with the same payload, clock rates,
block/window and pacing remain necessary for the actual regression diagnosis.

The initial 24-case run reached its 600-second wall bound without visible
buffered windows. A four-case version with ROM startup table copy and per-case
ROM byte validation reached its 300-second bound after partial windows. Neither
is a complete PASS and neither supplies the ratios above. The final four-case
batch preloads external DDR, flushes progress explicitly, checks every copied
byte after drain and retains one independent CRC phase. Its 300-second bound
was not extended.
