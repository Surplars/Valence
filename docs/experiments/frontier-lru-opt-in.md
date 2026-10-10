# Proof frontier and store-prefetch LRU: opt-in experiment

Evidence updated 2026-10-10. This is an **explicit opt-in backup milestone**.
The recommended `posted-performance-v3` ROB16/PRF48 profile is unchanged.
All five selected CPU cases have closed their scoped gates: case21, Bare19,
WRITE18, warm6 and warm0. This evidence record is not a recommendation change
or a remote publication receipt.

The experiment combines ROB64/PRF64, the bounded memory-proof frontier and
store-origin prefetch LRU victim selection. It improves the measured Sv39
case21 but retains the known Bare19 regression versus published v3. The complete
opt-in has **5.303% more Bare19 total cycles** and adds **35,149 scalar / 25,984
array declaration bits** versus recommended v3; LRU's isolated zero-state delta
does not describe that whole configuration. The evidence is real S-mode CPU
simulation with fixed programs and DDR behavior, not Linux throughput, live
FPGA, mapped PPA or STA.

## Source identity and defaults

The published starting tree is `a314ece03d7953b695ac8ca0e45c10337a7f1a1a`,
identified on published `dev` by `98fae6bd7d1603ee446529712715ff794fb08c35`
and on the local source lineage by `09f23d153577b792a5868ac5dd88bdcb7eead1cc`.
The experimental source/test checkpoint is
`417c31f81746e297924c37d519fce7206654d7d1`; its final production change is
`527a3ebe9b77a33656f12666b9bd4315bd77ec71`. All 197 production-source files
are byte-identical to that tested checkpoint and its component-runtime source
receipt. The proof-frontier production predecessor is
`2880b32d8b4a89fe254dafdaa59df256b8466286`.

The integration retains the 27 original capacity, frontier and LRU commits.
It adds a host-only serialization repair: omitted `--memory-proof-frontier`
no longer adds a false field to the frozen native profile. Explicit enable adds
`memory_proof_frontier: true`; `store_prefetch_lru_victim` already follows that
rule. Complete Scala constructor reports include both Boolean fields even when
false. This distinction preserves the published native profile contract without
ignoring unknown fields or changing any frozen profile digest.

`fpga/next/performance.py` and `performance-profile.json` remain unchanged.
The six recommended/control combinations preserve every original native-profile
value and command argument: posted ON, posted-only, and posted OFF, each with
canonical overlap ON or OFF. The generic selected/reference/storage-candidate
profiles also preserve their original full native configurations and commands.
The generic new Boolean defaults remain false; implicit FPGA capacity remains
ROB16/PRF48. Generic `OooParams` and historical board defaults retain their
separate meanings.

## Exact entry points

Use the generic exporter for the experiment. This complete command is preflight
only; it creates no output and performs no hardware build:

```sh
python3 -B fpga/next/export.py --output FRESH_OUTPUT \
  --lsu-entries 4 --data-translation-entries 16 \
  --virtual-ram-load-precheck --physical-load-ingress-flow \
  --load-order-older-retire --fetch-previous-packet \
  --dma-line-transfers --dma-line-entries 4 \
  --prepared-store-lookahead --store-next-line-prefetch \
  --store-prefetch-mru-insertion --posted-store-merge \
  --posted-prefetch-coexistence --posted-prefetch-head-offer \
  --canonical-virtual-store-overlap --rob-entries 64 --physical-regs 64 \
  --memory-proof-frontier --store-prefetch-lru-victim
```

The generic native exporter defaults to selected topology. The board preflight
uses `python3 -B simulator/gsim/fpga_next_board.py --tag UNIQUE_TAG
--preflight-only --variant selected` followed by the same configuration flags
above, without `--output`. Both produce the same Scala option vector. Scala
entry points use `--rob-entries=64` and `--physical-regs=64`.

- Omit `--store-prefetch-lru-victim` for the matched frontier-ON/LRU-OFF control.
- Omit both new Boolean flags for the ROB64/PRF64 frontier-OFF/LRU-OFF control.
- Use the unchanged `fpga/next/performance.py --output FRESH_OUTPUT` for the
  recommended ROB16/PRF48 v3 control. It deliberately rejects capacity or
  experimental flag passthrough.
- Preserve `--disable-canonical-store-overlap`, `--disable-posted-prefetch`, and
  `--disable-posted` on that performance entry. These keep their existing scope.
- Adding `--emit` to the native exporter or removing `--preflight-only` from the
  board runner executes a new hardware build and is a separate operation.

The reviewed frontier requires explicit ROB64/PRF64, LSU4, DTLB16, virtual RAM
precheck, canonical overlap, older-load retirement, and the staged two-issue
backend. Request empty-flow is excluded. Actual constructors additionally check
registered issue/address/translation/fabric prerequisites, 16 proof rows and
256 two-way cache sets. Store-PF LRU requires checked store prefetch. The measured
combination retains posted merging/coexistence/head offer, MRU insertion,
DMA4, two MSHRs, two response slots, two writeback slots and all prior protection.

| Configuration | Recommended v3 | R64 frontier ON / LRU OFF | R64 frontier ON / LRU ON |
| --- | --- | --- | --- |
| ROB / PRF / LSU | 16 / 48 / 4 | 64 / 64 / 4 | 64 / 64 / 4 |
| `memoryProofFrontier` | false | true | true |
| `storePrefetchLruVictim` | false | false | true |
| Proof rows / cache sets | 16 / 256, disabled | 16 / 256 | 16 / 256 |
| DTLB / line / ways | 16 / 64 bytes / 2 | same | same |
| Canonical / posted / PF / MRU | enabled | same | same |
| Prechecked request / translated response empty-flow | disabled | same | same |

The complete current constructor report has 31 profile fields, 139 core fields
and 11 cache fields. Against the published v3 report, the only added default
fields are profile `robEntries=null`, `physicalRegs=null`,
`memoryProofFrontier=false`, `storePrefetchLruVictim=false`; core
`memoryProofFrontier=false`, `memoryProofRows=16`, `memoryProofCacheSets=256`;
and cache `storePrefetchLruVictim=false`. The report schema is
`posted-board-full-profile-v2`. All original fields must compare exactly.
These report changes are not hardware qualification by themselves.

## Closed CPU evidence and selected regressions

The isolated LRU pair fixes ROB64/PRF64 and frontier ON; only
`storePrefetchLruVictim` differs. Comparing the complete opt-in configuration
with published v3 also changes ROB/PRF capacity and enables frontier, and must
not be presented as an isolated cache-policy comparison.

| Workload | LRU OFF kernel + drain | LRU ON kernel + drain | Current gate |
| --- | ---: | ---: | --- |
| Sv39 case21 | 427,579 + 5,573 | 345,578 + 5,565 | Full functional pair, real trap negatives and scoped structural witnesses pass |
| Bare19 | 384,957 + 5,562 | 384,957 + 5,562 | Full functional pair and real trap negatives pass; `NO_STRUCTURAL_WITNESS` |
| WRITE18 | 112,761 + 10,643 | 112,761 + 10,643 | Full functional pair and real trap negatives pass; `NO_STRUCTURAL_WITNESS` |
| warm6 | 24,589 + 0 | 24,589 + 0 | Full functional pair, READ zero-tail contract and real trap negatives pass; `NO_STRUCTURAL_WITNESS` |
| warm0 | 16,458 + 0 | 16,458 + 0 | Full functional pair, READ zero-tail contract and real trap negatives pass; `NO_STRUCTURAL_WITNESS` |

For case21, kernel-cycle speedup (`baseline / candidate - 1`) is **23.73%**
against the fixed R64/frontier-ON LRU-OFF control. Kernel cycles fall 19.178%;
kernel plus drain falls from 433,152 to 351,143, a reduction of 18.933%.
Against published v3 (431,622 + 5,580), kernel-cycle speedup is **24.90%** and
total cycles fall 19.684%. These are different denominators and metrics.

The independent full-address causal audit closes all 672 repeated source-line
reads: OFF actually selected the then-MRU clean source in each identified
chain; ON eliminates the corresponding exact source-PA reread. Source demand
AR falls 2,720 to 2,048 and source hits rise 13,664 to 14,336 across 16,384
source loads. ROI total AR falls 4,833 to 4,161 and R beats 38,216 to 32,840;
AW stays 2,049 and W beats 16,392. All 2,015 store-PF allocations have recorded
later use in both runs. The ON audit binds 1,024 exact dirty-PA/eight-C/AW/eight-W
chains. It does not invent a saved-cycle cost for each eliminated miss.

Actual distinct-line external-overlap witnesses increase from 641 to 991;
the 991 ON witnesses are nonoverlapping adjacent-line pairs. Remaining misses
are not counted as missed overlap opportunities. Independently, dirty-victim
selection increases PF release-owner occupancy from 6,081 to 43,836 cycles.
These are overlapping owner-occupancy cycles, not an additive stall total;
there is additional internal C/release waiting. ROI plus flush R+W traffic
falls from 453,312 to 410,304 bytes. Including flush, AW remains 2,305 and W
beats remain 18,440. The observed net cycle result already includes the dirty
release cost and all actual waiting.

ON still has 991 clean-source victims: 868 after all eight current-ROI source
uses and 123 before the current-ROI source fill. The claim is elimination of
the identified harmful rereads, not elimination of all clean evictions.
Cross-run correspondence uses full physical source and PF destination addresses;
ROB/way indices are local to each run. Within-run joins use full tokens/epochs.
TL source IDs are not equated with AXI IDs.

The adverse published comparison is retained. Bare19 is 365,235 + 5,618 on
published v3, versus 384,957 + 5,562 on the complete experiment. That is
**5.303% more total cycles** (390,519 versus 370,853), or 5.40% more kernel
cycles. The isolated LRU change has no effect on Bare19 or WRITE18 in these
runs. No same-guest published-v3 warm6/warm0 comparison is provided in this
milestone; the warm controls only isolate LRU at fixed R64/frontier ON.
Bare19 has zero frontier queries/inserts/starts, yet the frontier source
also changes ordinary preparation scheduling; zero proof activity does not
establish unchanged scheduling. This tradeoff prevents an unconditional
recommendation change.

The original legacy canonical endpoint join remains
`UNKNOWN_NOT_RECONSTRUCTED` for these CPU reports. No missing end sample was
fabricated. Exact actual offer/acceptance and full byte/fault/drain oracles
remain in force. The final case21 analyzer binds and rehashes the immutable
strict parser terminals and replays primary-log/negative controls; it does not
claim to rerun the large raw parsers itself. Actual parser success records are
retained; their invocation vector is deterministically source-derived rather
than independently captured. Each case21 side also retains its real trap
negative and seven exact raw proof mutations. The independent causal audit has
ten negative controls. Later functional-pair closure does not upgrade
`NO_STRUCTURAL_WITNESS` or the unknown legacy boundary join.

## Actual default-v3 and native resource audit

The official `fpga/next/performance.py --output FRESH_OUTPUT --emit` entry
actually exported default v3 from the frozen integration source. The complete
66-field native profile and argv match the published default. The separate
read-only actual-constructor audit passes the full 31/139/11-field report,
including six core, three cache and two DDR records. Both new controls are
explicitly false; no unknown field was ignored or preset digest relaxed.

Native default v3 has 92,636 reachable scalar-register bits, 709,879 array bits
and 98 RAM instances, equal to the published native reference. RAM geometries,
ports, helper bytes, module hierarchy and external paths match. There are no
frontier modules. **Literal native identity is false:** six module definitions
change and five gain an internal three-bit precheck-size port. The other 265
module definitions match byte for byte.

The exact connected graph fixes the new size high bit to zero at
`VirtualRamLoadPreparation`, wires it directly through `IntegerBackend`,
`IntegerCore`, `MachineCore` and `MappedMachineCore`, and uses only that high bit
in the new `DataTranslationAdapter` gate. The gate is therefore true in this
connected default graph. Remaining backend differences are three consistent
local aliases and one scalar AND-operand move. The narrowly scoped checker
covers every reachable instance, preserves raw differences and rejects eight
real text mutations. Independent review accepts this connected-top explanation;
it is not standalone adapter equivalence for arbitrary inputs, a general
formal proof, or timing equivalence. All six raw diffs and five port changes
remain recorded. All 542 interstitial segments and the split-file list match
literally.

The real export took 99.505 seconds including recompilation, with observed
process-tree peak RSS 3,006,408 KiB. The first enclosing runner failed its
post-run donor-cache guard: copied Zinc metadata contained old absolute paths,
and recompilation invalidated 2,127 donor class files. The successful native
export has its own receipt. The original runner FAIL remains unchanged.
An independently pinned continuation ran the constructor audit in 10.326
seconds (801,960 KiB peak process-tree RSS), performed no second export, and
retains its original `REVIEW_REQUIRED_RAW_NATIVE_DIFFERENCE` receipt. The
separate bounded review above resolves the specific differences without
rewriting those execution results. Missing cache classes were restored from
bytes individually matching the old manifest; all 2,457 cache hashes then
matched. Production/test sources and receipt-bound models stayed unchanged.
Do not copy Mill/Zinc `out` caches across source trees in future reproductions.

| Actual configuration | Scalar bits | Array bits | RAM instances |
| --- | ---: | ---: | ---: |
| Default v3 ROB16/PRF48, frontier/LRU OFF | 92,636 | 709,879 | 98 |
| ROB64/PRF64, frontier OFF | 123,420 | 731,943 | 98 |
| ROB64/PRF64, frontier ON, LRU OFF | 127,785 | 735,863 | 100 |
| ROB64/PRF64, frontier ON, LRU ON | 127,785 | 735,863 | 100 |

The whole opt-in delta versus default v3 is **+35,149 scalar / +25,984 array
bits**, with 21 RAM geometry changes. Capacity accounts for +30,784 / +22,064;
frontier adds +4,365 / +3,920; LRU alone adds 0 / 0 and changes no RAM geometry.
The two new RAM instances are the 140x4 frozen-owner memory and the 140x16
frontier payload memory. Existing ROB payload/PRF/owner memories also grow.
All 274 LRU-OFF module definitions equal the prior frontier-ON native output;
only the LRU-ON cache definition changes. Native declaration accounting is not
mapped FPGA area, placement, routing, timing or power.

## Reproduction and evidence boundaries

The repository contains the tested production sources, focused Scala fixtures,
independent component oracles, fixed profiles and runners. The exact CPU
observer/host capsules and large raw archives are separate recovery artifacts;
a plain checkout is not claimed to contain the complete CPU qualification
capsule. Their manifest hashes are recorded in
[the evidence index](frontier-lru-evidence.json). Restoring archived Bare19 raw
is required before historical raw-parser or pair rechecks.

- [Frontier design and limits](memory-proof-frontier.md),
  [fixture contract](memory-proof-frontier-fixture-contract.md),
  [selected metadata ports](memory-proof-frontier-ports.md), and
  [sampling contract](memory-proof-frontier-sampling.md) retain their original
  checkpoint history.
- `simulator/gsim/memory_proof_frontier.py`, `memory_proof_frontier_exact.py`,
  `memory_proof_frontier_exact_range.py`, their independent C++ harnesses and
  corresponding Scala fixtures retain the tested source identities.
- [LRU actual cache/home runner](../../simulator/gsim/store_prefetch_lru_victim/README.md)
  requires the frozen generated gate and exact tool receipt. Its 20 positive
  schedules and five intended negative controls passed per side. The standalone
  fixture has posted coexistence OFF, so its PASS is separate from the CPU
  composition, which has coexistence ON.
- [LRU policy contract](store-prefetch-lru-victim.md) and
  [capacity controls](../../simulator/gsim/rob_capacity/README.md) retain their
  original, explicitly historical schema expectations. Current-schema gates
  compare all fields; they never suppress unknown fields.
- The existing host-only performance, canonical and capacity checks passed
  9, 5 and 3 tests respectively, and the LRU CLI check passed 10 cases. The nine
  default/control preflights preserve the full original profile bytes/argv.
- Focused frontier truth, transport, LSU/range and late-fault gates, fresh CPU
  models and RV64GC positive/real-negative smoke tests have their own retained
  receipts. None substitutes for a pending workload or for physical FPGA work.

Generated FIR/SV/C++, model objects, ELF, runtime binaries and raw logs are not
part of the source publication delta. All prior posted/returnflow/canonical
paths and documented disable switches are retained. Warm6 and warm0 have zero ROI DDR AR/R/AW/W/B on both sides. All four selected
follow-up controls are cycle-identical across the fixed R64/frontier-ON LRU
pair and retain `NO_STRUCTURAL_WITNESS` plus the unknown legacy endpoint join.
This closes the selected functional controls, not a full regression or physical
FPGA qualification. The recommendation remains v3. Archive delivery identities
can be appended to the separate recovery index without changing source bytes.
