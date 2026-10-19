# Common-platform native short boot

`cpu_boot_native.py` consumes the centrally emitted **unchanged**
`CommonMachinePlatform` SystemVerilog and its `emission-profile.json`. It never
builds Scala, changes the RTL, installs a simulator, or uses Verilator/Vivado.
The existing Icarus exception is needed because the pinned GSIM step API does not
model independent clock edges.

## Profiles and ROMs

Both CPU selections use the same 128 KiB programmable ROM model, common fabric,
managed UART/CMU/tri-speed peripheral bank, Home 1024-line/4-way geometry, four DDR
slots, two write slots, and native four-bit AXI IDs. I1 retains 32 KiB I/D caches,
16 TLB entries and AIA. A1 retains the public Selected two-issue, 32 KiB I/D,
two-read-MSHR/two-writeback profile. The test does not reduce those capacities.

The 688-byte `cpu_boot.S` guest is **test firmware**, zero-padded to 128 KiB. It
never replaces the production TUI ROM. The separately supplied unchanged full TUI
binary must have SHA-256
`9b7b73d044f0c6a457f5ed7c3ae2f332aa3b076d26ddf65bef577fe24278e80d`.
The runner can reuse the same compiled model to check its exact 53-byte initial
UART banner. This is a banner-startup check, not complete TUI/Linux boot.

The explicit programming port loads all 32768 words while `bootEnable` is low.
An explicit low-to-high cold-reset edge initializes initially stopped gated domains. Only the fabric programming clock runs during asserted cold-reset initialization; the emitted SyncReadMem write port is not reset-gated. All clocks start before reset release, run continuously thereafter, and CPU startup is admitted once only. No force,
internal RAM poke, instruction replacement, warm reset, or fake MMIO response is
used. The production firmware's high DDR monitor/stack region is represented by
a separate bounded backing window; the aperture and hardware capacity are not
changed.

## Oracles

- Actual serialized managed-UART bytes, 460800/8N1 from the independent 50 MHz
  raw UART clock, plus scratch-register readback
- Dirty DDR reads/writes and byte lanes, followed by real final AXI writeback
- Timer high-half MMIO accesses and one precise timer interrupt
- APLIC GENMSI through the held CDC to IMSIC, one external interrupt, and exact
  MTOPEI identity 7 acknowledgment
- Original DDR code returning 9, dirty instruction store, FENCE.I, then new DDR
  instruction returning 42; all three fences must retire
- The first and modified-code fences cannot retire before the corresponding real
  AXI B completion, even if AW/W were already accepted and backing RAM updated
- Monotonic, progressing CPU time snapshots across the independent clock boundary
- AXI payload stability under deterministic AR/AW/W backpressure, preserved read
  and write IDs/owners, separate AW/W queues, delayed R/B replies and reverse
  ready-read selection

The host allows 16 independent owners, preserving the DUT's full capacity rather
than imposing a singleton bottleneck. Observed concurrency is reported; the boot
fixture does not claim to exhaustively saturate every hardware slot.

Optional negative controls corrupt the expected UART byte, suppress a read
response, or withhold a code-line write B response. A host-side wall timeout is
not accepted as a negative-control pass: the independent HDL oracle must fire.

## Evidence and limitations

Every run binds all main Scala, platform test Scala, SV resources, runner/guest/TB,
emitter source/classpath/artifact hashes, tool executables, guest and production
ROM hashes, and generated native executable/logs. Original evidence directories
are never overwritten. Commands have bounded time and a continuously checked
4 GiB free-disk floor.

An A1 export with packed assignment patterns can require the already installed
`sv2v` standard lowering before Icarus. This never changes the original emitted
SV used by production tools. Pass `--conversion-receipt` for converted input:
the runner verifies exact original emission/input/output/tool hashes, requires
`--exclude=SeverityTask`, and checks that every original `$error` and `$fatal`
severity task survives. A converted file without that chain is rejected.
`--firmware-only --firmware-bin ...` reports a separate banner-only status;
it cannot be reported as passing the short-boot guest.

The small BUFGCE model only latches CE on falling raw-clock edges. The actual
production synchronizer and managed peripheral boundaries remain instantiated.
This is digital protocol/function evidence, **not** metastability, clock-gating,
routed timing, FPGA, Ethernet packet, JTAG, complete ISA, or performance sign-off.

## Current qualification (2026-10-19)

The unchanged 688-byte guest passed on both full-capacity CPU selections using
native emission revision 3. Receipts are in the integration evidence tree:
`common-platform-i1-native-boot-r4/receipt.json` and
`common-platform-a1-native-boot-r5/receipt.json`. Both observed eight exact UART
bytes, 11 DDR reads, nine writes with nine B completions, two code-line B
completions, three retired FENCE.I instructions, one timer interrupt, one MSI,
and exactly one original/new code execution returning 9/42. Final DDR signatures
passed. A1 used the separately bound, severity-preserving conversion revision 4.
The guest exercised at most one concurrent read; this is not slot-saturation
qualification. A1 observed two pending B responses.

Both CPU selections also passed the unchanged production-ROM exact 53-byte
serialized banner check. Receipts are
`common-platform-i1-native-firmware-r2/receipt.json` and
`common-platform-a1-native-firmware-r2/receipt.json`. I1 observed 56,969 retired
instructions and A1 49,040; each received all 53 expected UART bytes. Each reused
its exact passing short-boot executable and loaded all 32768 ROM words from the
unchanged 69568-byte production image. This establishes banner startup only.

Absolute simulation periods are I1 CPU 3334 ps (approximately 299.940 MHz,
rounded to the simulator's 1 ps resolution), A1 CPU 10000 ps, fabric/timebase
4000 ps, UART/AON 20000 ps, and independent raw Ethernet TX/RX 8000 ps.
There is no frequency-ratio substitution or simulated-time acceleration.
Counts above describe functional coverage, not measured hardware performance.

Both direct-executable negative controls passed in
`common-platform-i1-native-negatives-r1/receipt.json`. The expected-UART-byte
perturbation was rejected by `COMMON_BOOT_UART_BANNER_ORACLE`. With the code-line
B response withheld, AW/W were fully consumed, one B remained pending, and the
last retired instruction was the code store at `0x8000020c`. The HDL cycle bound
then rejected the run with zero code-line B completions and zero retired fences.
Neither result was a tool timeout. The controls reused the passing I1 executable
without rerunning the positive guest, changing the DUT, or rebuilding the model.
`common-platform-cpu-native-summary-r1.json` binds all five passing receipts and
rechecks their artifacts, source/classes and exact production-ROM banner bytes.

Banner revision 1 was stopped, with evidence preserved, after measured
byte-copy/BSS startup throughput showed its 900-second wall bound was
insufficient. Passing revision 2 used an explicitly approved 2400-second bound.
All earlier ROM-width, reset-initialization and uninitialized-arbiter failures
remain preserved as regression evidence.
