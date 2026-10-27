# A1 efficiency refactor — first experimental checkpoint

2026-10-26; branch `dev/a1-efficiency-refactor-20261026`, control `e9bcc43`.
The measured candidate was a **precommit source snapshot**, bound by the mapping
`source-manifest.json`, not an implied later commit or a new default preset.

**Result:** matched CoreMark same-clock throughput improves **8.264% / 8.163%**;
normal same-flow mapping uses **5.869% fewer logic LUTs / 7.330% fewer FFs**.
This is focused experimental evidence, not a full ISA, Linux, routed FPGA or
production release. No physical Fmax, power, depth or critical-path improvement
is established. No local-machine rerun or public push is claimed.

## Implemented boundary

The explicit `CommonA1RebuildProfile.FullR1M3EfficiencyRefactor` profile
(`full-r1-m3-efficiency-refactor`) extends `FullR1M3IdentityFetchHorizon`.
Five flags remain default **OFF**, including in historical profiles:

| Flag | Implemented change and retained contract |
|---|---|
| `canonicalFetchCacheKeys` | Store canonical 57-bit high tags plus boundary-borrow tags; reconstruct all 64 address bits for three packet queries. 2052 address-state bits replace the old duplicated 5824 mapped address FFs. No truncation of lookup identity; validity/context/fault/accepted-owner handling stays with the caller. |
| `registeredMemoryOperandCapture` | Capture qualified registered load numeric values early; this is not permission to execute. Final start/proof admission still requires PRF-ready authority and the correct live consumer/producer identity. |
| `sharedMulDivOperandReads` | Share disjoint MUL/DIV source reads; logical PRF reads 15→13, bank reads 30→26. Preserve arbitration, write priority and operand authority. |
| `sourceLocalLoadProofCancellation` | Localize cancellation without shortening full 64-bit generation tokens or changing D2/T1/R2 capacity and ownership. |
| `sharedLoadProofPmpBounds` | Reuse exact 65-bit bounds while preserving byte coverage, overflow, first-overlap priority and permissions. |

Only this profile sets `branchPredictorEntriesOverride = Some(256)` (256-entry
bimodal); existing index/training semantics remain unchanged. This is not gshare.
The combined six-parameter result does not isolate individual flag benefits.
The canonical-key bit count is a source/emission geometry measure, not a
per-feature mapped-area saving; use the whole-tile resource table below.

Two issue / two writeback remain unchanged. No ISA, FP, PMP, coherence,
cache-capacity or debug capability was deleted to obtain these savings. The
benchmark safe-fetch region is exactly **128 KiB `[0x80200000,0x80220000)`**;
that region is not the total RAM capacity. The benchmark host is a single-hart
RAM home, not an external coherence probe generator. The normal mapping uses
`CommonA1CpuTile`, not the observation-heavy benchmark wrapper.

## Matched architectural performance

Same common-r2 ELF, one iteration / 2000-byte CoreMark, frozen independent
architectural oracle and matched external memory law:

| Seed | Control ROI cycles | Candidate ROI cycles | ROI instructions (both) | Cycle reduction | Same-clock throughput gain |
|---|---:|---:|---:|---:|---:|
| performance | 418254 | 386328 | 360525 | 7.633% | 8.264% |
| validation | 418674 | 387078 | 360366 | 7.547% | 8.163% |

Throughput gain is `control_cycles / candidate_cycles - 1`, not the cycle
reduction percentage. Full ISA observations and CRCs match for each seed;
performance CRC `8e3a1fd7e714e9f5`, validation CRC `8d840747e3c118f2`.
Both variants have 159 I requests, 65 D reads and no external D writes in these
runs. Dirty-resident flush was not requested. Total cycles including the
recorded setup/drain are 445061→411910 and 445596→412989; do not mix these
with ROI cycles.

The matched Nax same-program ROI is 268873 / 269245 cycles: Nax remains about
**1.437× faster at equal clock** than this candidate. This is a cycle comparison,
not a frequency-adjusted or equal-feature PPA ranking.

### Dependent-load result and preserved zero result

The dedicated `dependent-load-r1` guest contains 65 self-pointer loads; exclude
the first warmup retirement and measure 64 intervals. Reused frozen baseline /
candidate objects and the same backend/oracle were used for exactly four runs:
two positives and two exact result negatives.

- Every measured retirement interval: **7→6 cycles**, ROI **448→384 cycles**,
  **16.667% same-clock throughput gain** (14.286% fewer ROI cycles).
- Both: 65 physical requests/replies, one external D refill, no writes.
- Both accept **four I requests during ROI**. This is not fully hot I-cache
  performance and not an isolated bare L1 load latency measurement.
- No branch or M instruction is in that ROI. This still does not establish
  individual-flag causality within the combined candidate.

The earlier branch-free unrolled LD/MUL/DIV/W guest remains a **zero-gain**
control: both variants take **2332 total / 2306 work cycles**, with 247 retired
instructions and 53 physical requests/replies, under the separately named
historical whole-line latency-3 service. It is not the matched CoreMark service
or a Nax comparison. Do not erase this result or substitute the later workload
for it.

## Normal RTL resource mapping

One candidate map, no control resynthesis: the exact frozen tool/flow identities
were matched (firtool 1.135.0, sv2v 0.0.13, and all 36 recorded Yosys/ABC/Xilinx
identities). Normal top ABI remains 256 ports / 4482 bits. Independent streaming
counts agree with Yosys statistics; zero residual memories/processes and zero
reported check problems. Runtime **2671.58 s**, peak sampled owned RSS
**4,504,530,944 bytes (~4.50 GB)**; owned descendants were cleaned.

| Primitive measure | Frozen control | Candidate | Change |
|---|---:|---:|---:|
| Logic LUT | 198291 | 186653 | −5.869% |
| FF | 59318 | 54970 | −7.330% |
| LUTRAM instances | 628 | 648 | +3.185% |
| BRAM36 | 16 | 16 | unchanged |
| BRAM18 | 0 | 0 | unchanged |
| DSP | 30 | 30 | unchanged |
| MUXF | 33288 | 31270 | −6.062% |
| CARRY4 proxy | 5988 | 5812 | −2.939% |

LUTRAM is a primitive-instance count, not equivalent logic-LUT area. The Nax
normal map has 19238 logic LUTs, 10023 FFs, 45 BRAM18-equivalents (33 BRAM18 +
6 BRAM36), and 16 DSPs. Its FP, PMP, coherence, physical-address, cache and debug
scope differs: **do not calculate equal-feature efficiency/PPA ratios** from
these counts.

The exact historical depth verifier was not recovered from the current or
verified ancestor archives. Consequently no candidate depth or critical-chain
claim is made; the cached control depth of 64 is not compared against a new
substitute verifier. Source aliases / primitive-mode queries are supplemental,
not STA. No Vivado implementation, routed Fmax, power or board result was added.

## Validation scope and recovery history

- 30 pure checks across 10 suites; 11 actual component models, 9 positive runs
  and 60 exact negatives. Pure/source checks are not hardware execution.
- One candidate CPU object was built and reused (`8e36154ce44762ca716105c857fc80c5b862f4b85b722171cf2a2bc61443cc6b`).
  Five matched common cases; native supplement 80 retired / 11 AMO / 8 FP plus
  exact negative; four VM guests plus three exact negatives; four noncanonical
  high-bit/page cases plus exact negative. These are bounded tests, not full ISA.
- The initial forward-reference guard warning and original M/D stimulus failure
  remain in evidence. The qualified guard relocation and isolated host stimulus
  correction have separate receipts; history was not rewritten.
- Eight earlier padding/timing cases remain **INCONCLUSIVE** for the missing
  raw-held numeric-capture witness. Strict cancellation-ledger recovery has 17
  exact negatives, qualifies legitimate load-replay cancellation and a fresh
  generation replacement, and does not blanket-ignore ledger mismatches.

### Actual held-writeback witness (not a performance benchmark)

The standalone successful Bare load→AGU stress uses an independently qualified
legal post-assembly Home delay. Trigger/target Grants are cycles 54/55. Older
ALU owners `(12,12)` and `(13,13)` block target `(14,14)` at cycle 59. Consumer
`(15,15)` has numeric-capture samples at 59 and 60: **the same owner**, not two
distinct consumers. Target handoff is 60; PRF publication and consumer start are
61. The witness has 16 retirements, three LSU starts/completions and three
physical requests/replies. Its deliberately delayed service yields no benchmark
score. A same-object/binary/guest/service observation negative reaches and
rejects the exact consumer-result mutation; this is checker sensitivity, not an
RTL mutation or timing search.

Not established **inside this held window**: active VM proof admission, early
store base/data/partial-source capture, or fault/context/high-tag ABA cases.
Component fault/ABA checks and the general functional supplements are separate
coverage, not substitutes for those missing intersections. Original failed and
inconclusive receipts remain intact.

## Evidence and reproduction

Paths below are relative to the repository. Generated evidence lives under
`build/`; a clean checkout alone does not contain or recreate the experiment.
Use the archived source/tool/model/receipt bundle to restore exact inputs. Do
not overwrite historical receipts or execute frozen runners in place: several
have absolute paths, fixed output directories, affinity assumptions, or mutable
output handling. A fresh destination and reviewed path rebinding are required.
No claim is made that these evidence-local scripts are portable standalone tests.

Let `V = build/efficiency-refactor-validation-20261026-r2`,
`M = build/efficiency-refactor-full-cpu-mapping-20261026-r1`, and
`R = build/nax-matched-backend-independent-review-20261026-r1`.

| Evidence | SHA-256 |
|---|---|
| `V/validation-scope-summary.json` | `045ac62e5d1216ad612ab30cb970d8f80131c273703bd618863dae997a239b07` |
| `V/common-results/receipt.json` | `d15414f905311af18df0dced38f55d6feff2f5ac94bbeb8658ac11367fa21b2e` |
| `V/matched-coremark-comparison.json` | `becc26df39274509471aec1a2839d4dd184371f3697c0b2e54a3ddb27f557198` |
| `V/dependent-load-r1/comparison.json` | `4b1517db2d7aaa802ab9e1018c647350501a3fbcdf56fa5c6b204fc76c7ab3e2` |
| `R/dependent-load-runtime-review.json` | `f7e28a7955fd93a4d1801e1e8a866d0435ca1b59188f7c02e166629b2bd94b0b` |
| `M/receipt.json` | `4f41e2ee849a659fe77da5950dac0976c8c819170df7f21f34def180da1eb7d6` |
| `M/manifest.json` | `3ee064db591c2f2f2111f557073bf5d31d0e5ecce986a7d2b064e68619d276a6` |

`M/source-manifest.json` binds the actual measured sources; `M/resource-receipt.json`
and `R/efficiency-map-final-resource-review.json` bind the normal-map counts.
`V/architecture-only-unrolled-comparison.json` preserves the zero result.
`V/standalone-blocked-wb-r1-positive/receipt.json` and the corresponding negative
and independent runtime reviews establish the held witness. Earlier plan files
and comparison notes retain then-pending statuses: the sealed scope summary
supersedes them only for the explicitly completed checks, not for all gaps.

### Source entrypoints / restored execution plan

1. Restore and hash-check the archived sources, baseline objects, ELF/oracles,
   initialization receipt and exact tools against the manifests. Inspect
   `V/freeze-inputs.json`, `V/component-plan.json`, `V/run_batch.py` and the
   per-command JSON receipts before any authorized rerun. Preserve the old tree.
2. The repository's compile-receipt entrypoint is
   `python3 fpga/common/scala_compile_receipt.py --out <fresh-batch>/scala`.
   Focused pure suites are named in `component-plan.json`, including
   `platform.EfficiencyRefactorSpec` and `ooo.CanonicalFetchCacheKeysSpec`;
   use `mill -i IonSoC.test.testOnly <the planned suite names>`.
3. With the verified receipt's `runClasspathEntries` as `CP`, source emission
   entrypoints are:

   ```sh
   java -cp "$CP" soc.core.ooo.EfficiencyRefactorBenchmarkGsimMain <fresh-candidate-dir>
   java -cp "$CP" soc.core.ooo.CommonA1BenchmarkGsimMain <fresh-control-dir>
   java -cp "$CP" platform.CommonA1RebuildTileMain \
     full-r1-m3-efficiency-refactor <fresh-normal-dir> 0x80200000 131072
   ```

   The first two emit benchmark fixtures; the last emits the normal tile with
   the explicit safe range. Emission is not a GSIM pass or a synthesis result.
4. Restored `run_batch.py` separates `compile`, `specs`, `emit`, `component`
   stages, requires `--out`, `--root-go explicit-root-approval` and an `--id`
   where relevant. Its plan names all 11 component models and exact negatives.
   It binds GSIM/compiler through `VALENCE_GSIM_INIT_RECEIPT`; it does **not**
   rebuild CPU models automatically. Actual CPU compilation/link/guest command
   receipts in `V` and dependent-load `frozen-inputs.json`, `build.py`, `run.py`
   are the restoration reference, not a new generic launcher.
5. Reuse qualified CPU objects for the same backend, guests and oracle; keep
   negative controls, sanitizer settings and traffic/drain checks. Map only
   after the affected validation/admission gates, with `M/export-command.json`,
   `M/yosys-tools.json`, `M/run_map.py` and its resource guard as exact recorded
   references. The original map was run once, not per subchange.

**GSIM only; never invoke or fall back to Verilator.** This documentation was
checked against existing source and receipts without new builds, simulation,
synthesis, local-machine reruns or public publication.

## What is not implemented

Global four-read-port RF redesign, typed-PMP restructuring, compact leases,
frontend RAM conversion and gshare are future proposals, **not changes delivered
in this batch**. Further work needs its own coherent candidate, independent
correctness witnesses, matched end-to-end cycle measurements and appropriately
scoped resource/timing qualification. Current defaults remain unchanged.
