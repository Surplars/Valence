# A1 efficiency refactor — fifth experimental candidate

**2026-10-27: focused functional validation and the normal-tile resource map
passed independent review and were sealed. This remains a default-OFF experiment,
not an optimization winner or a promoted performance baseline.**

This experiment separates load request **payload nomination** from complete
transfer authorization. It preserves the fourth candidate's measured cycles;
**there is no incremental bandwidth or performance gain in this batch**. The same-flow map uses **0.79017% more logic LUTs** and **5.38407% fewer MUXF
primitives**; this mixed tradeoff does not establish an overall improvement.
Physical Fmax, routed timing and power improvement are not established. The
fourth candidate remains the subsequent performance baseline.

## Source identity and configuration

The measured implementation is a frozen source batch on local fourth checkpoint
`9d2652b1e81d5c08b77879ca386b49d61edea9b7`, not an implied fifth commit.
The fourth checkpoint's separately published, tree-identical snapshot is
[`955827c7e2712f3029fbfc29d62be4286f53ef5e`](https://github.com/Surplars/Valence/commit/955827c7e2712f3029fbfc29d62be4286f53ef5e)
(tree `f03fade46935a2330427f838a1db239374f4f631`). These commit identities are not interchangeable.
See [the fourth checkpoint](a1-efficiency-refactor-4.md).

`CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5`
(`full-r1-m3-efficiency-refactor-5`) adds `loadPayloadNomination` to profile4.
The flag defaults OFF and requires the existing coexisting ordinary physical and
certified load ingress topology. Earlier profiles retain it OFF. Two issue/two
writeback, full 64-bit tags and owner/generation authority, FP, PMP, VM, AMO,
coherence, cache and debug functionality are retained.

## Exact structural change and authority boundaries

The wide checked request selector no longer needs full ordinary `Offer/Pass`
authorization merely to nominate the raw source. Ordinary nomination uses final
raw-port validity, old incoming occupancy credit, absence of older incoming,
translated or waiting work, ordinary read shape, and absence of enabled sidecars.
Ordinary and unchanged certified nomination are mutually exclusive and both
select exactly the same final raw request. Their common raw selection also feeds
`NextLineAuthorization.request`. Registered identity and legacy payload selection
retain their existing fallback order.

**Nomination is not permission and cannot authorize a transfer.** The complete
ordinary offer still enforces original context/privilege, range, size/alignment,
mask, stability and flush conditions; certified checks retain descriptor, PMP,
epoch and fault authority. Original valid, ready, pass, enqueue, credit and owner
rules remain. The full original head is retained for authorization, faults,
privilege, sidecars and provenance. The existing final hint overwrite is retained.
An ineligible nominal request spills once via the old incoming path; it is not
newly accepted into checked. Ordinary physical loads still depend on the original
upstream PMP/exception authorization, not an invented DTA recheck.

The checked and incoming non-flow queues, translated/walker ownership, response
path and downstream service law are unchanged. No pipeline edge, storage or
outstanding credit is added. Full64 owner and fault/privilege authority are not
traded for a narrower selector.

Candidate assertions check source disjointness, older-source exclusion, full
offer implication, certified descriptor/raw equality, and complete valid checked
payload plus alignment equivalence to the former selector. Independent tests also
check final hint and faults, rather than relying only on the old-selector assertion.
**Invalid selected payload bits may differ by design.** Neither the ON internal
graph nor all invalid internal bits are claimed identical to profile4.

## Focused validation

One Scala compile covered 1,127 source inputs and 5,290 compiled-classpath files.
All **50 pure tests in 15 suites passed**. Whole-CPU and affected DTA hierarchy
lowering/combinational-loop checks passed. Pure checks are not behavioral tests.
With source annotations normalized outside strings, the OFF CPU FIR differs from
the saved profile4 FIR only in the existing assertion diagnostic literal
`MappedMachineCore.scala:160` → `:162`; independent review accepted that exact
literal change. This is not raw-file identity or arbitrary string normalization.

All **11 component cases passed**: two positive role runs, seven observer-checker
negative controls, and two real production-assertion negatives. The two positive
outputs are byte-identical (2,207,762 bytes, **2,241 frames**), with empty stderr.
Public events, credits, owners and complete valid checked request/final hint/fault,
physical/response/canonical payloads match. Invalid checked payload bits and the
new observation-only nomination signals are not required equal. Independent
accepted-ordinal, PTE/PMP and full-request oracles remain authoritative. Expected
negative exits are successful negative tests, not successful application runs.

All **30 CPU executions passed**: 12 profile4 control and 18 profile5 candidate,
using eight original business hosts and unchanged guests, oracle, memory service
and bounds. All **60 stdout/stderr comparisons** against the fourth candidate's
original outputs and all **24 direct corresponding positive control/candidate
stream comparisons** are byte-exact. This establishes the fixed-suite results,
not universal hardware equivalence or complete ISA qualification.

The control reused the r2 diagnostic-rebuilt fourth CPU object, SHA-256
`fc9fc83676dd1df7d8026240ca72b4fd07ab42ab7e367f59e83b12e4dd58a03c`;
there was **zero new baseline DUT compilation**. Candidate GSIM generation and
whole-object compilation each ran once; compilation took **171.330 s**. These
build times are not hardware performance measurements. Both roles separately
compiled/linked their original hosts to their respective single CPU object.

| Measured workload | Fourth control | Fifth candidate | Incremental gain |
|---|---:|---:|---:|
| CoreMark performance ROI cycles | 359572 | 359572 | 0% |
| CoreMark validation ROI cycles | 359864 | 359864 | 0% |
| Dependent-load retirement interval | 5 cycles | 5 cycles | 0% |
| Dependent-load ROI cycles | 320 | 320 | 0% |
| Independent-load ROI cycles | 90 | 90 | 0% |
| Independent physical request span | 105 cycles | 105 cycles | 0% |
| Component continuous64 acceptance / physical span | 64 / 64 cycles | 64 / 64 cycles | 0% |
| Component first physical latency / fixture span | 1 / 71 cycles | 1 / 71 cycles | 0% |

These are preserved fourth-candidate results, not a new official CoreMark score,
new NaxRiscv run, clock-frequency comparison or sustained bandwidth improvement.

## Normal-tile mapping — reviewed mixed result

The single admitted combined normal map used the fourth checkpoint's xcup/no-SAT recipe
apart from the input Verilog path. Preflight export, sv2v and proc inventory
passed. Normal CPU top: 256 ports / 4,482 bits; PRF 13/26, BHT 256, canonical
2,052, 60 memories and six completion banks retain baseline shapes; no blackbox.
The terminal result, not intermediate ABC counts, is used below. No repeat map
was selected to obtain a more favorable result.

| Primitive | Fourth normal map | Fifth normal map | Delta |
|---|---:|---|---|
| Logic LUT | 181606 | 183041 | +1435 / +0.79017% |
| FF | 51918 | 51918 | 0 |
| LUTRAM | 698 | 698 | 0 |
| MUXF | 31036 | 29365 | −1671 / −5.38407% |
| CARRY | 5596 | 5596 | 0 |
| INV | 1979 | 1980 | +1 |
| BRAM36 | 16 | 16 | 0 |
| DSP | 30 | 30 | 0 |

The bounded map used 4-CPU affinity, 6 GiB **sampled owned RSS**, 512 MiB reserve
and a 3,600 s timeout. The cgroup controller is unavailable; this is not a claimed
hard cgroup memory limit. The map completed in **2743.793 s**, with peak sampled owned RSS
**4,340,502,528 bytes** (4.3405 GB), exit 0, final check 0 problems and verified
empty owned cleanup. The 32 warnings and primitive modes match the baseline.
Independent final evidence review passed with the explicit mixed-resource
verdict. Fewer MUXF primitives did not reduce total logic LUTs; no frequency gain
was measured to offset the higher LUT count. Physical Fmax, routed timing,
physical area and power remain **unmeasured** even after logical mapping.

## Evidence and scope

Repository-relative evidence roots (generated build artifacts are not implied to
be committed or available from a source checkout):

- `build/fifth-efficiency-validation-20261027-r1/`: frozen inputs, compile receipt,
  emissions/OFF comparison, command receipts, original stdout/stderr,
  `CPU_RESULTS.md`, `COMPONENT_RESULTS.md`, `cpu-results.json`, `component-results.json`.
- `build/fifth-nomination-independent-review-20261027-r1/`: exact source/diagnostic,
  component runtime/terminal and CPU semantic/model/runtime/terminal gates.
- `build/fifth-efficiency-structural-design-20261027-r1/NOMINATION-CONTRACT.md`:
  selector and preserved-authority contract.
- `build/fifth-efficiency-full-cpu-mapping-20261027-r1/` and
  `build/fifth-map-independent-review-20261027-r1/`: map admission and terminal
  evidence, including the sealed receipt/manifest and final independent review.

| Evidence | SHA-256 |
|---|---|
| CPU results | `53834162668f460f8da6af39c0e31012e3f564094ec45e710cba5252e0b3d4d8` |
| Component results | `3ac2bad52c7e68361eb525d12d66a8e7d82bab24c3da13159df5a45f97209e45` |
| Independent CPU terminal review | `8380f6f978df26fae59e9b770a25202b8aceddc5c22dcc8dfcd4f308c8f0fdfe` |
| Sealed map receipt | `bfb690d2adecda02cd982c1dab6380072743c4f14e9bb08e5a2ad7fc0d5ce993` |
| Sealed map manifest | `d67a5dc062e79c0a105dfa58016146e1bdea354a205418bf18dfe4fe3b3c7e4f` |
| Independent final map review | `1147412bf1e327a933727fe8f89dca212dc66b27f62d9516d15cf0f32f4c4560` |

The separate passive throughput diagnosis and later instruction-fetch supply
proposal are **not changes or performance gains of this nomination candidate**.
No full regression, Linux, board execution, Vivado/P&R, bitstream or new CI run
is claimed. The option remains default OFF; no automatic baseline promotion.

## Tracked component host migration

The successful component host is retained at
`simulator/gsim/harness/load_payload_nomination.cpp`, copied byte-for-byte with
SHA-256 `2dbf761edec2e85f6c52e4e0cd38a692b36219e28de811e4b5cf57e079629b84`.
It reuses the existing tracked memory helper and translation oracle without
include edits or duplicate CPU hosts/guests. The original 1,127-source /
5,290-classpath compile freeze and original validation evidence are unchanged.
The separate post-migration host-only positive continuity replay and independent
terminal review **passed**. Each role compiled/linked only its migrated host,
reusing its original DTA object, then ran one complete positive. Both 2,241-frame
stdout streams equal their respective original successful output byte-for-byte;
stderr remains empty. All six compile/link/run commands passed without sanitizer
findings or remaining owned processes. Dependency records bind the unchanged
project headers. This added two positive runs only: no negative, CPU, DUT compile,
Scala compile or GSIM generation was repeated.

Continuity evidence: `build/fifth-migrated-host-continuity-20261027-r1/result.json`,
SHA-256 `378171914ab4ad09d145f8fc833f1c8f4472b9f5749b4e72401c724d4758dd61`;
independent terminal review:
`build/fifth-nomination-independent-review-20261027-r1/host-migration-terminal-review.json`,
SHA-256 `843013050e0d4c9f79a343c401e82a08daff3d28171e3ff2545eda19a31e1bc5`.
