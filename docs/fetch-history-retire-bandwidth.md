# Previous fetch packet and precise retirement-prefix bandwidth experiment

## Measured result

The unchanged archived GCC 14.2 monitor diagnostic now completes its scalar
8 KiB hot-read interval in **2191 ticks versus 3210**, a **46.51% throughput
increase** in the fixed 100 MHz simulation. This is the original four-instruction
`LD; ADDI; ADD; BNE` loop, not the earlier handwritten unrolled benchmark.
The board's GCC 13.2 diagnostic binary is unavailable here. These are not board
measurements or a claim that FPGA timing still meets 100 MHz.

All measurements below use the same production source, LSU4, physical ingress
flow, 32 KiB/two-way caches, two D-cache MSHRs, and coherent copy-DMA depth4/yield0
configured but idle. Both experimental controls remain **default OFF**.

| Original diagnostic interval | Both OFF ticks | Both ON ticks | Throughput change |
| --- | ---: | ---: | ---: |
| 8 KiB cold read | 8591 | 8579 | +0.14% |
| 8 KiB hot read | 3210 | 2191 | +46.51% |
| 8 KiB write | 6155 | 6155 | 0.00% |
| 8 KiB write flush tail | 5028 | 5027 | +0.02% |
| 8 KiB copy | 16946 | 15831 | +7.04% |
| 8 KiB copy flush tail | 5002 | 5005 | -0.06% |
| 128 KiB read | 166952 | 163243 | +2.27% |
| 128 KiB write | 252329 | 252329 | 0.00% |
| 128 KiB write flush tail | 17741 | 17741 | 0.00% |
| 128 KiB copy | 422833 | 419219 | +0.86% |
| 128 KiB copy flush tail | 9067 | 9071 | -0.04% |

Kernel and flush-tail intervals are separate. Copy payload counts each copied
byte once. Raw physical requests, replies, UART polling and speculation are
retained; they are not subtracted from elapsed time or useful payload.

## Why the combination matters

1. The original registered window loses the current packet on all 1023 hot-loop
   backward cursor transitions. The exact target packet was present in the old
   registered row zero one edge earlier.
2. The optional one-edge packet history recovers 514 of those transitions by
   itself. Nevertheless, hot-read time changes **3210 to 3211**, and 128 KiB read
   time worsens **166952 to 168670**. That single change is not a speedup.
3. With more frontend supply, the history-only configuration now has 1020 cycles
   where a completed ROB head cannot retire during a load-order check. This
   counter was zero in the original baseline. It is a measured bottleneck shift,
   not evidence that order checking alone caused the original three-cycle loop.
4. Enabling the existing precise older-prefix retirement control while holding
   history ON removes that global hold for older instructions. The checked load
   and younger instructions remain blocked. History then recovers all 1023
   backward transitions, the load request gap is two cycles on 1021 intervals,
   and completed-head order holds fall to zero.
5. All 1024 hot loads still have five-cycle start-to-result owner residency.
   Three LSU owners are live for 1020 cycles; four are never simultaneously live
   in this ROI. Thus owner latency did not become artificially shorter.

For this unchanged four-instruction loop with two-wide retirement, the ideal
steady-state instruction budget is two cycles per 8-byte word: 381.47 MiB/s at
100 MHz. The measured 2191-tick interval is 356.57 MiB/s, including its original
setup, instruction misses, fences and timer boundaries. This is a bound for the
current loop and retirement width, not the universal limit of a 100 MHz CPU or
the 64-bit memory interface. Large read/write/copy workloads remain far below it.

## Same-source comparison closure

Production anchor: `2288c7f008e9d6440e8a28e339da28152b54892a`.
The experiment uses three configurations from that exact production tree:

- Both OFF, and history ON/prefix OFF: fetch-history V1 fixture
- History ON/prefix OFF, and both ON: fetch-prefix V2 fixture

The middle execution is independently rerun. Its complete positive log, all
physical traffic, hot full-token stage trace and frontend timeline are
**byte-identical** across the two fixtures. Their observer/guest/schema inputs
are also identical. `simulator/gsim/compare_fetch_prefix_triad.py` reruns both
strict original comparators, verifies this join, and reports both-OFF to both-ON
results. It does not infer an unmeasured fourth same-source factorial cell.

Entry receipts in the experiment's evidence directory:

- `gsim/monitor-fetch-history-comparison-v1-r1.json`: single-history failure to improve
- `gsim/monitor-fetch-prefix-comparison-v2-r1.json`: fixed-history, prefix-only pair
- `gsim/monitor-fetch-prefix-total-triad-r1/receipt.json`: total same-source result

Every full diagnostic positive includes the original 18 `rdtime` values and UART
reports, independent initialized-memory and every-store checks, full-token
ownership/cancellation, return to the launcher and complete internal/external
drain. Four observation-corruption negatives run on each side of each pair.
These negatives mutate the checker view, not RTL or guest traffic.

## State and timing risk

The independent native-RTL census reports:

| Current LSU4 configuration | Reachable scalar declaration bits | Reachable array bits |
| --- | ---: | ---: |
| Both OFF | 81479 | 704967 |
| History only | 81612 | 704967 |
| Both ON | 81676 | 704967 |

The combined increment is 197 scalar bits: 133 for history and 64 for the
load-order check's complete generation tag. Port declarations are excluded.
The 69 added ROB input bits are wires, not 69 extra stored bits. All ten fixed
storage groups remain unchanged. Only `RegisteredFetchWindow`, `IntegerBackend`
and `RenameRob` change; the other 259 emitted module hashes match.

History adds a 68-bit raw packet/fault mux selected by primary presence. The
historical full-key/context authorization and same-cycle invalidate are outside
that raw payload mux cone. Retirement adds selection of an existing 64-bit tag
from 16 ROB entries, complete-token equality, and modular age comparisons. These
are real combinational timing risks. Native RTL declaration counts are not
mapped LUT/FF/BRAM counts; no synthesis, routed timing or physical qualification
has been performed for this candidate.

## Correctness gates and remaining work

Already executed for the current source/profile:

- Configuration checks and independent packet-history/real alignment tests for
  capacities 3 and 5, including faults, full addresses, contexts, invalidation,
  reset, intentional overwrite and negative controls
- Fresh selected whole-board RV64GC smoke and its negative for each model
- Original complete diagnostic A/B and strict three-configuration join
- Exact executing CPU order-replay oracle: both positives and 24 negatives,
  including full-generation cancellation before/after physical acceptance,
  no killed retirement, ROB wrap/reuse, two-lane retirement, final GPR equality
  and terminal external AXI emptiness before the next DDR sample
- Four fresh fetch-PMP/Sv39 positives and eight negatives: execute revoke/restore
  at a cached compressed gate, exact trap provenance, warm/cold/page-alias/chase,
  one permitted UART read, wrong-path MMIO exclusion and full guest signature
- Three native exports, source/config-bound resource and cone census
- Fresh cached-reference NEMU checks on both current models: 12 physical integer
  read/write/copy positives and 26 NEMU/ownership negatives; 123444 guest PCs,
  all 32 GPRs at each complete retirement edge, and all 4194368 RAM bytes per
  case checked without reference resynchronization or speculative stepping

- Four fresh active-CPU/copy-DMA and denied-data-PMP positives plus 14 negatives:
  two dirty source/destination generations, CPU scratch reads/writes while DMA
  is active, four resident DMA owners, denied-R drain/restart, and exact S-mode /
  MPRV denied-load traps with zero forbidden physical accesses

The concurrent-DMA check is functional: polling, speculation and overlap counts
differ, so its total cycles are not promoted to a DMA throughput comparison.
The denied-data-PMP guest exercises loads, not every store/AMO fault case.
Full ISA, Linux, MAC/CDC, exhaustive interrupt schedules and board timing remain
outside the listed gates. Same-binary short CoreMark performance regression also
remains a separate follow-up; the memory results do not predict a CoreMark score.

The next bandwidth work targets authorized store ownership and write allocation:
large writes are unchanged, and the original 128 KiB copy spends most of its
interval under serial-memory exclusion. The translated Linux store path also
requires separate treatment because the existing early-ack StoreBuffer only
accepts a subset of physical stores. No store-merge throughput gain is claimed
from the frontend/retirement results above.

## Archived proof revalidation

The three functional runners intentionally captured their execution-time host
Git HEAD as input metadata. Later host-only documentation/fixture commits change
that field even when every executed source/tool/model/guest byte is unchanged.
Their original direct `--audit` consequently rejects a later HEAD; the failed
attempt logs are preserved. This is not a hardware rerun or a data mismatch.

The separate `fixtures/fetch_prefix_archive_v1/revalidate.py` uses the frozen
original auditors. It proves both historical and current complete production
trees, ancestry, all input/artifact hashes and the original command/environment
identities, then permits only the historical `source_binding.host_head` metadata
difference. Each suite runs in an isolated read-only child. No original runner,
receipt, executable or result is rewritten. Any non-HEAD input difference still
rejects. Its own receipt records the actual audit HEAD and all three audit
results. See that fixture README for the explicit archive revalidation command.
