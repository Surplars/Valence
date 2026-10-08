# Instruction-cache held-hit correction

A stronger independently indexed, randomized hit stream exposed an inherited
response-backpressure bug before the data-packing candidate was tested. The old
parallel-way storage fails when a hit response stalls and the next offered request
selects another set. The prior directed hold test kept both offers within one line,
so its passing result did not establish cross-set response stability.

`SyncReadMem` only defines the read result for the cycle following an enabled read.
The old `hitReply` state continued to present that output during a multi-cycle stall.
The exported native helper advances its read address each edge and explicitly emits
X when delayed read-enable is false. GSIM also exposes changed data in that disabled
cycle. This is a protocol gap, not an acceptable new request changing the old reply.

The correction captures the first stalled `hitPacket` in the already-existing
`replyData` register and moves from `hitReply` to `lineReply`. It adds no payload
register or pipeline stage. An unstalled hit still replies one cycle after acceptance
and accepts the following request on that reply cycle. With a stalled reply, the
snapshot remains stable until consumption; release can accept a new request on the
same edge. Accepted requests and outstanding TileLink owners still obey their existing
invalidation/reset contracts.

The capture is exclusive of an accepted next request because `hitReply` with response
ready low closes admission. Demand refill and waiting-prefetch payload writes require
other states. A prefetch installation may occur during a held hit, but it cannot write
`replyData`. Invalidation removes residency and marks speculative owners stale; it
must not silently withdraw an already accepted cache response. The frontend separately
owns cancellation of stale fetch transactions.

## Evidence and qualification

The original failure is retained in
`docs/evidence/fpga-instruction-held-hit-defect-20261008.json`, including frozen source
hashes and generated FIR/header/C++/binary/test/diagnostic hashes. Seed 1 fails at
sweep cycle 21: the accepted packet at `0x80200a68` observes words from the differently
offered set. The original failing model and receipt are unchanged.

The source-only fix is commit `dec7d8e`; its isolated patch changes eight lines in
`InstructionLineCache.scala`. The separate packing option remains off throughout the
focused hit-stability suite. At the selected 512-line/two-way/two-word geometry, four
random seeds read every resident bank in both ways with held requests and responses;
the corrected baseline passes, as does its II1 and cold/hot latency check.

The final focused receipt `docs/evidence/fpga-instruction-hit-stability-20261008.json`
passes three models and 16 scenarios: packet2 prefetch off/on and packet4 prefetch on,
all at 512 lines/two ways with 19-bit tags and the selected 2 GiB aperture. It binds
20-cycle held replies with a different offered set, invalidation on
the first stall or release, prefetched return during the hold and precisely on the
first-stall edge, simultaneous invalidation, coordinated reset, stale-line refetch,
and same-cycle release/request turnover. A mutation restores unsafe `hitReply` after
the snapshot; the independent immutable-byte oracle rejects it in all three models.
The same receipt binds the corrected parallel-way four-seed resident-bank sweep.

Physical timing, mapped resources and the corrected whole-board profile remain
separate integration gates. Previous base receipts continue to describe the tests
that passed at their frozen source; they are not universal cache correctness claims.
