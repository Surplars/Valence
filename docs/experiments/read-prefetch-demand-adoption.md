# Opt-in read-prefetch demand adoption

This source backup preserves exact tested production bytes and the measured
Bare/Sv39 result, with a bounded extra-read cost. Generic defaults and current
performance/board presets remain OFF. The intended next unified board profile
will explicitly enable dirty retry and adoption after combined qualification,
with the old profile retained for rollback. This backup neither enables that
profile nor supplies its physical qualification.

The original CPU NO_EXTRA_SOURCE_RELOAD gate **failed for Bare and stays failed**.
The recorded CPU receipt still says SOURCE_FROZEN_NO_DUT_WORK; its completed
commands and per-mode results, and its final summarize failure, are preserved
without rewriting the receipt. The scoped performance conclusion below is a
separate decision that accepts the measured traffic cost for this optional
source backup. Machine-readable identities and limits are in
[the evidence JSON](read-prefetch-demand-adoption-evidence.json).

## Policy and invariants

An authorized ordinary read may attach to an already issued read-origin
prefetch for its full physical line. The existing MSHR, transaction tag, refill,
writeback and E-ack responsibilities remain owned until retirement. Attachment
saves a second allocation and lets the next line use another existing owner;
it changes no cache, LSU, queue or DDR capacity. Failed/denied/corrupt ownership
cannot fabricate a successful CPU response. Stores, fences, stale owners,
wrong lines and non-authorized requests cannot attach. Attached responses are
counted separately from resident useful-prefetch tokens.

The explicit --read-prefetch-demand-adoption flag requires split tracking and
independent demand admission, including their existing store-prefetch,
virtual-RAM-precheck and canonical-store-overlap prerequisites. Dirty retry is
independent; it is ON in both measured CPU arms. The FPGA exporter, official
Scala allowlist and GSIM board planner all carry the explicit flag. No preset
silently opts in. Actual pure Scala constructor reports for current A, B
and release presets pass the full-field checks with dirty retry and adoption
explicitly false in both profile and cache. The frozen preset manifests remain
unchanged; missing or enabled optional fields fail the host-side comparators.

## Completed evidence

The final focused component receipt binds source 507c81beefede7ecb806dc5219d65df8591ba5df
and production checkpoint 0c4beee087d3d4de036406ce3312cc4ff01a1b8c.
It passes 2 OFF and 18 ON actual component cases, 10 Scala configuration tests
and 6 precise poison negatives. Each component case checks the complete 128KiB
independent memory image. Real posted-enabled cache/home ownership,
backpressure, writeback/E holds and failed-refill aggregation are covered;
prior host failures and their repairs remain in the evidence archive. This
component result is not an executing-CPU or board claim. The original 2/18
cases did not dynamically exercise store, atomic or uncached-request exclusion
against a pending read prefetch. A separate host-only extension is being
prepared; its coverage is not inherited here and must close before unified
board-profile enablement.

The full-population matching B CPU runs retain ROB16, PRF48, LSU4, DTLB16 and
DMA4; the actual profile is 4/16/4, not a smaller surrogate. Both Bare and Sv39
run the original 64KiB COPY twice (131072 payload bytes) at the unchanged
100MHz reference with independent R32/B32 service laws. Functional bytes,
ordering, owner/drain checks and original applicable negative controls pass.
OFF reproduces the previous dirty-retry calibration's 105 original fields and
complete AXI traces. CPU known-error paths were not exercised, and actual
cache E-handshake cycle attribution is unknown in this CPU observer.

| Case | Same-source OFF ROI + flush cycles | ON ROI + flush cycles | Inclusive throughput gain | ON extra ROI read bytes |
| --- | ---: | ---: | ---: | ---: |
| Bare | 261697 + 8058 | 251815 + 8053 | 3.804624% | 896 (14 lines) |
| Sv39 | 273088 + 8204 | 250604 + 8187 | 8.694661% | 0 |

Against original f6B, Bare is 289431 + 8115 versus 251815 + 8053 cycles:
inclusive throughput +14.498899%, with 1792 extra ROI read bytes (28 lines).
Sv39 is 273627 + 8190 versus 250604 + 8187: +8.897527%, with no extra reads.
These percentages come directly from absolute totals; they are not compounded.
Flush carries no additional logical COPY payload. This is no new Fmax result.

Bare has 668 ROI attachments; Sv39 has 670. Each has 640 next-adjacent-line
A handshakes strictly before the prior attached refill with both owners live.
Full physical addresses, owner generations, complete tags and actual CPU
responses are bound. Bare source-region reads rise by 14 in ROI and net 5
before ROI: 19 extra over the whole run. Seven page-end lines have 20 gross
increases (6 before ROI + 14 ROI), offset by one fewer pre-ROI read elsewhere.

Every source AR matches the full-PA owner ledger. Bare ON has 39 verified
used-then-clean-evicted-then-reloaded chains; OFF has 20. All 39 ON chains have
an actual attached CPU response before eviction, and there are zero unknown
resident links. They are not 39 unused prefetches or 39 additional reads. The
new owner-generation reloads explain the failed zero-extra-reload target;
there is no observed duplicate A/AR within one owner generation. Sv39 has no
such chain. The bounded workload does not establish wider traffic behavior.

## Native cost and limits

Exact standalone cache native exports and their independent census pass.
Scalar register declarations are 8725 -> 8729 (+4); array bits remain 271876.
All 122 ports and reachable RAM geometry, address ports and read latency match.
The four new bits are two acquireIssued and two demandAttached bits.

Generated syntax adds 25 ternary, 3 equality and 1 variable-select occurrences.
The syntactic READY dependency graph is 1585 -> 1611 nodes. No path from the
current permission hint or current TL D valid/denied/corrupt inputs to READY
is found; the deliberately poisoned hint dependency is detected. These are
bounded source/dependency observations, not LUT/FF mapping, sensitization,
whole-cone equality, fanout, slack or Fmax proof. The first census checker
failure and corrected checker are both preserved.

There is no new board, physical DDR/CDC, GC/full-54, synthesis, STA, routed
frequency or bitstream claim. The attempted CPU RSS monitor did not identify
the DUT process, so its peaks are not valid DUT/process-tree RSS evidence.

## Reproduction and provenance

Focused checks, with a granted serial hardware slot and configured toolchain:

```sh
python3 -B simulator/gsim/prefetch_demand_adoption.py --output /fresh/output --run-grant
```

Host-only entry checks (no elaboration):

```sh
python3 -B -m unittest discover -s simulator/gsim -p test_read_prefetch_demand_adoption_cli.py -v
```

For a native preflight, use fpga/next/export.py --output /fresh/output with
--read-prefetch-demand-adoption and all prerequisites. Add --emit only when
an export is intended. The complete executed CPU options, commands, guest,
raw data, failures, model identities and independent host oracles are in the
persistent evidence packages identified in the evidence JSON. The source
backup includes [exact CPU host snapshots](../../simulator/gsim/prefetch_demand_adoption/cpu_snapshot/README.md)
and the exact six executed Scala wrappers. Relocated host paths were not
executed; original absolute paths describe the original recovery environment.
Preserve the frozen gate before evaluating a separately scoped policy.

The focused, CPU thin, unique-model and native packages are independently
versioned and SHA-256 bound. Packaging does not rerun those DUT or native tests.
The publication adds argument/constructor checks, with their execution status
recorded separately in the evidence JSON.
