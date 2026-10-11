# Opt-in read-prefetch dirty retry

This source backup preserves the qualified `readPrefetchDirtyRetry` experiment.
The generic setting and every existing performance and board preset remain OFF.
It is a separate development candidate based on public tree
`834b09a2264676d9eadcff3be403feffc20de85b` at commit
`f6b0faac7dbc7a3d9a644a02862c6b7b2d8c7f98`. It does not change the frozen
board qualification tree or establish routed timing, mapped resources, or a
working board. The evidence identities and exact counts are in
[read-prefetch-dirty-retry-evidence.json](read-prefetch-dirty-retry-evidence.json).

## Behavior and bounded cost

The feature remembers whether the current read line was entered sequentially.
A later accepted read of that same line can retry prediction after the first
opportunity was blocked. For a two-way cache, a read prefetch may select a dirty
victim only when the other way is the clean resident protected by the live store
prefetch token. Existing full-address/index protection and allocation ownership
remain in force. The captured allocation origin survives later token consumption
and MSHR reuse; a delayed dirty writeback acknowledgement cannot inherit a new
demand owner's identity. Demand victim selection is unchanged.

The option requires split read/store resident tracking and its existing
next-line/store-prefetch prerequisites. Use `--read-prefetch-dirty-retry` only
with `--split-prefetch-tracking` and the required store-prefetch options. Both
the native export and GSIM board CLI reject missing prerequisites, duplicate
flags and valued forms. No existing preset adds this flag.

Standalone native export of the exact production cache boundary adds one scalar
register bit: 8,724 to 8,725. Array bits stay 271,876; all 122 ports and seven
child-module files remain unchanged. The bounded emitted-syntax audit finds the
same upstream READY combinational cone after checked temporary-name renaming.
It retains clocked boundaries and validates its parser with an injected direct
dependency. These are declaration/dependency results, not FPGA LUT, STA, formal
equivalence, CPU/SoC resource or board claims.

## Qualification already completed

The final focused source is `a14a94ecd8237bb99531c01ce2f6f389503ad00e`.
Its source-bound GSIM cache/home gate passed 14 OFF and 14 ON cases, nine precise
negative mutations, and four Scala configuration tests. Every full 128 KiB
expected/actual image matches, including OFF/ON authored images. The checked
driver includes the final cancellation and saved-release witness boundaries;
the earlier `f99598c` driver is not the published focused driver.

The matching-board CPU pair uses the same B R16/PRF48/LSU4/D16/DMA4 population,
original 64 KiB × 2 copy guest, and unchanged independent read/write R32/B32 DDR
service. Full actual constructor/fabric JSON differs only in the new Boolean.
The original byte/reply/fault/ownership/drain controls pass. OFF reproduces all
105 original fields in both workloads and the exact original Sv39 AXI trace.
The following numbers are cycles, not host simulation runtime.

| Workload | OFF ROI + flush | ON ROI + flush | ROI throughput gain | Inclusive throughput gain |
| --- | ---: | ---: | ---: | ---: |
| Bare | 289,431 + 8,115 | 261,697 + 8,058 | 10.5978% | 10.3023% |
| Sv39 | 273,627 + 8,190 | 273,088 + 8,204 | 0.1974% | 0.1866% |

At the benchmark's 100 MHz normalization, copied payload throughput is
43.188 → 47.765 MiB/s for Bare ROI and 42.010 → 46.338 MiB/s including flush;
Sv39 is 45.683 → 45.773 MiB/s ROI and 44.355 → 44.438 MiB/s including flush.
These figures count the 128 KiB copied payload once and are not achieved board
frequency measurements or total AXI wire-byte rates.

Sv39 read and write traffic are unchanged. Bare adds 14 ROI read transactions,
112 read beats, or 896 bytes; its write traffic is unchanged. Bare useful read
prefetches rise from 36 to 1,344 while useful store prefetches fall from 2,010 to
1,370. This displacement and the small Sv39 improvement rule out a universal
performance claim.

The independent Bare trace join identifies every extra ROI read: seven source
lines `0x80402fc0`, `0x80404fc0`, `0x80406fc0`, `0x80408fc0`, `0x8040afc0`,
`0x8040cfc0`, and `0x8040efc0`, once per pass. A read prefetch supplies the first
word; a store prefetch then clean-evicts that exact source index before a later
source word demands a reread. All 14 full-address/generation/index witnesses
are retained. Warmup adds six more reads, so the whole-run increase is 20,
not 14. Bare has no dirty read-prefetch victims. Its read prefetches usually
lead the first offer by 40 cycles against a 57–58-cycle fill, leaving an
18–19-cycle wait. The reduced store-prefetch count accompanies 640 more posted
installations. These overlapping observations are not additive cycle savings.

Sv39 behaves differently: 670 demand allocations become read prefetches,
but the shared live-prefetch/writeback ownership gate replaces some previously
overlapping demand-plus-next-read-prefetch activity with serial prefetch
episodes. All 990 dirty read-prefetch episodes retain writeback responsibility
until acknowledgement near refill. Offline normalized full-address/ordered
transaction histories match across 3,119 keys; global cycle/ID order is not
claimed equal. This explains why higher usefulness alone does not establish
larger throughput benefit. Exact per-cycle causal attribution is limited by
which request offers the original trace recorded.

## Reproduction and observer history

The active focused runner is directly reusable from this checkout after a
source commit and an explicit serial execution grant:

```sh
python3 simulator/gsim/read_prefetch_dirty_retry.py --output /fresh/output --run-grant
```

It requires the pinned installed toolchain in `VALENCE_CLOUD_ENV`. This command
is documentation of the existing runner; it was not rerun for publication.
The six matching-board Scala wrapper files are copied byte-for-byte from the
qualified CPU source. `PostedStoreBoardLineageGsim.scala` contains the existing
single structural-type adapter. Production/configuration and Scala test bytes
are bound to their original focused or CPU qualifications; the combined
publication checkout itself was not recompiled.

The compact [CPU snapshot](../../simulator/gsim/read_prefetch_dirty_retry/cpu_snapshot/README.md)
preserves the exact final host observer and runner bytes in a new tracked path.
That new path was not executed. Its original relative paths and the complete
recovery topology belong to the independently saved CPU evidence package.

OFF reused 33 byte-identical qualified translation units and freshly compiled
the one changed unit; ON freshly compiled all 34 official generated units.
Header/CPP/compiler/flags/object hashes and current include dependencies were
checked, followed by complete OFF behavioral calibration. The old B receipt
did not capture historical system-header hashes; the record explicitly retains
that limitation and does not claim original whole-model byte identity.

Two observer corrections are retained with their original failed attempts.
Only the duration-dependent ON `fabric.samples` field is exempted from constant
fabric comparison. The former Sv39-only ledger lacked posted-store refill and
install observation, so the final ledger captures actual handshakes and full
slot/generation/cohort/epoch/PA, requires unique refill plus actual install
before owner retirement, and excludes duplicate legacy refill. Wrong-PA,
duplicate, wrong-generation and missing-install controls fail precisely. Bare
and both OFF workloads use the corrected observer. The original successful ON
Sv39 run is retained through an explicit zero-posted bridge proving all 6,146
owners had a unique legacy refill; it was not silently rerun or attributed to
the later observer. Original failed attempts and old fixtures remain in the
focused and CPU evidence packages. Their receipts retain old binary identities;
the thin package excludes generated executables.

Publication checked 3 CLI tests, 5 board-profile tests and 3 board-release tests,
plus exact bytes, modes and complete Git tree reconstruction. No DUT, Scala,
native export, Vivado or physical qualification was rerun for this packaging.
