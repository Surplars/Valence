# Posted performance preset: exact configuration and native equivalence

`python3 -B fpga/next/performance.py --output PATH --emit` selects the recommended
`posted-performance-v1` profile with physical posted-store merging ON. Add
`--disable-posted` for the matched OFF control. Hardware overrides and option
abbreviations are rejected; generic hardware/export defaults remain unchanged.

The recommendation favors contiguous physical store throughput. Original Bare
WRITE improves 91.23% in useful-byte throughput, while COPY loses about 15.25%
(17.9973% more cycles). See the unchanged measurements and workload limitations
in [the performance record](posted-store-seal-performance.md). The native
literal-state cost is +9462 bits, with no mapped PPA/STA result.

## Configuration contract

The wrapper expands to the existing native exporter; it does not introduce
another hardware default or constructor. Before output creation or Mill, the
exporter compares a canonical SHA256 of all 63 expanded profile fields with the
sealed OFF/ON receipts. Preflight prints the complete profile and exact native
command, so it is reviewable without compilation.

The separate pure `ooo.FpgaNextProfileMain` reporter consumes those exact emitted
native options through the unchanged `FpgaNextConfig.fromOptions` parser and the
existing complete `PostedBoardConfiguration` serializer. Qualification compares
the entire resulting JSON with the corresponding frozen Board model report,
including every one of the 24 FPGA constructor fields and 134 core fields. The
same values are compared to all six core instances and all cache/DDR constructor
records in the existing final-instance audit. This is complete-field equality,
not a subset of flags inferred from a profile name.

The fixed contract includes selected RV64GC, issue width 2, LSU4, D16/I8/PTE4,
512-line two-way 64-byte caches, two read MSHRs, two responses, two writebacks,
DMA line transfers with four owners, physical ingress, older-load retirement,
previous fetch packet, virtual RAM precheck, prepared-store lookahead, checked
store prefetch and MRU insertion. Prechecked request flow and translated-response
empty flow remain false. Posted merging is the only ON/OFF treatment; pending
posted/prefetch coexistence is not included.

## Actual execution and byte equivalence

Both fresh native exports and both complete pure configuration reports passed:

| Selection | Elapsed export + report | Raw native files identical | SystemVerilog files identical |
|---|---:|---:|---:|
| OFF | 95.32 s (includes fresh Scala compilation) | 266 | 265 |
| ON | 19.86 s | 269 | 268 |

The comparison uses every file in each RTL directory, including `filelist.f`,
with no signal renaming, normalization or omitted module. The new export
receipts' complete inventories equal the sealed native receipts and actual disk
bytes. The complete OFF/ON parameter reports differ only at
`profile.postedStoreMerge` and `core.postedStoreMerge`. All constructor comparisons
and an independent geometry/profile check passed. Actual runtime/compiler
classpath inventories contained 161 external dependency files, all matching
previously pinned hashes; the local compiled classes and resources are also
hash-bound in the retained runtime record.

All hardware source files, the native Scala emitter, baseline geometry and
native resources are byte-identical to the sealed qualified source. The only
native-export input changes are the Python exporter and the new preset wrapper.
The added Scala reporter is a pure test utility and is not invoked by the native
hardware entrypoint. The actual new native receipts bind the wrapper and exporter
bytes. Documentation and qualification records added afterward do not change
any emitted hardware input.

The frozen qualification source is `0f567b32adfe606494c0e18fe789533c31f5c4f7`
(tree `0571868b015dbff52c99365a64685ecc81608d4d`). The sealed native and Board
qualifications retain their original source identity
`0658f2d4a543ba5849498af626eec0a248363540`
(tree `cc1d50b223fc0b6ebec448292ce8964986b56af2`). Existing runtime results are
reused through exact parameter, source and native-byte equivalence; no new CPU
benchmark run is implied. The [machine-readable record](posted-performance-preset.json)
binds old and new receipts, full reports, source closure and tool identity.

## Checks and scope

The 66 FPGA host tests pass, including seven new preset contract tests. They
check exact native command expansion, full profile digests, posted-only disable,
rejected hardware overrides/abbreviations, legal-but-unqualified changes,
geometric drift and unchanged generic defaults. Frozen native inputs, pinned
tools and dependency files were checked before execution. Both exports used
the existing toolchain with a 3 GiB Java heap and two processors, in a fresh
output namespace and serially in a coordinator-granted slot.

```sh
python3 -B -m unittest discover -s fpga/next -p 'test_*.py' -q
python3 -B fpga/next/performance.py --output build/fpga-next/performance-review
python3 -B fpga/next/performance.py --output build/fpga-next/performance-off-review --disable-posted
```

For a full pure constructor report, take the preflight `command` array and
replace `ooo.FpgaNextMain` with `ooo.FpgaNextProfileMain`, selecting a separate
fresh output directory. This prints no hardware and writes `profile.json`;
the canonical hash of the complete report must equal the corresponding
`full_profile_canonical_sha256` in the machine-readable record. That comparison
checks every field, including nested values and types.

The original physical owner/bytes/traps/drain/negative-control qualification and
old-counterexample/new-directed-witness evidence remain intact. This preset does
not qualify Linux/Sv39 posted early ACK, posted plus either response/request-flow
experiment, pending posted/prefetch coexistence, mapped FPGA area, STA, a bitstream
or live-FPGA performance.
