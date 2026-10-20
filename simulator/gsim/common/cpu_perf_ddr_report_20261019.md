# DDR-resident exact-body result, 2026-10-19

Both native CPU positive runs passed, followed by one A1 final-pattern negative rejection. No hardware changes were made.

## Same four retired-PC windows

CPU and fabric counts are real independent rising edges. Each cell is ROM → DDR. Work is identical: 768/608/1280/1 retired instructions; 256/256/512/0 loads; 0/0/512/0 stores. Both marker instructions are excluded from retired counts.

| Profile | Window | CPU edges | Fabric edges | DDR code AR / R beats | DDR data AR / R beats |
|---|---|---:|---:|---:|---:|
| I1 | 256 dependent hot-data loads | 9279 → 1347 | 7734 → 1123 | 1 / 8 | 0 / 0 |
| I1 | 256 eight-way independent hot-data loads | 5819 → 1051 | 4850 → 876 | 2 / 16 | 0 / 0 |
| I1 | 4 KiB cold-data copy retirement | 16875 → 9023 | 14065 → 7520 | 2 / 16 | 128 / 1024 |
| I1 | Final FENCE.I and resumed marker | 8159 → 8306 | 6801 → 6923 | 1 / 8 | 0 / 0 |
| A1 | 256 dependent hot-data loads | 2035 → 2035 | 5088 → 5087 | 1 / 8 | 0 / 0 |
| A1 | 256 eight-way independent hot-data loads | 833 → 815 | 2082 → 2038 | 1 / 8 | 0 / 0 |
| A1 | 4 KiB cold-data copy retirement | 6652 → 6673 | 16630 → 16682 | 2 / 16 | 128 / 1024 |
| A1 | Final FENCE.I and resumed marker | 1805 → 1826 | 4512 → 4565 | 1 / 8 | 0 / 0 |

## Useful copy throughput: contiguous endpoints

This primary calculation runs from copy_begin retirement to drain_end retirement. It includes the one-CPU-edge gap between copy_end and drain_begin and completion/refetch of the final fence. It excludes loader, initial code transfer, and pointer-data warm-up. The original ROM result is recomputed with exactly the same endpoints; it is not mixed with the older two-window-sum denominator.

| Profile / placement | CPU edges | Fabric edges | Useful bytes / fabric edge | Simulated MB/s |
|---|---:|---:|---:|---:|
| I1 ROM | 25035 | 20867 | 0.196290794 | 49.073 |
| I1 DDR | 17330 | 14444 | 0.283577956 | 70.892 |
| A1 ROM | 8458 | 21145 | 0.193710097 | 48.428 |
| A1 DDR | 8500 | 21250 | 0.192752941 | 48.188 |

MB/s is merely 4096 bytes divided by the simulated elapsed time: I1 CPU period 3334 ps, A1 10000 ps, shared fabric 4000 ps. The I1 period is the actual integer simulation period, not an assumed exact 300 MHz. These are synthetic digital values, not board measurements or bus peak bandwidth.

For comparison with the earlier sum-only convention:

| Profile / placement | Two-window CPU sum | Two-window fabric sum | Inter-window CPU / fabric gap |
|---|---:|---:|---:|
| I1 ROM | 25034 | 20866 | 1 / 1 |
| I1 DDR | 17329 | 14443 | 1 / 1 |
| A1 ROM | 8457 | 21142 | 1 / 3 |
| A1 DDR | 8499 | 21247 | 1 / 3 |

## What changed and what did not

- I1 dependent and independent windows improve by 6.889× and 5.537× in CPU-edge count under the new execution placement; the copy-retirement window improves 1.870×. Contiguous useful-copy rate increases 1.445×. This is a ROM-to-cacheable-DDR execution-condition effect on the same hardware, not a CPU optimization.
- A1 dependent count is unchanged at 2035. Independent changes 833→815, copy 6652→6673. Contiguous useful-copy rate changes by approximately −0.49%; the experiment does not establish an A1 improvement.
- Final drain does not improve: I1 8159→8306 CPU edges; A1 1805→1826. In the DDR run, actual fence retirement occurs after 7646 I1 CPU / 6373 fabric edges, or 1797 A1 CPU / 4492 fabric edges from drain_begin. Fence-retirement-to-resumed-marker intervals are another 660/550 for I1 and 29/73 for A1. These intervals are measured; their internal causes are not partitioned into exclusive stall shares.
- I1 cacheability begins at 0x80200000, so the original 0x80000000 instruction stream was outside its cacheable range despite warm data. A1 has its own SynchronousFetch packet cache in front of its line-cache/ROM path. The very different placement sensitivity must not be generalized from I1 to A1. See the README for source anchors; this explains the plausibility of the difference but is not a measured internal stall attribution.
- First DDR execution is naturally cold after the loader FENCE.I. I1 adds code AR 1/2/2/1 within the four windows; A1 adds 1/1/2/1. No extra I-cache warm-up or repeat was introduced. Code traffic between markers is also retained in cumulative checkpoints.
- Both runs have exactly 192 completed data read transactions and 64 real data B completions. The 4 KiB copy reads 64 source lines plus 64 destination allocation lines; raw DDR read bytes are therefore not the same as useful copied bytes.
- Loader code stores and six code-line writebacks are outside all ROIs. At loader-fence retirement, I1 code AR/R is 6/48; A1 is 7/56. Both code AW/B are 6/6, and all 360 DDR bytes match the original. The extra A1 pre-entry code-region read is not assigned an internal source from addresses alone.
- Final totals are I1: 13 code AR/104 code R beats plus 192 data AR/1536 data R beats; A1: 14/112 plus 192/1536. Both have 70 AW/B and 560 W beats total: six code lines plus 64 destination lines.
- The exact original 360-byte body is embedded and verified byte-for-byte; every DDR-retired instruction is checked against the corresponding original word. Markers/trap/done PCs are shifted by 0x200000. Three original data apertures, cache/home geometry, clocks, host queues and service-law source are unchanged.
- The extra code traffic changes ticket indices and global edge phase. Same AR/AW/B service rules do not mean identical latency for each individual original request. Those state differences, cold fills, and finite code/data placement are retained, not normalized away.
- No fetch/LSU stall shares, timing closure, board performance, peak L1/LSU rate, steady-state DRAM rate, or reason to change the CPU/LSU follows directly from the old ~0.22 B/cycle figure or these finite tests.

## Validation, bounds, and receipts

Frozen source HEAD: d2b2d4f7aa83bd9479424437d596e9a0e905159c. Unchanged hardware compilation identity: c7c54336f730fe24a719cdda4ff8f84856ababa0. Both source/class/artifact chains were rehashed before and after new positive execution. Existing assertion-preserving A1 sv2v output was reused. No Scala compile, RTL emission, conversion, Vivado, Verilator, tool installation, Linux, or full-ROM run was performed.

Original body SHA-256: `31193326af006e2ca93f160d4f4b5d1f07137486301eee84f1b5f6f96fd782e8`.

Independent checks passed: four exact retired workloads; external 45-word code image at loader fence, DDR entry, and final completion; each retired DDR instruction; AXI-ID ownership/classification reconciliation; real B and accepted RLAST completion; final maintenance/home quiescence; 512 source and 512 destination words. The A1 wrong-pattern negative changed only expected final word 31 and failed specifically at COMMON_PERF_FINAL_PATTERN_ORACLE after the real final drain. It used the same compiled model and did not print the positive PASS token.

- I1 rom: `evidence/common-reset-i1-perf-r1/receipt.json`
  SHA-256 `0cdb91851f00e487989c933072ddf03f470fe2d0fc76f14f16133e3e39b66400`
- I1 ddr: `evidence/common-reset-i1-perf-ddr-r1/receipt.json`
  SHA-256 `93687f8b3d986975ea304734e0599e16a092a1049f9578b3f8a130315d5b7f60`
- A1 rom: `evidence/common-reset-a1-perf-r1/receipt.json`
  SHA-256 `1b9596da7cd5e44397bbdf59d36f084098d1aa556658d6f18e5ab48fb5b7f695`
- A1 ddr: `evidence/common-reset-a1-perf-ddr-r1/receipt.json`
  SHA-256 `6c086438414f8755b85b5ceafbf072fa88c95c4122c92ad7e57773792062a40b`
- A1 negative: `evidence/common-reset-a1-perf-ddr-negative-r1/receipt.json`
  SHA-256 `0d4bf5edad10904a87f2f6c52e5a7694dd5ddfdc3528515e79d3045bebebba1e`

Each invocation has a 600-second total command budget and a 4 GiB disk floor. Fresh positive evidence directories and the single negative directory preserve all logs; no unexpected failures occurred; the intentional negative failure and all logs are retained. The new worktree is sparse and only adds files under simulator/gsim/common. Full commands, per-command time/RSS/minimum-free-disk, fixture/tool hashes, and exact input binding are in the receipts. See cpu_perf_ddr_20261019.json for machine-readable figures.

Post-run static audit reverified every recorded artifact/fixture and all production source/class/RTL hashes. I1/A1 generated testbench and loader binaries are identical. The A1 positive and negative complete window/begin/fence log records match exactly. Actual invocation wall times were 95.19 s (I1), 113.39 s (A1), and 110.52 s (negative). The minimum observed free space was 4,863,201,280 bytes, above the 4 GiB floor. Total new evidence is 65183572 bytes, plus the small sparse worktree, below 100 MiB.
