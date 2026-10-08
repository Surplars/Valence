# Valence Bootrom V0.1 and UART RAM loader

Current VL100: RV64GC/two issue, CPU 100 MHz, UART raw 50 MHz, full 2 GiB DDR.
The 16550 baud reference is **7,372,800 Hz**, so **DLL=1 gives 460800 baud**.
The r5 DLL=7 erratum gives about 65829 baud; r6 corrects it. Old r5 artifacts
are preserved for diagnosis, not declared fixed by changing the host baud.
Build the corrected ROM with an explicit checked contract:

```sh
python3 fpga/firmware/build.py --ddr --ddr-bytes 0x80000000 --netboot \
  --cpu-hz 100000000 --uart-divisor 1 --uart-reference-hz 7372800 \
  --uart-baud 460800 --out <fresh-output>
python3 fpga/firmware/audit_uart_contract.py --rom <fresh-output> \
  --reference-hz 7372800 --baud 460800 --out <fresh-output>/uart-machine-code-audit.json
```

The auditor executes the compiled `uart_init` instructions against an independent
16550 model, checking DLAB, DLL/DLM, final 8N1 and FCR=7. Release also cross-checks
the actual emitted UART reference and BSP DTS. Source edits alone do not update
an already programmed ROM; the matching new bit must still be qualified.
The current network candidate additionally requires MAC CAP bit8 and the
busy-safe RX admission-stop/drain CSR at 0x90, plus DMA RX_STOP. It keeps RX
consuming through admitted frames and CDC/status tails before stopping DMA.
This needs matching new RTL; a ROM-only update cannot repair old hardware.
If the capability is absent, this ROM skips network initialization and leaves
UART recovery available. Complete failure-stage/timing diagnostics and the
pending physical acceptance checklist are in [NETBOOT-BOARD-TEST.txt](NETBOOT-BOARD-TEST.txt).
TFTP final ACK confirms transport only; UART VDON confirms RAM CRC only.
Neither host message proves the image ran. Host upload and final verification
wait are reported separately without changing wire protocol.

The clock/memory instructions below describe historical board profiles.

The board has 128 KiB BRAM ROM at `0x80000000`. The legacy Board40 profile
has 1 MiB UltraRAM; DDR profiles expose 512 MiB at
`0x80200000..0xA01FFFFF`. Select the clock and UART profile together.
The 2026-10-01 FIFO-UART builds are **45 MHz / 1,500,000 baud** and
**50 MHz / 115,200 baud**, 8N1, without hardware flow control.
Their UART reference clocks are 24,000,000 and 1,843,200 Hz respectively:
all divisors obey `baud = reference / (16 * max(divisor, 1))`.
Do not use CPU_HZ as a 16550 baud reference or reuse an old divisor=22 image
without adapting it. BootROM selects divisor=1 and enables the 16-byte FIFOs.
Older programmed bitstreams retain their original baud/reference semantics.
The BMG configuration is Native Dual Port ROM,
32768 x 32 bits on both ports, ENA/ENB pins, one-cycle read latency.

Build in WSL:

```sh
python3 fpga/firmware/build.py
python3 -m unittest discover -s fpga/firmware -p 'test_*.py'
```

Default outputs are under `build/fpga/firmware`: `bootrom.elf`,
`bootrom.bin`, `bootrom.coe`, `bootrom.even.hex`, `bootrom.odd.hex`,
`sample_app.elf`, `sample_app.bin`, and link maps. The COE is 32768
little-endian 32-bit words; bank hex files are the even/odd words used by
the portable GSIM ROM. Building firmware alone does not regenerate the
FPGA bitstream. The ROM-loader version must be synthesized/programmed once.

After that one board update, close other serial terminals and run on Windows:

```powershell
python -m pip install pyserial
python uart_load.py COM5 sample_app.bin --baud 1500000 --run --console
```

The tool also works on Linux (`python3 ... /dev/ttyUSB0 ...`). It validates
a download at the specified host baud, checks the final RAM CRC, and optionally
starts the app. Applications that reprogram UART need the exact profile's reference clock.
For example divisor=13 gives approximately 115384.6 baud on the 24 MHz reference,
while divisor=1 gives exactly 115200 on the 1.8432 MHz reference.
Set the OpenSBI/DTB UART clock-frequency accordingly; `--baud` changes only
the host serial port, not the running application's UART initialization.
Changing a RAM application thereafter needs only compile + serial download.
The example prints `RAM APP OK` and returns to the monitor. With an interactive
terminal, `--console` forwards keystrokes to UART while displaying board output;
the board handles input echo. Enter sends a carriage return. Ctrl-C closes
the host console; it does not stop the CPU. If stdin is redirected, the console
remains receive-only. Hardware reset recovers a hung
program and returns to ROM. Do not keep a terminal open on the same COM port.

The BootROM only receives and boots programs; RAM/ALU/timer/echo diagnostics
belong in downloaded applications. Reset enters UART download mode, without
trusting any image left in RAM:

```text
Valence Bootrom V0.1
download mode (UART)
```

After a verified download it prints `DOWNLOAD OK` and `ready to boot`.
With `--run`, it then prints (DDR profile):

```text
boot from UART (DDR) @ 0x0000000080200000
```

The UltraRAM profile uses `(RAM)`. UART is the image source, DDR/RAM is
the execution memory; flash/SD boot is not implemented. There is no command-line
prompt. Use the updated host tool, which waits for the complete `ready to boot`
status line; it also accepts the legacy `> ` prompt for older programmed ROMs.
The binary VLD1 protocol is unchanged.
Only two monitor commands remain:

- `d`: enter binary download mode (normally sent by the PC tool).
- `g`: execute the verified RAM image. A new download invalidates the old image.

Without `--run`, download only prepares the image; it does not auto-execute.
Retired test commands and other input are ignored. Normal application return
prints `APP RETURN` and permits rerun/re-download. Recoverable traps invalidate
the image and return to download mode. CRC, range checks and receive timeouts
are retained; they are download integrity protections, not built-in self-tests.

## DDR50 memory profile

Build with `python3 fpga/firmware/build.py --ddr --cpu-hz 50000000`
(use `--out build/fpga/firmware-ddr50` to keep baseline outputs separate).
The DDR hardware aperture is 512 MiB at `0x80200000..0xA01FFFFF`.
The monitor moves to `0xA01FC000..0xA01FFFFF`; the sample app's stack is
`0xA01F8000..0xA01FBFFF`. The loader limit is `0x1FFFC000` bytes
(512 MiB minus 16 KiB). Application code/data/BSS must leave its own stack
space as well. The flat-binary load/entry and VLD1 protocol remain unchanged.

```powershell
python uart_load.py COM4 image.bin --memory ddr --baud 115200 --run --console
```

The host defaults to `--memory uram` for compatibility. Choosing `ddr`
does not expand old hardware or old ROM firmware; a mismatched old monitor
rejects an oversized header. Rebuild/program the DDR ROM COE once.
For Linux, separately provide a matching OpenSBI/DTB boot arrangement and
reserve the monitor region; this loader still enters M-mode with a0=a1=0.

## Application ABI and memory (default UltraRAM profile)

The loader accepts only flat binaries, not ELF. Link code at `0x80200000`;
use `riscv64-unknown-elf-objcopy -O binary app.elf app.bin`.
The default entry is the first byte and must be 4-byte aligned, within the
downloaded image. An alternate entry can be supplied with `--entry`.
The current build targets RV64IM plus Zicsr/Zifencei, LP64; no floating point
or compressed instructions are required.

The top 16 KiB, `0x802fc000..0x802fffff`, belongs to the monitor's globals,
receive buffer and stack. The downloader rejects lengths above 1008 KiB and
never writes there. This is a loader check, **not isolation**: M-mode apps
can still overwrite this region or disable the monitor.

The example linker reserves an additional 16 KiB app stack at
`0x802f8000..0x802fbfff`; code/data/BSS must fit in the lower 992 KiB.
The sample startup initializes its own stack and global pointer and clears
BSS. Initialized data is already present in the flat binary at its RAM
address; BSS is not transferred. Other apps must provide equivalent startup.
A binary may use the full 1008 KiB only if it arranges its stack elsewhere
within its own allowed region.

Launch is in machine mode, bare addressing, interrupts disabled, unlocked PMP
entries disabled, after `fence rw,rw; fence.i`. `a0=a1=0`; no Linux/OpenSBI
boot ABI is provided. Normal return through `ra` restores the ROM stack and
monitor. The example may be downloaded/run repeatedly; rerunning without
downloading does not reset initialized data. A synchronous trap recovers the
download mode if the app preserved the ROM trap handler and memory access. Apps that
replace mtvec, lock PMP, change privilege, corrupt monitor RAM or hang may
require hardware reset. This is a trusted development monitor, not a secure
bootloader.

## Version 1 serial protocol

All integers are unsigned 32-bit little-endian; CRC is reflected IEEE CRC32
(polynomial 0xedb88320, initial/final XOR 0xffffffff), matching Python
`zlib.crc32`. Nothing is executed until the entire stream and RAM readback
CRC pass. Each chunk is buffered and checked before RAM writes.

1. Send ASCII `d`, wait for `VLOAD1\r\n`.
2. Send 36 bytes, Python struct `<4s8I`:
   `VLD1`, version=1, load=0x80200000, entry, image_length, image_crc32,
   chunk_size=256, reserved=0, CRC32 of the first 32 bytes.
3. Wait for a 12-byte `<4sII` response: `VACK`, sequence=0xffffffff,
   status=0. On rejection the monitor returns to download mode.
4. For each 256-byte chunk (last may be shorter), send `<4sIII`:
   `DATA`, zero-based sequence, payload length, CRC32(payload), then payload.
   **Wait for VACK before sending the next chunk.** Duplicate previous chunks
   with matching metadata are acknowledged without advancing the image.
5. Status values: 0 OK, 1 bad header, 2 bad range/length, 3 CRC error,
   4 unexpected sequence, 5 receive timeout/UART framing/overrun.
   A payload CRC error can be retried with the same sequence.
6. After the last chunk's VACK, wait for `VDON`, image_length, image_crc32.
   Only this completion marks a verified image. A final CRC failure reports
   VACK sequence=0xffffffff/status=3. `ready to boot\r\n` follows success;
   failures return to `download mode (UART)`.
7. Send ASCII `g` after the full readiness status line to execute.

The optimized UART has 16-byte RX/TX FIFOs (FCR=7 in BootROM).
Firmware still drains each byte promptly, then computes CRC/copies after the
whole chunk while the PC waits for ACK. FIFOs absorb short service delays;
they cannot prevent loss under sustained overload. OE/PE/FE/BI abort a corrupt
transfer rather than accepting it. Legacy bitstreams have only a single-byte
holding register.
The default PC timeout is 1 second per ACK, up to two retries; firmware aborts
a partial frame after a 3-second byte timeout and drains to an idle gap.
The final RAM readback budget is max(30 seconds, image size / 16 KiB/s),
with a `--verify-timeout SECONDS` override. If a final response is lost,
start a fresh download instead of replaying binary into the command loop.
These controls prevent unbounded memory writes; line noise/errors are
reported. A new session starts with `d` once download mode has returned.

## DDR50 downloadable memory tester

`python3 fpga/firmware/build_ddr_test.py` builds `build/fpga/ddr-test/ddr_test.bin`
(and ELF/map). This is a RAM application, not a ROM replacement; no Vivado build
is needed. Requires a matching **DDR profile**, 512 MiB CPU-visible aperture,
and correct CPU timebase/UART baud. Do not run on the old 1 MiB UltraRAM board.
Build separately for the two FIFO candidates:

```sh
python3 fpga/firmware/build_ddr_test.py --cpu-hz 45000000 --baud 1500000 --out build/fpga/ddr-test-45m
python3 fpga/firmware/build_ddr_test.py --cpu-hz 50000000 --baud 115200 --out build/fpga/ddr-test-50m
```

The baud argument records the inherited BootROM baud in the application's
banner; the tester does not reinitialize UART. Both are 6088-byte flat binaries.
Use `--baud 115200` on the host for the 50 MHz FIFO bit. The historical
50 MHz / 1.5 Mbaud commands below refer to the older release.

```powershell
python .\uart_load.py COM4 .\ddr_test.bin --memory ddr --baud 1500000 --run --console
```

It automatically runs a small smoke test, then accepts these single keys
(no Enter required):

- `s`: rerun smoke: 64-bit walking-one/zero, byte/halfword/word lanes,
  sparse address-bit 3..28 alias checks and low/middle/high blocks with six patterns.
- `q`: smoke plus eight 64 KiB windows spread across the aperture; six patterns
  (zero, ones, alternating bits, address-dependent data and its inverse).
- `f`: scan `0x80400000..0xA01F7FFF` twice, with address-derived data and its
  inverse. Each pass writes the entire range before reading it, to detect aliasing.
  This is about 510 MiB, not the full physical 2 GiB DDR and not the reserved areas.
  It can take minutes; write/read progress is printed every 8 MiB.
- `x`: return to BootROM from the menu. During quick/full tests, request abort
  at the next progress/pattern boundary; then `x` again returns to BootROM.

**Destructive:** existing contents of tested addresses are overwritten. The low
2 MiB (program/BSS) and high 32 KiB (application stack + BootROM) are excluded.
The linker checks that the program/BSS stay below the first tested address.
A severe physical/address-decoder fault can still corrupt code or stack and hang
the CPU; reset if needed. Do not run alongside an OS or other DDR payload.

Writes are volatile and separated from readback. On this Valence configuration,
`FENCE.I` drives L1 dirty-line writeback/invalidation; the tester explicitly uses
that path so it does not only test dirty cache hits. This is a **Valence-specific**
property, not a general RISC-V guarantee that FENCE.I flushes all data caches.

Failures show address, expected/actual 64-bit values, then stop after at most
eight mismatches. PASS/FAIL/ABORTED and elapsed milliseconds are reported.
PASS is a CPU/AXI-visible functional check, not DDR electrical margin/temperature
qualification or a complete March/retention test.

Focused validation: `GSIM_CXX=clang++-19 make gsim-ddr-test-app` uploads the exact
downloadable binary, runs its automatic smoke and returns to ROM, checking
actual sparse AXI backing memory contents as well as UART PASS output.
Quick/full scans are intended for the board and are not run in the focused GSIM.

2026-09-30 validation: the exact 6040-byte binary passed the focused GSIM in
3642430 cycles (2093 AXI read bursts, 833 write bursts), including backing-memory
readback and return to BootROM. All 12 host protocol tests also pass.

## DDR50 / 115200 CPU-visible bandwidth benchmark

The user reports the 2026-10-01 DDR50/115200 bit downloads/runs correctly and
the DDR tester passes; the DDR45/1.5 Mbaud board trial fails. This makes
DDR50/115200 the working board baseline, **not proof of the high-baud failure's
root cause**. No UART/clock RTL change or new bit is needed for this benchmark.

Build the RAM app (RV64IM/Zicsr/Zifencei, LP64, entry 0x80200000):

```sh
python3 fpga/firmware/build_ddr_bench.py
```

Outputs: build/fpga/ddr-bench-50m/ddr_bench.bin, ELF/map and disassembly.
Defaults are 50,000,000 Hz timebase and inherited 115200 baud; the program does
not reconfigure the UART. Copy the binary to the matching release's firmware/
directory, then:

```powershell
python .\uart_load.py COM4 .\ddr_bench.bin --memory ddr --baud 115200 --run --console
```

Startup runs a 4 KiB functional smoke with rates, then accepts single keys:

- s: repeat the 4 KiB smoke; too small for representative steady-state bandwidth.
- q: warm 1 KiB cache-read baseline, 64 KiB x4 and 1 MiB x1 read/write/copy,
  plus a 1 MiB dependent pointer ring.
- b: 8 MiB x1 read/write/copy plus an 8 MiB dependent pointer ring.
- x: drain/write back and return to BootROM. No mid-kernel abort polling is done,
  so timed loops do not include serial accesses; hardware reset recovers a hang.

Destructive fixed buffers start at 0x80400000 (source), 0x81400040 (destination)
and 0x83000000 (ring), each at most 8 MiB. The low 2 MiB code region and upper
32 KiB app-stack/monitor region are excluded; the linker checks program bounds.
Do not run alongside an OS or other DDR program whose data must be preserved.

The board has a 32 x 64-byte = 2 KiB write-back data L1. Volatile does **not**
disable it. Read/copy start after Valence-specific FENCE.I writeback/invalidation;
write/copy timing includes final dirty writeback. The 64-byte destination offset
avoids same-index source/destination cache thrashing. The warm 1 KiB result is
explicitly a cache measurement, while large buffers exercise the full CPU,
cache, TileLink, AXI CDC and DDR path. These are not DMA or MIG peak rates.

All timings use rdtime (50 MHz ticks), not unimplemented cycle/instret CSRs.
UART printing, initialization, poisoning and post-checks are outside timing.
Rates are binary MiB/s (1 MiB = 1048576 bytes), truncated to 3 decimal places.
Copy's primary rate counts copied payload once; logical R+W counts twice, not
actual AXI/DDR traffic (cache refills, RFO, eviction and instruction fetch differ).
The pointer ring has one dependent 64-bit load per 64-byte line; reported
ticks/hop and ns/hop include CPU/cache/bus latency and loop overhead, not DRAM
tCAS. The odd step visits every power-of-two-sized ring node before reuse.

Validation entry points: make ddr-bench-host-test and
GSIM_CXX=clang++-19 make gsim-ddr-bench-app. The latter directly loads the exact binary into independent AXI backing memory,
uses a minimal FIFO-enabling ROM call/return stub, executes only its 4 KiB smoke
and return, and checks reported units and AXI backing data. It does not re-test
UART uploading or the real BootROM; those have separate board-download coverage. The larger q/b cases are board
measurements, not full-size GSIM tests. Host kernel tests cover all power-of-two
working sets 1 KiB..8 MiB, expected checksums, copy, complete rings, units, data
corruption and zero-timer rejection. Synthetic GSIM rates are not FPGA results.

2026-10-01 focused result: host ASan/UBSan checks PASS; direct-load hardware GSIM
PASS at 3,713,840 cycles, 1,525 read bursts, 711 write bursts and 1,614 AXI stalls.
The exact downloadable 5,638-byte binary SHA256 is
46D728EF19758A8273DC488B4F5399F8951E3E9934FE507087B5F27926773110.
The initial full low-baud UART-upload GSIM attempt exceeded its 600-second budget
and is not counted as a pass; the final focused entry explicitly uses direct
memory loading. q/b FPGA bandwidth has not been measured by this agent.

## DDR50 OpenSBI + Linux / BusyBox

See [Linux bring-up](../../docs/linux-bringup.md) for the exact board layout.
Use the existing stable DDR50/115200 bit, not the experimental replay-stage RTL.
No floating-point hardware is required: kernel FPU is disabled, and musl 1.2.5,
BusyBox 1.37.0 is static RV64IMAC/lp64 soft-float.
Do not substitute prebuilt lp64d distro executables.

```sh
python3 fpga/firmware/build_rootfs.py --jobs 16
python3 fpga/firmware/build_linux.py --jobs 16
python3 -m unittest discover -s fpga/firmware -p test_linux_image.py
GSIM_CXX=clang++-19 python3 simulator/gsim/board_linux.py \
    build/fpga/linux-ddr50-busybox/opensbi_linux_ddr50.bin
```

The current source no longer builds, packages or autoruns custom fastfetch,
and no longer needs its source archive or the CMake tool archive. BusyBox and
musl sources remain required. Existing built images are historical artifacts;
this source change does not rewrite them or claim a fresh board boot.

The rootfs builder requires existing pinned archives (hashes in the script), or
already unpacked sources under `simulator/build`; it performs no network download
or system installation. Build tools: Linux and bare-metal RISC-V GCC/binutils,
make, host compiler and kernel build prerequisites. Target Linux
UAPI headers are copied into an isolated musl sysroot, not host glibc/CRT libraries.
The Linux builder reads clean local `simulator/build/linux` and pinned OpenSBI.
Outputs, logs and manifest are in `build/fpga/linux-ddr50-busybox`.

```powershell
python .\uart_load.py COM4 .\opensbi_linux_ddr50.bin --memory ddr --baud 115200 --run --console
```

Entry remains `0x80200000` (OpenSBI); do NOT set entry to the Linux payload at
`0x80400000`. OpenSBI embeds the DTB because the ROM hands off a1=0, relocates it
to `0x80300000`, and enters Linux in S-mode. The upper 16 KiB monitor region is
reserved in DT. No bit rebuild is needed to change this downloaded image.
The historical image was approximately 5.15 MiB; size/upload time must be
remeasured after rebuilding. After boot, BusyBox ash shows `valence#`; use
`uname -a`, `free -m`, `cat /proc/cpuinfo` or short `coremark 0 0 0 1` checks.
Rootfs is volatile RAM only; no network or persistent block device is enabled.
The console uses SBI DBCN/hvc0 polling, not qualified Linux AIA/UART IRQ support.
The image manifest distinguishes GSIM testing from actual board validation.
