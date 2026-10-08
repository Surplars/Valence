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
  controller selftests before waiting (at most five seconds) for the deferred
  8250 probe. It requires the expected MMIO port and a nonzero IRQ in
  `/proc/tty/driver/serial`, not just a placeholder `/dev/ttyS0` node.
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
`FIFO IRQ terminal ready` message is not guaranteed: normal 8250 startup clears
FIFOs. Runtime ordered/loss-free behavior is tested under the bounded workload,
not promised for arbitrary overload.

## Recovery and acceptance

If AIA selftest or native UART binding fails, the bootstrap writes an explicit
error to `/dev/kmsg` (visible through the remaining early/native output path),
then fails closed rather than quietly running an irq=0 polling port. Reset and
load the unchanged `--console sbi` recovery image. Network/platform failures
**after** UART readiness still leave the native getty available; an IRQ-controller
failure cannot retain an interrupt-driven input terminal.

Short isolated checks:

```
python fpga/firmware/linux_uart/test_uart_profile.py
python fpga/firmware/linux_uart/test_aia_budget.py
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
