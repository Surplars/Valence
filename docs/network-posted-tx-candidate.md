# Optional posted TX queue candidate

This is a separate increment over the verified posted-RX/parameter candidate.
It does not establish an improvement in the reported physical Linux TX rate.
The earlier RX candidate remains a fallback. The Linux driver still requires a
matching-kernel build before production use; fake-MMIO tests are not that build.

## Configuration and resource boundary

NetworkDmaConfig adds `postedTxSlots`: 0, 1, 2, 4, 8, 16, default 0. The native/export
key is `--network-tx-slots=N`. Zero elaborates no TX owner-queue module or arrays.
The initial candidate selects four. RX banks, RX owners and memory credits remain
independent. There is one existing TX staging RAM, not one payload RAM per owner.
For four entries and a 2 GiB aperture, descriptor fields/owner bits are about 240
bits, plus 128 staged address/length bits and counters/control. This is a source
storage bound; synthesized FF/BRAM use and timing are unmeasured.

Linux's `tx_queue_slots` defaults 4 and is capped by advertised hardware depth.
Only that many coherent 2048-byte payload buffers are allocated, or one on legacy
hardware. Portable software owner metadata is bounded at 16 slots. The first
TX4 pool adds 6 KiB of DMA-addressable DRAM over the old single TX buffer. Payload
still copies from skb; the hardware still stages a whole frame before emission.

## Additive MMIO ABI

The DMA ID and 256-byte decode remain unchanged. Capability 0x98 adds bit 2 for
posted TX and bits 31:24 for depth. Existing RX bits/depth/memory credits remain.
Absent/malformed TX capability uses the old TX path. With slots 0, the new words
remain reserved and reject accesses.

| Offset | Write | Read |
| --- | --- | --- |
| 0xe0 | Staged aligned TX address | Retained completion-head address |
| 0xe8 | Staged byte length | Completed bytes [15:0], error bit 16 |
| 0xf0 | Exact command value | enabled bit 0, stopped bit 1 |
| 0xf8 | Reserved | pending [7:0], completed [15:8], active bit 16, stopped bit 17, enabled bit 18 |

Commands are mutually exclusive: ENABLE=1, DISABLE=2, POST=4, POP=8, STOP=16.
Enable/disable requires no owners, no active transfer and no unacknowledged
legacy completion. The driver clears an idle legacy completion before enabling.
Legacy TX address/length/command writes are rejected while posted mode is enabled.
Reset disables posted mode. Four staged/read-alias registers avoid a new MMIO
window and preserve legacy address decoding.

POST validates bounds, alignment, length and overlap with retained owners in
the same TX queue. Callers must keep TX buffers disjoint from RX or other DMA
owners; the Linux allocator supplies distinct buffers for the two pools.
Ownership lasts through completion POP; filling the completion FIFO cannot
silently recycle a descriptor. Completions remain in posting order, and IRQ bit 0
stays asserted while any retained TX completion remains. RX IRQ/owners remain
independent. Staged writes cannot change an active descriptor or held bus offer.

A memory error drains accepted/held reads and emits no partial packet. Completion
for success means the final data beat reached the MAC stream, matching the prior
DMA semantics; it is not a physical wire timestamp. STOP prevents fresh launches,
finishes an active memory/stream transaction, then cancels pending descriptors in
FIFO order with bytes=0/error=1. A STOP accepted on a potential-launch cycle wins.
POP all completions, DISABLE, then ENABLE to clear the stopped condition.

## Linux ownership and batching

The TX lock selects a free slot, copies skb bytes, publishes with dma_wmb and
POSTs, then releases the copied skb. The queue stops only at the selected pool
limit. Full-pool NETDEV_TX_BUSY retains the skb. NAPI drains up to the selected
TX depth even with RX budget 0, validates count/FIFO address and successful byte
length, consumes with dma_rmb, POPs, and wakes the netdev queue when capacity is
available. Counters expose selected TX bytes/slots, owned slots, maximum drain
batch and completion high-water mark. RX batching and its budget remain intact.

Unknown, stopped/reset or wrong-order ownership faults mask interrupts and pin
buffers. The driver never issues TX STOP during ifdown. Ifdown preserves already
posted work and allocations, and a later ifup consumes retained completions.
An externally stopped TX queue is therefore a reset-required fault, not a driver
stop/restart recovery path. No module unload/unbind or forced DMA unmapping is
added. Both pools remain pinned after a late probe failure if any DMA was armed.

## Proof scope

Native tests execute actual xmit/configuration/IRQ/NAPI/stop/cleanup bodies and
portable queue helpers against an independent numeric MMIO model. Payload is
compared at POST, checked for mutation while owned, and poisoned at POP. They
cover selected pools 1/2/3/4/8/16, FIFO wraps/full, skb retention, successful/error
completions, malformed metadata/capability, IRQ rearm, budget 0, simultaneous RX,
ifdown completion retention, pinned cleanup and legacy TX. A deliberate payload
corruption must fail independently.

The focused hardware runner plans TX-disabled/TX1/TX4 packet models, a queue-only
exact-event fixture (POST+launch, completion+POP and STOP-before-launch), a TX4
native-MAC wire/FCS model, and a TX4 coherent 512-line dirty-source model. Retained
executables, source/FIR hashes and independent negative controls document what
actually passed. The queue-only fixture does not replace the full DMA/GMAC tests.
Physical CDC, matching Linux kernel execution, board throughput and routed timing
remain separate. Full E2E must use the exact final merged RTL and ROM; an older
compiled CPU model is not evidence for this increment.
