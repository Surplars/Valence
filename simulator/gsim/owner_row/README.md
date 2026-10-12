# Final52 owner/row source and qualification

The reviewed entry is `python3 fpga/next/board_final.py --output build/final52`.
Its default operation checks the source/configuration and emits no RTL. The entry
selects exactly 52 CPU/native options plus the separate physical MAC T1 option;
T1 is not a 53rd CPU option. CPU frequency remains 100 MHz, issue width 2,
ROB16/PRF48, LSU4, DTLB16, four DDR slots, two proof slots and two early-load
credits. Tri-speed MAC and the existing hard JTAG USER2 connection remain selected.

The two new controls are default OFF in generic constructors:
`sharedCanonicalStoreOwnerMatch` reaches the actual backend through one OooParams
field; `localPayloadWriteRow` reaches the wrapper, actual manager and all four
slots. The first replaces 16 final 68-bit consumer token comparisons with 4-bit
index comparisons. Full-token producer and LSU ownership checks remain. The
second localizes seven upper-bank write-row connections per slot, preserving
bank0, data and write enables. Native declared state, arrays, ports and pipeline
cycles are unchanged. These are source/native facts, not mapped area or timing.

Run the bounded public checks from the repository root:

```
python3 simulator/gsim/owner_row/check_retained.py
python3 fpga/next/test_owner_row_profile.py
python3 fpga/next/test_board_final.py
python3 simulator/gsim/owner_row/test_check_retained.py
```

The checker verifies public receipt bytes, necessary source fingerprints,
aggregate production and full Scala source closures, default-OFF declarations,
actual recorded constructor forwarding and the final52 Python configuration.
It does not run Scala, GSIM, NEMU, Vivado or a hardware model. The board entry tests
use a mock emitter and real source staging/Tcl contracts; their PASS means only
that those contracts passed.

The small receipt records completed qualification in an external evidence
bundle: full imported 199 production and 341 test Scala compilation, 11 selected
configuration tests, 239 native modules, and one ON full CPU model compared with
the saved exact final50 baseline. Sv39/Bare inclusive cycles are 191618/194153;
all 105 functional fields, complete stdout, 12 result sections, raw AXI and supply
match with zero inclusive/ROI/tail deltas. Same-object NEMU uses the CPU's 36
objects, passes hot/compressed in 1847/958 cycles and rejects PC/GPR/memory
corruptions, with no DUT regeneration, DUT object rebuild, reference rebuild or
state resynchronization.

CPU COPY traffic is distinct from real-manager component stress. The owner
component contributes 4648 backend cycle observations and ten negative runs,
four boundary modes and a 99-module native comparison. Row component coverage
contributes 23223 observations, 13 negative controls and six native widths.
These observations do not establish high-outstanding CPU throughput or new
network concurrency. Mapped netlist, mapped resources, placement/routing and
STA are NOT_RUN. The explicit post-synthesis USER2 gate remains unexecuted.

Original failed config receipts and component source history remain in complete
external evidence. The first combined config run passed 10 of 11 tests after
full compilation, then failed a cwd-relative manifest lookup; the test-only
root resolver correction passed the repeat. The component host's aligned,
zero-initialized storage is established before public model construction,
followed by real reset and RAII destruction. The earlier post-construction
memset design was corrected before dynamic qualification. Invalid payload is
authorized only by the real validity and ownership gates.

The frozen `timing-batch-owner-row-profile.json` retains its source-acquisition
status; the later qualified source and results are bound by
`board-final-profile-v1.json` and this directory's public receipt. Opaque hashes
and Library references identify complete external evidence. No external bundle
is downloaded or validated merely by checking the source. Optional
`--external ROLE=FILE` verifies an explicitly supplied bundle's bytes only.

For the old, fully source-bound final50 entry, restore the complete repository at
`3fcfaf6d63b0bfa628f51856644678fcb5639928` (tree
`fdaad0fbf9d101df8ddfb2f6f8858980753dfcc1`) and run its original `board_final.py`.
The unchanged fifty-option vector remains available for explicit OFF selection
on the new source. The old entry/checker does not inherit a valid source hash on
the new source. Its historical receipt is retained under `zero_cycle_cleanup`.

An explicit later `board_final.py --output build/final52 --emit` runs the native
exporter. It still does not synthesize, implement or validate physical hardware.
The staged physical flow requires a separately authorized consumer and its
post-synthesis gates.
