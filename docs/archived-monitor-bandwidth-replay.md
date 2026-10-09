# Unmodified archived monitor bandwidth replay

## Result and scope

The complete bandwidth entry of the archived GCC **14.2.0** diagnostic passed on
both frozen selected LSU2 models. Only physical load ingress differs; depth4/yield0
copy DMA is configured but idle. All seven original UART reports, their actual
`rdtime` values, in-diagnostic UART/flush history and final return were preserved.
The guest was neither recompiled nor patched. A separate 64-byte launcher selects
its existing `b` entry and flushes only after the diagnostic has returned.

This is not the board's GCC13.2 object. The launcher does not recreate the earlier
monitor's cache history, and the fixed DDR host schedule is not physical MIG/DDR
latency. The actual board hot read +1.497% and this model +0.156% are distinct
observations. Neither is predicted by the hand-written unrolled benchmark's
+19.645% ingress gain.

## Exact original measurements

These are guest timer ticks at 100 MHz. Flush tails stay separate; copy useful
payload counts once rather than summing source and destination bus bytes.

| Original interval | Ingress OFF | Ingress ON | Tick delta | Rate change |
|---|---:|---:|---:|---:|
| read_cache_sized_cold | 8613 | 8601 | -12 | +0.140% |
| read_cache_hot | 3215 | 3210 | -5 | +0.156% |
| write_cache_sized | 6155 | 6155 | +0 | +0.000% |
| write_cache_sized_flush | 5028 | 5026 | -2 | +0.040% |
| copy_cache_sized | 17316 | 16941 | -375 | +2.214% |
| copy_cache_sized_flush | 5002 | 5002 | +0 | +0.000% |
| read_over_cache | 174125 | 169773 | -4352 | +2.563% |
| write_over_cache | 252329 | 252329 | +0 | +0.000% |
| write_over_cache_flush | 17741 | 17744 | +3 | -0.017% |
| copy_over_cache | 431155 | 422768 | -8387 | +1.984% |
| copy_over_cache_flush | 9063 | 9063 | +0 | +0.000% |

Hot 8 KiB throughput is 243.001 to 243.380 MiB/s. Writes remain 6,155 ticks for
8 KiB and 252,329 ticks for 128 KiB. The flush-tail rows are completion costs, not
separate useful-payload transfers. Do not interpret their inverse-duration change
as a data-bandwidth result.

## What the physical shortcut actually changes

For all 1,024 useful hot-loop loads:

| Stage | OFF cycles | ON cycles |
|---|---:|---:|
| LSU start to FIFO acceptance | 0 | 0 |
| FIFO acceptance to physical cache request | 3 | 2 |
| Physical request to reply | 1 | 1 |
| Reply to LSU reply | 1 | 1 |
| LSU reply to accepted result | 1 | 1 |
| Start to accepted result | 6 | 5 |

There are zero timed Dcache read/write misses, refills or evictions. The ROI still
has instruction-side fetch traffic: two AXI read bursts on each side, so "hot data"
does not mean the entire machine performs no external traffic.

The steady scalar loop remains at one load every three cycles: 1,020 of 1,023 OFF
start gaps and 1,021 of 1,023 ON gaps are exactly three cycles. Useful hot-read
retirement is 4,106 instructions on both sides. Owner residency drops from 6,144
to 5,120 owner-cycles; no data latency is fabricated or subtracted.

The registered load-order check is active for 1,024 cycles on each side, but
`done_head_zero_commit_with_order_hold` is **zero** on both sides. It is therefore
not an observed direct done-head retirement blocker for this scalar loop.
Overlapping head-state counters are not a mutually exclusive causal partition.
A four-instruction scalar loop (`LD; ADDI; ADD; BNE`) differs fundamentally from
the custom eight-load unrolled loop with four independent sums. Exact issue,
dependency and owner-capacity attribution requires the next passive experiment;
we have not proven a specific recurrence to be the remaining three-cycle limit.

### Ceilings, not promises

At 100 MHz, a 64-bit transfer every cycle is 762.939 MiB/s at that interface. The
current two-owner all-hit residency gives an owner-capacity-only ceiling of
254.313 MiB/s for six cycles and 305.176 MiB/s for five cycles. The ON scalar
launch cadence instead approaches 254.313 MiB/s before boundaries and instruction
misses. Two-wide retirement and four scalar instructions per word gives a separate
381.470 MiB/s instruction-count ceiling. These are constraints of this particular
loop and current pipelines, not a global maximum for a 100 MHz CPU.

## Independent acceptance and traffic accounting

Both runs check every physical RAM reply and CPU-known-memory reply against
separate byte-lane memory views. All A and B writes are checked against independent
closed-form patterns and generation/order expectations before updating the oracle.
Each run has 52,224 verified A stores and 34,816 verified B stores, 18 full-token
actual `rdtime` results joined to retirement, the original success line, complete
return and final owner/bus drain. Data, full-token and marker observation negatives
reject on both sides (six negative executions total). These negatives mutate the
observer, not the DUT or guest.

Whole-run physical requests/replies are OFF333,864 and ON333,910. These include
UART polling and speculation; they are not held artificially equal. Every original
timed hot/cold useful load is joined by full token to its original instruction PC.
Final backing data is checked across all 128 KiB of both buffers.

The legacy output label `cpu_forwarded_replies=0` only counts registered ACKs and
misses immediate store-buffer forwarding. The independent CPU reply oracle still
checks these replies: OFF74,238−74,209 and ON74,193−74,164 both give 29, matching the
flow ledger's immediate forwarded count. Preserve this reporting caveat with the
immutable receipts rather than silently rewriting an old metric.

The frozen integration ledger predates newer explicit `slotOwners`,
`stalledRequest` and `stalledReply` observer fields. Its final zero live/start and
queue/shadow invariants imply no raw held request or reply under the bound RTL;
`build/monitor-bandwidth-terminal-review/TERMINAL_REVIEW.md` records that source
argument. This is not a claim that the newer per-cycle held-payload tests ran.

## Identities and next gate

- Production source freeze: `66c06d786275dc28c099301162cd09e70497f6eb` in the
  preserved integration checkout. Model receipts bind full actual source maps;
  their older Git-at-build label alone is not the source identity.
- Original ELF SHA256: `17a26a142b01c755e852876239f12b65569cb15e703a3137a0356ffd2984c1f4`.
- Original binary SHA256: `3c6d9e6f259a0f82cb1b8584a2a3b57c6716b6df781b3bafd3237605351e9451`.
- OFF receipt: `bc2f67ab0a90f05268c981666a5d50df4c7823de76d34bb017911764655336a5`.
- ON receipt: `ad052354656cb313d5d837258e79e3f558a5a94a4a3a5f62ab204ab9926d0c02`.
- Comparison: `71648b32508f18012cdd8d55b90b3c6718c21ca883121a6e9e14114df28db7a6`.

Entry receipt: `build/gsim/monitor-whole-comparison-r1.json`; qualified fixture:
`simulator/gsim/fixtures/monitor_bandwidth_replay`. Fresh preparation requires the
explicit pinned diagnostic archive; this gate does not claim a source-only
recompilation reproduces GCC13.2. Generated `static-r1` files are evidence only.

Next, reuse the exact unchanged ELF on the current LSU4 older-prefix OFF/ON pair,
with four-owner strict ledgers and passive issue/dependency attribution. The new
observer is separate from this immutable pair. Functional replay/cancellation
qualification remains a prerequisite to promoting the older-prefix experiment.
No FPGA mapping, 100 MHz timing, board or NEMU claim is made by this replay.

## Independent review closure

A separate read-only review rehashed all466 model-source inputs and126 archive
source inputs, all model/fixture/prepared/compiler products, and independently
replayed the raw full-token request/reply TSV for both runs. It verified every
RAM read and pattern store, both final buffers,824 UART bytes and18 timer records.
An extracted immediate-reply checker passed clean data and rejected corrupted
data, a high generation-tag bit and a reply error with registered ACK forced off.

The original standalone `compare.py` is not a general trust boundary: modified
receipts can omit steps/products or alter parsed result values without rejection.
The exact pinned receipts above remain valid because this independent review
required complete evidence, reparsed the original logs, recomputed the comparison
and reproduced its exact SHA256. The future v2 comparator must enforce those
checks itself. No old receipt or fixture has been rewritten.

Review: `build/monitor-original-independent-review/REVIEW.md`, SHA256
`9e083ae811d87ba20636746a246221be7de7bc492a363e9a67194a66d130a7b8`;
its `proof.json` contains the machine-readable closure.
