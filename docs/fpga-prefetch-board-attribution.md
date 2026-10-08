# Passive attribution of bounded prefetch retention

The exact Selected board at `71dae69300bf953d3d12923a3816fe873f0c4a9e`
passes the one/three-attempt comparison and an additional passive replay. Existing
FIR, generated C++, object, binary, guest, source and original-log hashes are bound
in `evidence/fpga-prefetch-board-attribution-20261008.json`. No RTL or model was
rebuilt for this attribution. Every original positive output row and cycle count
is unchanged. Both variants independently check all 49,152 accepted source-load
responses against the external address-to-value formula; corrupted observations
and an altered immutable prefetch token are rejected.

The read kernel falls from 279,718 to 181,647 host ROI cycles. Its source-range
AXI reads fall from 3,072 to 2,334, exactly explained by 738 additional first-line
hits on previously resident lines. Each of the three passes reads 778 unique
source lines, consumes 748 new prefetch tokens, and reuses the same 246 lines
already resident in way 1 before the ROI. The 2,244 allocation/useful events cover
748 unique addresses. Prefetch's existing first-clean-way selection makes this
residency behavior different from demand LRU replacement. Total ROI AXI reads
fall by 741; the remaining three-request difference lies outside the source range.

Of the 2,244 read prefetch tokens, 2,202 are first consumed one cycle after fill
and 42 after 32 cycles. This is measured fill-to-consumption time; it does not
establish that all useful prefetches hide complete demand misses. The aggregate
cycle gain includes both replacement/residency and changed miss timing.

Copy rises from 641,791 to 644,683 cycles. All 252 prefetch tokens, covering 250
unique addresses, fill and are evicted without consumption by the exact matching
destination store. `DST_BASE=0x81400040` makes `dst[n]` share the set of
`src[n+1]`; the untouched prefetch enters at LRU and that destination miss selects
its exact way. These events split 250/1/1 across the three passes and add exactly
252 source reads. No reported useful consumption lacks a real immutable-token
cache hit.

The unchanged inherited release classification falsely labels 41 direct demand
releases as prefetch releases for 123 cycles in the read ROI. Actual prefetch
release owners contribute 6,732 cycles. This attribution does not enable the
separately qualified release-classification correction.

One untimed baseline token distinguishes tracking lifetime from payload lifetime:
token 1,889 at `0xffff7fc0`, index 255, allocates at cycle 3,135,725 and fills at
3,135,793. A flush clears tracking at 3,151,462 while retaining the clean line;
its first actual read hit occurs at 3,179,075 without a useful-counter event.
The ledger requires that observed intervening flush and absent matching tracking
state. It also distinguishes store-first consumption, but neither replay has
such an event. The initial read-only first-use equality failed on this legitimate
case; that failed log is preserved in `board-prefetch-ledger-r6`.

The final replay is `build/gsim/board-prefetch-ledger-r8`. Per-token timestamps,
per-pass source-address/read counts, and first-hit address/way/fill provenance are
persisted as CSV and independently reduced. Earlier incomplete runner attempts
remain available. These are controlled GSIM workload results; physical bandwidth,
mapped resources and routed timing remain unmeasured.
