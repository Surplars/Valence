# RAM-only 195 / 155 MHz clock round-trip diagnostic

This is a separate downloadable payload for the existing CMU ABI2 / telemetry
ABI1 bitstream. It does not replace BootROM, regenerate ROM IP, program a board,
or qualify setup/hold timing. It is intended for a dedicated diagnostic boot,
not execution alongside Linux or another live payload.

## Build and load

Run `python3 fpga/firmware/build_dvfs_roundtrip.py` with the pinned RISC-V compiler
on PATH. `--scratch-bytes` accepts64..256KiB, multiple of64. The output contains
ELF, flat BIN, link map, symbols and a source/artifact hash manifest. Load the
BIN at0x80200000 with the existing BootROM UART/JTAG download workflow. The
loader automatically enters the payload after verification, but **the payload
does not change clocks until you type lowercase r**. Type q or wait60 seconds
to leave without changing any rate. UART settings remain the existing460800;
no UART divisor is reprogrammed. BootROM treats an external program return as
untrusted ownership, so reset the board after this diagnostic, pass or fail.

For the UART loader the matching memory profile is `ddr2g-menu`; retain its
normal verification/automatic-launch protocol. Do not send an ELF as a flat BIN.

## Explicit sequence

The payload first requires both clocks already configured50MHz, both CMUs idle,
valid and error-free, advertised compatible D/M/O bounds, diagnostic admission,
and an idle memory DMA. It validates both target profiles before changing either.

1. Observe50/50 and preserve/check the allocated scratch data.
2. Request CPU195 while fabric stays50, then observe and check memory.
3. Request fabric155 with CPU195, then observe and check memory.
4. Request fabric50 with CPU195, then observe and check memory.
5. Request CPU50, then observe/check50/50 and restore original scratch contents.

Exact tuples are CPU195:D10/M39/O5=0x05270a,
fabric155:D10/M62/O10=0x0a3e0a, and50:D10/M40/O20=0x14280a.
These use the existing software parameter ABI, not the BootROM console's initial
50..150MHz advertised list. Mathematical validity is not native/board qualification.

Each phase logs requested/configured Hz, status/errors/completion count,
independent measured Hz, sample sequence, edges, CPU retirement and AXI reads.
It requires fresh valid meter windows, advancing cumulative edge counters,
CPU retirement, and measured frequency within1% of the requested frequency.
The1% is a meter-boundary tolerance, not timing margin. Cold scratch checks must
also produce advancing cumulative fabric AXI R beats; zero traffic fails.
A complete pass ends with `DVFS_ROUNDTRIP_PASS_DIAGNOSTIC_ONLY`.

## Memory ownership and limitations

The linker reserves exactly0x80200000..0x80300000 exclusively for this payload,
its BSS, stack, scratch and disjoint sweep region. Standard DTB/firmware regions
at or above0x80300000 and BootROM high-RAM reservations are not touched. The
manifest gives exact actual scratch, sweep and backup addresses. Link-time
assertions prevent collision with the16KiB stack. Scratch is NOLOAD, is not
zeroed by startup, and is copied to a private BSS backup before writing patterns;
the original bytes are restored and reread before returning. Sweep is read-only.
No arbitrary user-supplied physical range is accepted.

This allocation cannot coexist with a kernel or another live image that owns
these addresses. Downloading the diagnostic already replaces the prior payload;
use a fresh dedicated test boot, not an in-place Linux test. The scratch backup
protects only its explicit allocation, not against general hardware failure.

The cold-read method follows this SoC's existing monitor contract: fence.i
writes back private dirty lines, followed by two disjoint64KiB read-only sweeps
for current caches of at most32KiB and one/two ways. This is not a generic RISC-V
fence.i guarantee. Do not claim coverage for a different cache architecture.

Polling, sample retries and recovery are bounded. On failure the application
logs the exact failed stage, attempts fabric50 then CPU50 only when the controller
becomes idle/nonfatal, and restores scratch if execution remains available.
A stopped clock/fabric can block CPU execution/MMIO itself; software bounds are
not an independent watchdog and cannot guarantee recovery from a frozen CPU.
Reset is required if a fatal/busy state persists or scratch restoration fails.

## Host checks

Compile/run `test_dvfs_roundtrip.c` with a C11 compiler. It independently checks
actual195/155/50 tuples, exact request ordering, every request/observation failure
stop point and frequency tolerance boundaries. Existing
`python3 fpga/firmware/test_clock_control.py` covers the MMIO helper and coherent
telemetry read behavior. Neither host test claims hardware execution or timing.
