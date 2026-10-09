# Cloud CPU memory experiments: publication status

The tested integrated hardware source is commit
`9483b274e6d9a32df60255c1dc1d1a884b8260c4`, production `src/main` tree
`80a8a05d3a167825a98b240661610c70ac6202de`. This publication child changes
documentation only. Its production and all 225 effective native-export inputs
remain byte-identical to 9483. The original 1981-file model/host receipts retain
the 9483 identity; they are not rewritten to the documentation commit.

**Production defaults remain D8, prepared-store OFF, checked-store prefetch OFF
and store-prefetch MRU OFF. Pulling the code does not enable the measured
experimental profile or automatically obtain its COPY improvement.** MRU requires
checked-store prefetch. The lost posted-store merging and store-buffer writeback
reservation experiments have not been restored.

## Select the measured experimental profile

The measured profile uses selected C with D16/I8/PTE4, LSU4/DMA4, virtual RAM load
precheck, physical ingress, older-load retirement, previous-fetch packet,
prepared-store lookahead, checked-store prefetch and MRU insertion.
`prefetchBreakOnStore=false` remains unchanged. Activate the already pinned
project tools and run from the repository, using a fresh output directory.

The exact qualified GSIM profile selection is:

```sh
mill -i -j 1 IonSoC.test.runMain ooo.FpgaNextBoardGsimMain \
  build/gsim/fresh-mru-selected-c \
  --selected --lsu-entries=4 --virtual-ram-load-precheck \
  --physical-load-ingress-flow --load-order-older-retire \
  --fetch-previous-packet --dma-line-transfers --dma-line-entries=4 \
  --data-translation-entries=16 --prepared-store-lookahead \
  --store-next-line-prefetch --store-prefetch-mru-insertion
```

This emits the model; generation, C++ compilation and execution are separate
source-bound qualification steps. The corresponding native RTL export is:

```sh
python -B fpga/next/export.py --output build/fpga-next/fresh-mru-selected-c \
  --lsu-entries 4 --virtual-ram-load-precheck --physical-load-ingress-flow \
  --load-order-older-retire --fetch-previous-packet --dma-line-transfers \
  --dma-line-entries 4 --data-translation-entries 16 \
  --prepared-store-lookahead --store-next-line-prefetch \
  --store-prefetch-mru-insertion --emit
```

The export does not synthesize or install a board image. These commands differ
from the recorded commands only in the reusable fresh output paths.

## Executed gates and measured scope

New 9483 receipts cover 32 focused Scala/config tests, a fresh full-Board C+MRU
GSIM model, RV64GC positive and independent mismatch runs, real M-mode timer
interrupts, three independent M/Bare integer NEMU cases, coherent CPU+DMA, and
formal S-mode Sv39 WRITE20/COPY21 singletons. Applicable data, owner, exception,
drain and deliberately corrupted-input controls passed. NEMU compares each
retired PC and all 32 GPRs at the complete retirement-edge boundary; it does not
claim per-lane intermediate register snapshots or FP/CSR/VM NEMU coverage.
An interrupted NEMU attempt and its intermediate GPR bookkeeping marker remain
unchanged; the authoritative continuation audits completed exits/logs and runs
only the two missing negatives.

The new native C+MRU export has exactly the same 225 effective input files and
265 module byte sequences as the separately qualified 6d7a MRU-ON export, with
the same hierarchy, literal state and ten fixed-memory contracts. A separate
D8 comparison with the new features disabled on the selected/read/LSU4/DMA4
profile found zero state/array delta and 263 of 264 native modules byte-identical
to public dev. Its remaining cache difference is covered only by the documented
local-name/single-mux syntactic explanation and 17 negative checks. Neither
comparison is a general formal-equivalence or mapped FPGA timing proof.

The same-source 6d7a MRU OFF/ON pair is the relative-performance evidence:

| Sv39 4-KiB, 128-KiB case | MRU OFF kernel ticks | MRU ON kernel ticks | Flush OFF / ON |
|---|---:|---:|---:|
| WRITE20 | 207483 | 207483 | 10681 / 10681 |
| COPY21 | 633266 | 497148 | 5636 / 5574 |

PF-only COPY wasted 2015 complete line reads after source demands evicted
installed destination prefetches before use. MRU reduces read requests from
6176 to 4161 and read beats from 48963 to 32843, with 2015 useful store-origin
prefetches and no increased write traffic or flush cost. For this tested stream
profile, use checked-store PF and MRU together. The new 9483 singletons reproduce
207483/10681 for WRITE and 497148/5574 for COPY; they are not a new OFF/ON pair.
See [the detailed measured report](recovery/store-prefetch-insertion-results.md).

## Complete original ROM menu on D16

The original 54-case `u` menu completed on the 9483 C+MRU **D16** model in
96,009,421 cycles. All 54 observed-state rows and 54 complete UART rows passed:
18 each in S-Bare, Sv39 with 4-KiB pages, and Sv39 with 2-MiB pages. The run
checked three deliberate faults, 54 S-mode returns, 57 total trap returns,
32,768 independent data words and 2,048 PTE words per row, and 163 rejected
oracle corruptions. The original `RETURN STATE PASS`, return to the menu,
subsequent `h` command, all three ANSI menu renders, 64 CSR/PMP context fields
and the independent final 262,144-byte DDR oracle passed. Final owner drain
is **one empty snapshot across 18 categories**, not two consecutive snapshots.

Execution used one cold seed followed by 96 complete DUT/host checkpoint
resumes under the same executable, input binding and lineage. The final audit
verified every completed chunk's artifact hashes and cycle continuity. Two
attempts with unknown exit status remain preserved; they are not counted as
completed work. The separate short fresh-process equivalence and malformed
checkpoint tests qualify this exact-ABI continuation mechanism, not general
checkpoint portability. No guest reset occurs at the chunk boundaries.

The following values come from this menu's independent `rows.csv`, with its
own sequential cache and translation state. They do not replace the standalone
WRITE20/COPY21 measurements or the same-source MRU OFF/ON comparison above.

| 128-KiB streaming menu mode | WRITE kernel / flush ticks | COPY kernel / flush ticks |
|---|---:|---:|
| S-Bare | 215809 / 10694 | 383555 / 5607 |
| Sv39, 4-KiB pages | 207561 / 10674 | 497145 / 5567 |
| Sv39, 2-MiB pages | 205962 / 10663 | 493923 / 5565 |

The terminal audit is `bootrom-full54-checkpoint-prep-r3/final-audit-r1/receipt.json`,
SHA256 `ce548188def3b7515e0e4e941c812b8153457d7e9867e9c81e373254ee7728e8`.
Its postprocess summary is SHA256
`dd13d9d19e82c37ed82d059058c0bed394e4ca892234d3173e1bf1808daf6f09`;
the complete 54-row CSV is SHA256
`6a64fb5ad522de4908673c58f174193334bb6425a80aabe7cdabf9ab41eb3b38`.
The interrupted 6a26 execution retains its original incomplete status. It is
not relabeled to the completed 9483 run. Menu payload rates use the specified
100-MHz TIME scale; sparse access rates are not DDR wire bandwidth, and this
run does not expose a per-row TLB miss counter.

## Optional translation-capacity checks

The supported D-TLB sizes are 4, 8, 16 and 32, with **8 still the default**.
A fresh same-source 9483 D16/D32 pair held the complete C+MRU profile fixed
apart from `--data-translation-entries`. Its 17-page alias case took 65638
versus 5075 ticks and its 32-page case 123430 versus 8915; Bare and at-most-16
page cases were unchanged. The original formal S-mode 32-page READ case11
took 243726 versus 14998 ticks, with complete data, fault, return and negative
checks. The native D16-to-D32 delta is 3313 reachable scalar bits and zero
array bits, with fixed memory contracts preserved. This is an optional
capacity-sensitive result, not a general Linux gain. No N33 alias boundary or
complete D32 54-case menu was run.

To select that D32 experiment, replace only `--data-translation-entries=16`
with `--data-translation-entries=32` in the GSIM command, or the corresponding
space-separated value in the native command. All other options stay fixed.
The D32 summary is `final-dtlb32-combination-r1/summary.json`, SHA256
`d1bf31f0ea2c260f607d160027ee6e1a07e8eb64e6edd002b39646a234c9cc7c`.

The minimum D4 parameter also passed a fresh 9483 component gate: 10 walks,
4 hits, replacement wrap, flush, permission/peek checks, 17 accepted requests
and responses, and a rejected independent address mismatch. Its receipt is
`dtlb4-focused-final-r1/receipt.json`, SHA256
`0a9a33ad614ab150d7c116a3f374b042b87e081fffcb705e40267cb6ff022d45`.
This is component coverage, not a D4 full-CPU performance result.

## Remaining boundaries and archived evidence

The controlled Sv39 late-cancel/ROB-reuse gate remains blocked and unexecuted.
There is no mapped/routed PPA, FPGA-board bandwidth, general Linux performance,
or simultaneous Sv39 IRQ/DMA qualification in this publication. Existing
MAC/JTAG source is retained without a new board-level networking claim. The
H extension has not been implemented or advertised through `misa.H`. The lost
physical posted-store merge/WB-reservation work remains outside this source;
its former results are not inherited by the reconstructed implementation.

Complete binaries, generated models and large logs stay in immutable evidence
archives, outside the publication diff:

| Evidence | Library ID | Archive SHA256 |
|---|---|---|
| Complete 9483 source | `libfile_ff668136792081919c29f27c090b008b` | `c7963efa99480f24512904025f24c62fa918f76fda774cc83f00ecce2cddb60b` |
| Fresh C+MRU model, GC and native | `libfile_a19c69675f8481919acb1797b30a6c2d` | `6b90d650738f6a56abc04ef04d12e319805f375e6a2dc2b063092d2ba64d90d3` |
| Five targeted runtime gates, including preserved interruption | `libfile_aaa2ac45026c8191aa27c2e6aeec2faf` | `3ada182552fa46673c372e3623418743ac3f7ae09293e2473d99176e9fe29d0f` |
| Default-OFF native comparison and narrow explanation | `libfile_25032a1731508191850f380228e95da6` | `248021aa48602d2316eca7f57f143990d78801ca756c0814d7616a09243f4fdd` |
| Final 9483 optional D32 model, alias, formal READ and native comparison | `libfile_b14762ddaf588191b1eb7aeec3b54911` | `f35436e28f6903f03a38904815f7a314924fd8a54258b16c9df9e39eff1ca42a` |
| Final 9483 D4 minimum component gate | `libfile_a5be943ebda8819182895e614fd5ea29` | `2484f68f062e7b547e7f804ef9cbc8b263be4d1bd9c4712e9ab478d87372971e` |
| Exact-ABI checkpoint mechanism and guarded launcher | `libfile_12105c3a638c81919db0899445f57ae5` | `f8ff7915967dd1a611b2e4f98a0039d1bb816118bbf64ffb9d6cb23abe77d62c` |
| Complete D16 original ROM 54-case run, all checkpoints, audit, CSV and ANSI menus | `libfile_915e25b1fed4819194d4858d812fdce4` | `358ff6de68d876de02dbd007fee6dd465eaed24abd49b2462f21d7adcb176ce8` |

The compact historical PF index preserves the exact SHA, byte size and archive
location of its original full document. It has no code consumer; this is a
documentation packaging change, not an alteration of the historical proof.
