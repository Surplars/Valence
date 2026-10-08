# Bounded windowed network-boot candidate

This is an opt-in protocol/DMA candidate, not evidence of a repaired board loss cause,
wire-speed throughput, routed timing, or PHY/CDC validation.

## Packet capacity and backpressure

The GMII receiver has four 2048-byte banks. A bank is published only after the entire
wire frame passes the existing CRC/address/length checks, then remains immutable
until the final ready/valid output beat retires. Four queued banks cause subsequent
physical frames to be drained and dropped whole. GMII cannot be backpressured.
A frame being captured owns its producer bank; output uses a different consumer bank.
Admission stop includes both partially captured and retained banks in owned-busy,
so the producer barrier cannot acknowledge while any admitted packet remains.

The CDC FIFOs remain finite elasticity, not packet storage. The packet DMA still
stages and writes one frame at a time, with four *memory transaction* credits.
New posted descriptors eliminate firmware rearming gaps between those frames;
they are not four simultaneous memory-transfer engines.

## Additive RX queue ABI

The V1 identity and all existing offsets remain unchanged. Reset selects legacy
single-descriptor mode, preserving the local Linux driver. Capability 0x98 retains
bit 0 (safe RX stop), adds bit 1 (posted queue), and reports depth 4 in bits 15:8.
Every register is an aligned full-width 64-bit access.

- 0xa0: staged physical buffer address, read/write
- 0xa8: staged byte capacity, read/write
- 0xb0: write 1 to POST; transfers the staged buffer to DMA ownership
- 0xb8: queue enable 0/1; change only with no active, pending, or completed owner
- 0xc0: pending count [7:0], completion count [15:8], active [16], stopped [17]
- 0xc8: oldest completion's buffer address, read-only
- 0xd0: oldest completion's actual bytes [15:0], error [16], read-only
- 0xd8: write 1 to POP the oldest completion; returns its slot to software

POST validates the entire aligned RAM range and rejects overlap with any owned
slot, a full queue, disabled/stopped mode, and malformed writes. Rejection does
not transfer ownership. Completion storage is retained until POP; completed slots
still consume the four-slot capacity. Completion order equals submission order.
An error completion may report received bytes but must never be used as valid data.
Legacy RX descriptor mutations are rejected while queue mode is enabled. TX is
unchanged and remains independent. Queue RX interrupts remain asserted while any
completion is retained.

The CPU must finish buffer initialization before POST (publish fence), and observe
the completion plus a consume fence before reading the payload. Coherent DMA still
uses the existing coherence path. Queueing is not permission to remove fences or
reuse a buffer before ownership returns. Software copies completed data before
POP/repost, so a later DMA write cannot race a packet parser.

## Stop, cancellation, and handoff

First close GMAC admission. Continue consuming completions and posting scratch
buffers until the MAC's producer-drained acknowledgement arrives. Then write
RX_STOP (0x90 = 1): no additional queued descriptor launches; an empty active
wait is cancelled immediately, a partial data/status pair drains to *both* stream
boundaries, and accepted memory operations retire. Pending owners receive error
completions in order after the active owner retires. Pop every completion, verify
no active/pending owner, then disable queue mode. Disabling clears the stop latch;
a new POST cannot clear it. Only after these barriers may firmware disable MAC
and hand ownership to UART recovery or an unmodified legacy Linux driver.

A half frame/status stream or stalled memory target can still prevent drain;
software timeout is a failure, never evidence that ownership returned.

## Protocol and reserved memory

Build the candidate with `--netboot --netboot-posted-rx`. Capability fallback uses
legacy RX and 512-byte/window-one TFTP. The new path negotiates at most 1024-byte
DATA blocks and four-packet RFC 7440 batches; this is cumulative-ACK windowing,
not an unlimited continuous sliding stream. TX scratch is 512 bytes, legacy parse
scratch 2048 bytes, and four posted receive buffers are 1152 bytes each. Normal
IPv4/TFTP with a 1024-byte payload fits even with a 60-byte IPv4 header. VLANs are
not supported; frames larger than the posted capacity fail atomically and drain.
The existing 16 KiB monitor reservation and minimum 8 KiB stack remain enforced.

Full-stream CRC counts bytes once in accepted in-order DATA; independent RAM
readback remains mandatory. Final ACK retention has a fixed deadline and must
not be extended by duplicate traffic. UART cancellation and final quiet barriers
remain required before jumping.

## Verification boundary

New independent hardware harness cases cover four-bank retention/overflow/wrap,
four posted completions, full queue rejection, completion retention, ring wrap,
both half-stream cancellation orders, empty-wait stop, and legacy restart. The
existing byte/CRC, malformed status, memory-fault, held-request, and coherence
oracles remain. Native firmware/host tests do not establish physical hardware
behavior; actual executed commands and status belong in the delivery receipt.
