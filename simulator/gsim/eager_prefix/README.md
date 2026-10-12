# Optional direct eager fetch prefix selection

The default board entry remains `python3 fpga/next/board_final.py --output build/final52`.
The separately selectable A/B candidate is
`python3 fpga/next/board_eager_prefix.py --output build/optional53`.
Both commands perform source/configuration preflight only. They create no output
directory and execute no compiler, simulator or FPGA tool unless `--emit` is given.

Optional53 adds exactly `--eager-fetch-prefix-select` to the unchanged final52
CPU/native option vector. MAC T1 is a separate physical option, not a 54th CPU
option. Both entries retain USER2, 100 MHz CPU, issue width 2, ROB16/PRF48, LSU4,
DTLB16, four DDR slots, two proof slots and two early-load credits. Generic
constructors keep the new Boolean false. The candidate requires the existing
aligned permission stage and changes no other constructor field or capacity.

Run the bounded public checks from the repository root:

```
python3 simulator/gsim/eager_prefix/check_retained.py
python3 fpga/next/test_eager_prefix_profile.py
python3 fpga/next/test_board_final.py
python3 simulator/gsim/eager_prefix/test_check_retained.py
python3 simulator/gsim/eager_prefix/test_entry.py
```

The checker validates the public receipt, necessary source fingerprints,
aggregate production and complete Scala closures, actual recorded constructor
selection, and both entry preflights. Entry tests use a mock emitter with real
source staging and Tcl contracts; their PASS is source-contract evidence only.
These checks do not rerun Scala, GSIM, NEMU, a native board or physical tools.
External receipt/bundle hashes identify retained private evidence. An explicit
`--external ROLE=FILE` checks supplied bytes only; unseen bundles are not silently
downloaded or revalidated.

The recorded qualification compiled all 199 production and 343 test Scala files
plus 18 HardFloat files, with 37 focused Scala and 15 Python profile tests.
Full native comparison covers 239 modules; only `RegisteredFetchPacket` changes,
and the other 238 modules are byte-identical. All native module ports, declared
state and arrays remain equal. State is a per-module declaration census, not an
instance-expanded or mapped physical resource count.

The rewrite removes one four-bit prefix length sum, four offset comparisons,
and one four-input 64-bit indexed selector plus a separate four-level conditional chain.
Wide masks increase from three to five and OR joins from two to four. These are
structural facts; control fanout, buffering, mapped LUT/cell cost, Fmax and STA
remain unmeasured. This is one selector, not four independent mux banks.

The independent component observed 4,140 exactly equal OFF/ON whole cycles,
including hot II1 and boundary/fault/context coverage, and passed 14 negative
controls. One newly generated ON CPU model matched saved52 at 191618 Sv39 and
194153 Bare inclusive cycles, with all 105 functional fields, all 12 result
sections, complete stdout, raw AXI and supply equal. Inclusive/ROI/tail deltas
are all zero. The original read/memory/trap controls pass. The same 36 ON CPU
objects pass NEMU hot/compressed in 1847/958 cycles, with exact saved52 stdout
and PC/GPR/memory corruption rejection. NEMU performs no DUT regeneration,
object recompilation, reference rebuild or state resynchronization.

There is no new OFF CPU run. The new-source default52 native bridge is not raw
byte-identical: exactly two selector-local automatic declarations are renamed
and moved within the same pure-initializer prefix. The strict comparison proves
their exact expressions, lexical scope, dependency and use positions, and an
identical remaining token stream. All other modules are raw byte-identical.
The original comparator failure and original outputs remain in private evidence;
the repaired audit passes 19 helper checks and six actual-copy tamper controls.

The old owner-row52 receipt remains byte-for-byte historical. Its original
checker binds the complete source at
`b22f10fde916a0c8209d070e282ebd98cf4c0b2f`, tree
`a931ea8ec32438b5fe45852509b0b3dc0a782a6b`.
Restore that complete revision to replay the original source-bound entry/checker.
On this source, use the eager-prefix checker for the explicit default52 bridge.
The source-acquisition eager-prefix manifest also retains its original unqualified
status. Later results are bound separately by this directory's public receipt.

All tested production and Scala test bytes remain identical to tested local tree
`5736ae9442acfe05a4ffee1df58726c86e7d7e69`; that local root is not the remote
publication parent. The public entry's receipt pin and default52 export-source
closure were rebound with source-only checks after qualification. No CPU rerun
or physical result is attributed to that entry-only bridge.

An explicit `board_eager_prefix.py --output build/optional53 --emit` later exports
RTL and stages the unchanged MAC T1 and hard JTAG USER2 contracts. The result can
be checked with `board_eager_prefix.py --verify-export build/optional53`.
The staged post-synthesis USER2 gate still requires a separately authorized
physical consumer. Synthesis, mapped resources, placement/routing, STA and
bitstream generation are NOT_RUN. CPU COPY parity is not a new high-outstanding
throughput or network concurrency result. Default52 remains selected until a
separate physical A/B decision is made.
