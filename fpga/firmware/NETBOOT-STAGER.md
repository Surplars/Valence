# RAM netboot stager candidate

Status: cloud-built and independently structurally reviewed; not board validated.
ELF layout/host-copy tests are not target CPU execution or throughput measurements.
Do not replace the passed bitstream. This is an optional checked RAM payload for
its existing ROM loader. The focused real-I1 relocation/handoff smoke has passed; full network execution
on the board and performance remain unverified.

## Why this candidate

Current I1 ROM fetches are uncached. A1 also bypasses its full L1 for ROM, but
uses a two-instruction/64-bit ROM bridge with a retained beat. Saved identical
synthetic workloads show differing cycle cost, not a matched netboot rate test.
The user's historical 2 MB/s versus 0.2 MB/s needs paired board logs; CPU frequency
alone has not been established as the cause. Linux's later CMU policy cannot
accelerate a download that already finished.

The first download is a roughly 20 KiB stager. Its existing netboot protocol,
posted RX, CRC and copy implementation then execute from cacheable RAM, without
changing clocks, registers, PHY, TFTP options or the passed FPGA image.

## Address and handoff contract

- ROM loads the VLD at 0x80200000 and jumps to its entry there.
- A PC-relative, stackless stub disables interrupts, installs a temporary trap,
  copies initialized sections to 0xFFE00000, fences, and jumps high.
- The high entry establishes high GP/SP/mtvec and zeros high BSS. Code, constants,
  function pointers, RX storage and data are linked high, not patched low aliases.
- Runtime reservation is [0xFFE00000,0xFFE20000), including a 16 KiB stack.
  The final image must remain in [0x80200000,0xFFE00000).
- The unchanged verified loader performs stream CRC, final ACK handling, DMA
  quieting, dirty target memory flush and independent RAM CRC. Failure never
  launches. The final entry is zero-extended explicitly for the RV64 uint32 ABI.
- Final handoff matches ROM: hart 0, a1=0, interrupts/MPRV off, bare SATP/PMP,
  fence rw/rw and fence.i. This expects the normal packaged OpenSBI/Linux image,
  not an arbitrary kernel requiring a direct DTB argument.
- Reset after failure. This is a dedicated boot stager, not a returning monitor.

## Build and inspect

Use explicit IPs matching the ROM actually bound to the board bitstream, not
assumptions based on current source defaults:

```
source scripts/cloud/env.sh
python3 fpga/firmware/build_netboot_stager.py --out build/my-stager \
  --board-ip BOARD_IP --server-ip HOST_IP
python3 fpga/firmware/check_netboot_stager.py build/my-stager --negative-tests
```

The builder writes ELF, map, segment/symbol/disassembly reports, flat binary,
checked valence.vld and hashes. The checker independently parses ELF and compares
all flat load bytes, simulates the copy, checks high bounds/stack and the actual
entry zero-extension instructions. Negative tests recreate a VMA/LMA gap,
corruption, wrong entry, stack overlap and the old sign-extension launch bug.

## Host preparation for an eventual board test

Keep the final checked image's exact basename linux.vld. The existing packer can
create it from the existing boot payload; it does not invent a second format.
Do not overwrite files while the server is running. Both files are validated
before binding; only these two exact names are served on one listener.

```
python3 fpga/firmware/netboot_host.py serve build/my-stager/valence.vld \
  --second-image /absolute/path/linux.vld --memory ddr2g-menu \
  --bind HOST_IP --board BOARD_IP --once
```

Run only on the authorized trusted board network. This command does not change
host IP/firewall settings. The user initiates ROM netboot with its existing n
menu action. No new bitstream is needed. EOF ACK means transport completion,
not CRC success or Linux boot. Observe the stager UART CRC/launch result too.

## Measure without conflating phases

Collect complete host TFTP STATS and board NB totals lines for baseline and
candidate, keeping image hash, CPU/fabric rate, PHY rate, block/window and pacing
identical. Use analyze_netboot_log.py, also packaged as valence-netboot-report.
It reports receive/wait, copy, stream CRC, ACK service and RAM CRC separately;
receive wait includes DMA/MMIO polling and cannot alone identify network delay.
Host mean ACKed payload rate includes ACK waiting, not Ethernet wire rate.
Compare an explicit --packet-delay-us 0 run separately; default 100 us remains.
The aligned sliding-copy optimization is correctness tested but not yet measured
for speed on either CPU. Do not claim a recovered 10x rate from these tests.

The host large logical test transfers 208 MiB without storing a giant fixture,
exercising three 16-bit block wraps, dropped DATA65535 and ACK0 retransmissions,
and the zero-length final block. Actual firmware tests also cover >64 MiB with
stream and independent RAM CRC. These are protocol tests, not board throughput.

## Focused target CPU evidence

The source-only test runner is simulator/gsim/common/netboot_relocation_native.py.
It requires a fresh full-capacity I1 boot50-static programmable-ROM emission;
it never changes emitted DUT files or the production ROM image. It reuses the
actual cpu_boot_tb AXI DDR service and adds the strict high memory window.
A small ROM trampoline enters the real production low relocation stub.
A test-only high-linked main checks GP/SP/mtvec, initialized data, BSS clearing
from nonzero DDR, and a high function pointer before invoking the unchanged
production stage_launch. A low guest then verifies a0/a1/mie/satp.

The 2026-10-23 check2 run retired 826 high-address instructions (1304 total),
with 44 actual AXI reads and 14 writes. Restoring the old sign-extension launch
bug in external DDR caused a real instruction access fault at
0xFFFFFFFF80210000, cause 1. Neither condition was manufactured by internal
register pokes. The model retains 32 KiB I/D caches, a 16-entry I1 TLB, and the
full platform geometry. The production stager network main is not executed by
this fixture; the separate protocol tests cover its shared network library.
These counts are functional coverage, not a throughput benchmark or board proof.
