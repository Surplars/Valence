OpenIon Orbital-I1 diagnostics V0.1 - current batch44 CPU300 / UART460800

Use i1_diag_menu_cpu300_o3.bin, not the internal i1_diag_smoke test twin.
Reset the board; use the existing OpenOCD session:
  valence_ram::start
  valence_download_and_run {/mnt/e/VM/Share/Valence-rtl/i1-diagnostics-cpu300-o3-20261018-r1/i1_diag_menu_cpu300_o3.bin} 0x80200000
UART 460800 / 8N1 / no flow control. COMMIT automatically launches the menu.
No bit/RTL/clock change required. Filename path belongs to OpenOCD's OS.

c: official unchanged CoreMark, -O3 RV64IM, standard 2000bytes, automatic >=10s
   (calibration may also take seconds). Real cycle/instret/time, IPC and CoreMark/MHz.
   Only FORMAL_RESULT_VALID with complete CRC output and >=10s is a valid run.
   No LTO, no algorithm edits. HAS_FLOAT=1 permits precise software-float time
   reporting OUTSIDE the timed integer workload; no hardware FPU instructions.
k: 1-iteration CoreMark CRC smoke; NEVER report this as a score.
b/m: S-mode Bare / Sv39, 1MiB per buffer, same assembly loops.
   Sv39 data uses nonidentity mappings and 4KiB pages; code uses 1GiB identity leaf.
p/t: both modes. t is CPU-visible end-to-end bus-path throughput, NOT raw AXI duty.
l: both modes, 8MiB per buffer.
h: 16KiB per buffer, 256 repetitions, cache-resident path (32KiB D-cache).
s: 256-byte Bare/Sv39 data checks, intentional unmapped-page exception, CoreMark CRC smoke.
d: DMA unavailable. This current no-MAC I1 bit contains no general memcpy DMA.
i/?: configuration / menu.

READ uses 8x64bit loads, WRITE 8x64bit stores, COPY_SCALAR pairs each load/store,
COPY_U8 groups eight independent loads before stores. All bytes are verified after
timing, READ has an expected arithmetic checksum. No UART inside measured loops.
Timers/counters are real CSR reads. Payload MiB/s uses 1048576 bytes/MiB.
COPY logical R+W counts 2x payload; neither is an actual AXI transaction counter.
Cache stays enabled. Normal fence orders memory but DOES NOT FLUSH dirty D-cache
on this hardware. Dirty-tail writeback is NOT explicitly included in the timing;
use large buffers for steady-state comparison, not MIG-peak claims.
64bit/300MHz AXI ideal single-direction data ceiling = 2400MB/s = 2288.818MiB/s;
protocol, bubbles, CPU issue, fill/writeback, CDC and DDR reduce actual throughput.

DESTRUCTIVE scratch: source [0x81000000,0x81800000), destination
[0x83000040,0x83800040); code/data/page tables/stack occupy the first1MiB at0x80200000.
Standalone M-mode entry, no OpenSBI/Linux, no interrupts or other loaded guest.
S-mode jobs restore to M through checked ECALL; unexpected S faults report cause/PC/tval.
Do not use this DDR scratch concurrently with an OS or another memory agent.
This release does not add DMA hardware or bus-performance counters. Board results
must be collected on the real board. A short GSIM smoke is not a formal score.
