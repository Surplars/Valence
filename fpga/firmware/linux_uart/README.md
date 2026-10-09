# Interrupt-driven runtime terminal candidate

This is a **software-only, opt-in candidate**, not a new bitstream. The frozen
BootROM, TUI, UART upload protocol, clock profile and production RTL are unchanged.
The default build remains `--console sbi` for recovery. The candidate requires the
existing qualified single-hart CSR-only APLIC/IMSIC implementation.

## What changes

- Build the Debian/Dinit kernel stage with `--console uart-irq`. The kernel,
  rootfs and delivery records carry the explicit console profile; mixing owners
  fails validation. Result filenames gain `_uart_irq`.
- Use upstream built-in `SERIAL_8250`, `SERIAL_8250_CONSOLE` and
  `SERIAL_OF_PLATFORM`, with `console=ttyS0,460800n8`. No private TTY driver.
- Disable `HVC_RISCV_SBI` entirely. Merely removing `console=hvc0` would leave
  an HVC receive owner that could race the native UART.
- The UART DT node uses the existing APLIC source **3**, level-high, byte MMIO at
  `0x10000000`, register shift 0, FIFO size 16. Packet DMA remains source 6;
  memcpy remains source 4. No invented `riscv,imsics` aperture.
- `clock-frequency=7372800` is the UART's **virtual baud reference**, not its raw
  50 MHz peripheral clock. DLL=1 gives the unchanged 460800 baud.
- Dinit `/init` mounts API filesystems, loads the AIA module and verifies both
  controller selftests before waiting (50 checks with up to 49 0.1-second sleeps, plus probe/process work) for the deferred
  8250 probe. It requires the expected MMIO port and a nonzero IRQ in
  `/proc/tty/driver/serial_8250`, not just a placeholder `/dev/ttyS0` node.
- After configuring CLOCAL (there are no external modem carrier pins), `/init`
  reopens stdin/stdout/stderr on ttyS0. This is essential because the kernel tried
  to open `/dev/console` before the modular IRQ controller existed. Agetty is
  switched to ttyS0 before Dinit starts. Later `modprobe valence_aia` is idempotent.

## Runtime behavior and limits

Upstream 8250 owns locking, the software transmit FIFO, TTY flip buffers, error
accounting, and console synchronization. Ordinary terminal TX fills up to the
16-byte FIFO and enables THRE only while software output is queued. RX drains
with the upstream 256-character budget; the 16550A receive threshold is eight
bytes and sparse input is delivered by the hardware four-character timeout.
There is no periodic SBI/HVC receive poller in this profile. The unchanged
hardware implements THRE reassertion on IER 0→1, so upstream's startup tests do
not need the broken-THRE backup timer. The board still must confirm this with
its real interrupt path.

The AIA parent now yields after 64 **valid** claims without disabling delivery;
the next identity remains pending. Previously sustained legal traffic could be
misclassified as a storm and disable all sources. Invalid IDs still fail closed.
`irqchip_status` exposes `budget_yields` for this distinction. The existing
mask/ack/unmask held-level retrigger protocol is preserved.

`earlycon=sbi` remains for output before native binding and is retired by normal
console handover (no `keep_bootcon`). OpenSBI/BootROM never become concurrent
runtime input consumers. Early boot and panic output still use polling. The
upstream 8250 **printk console path also uses bounded FIFO polling**, even when
normal TTY RX/TX are interrupt driven. This candidate does not claim that every
kernel console write is interrupt-driven or free of spin waits.

The baud rate and wire bandwidth are unchanged. CPU idle use, typing latency,
IRQ rate and achieved throughput need measurement on the board. A 16-byte FIFO
has finite interrupt-latency tolerance; prolonged printk floods or disabled IRQs
can still overrun RX without hardware flow control. Input typed before the
`FIFO IRQ binding ready` message is not guaranteed: normal 8250 startup clears
FIFOs. Runtime ordered/loss-free behavior is tested under the bounded workload,
not promised for arbitrary overload.

## Recovery and acceptance

If AIA selftest or native UART binding fails, the bootstrap writes an explicit
error to `/dev/kmsg` (visible through the remaining early/native output path),
then fails closed rather than quietly running an irq=0 polling port. PID 1
stays asleep and records `/run/valence/uart-recovery-required`, preserving
diagnostic output without claiming an interactive input terminal. Reset and load the unchanged `--console sbi` recovery image. Network/platform failures
**after** UART readiness still leave the native getty available; an IRQ-controller
failure cannot retain an interrupt-driven input terminal.

Short isolated checks:

```
python fpga/firmware/linux_uart/test_uart_profile.py
python fpga/firmware/linux_uart/test_aia_budget.py
python fpga/firmware/linux_uart/test_uart_bootstrap_regression.py
python fpga/firmware/linux_net/test_build_image.py
GSIM_CXX=clang++-19 python simulator/gsim/uart_runtime.py
```

The GSIM batch uses unchanged UART RTL, independent TX/RX byte sequences,
full-duplex FIFO operation, idle zero-MMIO checks, THRE re-enable semantics,
sparse-input timeout, mutation rejection, and APLIC source-3 held-level rearm.
It does not boot Linux. No full GSIM, long Linux simulation, Vivado or bit
regeneration is required by this software candidate.

Before release: compile the kernel and modified AIA module with `W=1`; validate
compiled DT phandles; audit the exact embedded rootfs; then on the existing bit
confirm source-3 `/proc/interrupts` counts increase during input/output, idle IRQ
counts stop, no `khvcd` exists, TX/RX bytes match a host-side sequence, and GMAC
source 6 still works during a bidirectional UART load. Measure CPU use and
latency against the SBI image at the same baud. Board tests are pending.

## Primary sources audited

Pinned Linux source: `551c722f40809618230001baccf219193e22fc5a`.

- [8250 OF binding](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/Documentation/devicetree/bindings/serial/8250.yaml)
- [8250 OF probe](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/drivers/tty/serial/8250/8250_of.c)
- [8250 RX/TX, THRE startup tests and console code](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/drivers/tty/serial/8250/8250_port.c)
- [SBI HVC initialization](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/drivers/tty/hvc/hvc_riscv_sbi.c)

## RV64 binding-format regression (2026-10-08)

The first real-board IRQ image reached a correctly bound 16550A ttyS0 at
`MMIO:0x0000000010000000`, Linux IRQ 3, then falsely timed out in `/init`.
The original bootstrap compared the address to an unpadded string. Linux
`uart_get_ioinfos()` uses `%pa`, and `lib/vsprintf.c:address_val()` formats
`sizeof(phys_addr_t)` bytes, so RV64 prints sixteen hexadecimal digits.
The v2 strict expression accepts leading zeros at the same physical
base; wrong addresses, unknown UART types, zero IRQs and failed AIA selftests
remain rejected. No timeout increase or IRQ bypass is involved.

That v2 real-port `/proc` predicate was intentionally independent of sysfs serial
controller/port nesting. The earlier regression tests reproduced the nested ctrl/port/tty
shape, deferred probe stages, real padded output, invalid lookalikes and a
non-exiting PID 1 recovery state, but used the wrong proc filename. The original shipped RV64 `mawk` also rejects
the old predicate and accepts the corrected predicate under QEMU user-mode.
This is software reproduction, not a successful repaired-image board boot.

## Pinned proc-name repair (2026-10-09)

The v2 image still reached 8250 probe, then falsely reported a binding timeout.
The exact pinned kernel registers `serial8250_reg.driver_name = "serial_8250"`;
`serial_core.c` copies that name to the tty driver and `proc_tty.c` creates
`/proc/tty/driver/serial_8250`. v2 inspected the different `/serial` pathname.
The old regression fixture used that same incorrect filename, masking the bug.

The repaired bootstrap reads only the canonical `serial_8250` file. It accepts
RV64 zero-padding while still requiring line 0, type 16550A, byte MMIO at
`0x10000000`, a nonzero Linux IRQ, and a character ttyS0. It deliberately does
not fall back to a different driver's file or extend the timeout. Linux virtual
IRQ numbering is not required to equal APLIC hardware source 3. AIA health is
checked again after deferred probing. The readiness message says binding is
ready; actual interrupt traffic remains unverified until board acceptance.

Recovery records the proc contents/controller state once in
`/run/valence/uart-failure.log` and keeps PID 1 alive even if diagnostics cannot
be written. `command exec` is deliberate: in Debian dash, a failed redirection
on bare special builtin `exec` exits the shell before an `||` recovery handler.
The shipped RV64 dash and mawk are tested through QEMU user-mode, including a
failed tty descriptor reopen. No QEMU hardware/UART claim is implied.

`kernel_proc_contract.py` checks the SHA-256 of the three exact upstream files,
derives the proc pathname from their registration chain, and compares it to the
bootstrap. The kernel preparation and final image stages run this gate. Old
kernel receipts without the contract must be re-qualified into a fresh output;
never edit a completed image's receipt to imply it passed a newer check.
`PROC_FS`, `SYSFS` and `DEVTMPFS` are explicit native-console requirements.

Source-only checks, using already available tools and sources:

```
python3 fpga/firmware/linux_uart/kernel_proc_contract.py --kernel-source simulator/build/linux
VALENCE_LINUX_SOURCE=simulator/build/linux python3 fpga/firmware/linux_uart/test_kernel_proc_contract.py
python3 fpga/firmware/linux_uart/test_uart_bootstrap_regression.py
python3 fpga/firmware/linux_uart/test_uart_profile.py
# Optional replay using the already shipped Debian target tools:
VALENCE_QEMU=/path/to/qemu-riscv64 VALENCE_TARGET_ROOTFS=/path/to/preserved/v2/rootfs \
  python3 fpga/firmware/linux_uart/test_uart_bootstrap_regression.py
```

The filesystem fixture is independent of production pathname substitutions.
It tests the canonical file, the old-path mutation, missing canonical file with
a misleading legacy file present, deferred probe, bad/zero IRQ, wrong MMIO,
unknown UART, module failure, late controller fault, termios/open failure and
failure to write diagnostics. Pinned source changes and old helper names are
negative tests. Preserve the original v1/v2 archives and receipts as evidence.

### Adapted image workflow and U-Boot handoff

Use the existing signed Debian 13 seed and pinned Dinit tools. A native UART
build adds `--console uart-irq --init-system dinit --initramfs-compression lz4`
to the kernel-stage command in `debian_rootfs/README.md`; build each kernel,
rootfs and delivery into a new independent directory. `--reuse-kernel` may seed
that new kernel cache only from its matching recorded baseline. Do not run a
kernel/rootfs build while the shared heavy-build slots are occupied.

The rootfs preserves Debian commands, all five current matched modules, and
Dinit. No package install is needed for this repair. No self-built fastfetch or
its source/license payload is added. The unused legacy custom BusyBox is still
excluded from the Dinit archive; Debian-owned files and old seeds stay intact.
The corrected helper must appear in the newly packed cpio, its source digest
must match the new rootfs receipt, and the exact cpio must round-trip through
the LZ4 bytes embedded in the kernel. Run the packed-content audit after image
construction; passing source tests alone does not produce a repaired image.

New deliveries export `Image` (the exact raw Linux bytes with embedded
initramfs) and the paired `valence-vl100.dtb`, in addition to the existing
combined OpenSBI BIN/VLD. The content audit independently compares raw `Image`
with the bytes inside the combined firmware. U-Boot `booti` consumes raw Image,
never the VLD download wrapper. The runtime DTB must match the UART IRQ profile.

Current hardware contract: DDR starts at `0x80200000`, spans `0x80000000` bytes
(2 GiB), and ends at `0x100200000`; `0x80000000` itself is the ROM base.
CPU is 100 MHz; UART remains 460800, byte MMIO at `0x10000000`, APLIC source 3.
Combined firmware enters OpenSBI at `0x80200000`, uses its embedded DTB at
`0x80300000`, and Linux enters at `0x80400000`.

For the corrected U-Boot stage-2 defaults, stage raw Image at `0x84000000` and
its external DTB at `0x90000000`, then use `booti ${kernel_addr_r} - ${fdt_addr_r}`.
There is no separate initrd. The earlier `0x83000000` DTB staging address is
unsafe for this large embedded-rootfs Image: booti relocates the Image to
`0x80400000` before parsing the external DTB and would overwrite it. The U-Boot
build separately validates staging and relocation ranges; those checks and
board boot are not implied by the Linux source tests.

The runtime DTB now reserves both diagnostics `[0xfff78000,0xffff8000)` and
monitor `[0xffff8000,0xffffc000)` with `no-map`, under `reserved-memory`.
Previously only the monitor was reserved. The image range checks and VLD packer
use the tighter `ddr2g-menu` limit so payloads cannot occupy diagnostic RAM.
The 512 MiB and 1 GiB legacy profiles retain their existing reservations.
