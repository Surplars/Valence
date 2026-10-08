# Network capacities and Linux posted RX candidate

This layer follows the windowed-netboot candidate and is based on upstream
`6c8977f684830137fae088d4679f9d84e5ce4a11`. The input Linux driver SHA256 was
`9e7c9d630acf19cfdf46f7ab644a14e3d1e70d62f31962d179f4cc257de3eaf9`.
The pinned CPU+GMAC end-to-end result for the preceding fixed-capacity ROM does
not certify this newer, separately built ROM or a Linux kernel execution.

## Independent elaboration capacities

`soc.ip.dma.NetworkDmaConfig` is threaded through EthernetSocTop, BoardSocTop,
MachinePlatform, ManagedPeripheralBank and ManagedGmac. Fields:

| Field | Legal values | Default |
| --- | --- | --- |
| maxFrameBytes | powers of two, 64 through 16384 | 2048 |
| macRxSlots | 1, 2, 4, 8, 16 | 4 |
| postedRxSlots | 1, 2, 4, 8, 16 | 4 |
| memoryCredits | 1, 2, 4, 8, 16 | 4 |

These are independent. A legal constructor does not prove every combination,
board timing closure, a loss-free link or endpoint support. Reset still selects
the old single-descriptor software ABI, including when postedRxSlots is one.
`Serialized` selects one MAC bank, one posted owner and one memory credit.

ManagedBoardSocMain and EthernetTimingMain accept keyed options alongside their existing positional args:
`--network-frame-bytes=N`, `--network-mac-slots=N`, `--network-rx-slots=N`,
`--network-memory-credits=N`. Duplicate, unknown or malformed keys fail closed.
ManagedBoardSocMain forwards all four settings into the native MAC/DMA.
EthernetTimingMain uses an external vendor MAC: only its DMA capacities are
controlled here, and only when the board wrapper and DMA are selected.

Selected capacities determine actual arrays and widths. MAC RX payload storage is
`macRxSlots * maxFrameBytes` bytes of SyncReadMem, with one write port and one
read port; default 8192 bytes. DMA retains independent RX and TX staging RAMs,
each maxFrameBytes bytes, and MAC TX has its own frame RAM. This architecture
still copies frames through staging and software; the change does not remove
those copies. CDC stream FIFOs retain their previous fixed depth (16 words),
which is neither a packet credit nor a promise to absorb an unpaced stream.

Descriptor storage retains validated aligned physical word addresses only,
`ceil(log2(ramBase + ramBytes)) - 3` bits per owner, plus a bounded capacity and
17-bit completion. For the 2 GiB board aperture starting at 0x80200000, that is
30 address + 12 capacity + 17 completion bits per slot, versus three 64-bit
fields before. This is a source-level storage bound, not a synthesized FF/BRAM
utilization or timing claim. Vivado utilization has not been measured.

DMA capability 0x98 preserves RX_STOP bit0 and posted-RX bit1; queue depth is
bits15:8 and ordered memory credits are bits23:16. MAC capability adds valid
bit9 and MAC RX slots in bits31:24; previous max-frame bits63:32, media bits23:16
and RX_STOP bit8 are unchanged. Old software may ignore these additive fields.

## Firmware and host bounds

The host can negotiate windows 1 through 16, default 4; RFC7440 remains batched
windows with cumulative ACKs. It retains default 100 microsecond packet pacing.
Board builds explicitly select `--netboot-block-bytes` (512 or 1024),
`--netboot-window`, and `--netboot-rx-slots`. Window must fit software slots.
Slot stride rounds block size plus 86 bytes of accepted headers to 64 bytes.
The existing 4608-byte posted-buffer budget and 8 KiB reserved boot stack are
hard limits: 1024-byte blocks allow up to four software slots; 512 allows seven.
The portable protocol permits 16 but the board scratch budget does not.

The effective request is capped by software slots, hardware posted depth and
advertised MAC banks. An unknown MAC-bank capability conservatively requests
window one. Hardware queue depths 1/2/4/8/16 are accepted; malformed depths use
legacy fallback. The current board firmware and Linux endpoint require hardware
max-frame capacity at least 2048 even though smaller hardware-only configurations
are legal. Firmware actual globals/stack layout and compiled ROM are audited.
512-byte/window-one legacy fallback, exact-once stream CRC, RAM readback CRC,
fixed final-ACK deadline, fences and checked UART recovery remain in place.

## Linux RX ownership

`rx_queue_slots` is a read-only module parameter, default four, range 1..16,
capped by advertised hardware depth. Only that many coherent 2048-byte RX
buffers are allocated. The existing coherent TX buffer remains single-owner.
The driver probes additive DMA registers only when the paired MAC advertises
RX_STOP. Missing/malformed posted capability selects legacy RX. Existing active
queue ownership at probe is refused.

Before admission is enabled, software posts the selected pool. Full-width MMIO
and dma_wmb publish descriptors; dma_rmb precedes CPU payload consumption. A
retained completion must match the software FIFO head and owned count. Payload
is copied into an skb before POP, then the same buffer is reposted. Capacity is
programmed once for the pool, not on every packet. NAPI can consume multiple
completions within the existing weight-eight / two-millisecond work budget.
Two milliseconds is a maximum poll-work budget, not a recurring polling delay.
TX completion handling remains independent of a zero RX budget.

Unknown, out-of-order, reset or stopped ownership faults mask interrupts, stop
the netdev queue and retain DMA-addressable allocations. The existing ifdown
policy keeps buffers pinned and hardware owners intact; reopening consumes the
retained completions. There is still no safe module unload/unbind implementation.
A rare late probe failure after userspace has armed DMA intentionally retains
buffer allocations rather than unmapping an owned address; board reset is then
required. RX_STOP handoff release and the user's init/dinit files are preserved.

Driver diagnostics expose mode, allocated slots/bytes, owner count, largest
observed NAPI RX batch, completion high-water mark, advertised MAC banks/memory
credits, and the explicit single TX slot. These are utilization witnesses for a
future board test, not evidence that larger queues improve throughput.

## Focused checks and remaining limits

Native checks execute the actual queue helper and extracted driver
configuration/IRQ/NAPI/ifdown/cleanup bodies against a numeric fake-MMIO oracle.
They cover copy-before-POP (buffer poisoned on POP), owner/FIFO errors, full and
duplicate posts, stopped/reset faults, allocation errors, budget/time yields,
TX-only budget zero, IRQ rearm races, completion retention when an IRQ is omitted,
ifdown/reopen, pinned cleanup and legacy handoff. The omitted-IRQ case proves
retention and a later poll; it does not prove recovery from a permanently lost
interrupt without any subsequent scheduling event.

The native fixture stubs kernel scheduling/allocation, so it is not a kernel
module build. Supported kernel source/headers were unavailable in this cloud
workspace. Native firmware capacity combinations and Python/C interoperation
are separate from actual hardware execution. The hardware runner
`simulator/gsim/network_capacity_checks.py` defaults to preflight only; an
explicit `--build-run` runs selected 1/1, 4/4 and 16/2 posted/credit tuples,
MAC-bank 1/16 boundaries, default coherent DMA and shutdown with independent
corruption negatives and source hashes. The high-address cancelled descriptor
case checks compact-address reconstruction above 4 GiB without touching RAM.

A focused RTL receipt, kernel build, merged CPU+GMAC test for the new ROM, and
short real-board measurements must be reported separately. No Linux execution,
physical CDC, PHY throughput, resource saving or routed timing is established
by software or aliased-clock tests. TX batching is not implemented in this layer.
