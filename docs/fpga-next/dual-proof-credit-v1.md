# Optional dual proof-row and early-load-credit board

This explicit same-board candidate selects two pending-store proof rows and two
early-load credits. Generic defaults remain one row and one credit. The existing
durable-read, rollback and frozen physical profile manifests stay unchanged.
The four production files are the exact bytes used by the terminal focused,
board and native runs; publication adds configuration plumbing, the explicit
profile entry, host-only assertion-message repairs and evidence documentation.

## Selection and reproduction

From the repository root, inspect the complete optional profile without running
tools or creating output:

```sh
python3 fpga/next/board_dual_proof_credit.py --output /path/to/fresh-rtl
python3 fpga/next/board_dual_proof_credit.py --print-native-options
```

Append `--emit` to the first command to export native RTL with the configured
Mill toolchain. Export does not run synthesis, STA, bit generation or a board.
The entry checks the whole 57-field profile, 150-field core and 19-field cache
constructor, including unknown and missing fields. Against the saved complete
1/1 board, only the two capacities change after adding the new credit field
with expected default one. R16/PRF48/LSU4/DTLB16/DMA4, issue width two,
cache/DDR geometry, peripherals and the query/PMP pipeline remain the same.

The portable focused runner and hosts are committed. Run these stages in order
with a fresh output directory and the pinned GSIM toolchain:

```sh
python3 simulator/gsim/dual_proof_credit.py STAGE \
  --output /path/to/fresh-output \
  --toolchain-root /path/to/toolchain \
  --activate /path/to/toolchain/activate.sh
```

Stages are `freeze`, `config`, `emit`, `generate`, `sanitized`. The terminal run
passed eight Scala checks, six models and 28 expected failures, each bound to
a nonzero injected-event count and a specific independent-oracle/assertion
anchor. ASan and UBSan were combined; leak detection was disabled because LSan
is unavailable under ptrace. This is focused coverage, not full regression or
formal proof. The two old legacy runners now match the new pre-edge-free-entry
assertion text. The existing capacity-one rejection proves that message;
the publication repair does not claim a fresh legacy model run.

## Original service-law result

The measured COPY payload is 128 KiB at a nominal 100 MHz. Inclusive time is
ROI plus the clean drain tail. Published baseline is
`e8c0062617255a370ed1bf13980f0c874b81e4fb`, tree
`20f7afcc13c62f1a102a31c8ad45e110b9bcf5f0`.

| Case | Baseline ROI + tail | Candidate ROI + tail | Inclusive throughput |
|---|---:|---:|---:|
| Sv39 | 238,718 + 8,187 = 246,905 | 229,966 + 8,185 = 238,151 | 50.62676 → 52.48771 MiB/s (+3.676%) |
| Bare | 252,648 + 8,046 = 260,694 | 252,648 + 8,046 = 260,694 | 47.94894 MiB/s (unchanged) |

Sv39 ROI throughput rises 3.806%; ROI cycles fall 3.666%. Inclusive cycles fall
3.545%, distinct from the 3.676% throughput increase. The complete architectural
oracle, copied memory and clean tail pass, with 105 captured functional and
performance fields. Three actual board corruptions are rejected. Changed
traffic/cycles are measured, not forced to equal the baseline. One fresh board
model is shared between the two original-law cases and the auxiliary law below.
The saved CPU receipt's `PASS_BARE_ONLY` status names its last stage; its stage
map and cases contain the preceding successful Sv39 run and negative controls.

No credit-state observer was added to the board. These results do not attribute
all gain to a single gate or claim measured board utilization of the second
credit. The dedicated real backend provides the two-owner coverage.

## Separate fixed-wholeburst law

This auxiliary result is compared only with its own baseline: 230,864 + 8,186 =
239,050 cycles becomes 229,590 + 8,183 = 237,773. Inclusive throughput increases
0.537% (52.29032 → 52.57115 MiB/s); cycles fall 0.534%. The fixed service verifier
passes. It is a second synthetic service law, not validation of actual MIG DDR
behavior, and must not be mixed with the original-law denominator.

## Cumulative engineering comparison

The separate saved 616-binding comparison establishes the historical
`f6b0faac7dbc7a3d9a644a02862c6b7b2d8c7f98` source/model/binary/publication
identities, both raw stdout identities, and identical guest, memory
initialization, original DDR service and independent architectural oracle bytes.
The actual historical profile has 44/142/14 fields; missing fields are not
invented. CPU/cache features intentionally accumulated between revisions.
Population, geometry, peripherals and R16/PRF48/LSU4/DTLB16/DMA4 match.

| Original-law case | Historical inclusive cycles | Candidate inclusive cycles | Cumulative throughput increase |
|---|---:|---:|---:|
| Sv39 | 281,817 | 238,151 | 18.335% |
| Bare | 297,546 | 260,694 | 14.136% |

These cumulative gains are not attributed to the present 2/2 change alone.

## Native cost and limits

One candidate native export reuses the exact published baseline export. Native
counts change by +314 scalar bits, +0 array bits, +0 instances, +310 internal
port bits and +0 top-level port bits. The proof bank contributes 244 scalar bits;
the credit bank contributes 70. Actual CPU constructor and fabric JSON are
checked in full; native identity uses the exact same selected options, recorded
source/tool contract and emitted RTL hashes. No separate native constructor
JSON was produced. Native declarations do not establish mapped FPGA resources,
fanout, placement, timing, frequency or timing-adjusted net benefit. No physical
STA or actual MIG/board validation is claimed.

## Saved evidence and recovery

The compact `simulator/gsim/dual_proof_credit_qualification.json` binds source,
guest, host/service and terminal receipt hashes. Full raw receipts and historical
failures remain in recovery evidence, outside Git; generated RTL, models,
binaries and raw traces are not committed.

Focused recovery Library item: `libfile_99723945632c8191bf717157170be803`, version 0,
archive SHA-256 `7e07ea50d9c3ad897cf1695e11e1af788ebc0a4839e1ed1e92ac6a860c1c9bc2`.

Whole-board terminal evidence: `libfile_69c2d07ef0e081919cd8cd6c5a8d0262`, version 0,
13,502,431 bytes, SHA-256
`795f68227fc90c7949cbf85727f0dad5e334ec38d0fa1977c3150937294c1de9`.
Current 37-translation-unit model recovery: `libfile_d350897f6340819181f2e7d1506c5fdf`,
version 0, 27,073,911 bytes, SHA-256
`601e8a668aa9dd3dc17fd8804ca047b18cb89c41e23c0023ddcaa308eab5e9d8`.
The entry is `micro-proof-credit-pipeline-r1/persistence-r1/terminal-aggregate.json`,
SHA-256 `1ba80d2342ccc1323463a37dcea6b3dead57771cf84cae6be0a0bae8a4bac100`.
Use the bundle's `persistence-r1/RECOVERY.json` and `restore.py` for reconstruction;
`library-index.json` also names the pinned e8 baseline and toolchain dependencies.

The saved whole-board scripts are historical reproducibility recipes, not
arbitrary-checkout portable CLIs. Restore the complete recovery layout, then map
its former root `/workspace/scratch/41e4a649bb60/recovery-20261011-0913` to the
restored root. `micro-proof-credit-pipeline-r1/board-plan-r1/run_cpu.py` expects
its sibling frozen `source`, existing contract and stage grants, the saved
`proof-owner-match-reuse-r1` baseline, `cpu-supply-f722/guest`, and `toolchain`.
`run_fixed.py` and `run_native.py` reuse that contract and saved model/native
bindings. Read the archived README and aggregate receipt before resuming;
the scripts refuse overwriting previous output. Use a new reviewed revision
for a fresh board rerun. The explicit profile and portable focused runner above
are the supported entry points from an ordinary checkout.
