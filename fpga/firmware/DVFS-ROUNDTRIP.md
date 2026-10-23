# RAM-only configurable clock round-trip diagnostic

This is a separate downloadable payload for the existing CMU ABI2 / telemetry
ABI1 bitstream. It does not replace BootROM, regenerate ROM IP, program a board,
or qualify setup/hold timing. It is intended for a dedicated diagnostic boot,
not execution alongside Linux or another live payload.

## Build and load

Run `python3 fpga/firmware/build_dvfs_roundtrip.py` with the pinned RISC-V compiler
on PATH. The safe default target is50/50MHz; it does not select a higher rate.
Specify `--cpu-hz` and `--fabric-hz` explicitly to build another candidate.
For example, `--cpu-hz 100000000 --fabric-hz 100000000 --out build/dvfs-100-100`
creates a100/100 candidate, NOT a timing-qualified rate. Do not run a high-rate
candidate until its full-domain STA/native checks have been accepted.
`--scratch-bytes` accepts64..256KiB, multiple of64. The output contains
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
2. Request the configured CPU target while fabric stays50, then observe and check memory.
3. Request the configured fabric target with CPU at its target, then observe and check memory.
4. Request fabric50 with CPU still at its target, then observe and check memory.
5. Request CPU50, then observe/check50/50 and restore original scratch contents.

Example mathematical tuples are CPU195:D10/M39/O5=0x05270a,
fabric155:D10/M62/O10=0x0a3e0a, and50:D10/M40/O20=0x14280a.
These are not recommended or qualified operating points. CPU/fabric100MHz use
D10/M40/O10=0x0a280a. The actual build manifest and UART banner identify the targets.
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
telemetry read behavior. `test_dvfs_payload.c` runs the real main/observer/restore flow using host MMIO,
UART, time and cache hooks: cancel without writes, initial-rate rejection,
ordered target changes, stale/mismatched meter, absent read traffic, switch-error
recovery and scratch-restore failure. Build it with the same target macros, e.g.
`-DDVFS_CPU_HZ=100000000U -DDVFS_FABRIC_HZ=100000000U`.
Host hooks are not physical cache/DDR/native execution or timing proof.

## Exact UART loading recipe

After the matching board bitstream has booted at50/50, replace COMx with the
verified UART port and use:

`python fpga/firmware/uart_load.py COMx build/dvfs-100-100/dvfs_roundtrip.bin --baud 460800 --memory ddr2g-menu --console`

This downloads and launches the payload but does not trigger its clock requests.
Check the printed CPU/FABRIC targets against the approved test point before
typing r. Use q to exit if they differ. Never use the previous195/155 payload
as a substitute for a newly accepted lower-frequency candidate.

## Exact125/125 candidate matching the selected STA tuple

Build with `--cpu-hz 125000000 --fabric-hz 125000000 --cpu-parameters 0x08280a
--fabric-parameters 0x08280a --out build/dvfs-125-125-exact`. Both explicit tuples
are D10/M40/O8. They differ from the shared canonical125MHz profile D10/M50/O10.
The shared solver, ROM and hardware are unchanged; a diagnostic-only validated
staging-write adapter substitutes the explicit tuple while preserving the common
request/response, admission, error and timeout API. All fallback50 requests retain
D10/M40/O20. The builder and application independently reject wrong range, reserved
bits or a tuple whose exact frequency equation disagrees with the requested Hz.

The manifest records the exact packed values. Check both target Hz and MDO in the
UART banner BEFORE pressing r. This package is pending exact STA/native validation,
not qualified by virtue of having built. Do not substitute the older M50/O10
125MHz candidate for an M40/O8-qualified point.
