# Recommended posted performance preset v2

`python3 -B fpga/next/performance.py --output FRESH_PATH --emit` selects
`posted-performance-v2`: posted merging, posted/PF coexistence and PF-only
initial head offer are ON. Generic module/export defaults remain OFF. Both
translated-response empty flow and prechecked request flow remain OFF.

There are three fixed selections; arbitrary hardware overrides and option
abbreviations are rejected:

| Selection | Posted | Coexistence | Head offer |
|---|---|---|---|
| Default recommendation | ON | ON | ON |
| `--disable-posted-prefetch` (original v1 recommendation) | ON | OFF | OFF |
| `--disable-posted` | OFF | OFF | OFF |

The two disable switches are mutually exclusive. Generic exports additionally
support coexistence ON/head offer OFF for the measured A control; that control
is not the original v1 recommendation. Head offer requires posted merging and
coexistence; coexistence requires posted merging. Existing eligibility and
profile guards continue to enforce the other prerequisites.

## Current measured behavior

The original case18/19 guest was run in S-mode Bare physical addressing on fresh
qualified Board models. Both A and B enable
posted merging and coexistence; only head offer changes. Reported cycles are
kernel plus subsequent flush, kept separately:

| Workload | A: head offer OFF | B: head offer ON | Independent historical v1 reference |
|---|---:|---:|---:|
| COPY19 | 457,146 + 5,620 | 365,235 + 5,618 | 452,641 + 5,666 |
| WRITE18 | 112,826 + 10,646 | 112,826 + 10,646 | 112,826 + 10,647 |

COPY B/A throughput is 1.251649x for the kernel and 1.247842x including flush.
Relative to the separate historical v1 reference it is 1.239314x and 1.235819x.
The prior coexistence-only COPY regression (457,146 versus 452,641) remains part
of the record. A separate no-posted architectural historical reference is
383,603 COPY kernel + 5,618 flush cycles, as retained in the published
[seal performance record](posted-store-seal-performance.md). B is 5.029% faster
for the kernel and 4.953% including flush against that historical measurement;
it was not freshly rerun in this A/B. WRITE retains its benefit with the same A/B cycles and exact
ROI/flush AXI metrics. All byte, signature, fault, owner, quiet2 and trap-negative
gates passed. COPY retains 2,015 allocated/useful prefetches and 33 single-member
owners; WRITE retains 2,048 eight-member owners and no prefetch allocations.
These are fixed-workload cycle results, not wall-clock or physical timing claims.

## Actual preset qualification

The source-only recommendation commit is
`996d998275624e7527ce278dc0bc9157ef3ab3d1`, tree
`bf354b96def51878a64f8813daceef4a0cf344d6`. All 194 production blobs/modes equal
qualified `6f1e8c4fb1064f6d4fdd0b5ccbc4d5d595b5de94`; the measured Board helper
source retains its separate `e9af6a49e73f6606be233086fc1f57a4b86acb73` identity.
Each selection has a freshly executed pure constructor report: all 65 export
fields and all 26 FPGA, 135 core and 10 cache constructor fields are compared,
including nested values and types. The full canonical fixture and digests live
in `fpga/next/performance-profile.json` and the wrapper.

The recommended ON native emit matches all 269 raw files (268 SystemVerilog)
from the qualified head-offer ON native export, with no normalization. Full
OFF matches all 266 raw files (265 SystemVerilog) from the earlier integration
OFF export. The legacy posted-only control has a fresh complete actual profile;
its native correspondence uses the prior integration emit with unchanged
production inputs. No new GSIM run of these integration launchers is implied.

The prior `0d1bdaf435d6666188d3dbca05838291b22c847a` integration versus original
f1 native raw equality remains FAIL: one cache module differs on each side.
OFF has two internal wire renames. Posted-only ON has three wire renames and
one scalar alias extracted at exactly three consumers. A separate narrow proof
checks scope, widths, unique declarations, collision-free names, continuous
assignments, no extra writes and equality of every remaining token after those
exact transformations. Independent review rejected all 12 nonzero logic/type/
write/gate mutations. This is bounded structural correspondence, not raw byte
equality or general formal/timing equivalence. The original failed receipts are
retained. All 161 external runtime dependencies are hash-bound; six absent
source-local optional Mill resource directories are explicitly enumerated.

The [current machine-readable record](posted-performance-preset-v2.json) binds
profiles, receipts, source identities and scoped evidence. The original
[v1 machine-readable record](posted-performance-preset.json) remains unchanged.
Documentation added after qualification does not change native inputs.

## Coverage and limits

The focused gate contains 13 fresh genuine CPU/cache/home cases covering hot/
cold PF A-held, E/ReleaseAck tails, held request/response, FENCE/SATP drain, PF
AXI error and a distinct generation-two exhaustion model. It uses a smaller
cache/backing geometry than the Board benchmark. Exact unchanged consumer
source reuses the original 49 complete-byte cases and 12 expected assertions;
those are not fresh combined CPU runs. `full_qualification=false` remains:

- Eligible producer head overlapping candidate cancellation: UNREACHED.
- Otherwise eligible PF-only head overlapping integer/FP/posted accepted owner:
  UNREACHED in the serialized programs; source gates and direct assertions remain.
- Broader recovery/trap, denied PMP, misaligned, virtual, atomic and MMIO producer
  fault injection is not fresh coverage.

The Board diagnostic `reserveWithoutCapacity` copy omits `postedLaunchAllowed`;
bit 35 is not reliable capacity-stall evidence. The performance, AXI and direct
assertion gates do not depend on it. This limitation does not change the frozen
DUT or justify attributing individual blocked cycles as removable.

Head offer adds no literal scalar/array state (0/0 delta in the qualified native
pair). The older full 54-case/Sv39 runs used different source; this combination has not
run that full suite or Linux. No mapped PPA/STA, routed timing, bitstream, live
FPGA, Linux/Sv39 posted
early-ACK or posted-plus-returnflow/prechecked-flow qualification is claimed.
See [integration scope](posted-prefetch-integration.md).

## Historical v1 record (retained below)

Everything below describes the original published v1 source and receipts only.
Its old selection, field counts and measurements are not the current v2 contract.

### Original posted performance preset: exact configuration and native equivalence

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
