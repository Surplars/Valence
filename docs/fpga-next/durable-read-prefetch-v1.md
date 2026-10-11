# Optional durable READ prefetch with ready-store bypass

The combined candidate improves the measured Sv39 COPY run, with a small Bare
cost. It is an explicit optional entry. Older recommended presets and the
published `81ed0a53a066ff724101f6d9f2d19f764c32c520` entry remain available;
all three new generic policies default to false.

| Matched simulator case | Published 81ed ROI + clean tail | Candidate ROI + clean tail | Inclusive time change | Inclusive payload MiB/s, before → after |
| --- | ---: | ---: | ---: | ---: |
| Sv39, original DDR law | 247034 + 8189 = 255223 | 238718 + 8187 = 246905 | −3.2591% | 48.9768 → 50.6268 |
| Bare, original DDR law | 251815 + 8053 = 259868 | 252648 + 8046 = 260694 | **+0.3179%** | **48.1013 → 47.9489** |
| Sv39, separate burst-locked law | 243398 + 8190 = 251588 | 230864 + 8186 = 239050 | −4.9835% | 49.6844 → 52.2903 |

The original-law Sv39 throughput change is +3.3689%; time reduction and
throughput increase are different ratios. Against the older 7cc baseline's
250604 + 8187 = 258791 cycles, this same candidate reduces inclusive time
4.5929% and increases throughput 4.8140%. Generation improvements are not
multiplied. The isolated ready-store experiment's 269280 + 8030 = 277310
regression remains preserved as negative evidence.

Rates count 131072 logical COPY payload bytes once: `12500000 / cycles` MiB/s.
100 MHz is the unchanged reporting normalization, not a measured clock or
timing closure. The traffic includes both read and write transfers, which
must not be double-counted as COPY payload. Neither DDR law establishes MIG
or board performance.

## Exact configuration and behavior

The complete profile is two-issue ROB16/PRF48/LSU4/DTLB16/DMA4, with the existing
full board fabric, two read MSHRs, two writebacks, and a 16-attempt prefetch
lifetime. The optional entry adds exactly these arguments to the 81ed entry:

```
--pending-ready-store-bypass
--durable-read-prefetch-candidate
--read-prefetch-behind-store
```

The manifest carries the actual executed 56-field profile, 149-field core and
19-field cache constructor, complete emitted fabric and ordered options. It is
not a selected-field summary. CPU and native constructor JSON agree exactly.
The inherited `productionCommit` string inside fabric metadata is only an
older label; the measured source is commit
`96b7217f6a28d98f53949f0db311de4a9a6f4f13`, tree
`d1620ce9c5c93cfe56b6b17131482aa62078654e`, bound by file hashes and the tested
commit bridge.

Ready-store bypass relaxes a younger load offer only past an exact proved,
disjoint, non-head ready store. The current head and existing ownership,
ordering and credit restrictions remain checked.

An accepted READ may capture a candidate behind exactly one live, unattached,
nonposted STORE-origin prefetch owner. Capture does not allocate an MSHR.
The candidate can wait through the permitted finite READ lifecycle, including
a held ordinary full-tag resident WRITE hit, while the original monotonic
deadline continues to expire. Every allocation rechecks the existing guards
and requires pre-edge READ-token capacity. Allocation and retention are
exclusive; no same-edge token reuse, candidate overwrite, deadline refresh,
posted-store promise or new cache state is introduced. STORE-origin waiting
keeps its original finite rules.

## Measured evidence

The actual cache/home fixtures ran modes (0,0) and (1,1), twelve schedules each,
with 24 independent 128 KiB final images and seven actual corruption controls
that exited nonzero. Retention-only (1,0) has static constructor coverage and
is **dynamically unqualified**. The source includes those checks in
`DurableReadPrefetchConfigSpec`, `DurableReadPrefetchGsimMain` and
`simulator/gsim/durable_read_prefetch.py`.

All three CPU cases pass independent architecture, read-data, final-memory,
trap, ownership and fabric checks with the complete 105-field schema. Three
real read/memory/trap corruptions and two extra wrong-owner/token-capacity
observer corruptions are rejected. One actual 36-unit GSIM model was compiled;
the follow-on cases reused those objects. The published OFF CPU is its retained
qualified model with the existing exact publication bridge, not a new build.
There is no isolated ready-OFF/durable-ON CPU measurement.

Original-law Sv39 READ counts are 4024 candidates, 2014 allocations, 1344
resident-useful and 670 attached-demand completions. Resident-useful excludes
attachments. The published baseline already had 2014 allocations and the same
1344 + 670 useful split; extra candidate captures alone are not extra useful
work. STORE counts remain 2014 candidates/allocations/resident-useful.
ROI AR/R/AW/W are unchanged at 4160/32832/2048/16384, and tail counts remain
4/18/257/2056. The measured gain accompanies changed scheduling and no extra
external traffic.

At the physical data adapter/router → private L1 request port, accepted
cycles stay 32768; held cycles increase 34178 → 37326 and no-offer cycles fall
180088 → 168624. Those three mutually exclusive classes sum to each run's
ROI: a net reduction of 8316 cycles. The R-or-W data-handshake fraction rises
19.9228% → 20.6168%, with the same 49216 transfers and zero R/W overlap.
No-data-handshake cycles do not distinguish absent VALID from backpressure;
these counters establish conservation, not a causal savings decomposition.

The original DDR law uses R32/B32 eligibility and newest-eligible selection
per returned beat. The separate second law selects newest-eligible only at
returned-burst boundaries and holds that burst through LAST fire. Its
independent service checker confirms no interleaving and one-cycle interbeat
spacing; results from the two laws are kept separate.

The first CPU attempt failed an old passive formation mask. That failed
receipt, binary and raw output remain intact. The successful attempt changes
exactly `production_probe.h` and `supply_ledger.h`: the precise sole STORE-owner
formation exception and a bit-19 pre-edge READ-token capacity veto. These are
host-only observers, gated by the actual cache options. They change neither
DUT inputs/state nor guest, DDR service or architectural oracles. Exact
successful headers, patches and a checked materializer are committed under
`simulator/gsim/durable_read_prefetch/`; the original 17-file snapshot stays
unchanged.

## Native cost and compatibility boundary

The actual full-board native census is unchanged from 81ed: 97,337 scalar
register bits plus 729,335 array register bits; 568 module instances; 237,478
summed internal port bits and 353 top-level port bits. All deltas are zero.
External resource bytes and paths agree. These are reachable post-firtool
declarations, not mapped LUT/FF/BRAM/DSP utilization. Internal port sums count
both sides of module boundaries and are not package pins.
All 129 native array-memory instances (46 definitions), their 186 named read
and 129 named write port families, and exact named state/interface signatures
are identical. These port families are not inferred physical RAM primitives.

Combinational logic changes in the existing backend offer and cache candidate
capture/allocation/retention cones. Zero declaration cost does not imply zero
LUT cost or unchanged delay. No new synthesis, STA, routing, frequency or
board qualification is claimed.

The new source with all three policies OFF has 292/293 native files exactly
equal to published 81ed. `NonBlockingCoherentLineCache.sv` is not byte-equal.
The narrow certificate permits one fixed identifier mapping and the added
`!canAllocate` retention guard, whose redundancy is derived from exact source
implications over known legal states. All other tokens match and four logic
mutations are rejected. This is not arbitrary-X-state equivalence or a
whole-design formal proof; the raw inequality remains recorded.

## Reproduction and retained artifacts

The following commands are source-only and print the complete checked export
or ordered options without running hardware:

```
python3 fpga/next/board_durable_read_prefetch.py --output /fresh/path
python3 fpga/next/board_durable_read_prefetch.py --print-native-options
python3 fpga/next/board_bound_store_prefetch.py --output /fresh/rollback-path
```

`--emit` on the explicit candidate entry performs native export only. It does
not run Vivado or create a bitstream. Use the optional entry's complete options
for `ooo.FpgaNextProfileMain` and `ooo.CpuMatchingBoardProfileGsimMain`, never
assemble a shorter hand-written profile. The focused runner accepts explicit
`--toolchain-root`/tool paths, `--output`, and `--preflight-only`; actual serial
build/run requires `--execute`.

For a fresh CPU model, prepare the exact measured passive host from its actual
constructor and fabric. The script rejects any missing/changed/unknown
constructor field, fabric drift, modified observer bytes or existing output:

```
python3 simulator/gsim/durable_read_prefetch_host.py \
  --profile /fresh/model/profile.json \
  --fabric /fresh/model/actual-fabric.json --output /fresh/host
```

Use `--law burst-locked` for the separately pinned second-law header. The
`prepared-host.json` receipt gives all 17 exact source hashes, measured model
compiler flags, four cache-bound host defines and three required guest hashes.
It is source preparation, not a newly executed qualification. Preserve GSIM
`--threads=1 --cpp-max-size-KB=1024`, enumerate every actual contiguous generated
unit without assuming a 35/36/37-unit cap, compile serially with the recorded
ASan/UBSan flags, and preserve every failed receipt. Do not change service or
runtime deadlines to obtain a pass.

The [evidence index](../experiments/durable-read-prefetch-evidence-v1.json)
names exact Library IDs, archive hashes, source/host identities and receipt
paths. The CPU evidence archive includes the complete executed runners,
contracts, original/positive/control/fixed 17-file hosts, guest hashes, raw
traces, negatives and all three final cases. The separate model archive retains
the unique 36 translation units and all four actual binaries, including the
failed observer attempt. Large generated artifacts and ELF files are external
recovery evidence and are not committed to Git.

Publication adds no changes to tested production Scala or fixtures. The new
entry, materializer, manifest and documentation are bridged by complete source
bytes and short host/configuration checks. The branch update is a separate
root-reviewed compare-and-swap against exact 81ed; `main` is untouched.
