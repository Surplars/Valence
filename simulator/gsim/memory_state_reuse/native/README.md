# Native cost of two independent default-OFF state-reuse flags

Actual native lowering confirms the combined candidate removes **4,800 reachable scalar register bits**, with unchanged RAM contents, geometry, ports, and hierarchy. This is a declared-state measurement, not a mapped LUT/FF/BRAM/DSP or timing result.

| Index reconstruction | Shared address state | IntegerBackend scalar bits | Production scalar bits | Reduction | Backend reduction | Production array bits |
|---|---|---:|---:|---:|---:|---:|
| OFF | OFF | 25,074 | 127,785 | 0 | 0% | 735,863 |
| ON | OFF | 24,690 | 127,401 | 384 | 1.531% | 735,863 |
| OFF | ON | 20,658 | 123,369 | 4,416 | 17.612% | 735,863 |
| ON | ON | 20,274 | 122,985 | 4,800 | 19.143% | 735,863 |

The combined reduction is 3.756% of the production scalar declaration total. The two flags remain independently default OFF. Functional lifetimes and stale-owner behavior require the separate actual focused DUT gate; the 22 passing pure configuration checks do not substitute for that gate.

## Exact retained and removed state

- Index ON removes exactly 64 six-bit queue token-index registers, 384 bits. Every one of the 64 full-width token tags remains: 4,096 bits in every mode.
- Address ON removes exactly 64 61-bit loadBeat registers and 64 eight-bit loadLanes registers, 4,416 bits. Existing storeAddress remains 4,096 bits and storeByteLanes remains 512 bits.
- Combined ON removes exactly those 192 scalar declarations, with zero added declarations and zero width changes. IntegerBackend scalar declarations are 2,640 → 2,448. The full per-field inventory and differences are retained.
- All 484 reachable internal instances and module ports match. All 100 reachable RAM instances retain identical helper bytes, geometry, actual ports, and latency. The ten fixed-storage contracts match exactly.
- OFF/OFF is byte-identical, module for module, to the saved qualified preparation-priority ON native export. No wrapper-name accommodation, module alias, expression normalization, or unsupported alias was required. Every ON treatment changes only IntegerBackend.sv.
- Three BUFGCE instances and one blk_mem_gen_0 ROM are explicitly excluded from internal declared-state counts; their paths, wrapper bytes, and multiplicities remain unchanged.

## Selection-network tradeoff

Shared address state adds an ordinary-load write alternative to each existing storeAddress/storeByteLanes row. Native RTL has three conditional writer branches per row instead of two, with the existing two preparation writers retaining priority. The new branch uses the final LSU ordinary-load class, its row decode, the canonical beat with three zero low bits, and actual byte lanes. The removed load-only registers previously had their own write branches. No RAM read/write port is added.

| Mode (index/address) | Backend scalar declarations | Continuous assigns | Ternary marks | Local equation nodes | Backend SV bytes | Byte delta |
|---|---:|---:|---:|---:|---:|---:|
| OFF/OFF | 2,640 | 111 | 1,392 | 2,826 | 1,749,312 | 0 |
| ON/OFF | 2,576 | 111 | 1,384 | 2,826 | 1,721,065 | −28,247 |
| OFF/ON | 2,512 | 111 | 1,392 | 2,764 | 1,761,042 | +11,730 |
| ON/ON | 2,448 | 111 | 1,384 | 2,764 | 1,732,795 | −16,517 |

The address-only SV grows by 11,730 bytes despite removing 4,416 scalar bits. The bounded assignment dependency depth remains 20 and the local equation graph is acyclic in all four exports. These are textual/graph structure indicators: equal depth and ternary counts do not establish equal physical mux cost, critical-path delay, or LUT count. In particular, the 4,800-bit state saving cannot be directly subtracted from LUT usage.

## Binding and execution

- Hardware candidate: `4d3f1b57643ac9e59d379192e25e03372f6bd2c5`, following index-only `2a2a3c858b484b8a69a1c5323f874c15a4e05762` and qualified baseline `0da2a2258a202f911a1f2ad7a1dd6ed18098a5af`.
- Exact compiled source: `3969476cad0775f5b6de405502a4e6822f566311`, tree `8cdf1a66d2893d6a96f29ecc2fcac731fa885775`. Its only differences from the hardware candidate are two test files. The exact baseline-to-final incremental source bundle, binary format-patches, and 2,383-file source inventory are included; the baseline dependency is identified below.
- One shared production/test Scala compile, followed by 22 passing tests in six affected pure configuration suites. No second production/test compile. The bound classpath was handed back for the separate focused DUT gate.
- Four independent ordinary FpgaNextSocTop constructions and native lowerings, sequentially, on the same ROB64/PRF64/D16/LSU4/DMA4/frontier/LRU/preparation-priority full profile. Actual constructors are bound for six core, three cache, and two DDR instances, with 142 core fields, 34 profile fields, and 11 cache fields. Only the two requested flags and experiment labels vary.
- Pinned existing toolchain and firtool 1.135.0; no installation, download, Clang, GSIM, Vivado, or synthesis in this task. Mill compilation used pinned Azul 21.0.10. Every runtime class/jar, tool, source, full profile, constructor report, FIR, and emitted native file is hashed.
- All ten stages passed. Native stage duration was 10.3–11.3 seconds each, with approximately 427–431 MiB observed process-group RSS. Host runtime/memory is not hardware performance evidence.
- The original immutable runner had a 650 MiB free-space guard. The coordinator required 700 MiB during the live run; direct disk observations remained above 1.3 GiB, including 1,374,519,296 bytes at native completion. An attempted independent process guard could not see another exec session's isolated process namespace; it was not active and is not claimed as a verified 700 MiB automatic guard. See the disk-observation receipt.

## Evidence and reproduction

`analysis/summary.json` is the compact machine-readable cost table. `analysis/cost-details.json` contains exact removed field names, widths, declaration counts, and all per-row writer counts. `analysis/*-census.json` contains the complete reachable hierarchy and RAM/port census. `analysis/*-comparison.json` and `analysis/diffs-*` preserve literal differences. `analysis/negative-controls.json` records five fail-closed parser controls. `analysis/structure-indicators.json` and `analysis/*-control-graph.json` preserve bounded combinational structure evidence.

Each `execution/<mode>/` retains the full raw native SV, the losslessly compressed input FIR, full configuration, actual construction audit, and export receipt. `execution/receipt.json` retains exact commands, completion status, logs, and resource-sample hashes. `execution/runtime-binding.json` binds the one shared compilation. `source-freeze.json`, `plan.json`, and `evidence-manifest.json` bind the source, tool, helper, and result bytes. `historical-baseline/receipt.json` and `historical-baseline/profile.json` identify the original native comparison; its complete RTL is identical to the fresh OFF/OFF copy included here.

Source restoration requires qualified baseline Library item `libfile_0127f1e355788191938e13aaa7def060` version 0 (5,325,692 bytes; SHA-256 `fde76c13670b0e260f4489613b8529a15c4fc8b13e9956505b77693d2a3ba02c`). It supplies prerequisite commit `0da2a2258a202f911a1f2ad7a1dd6ed18098a5af`. Fetch the included `source-from-0da.bundle` into that repository and check out `3969476cad0775f5b6de405502a4e6822f566311`; `source-from-0da.patch` is an additional binary format-patch representation. The previously persisted functional package is `libfile_d5ccbfbd80548191a5a65d4e9aec96f8` version 0 (5,917,430 bytes; SHA-256 `ba11f84bde18ce8f9a1793ff94b9fc3585461b0cc35d525e01a447b3376e81e6`). These exact upstream identities were supplied by the coordinator and were not redownloaded by this worker.

For a new workspace, restore the exact compiled commit as above and use the same pinned toolchain; the runner's absolute paths must be rebound to that workspace and a fresh plan/execution generated. Its `prepare` action is source-only. `run --slot-granted` is permitted only after the coordinator grants the Java/native slot. The audit is Python-only. Existing receipts must never be overwritten to describe a fresh run.
