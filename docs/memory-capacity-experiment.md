# Opt-in four-slot memory-capacity experiment

## Result (2026-10-07)

**PASS, bounded functional and same-clock cycle experiment.** The new explicit
`staged-fetch-turnover-mlp4` profile derives exactly
`timingParams("staged-fetch-turnover").copy(memoryEntries = 4)`.
Every existing profile and default remains unchanged. This is not a default
replacement, a bitstream, a physical timing/resource result, or an official
CoreMark score.

The exact matched RV64IMC/lp64 CoreMark image improves from **486605 to 472290
raw guest ticks**, a **14315-tick / 2.9418% reduction**, or **1.03031× same-clock
throughput**. Inclusive ROI cycles are **486606 → 472291**. All **360528** retired
PCs are byte-identical and all CRC/architectural UART text matches; only printed
ticks, elapsed time and derived rate are excluded from the UART comparison.

The original 19198 capacity-excluded observations justified testing the change;
they were not predicted savings and are not a causal explanation of the measured
14315-tick difference. The candidate does not enable or generalize the two-slot
owner ledgers. No new selected-capacity exclusion count is claimed.

## Configuration and derived capacity

Pure Scala checks prove full parameter equality against the selected profile
with only `memoryEntries` changed, both at timing-profile and RV64GC/2GiB board
configuration boundaries. The uncompressed bare-core fixture also has exactly
this one-parameter difference between its two variants.

Fixed: two-wide rename/issue/commit/completion, ROB16, PRF48, 64-bit tags,
predictor32, StoreBuffer write entries2, disabled registered load-issue forwarding
and load-completion bypass, selected fetch turnover, I-cache32 lines/2KiB/2ways,
current two-way D-cache, RV64GC/full F/D, 100MHz, UART460800 and DDR2GiB.

Existing parameter coupling also changes:

| Physical structure | Baseline | Candidate |
|---|---:|---:|
| LSU slots | 2 | 4 |
| Registered LSU request FIFO | 2 | 4 |
| LSU response-owner FIFO | 2, 1-bit owner | 4, 2-bit owner |
| StoreBuffer physical-response owner credits | 3 | 5 |
| StoreBuffer write entries | 2 | 2 |

Strict emitted-FIR checks verify actual slot instances and all these RAM widths
and depths, rather than trusting the profile name. Negative parser tests reject
incorrect geometry and each deliberately corrupted capacity.

Unchanged downstream capacities: translation ingress2, translated8, checked2,
translation owner8, return buffer2, mapped/platform owner8, cache-hit response2,
and one active cache miss. There is no additional MSHR or concurrent-miss claim.

## Observed live occupancy

Passive static scalar leaf taps avoid dynamic-vector BoringUtils generator
problems. Live counts include occupied LSU slots, including their operation and
response lifecycle; they are not counts of concurrent misses.

| Live slots | Candidate ROI cycles |
|---|---:|
| 0 | 177980 |
| 1 | 192889 |
| 2 | 68326 |
| 3 | 30678 |
| 4 | 2418 |
| **Total** | **472291** |

Separately, the independent bare-core accepted-request oracle reached four
outstanding loads in both the independent-load and younger-load-bypass cases.

## Short correctness and performance checks

All hardware checks used the standard GSIM generator and Clang ASan/UBSan flags.
No Verilator, full GSIM, long Linux, Vivado, synthesis, implementation or push ran.

- Four pure Scala configuration/isolation tests and ten parser/geometry tests.
- Exact selected-profile backend: three event-driven seeds; four accepted/live
  old loads before a real delayed branch redirect; three same-ROB-index/new-tag
  reuses before any old reply; 12 stale errored replies discarded; no stale
  completion, exception or retirement; 196 full-owner witnesses; request and
  commit backpressure; all credits drained. Corruption negative rejected.
- Selected four-slot core/NEMU timing-memory check: 50 programs, 20986 commits,
  2312 loads, 2622 stores, 144 redirects. Existing independent memory state,
  request stability, errors and precise non-RAM access checks retained.
- Selected pipeline recovery: 11 programs, with held-lane/other-lane progress,
  older-branch resolution and ALU-forwarding witnesses.
- Six focused independent-load, younger-bypass and same-address/overlapping DMA
  replay cases; NEMU register-corruption negative rejected.
- StoreBuffer write2/physical-owner5: six seed/latency runs. Every delayed case
  reached five pending responses and two outstanding writes. Guaranteed-write
  error and read-value corruption negatives rejected.
- One RV64GC/2GiB candidate board model reused for matched CoreMark, short DDR
  read/write/copy/chase, and actual RV64GC context smoke. The context check saw
  all 32 FPRs, one S-mode ecall and compressed advances; injected anchor/context
  corruption was rejected. This is short context-mechanism coverage, not Linux
  scheduling or broad numerical FPU throughput.

### Same-payload bare-core throughput

These are synthetic ideal-instruction-device/RAM results, separate from board
CoreMark. Each retirement is independently checked against NEMU.

| Fixture | RAM latency | Baseline cycles | Candidate cycles |
|---|---:|---:|---:|
| Independent ALU | 1 | 515 | 515 |
| Dependent ALU | 1 | 1027 | 1027 |
| Dual dependency | 1 | 515 | 515 |
| Not-taken mixed | 1 | 132 | 132 |
| Direct jumps | 1 | 132 | 132 |
| Taken loop | 1 | 147 | 147 |
| Load/use | 1 | 135 | 134 |
| Memory/ALU mix | 1 | 391 | 391 |
| Compiled sum | 1 | 1459 | 1459 |
| Load/use | 12 | 457 | 235 |
| Memory/ALU mix | 12 | 1015 | 1006 |
| Compiled sum | 12 | 1848 | 1666 |

### Short DDR comparison includes a regression

The same selected turnover/32-line baseline and byte-identical DDR/GC payloads
show a mixed result; these are synthetic AXI timings, not measured board rates.

| DDR fixture | Baseline ticks | Candidate ticks |
|---|---:|---:|
| Read, cold start | 5684 | 4883 |
| Write plus flush | 8112 | 8115 |
| Copy plus flush | 13744 | 13735 |
| Pointer chase | 4012 | 4012 |

The **write test regresses by 3 ticks (0.037%)**. No tuning or extra change was
made to hide it. The RV64GC context-smoke duration stays at 32177 cycles.
Baseline raw logs are in `build/gsim/frontend-perf-combined32-20261007/`;
matching payload hashes are recorded in the baseline/candidate receipts.

### Preserved failed fixture attempt

The first new cancellation fixture timed out at cycle2000 because it held
`commitEnable=false` before launching the replacement load. Production memory
issue correctly requires `commitEnable`; all four old responses had already
been canceled/discarded and all memory credits were drained. This was a fixture
scheduling deadlock, not a production fix. The revised fixture leaves commit
enabled until replacement request acceptance, then holds retirement before its
withheld response. Every original ownership/cancellation witness remains.
The generated hardware/model and all production/Scala sources were unchanged;
only the C++ test was relinked against the same sanitized model object. Failed
log/executable/harness, diagnostics and the accepted hash-verified reuse proof
are retained under the r1 cancellation directory.

## Physical acceptance remains open

At equal clocks the measured throughput gain is 3.031%. Break-even requires
`candidate_frequency / baseline_frequency > 472290 / 486605 = 0.970582`:
only about **2.94% achieved-clock loss** can be tolerated. Larger request and
completion arbiters, four-way payload/owner muxes, empty/serial reductions,
completion/replacement-to-ready paths and cancellation fanout remain unmeasured.
No prior frontend/netboot implementation result qualifies this candidate.

Keep this opt-in pending a separately authorized, matched physical comparison
with LUT/FF/BRAM, timing and effective-throughput accounting. No second knob was
tuned to improve the measured result.

## Reproduction and evidence

Fresh complete bounded run (cloud toolchain):

```sh
source scripts/cloud/env.sh
python3 simulator/gsim/memory_capacity.py --tag UNIQUE_TAG
```

The accepted run reused only the byte-verified cancellation model after the
fixture-only repair; its command is captured in the runner log:

```sh
python3 simulator/gsim/memory_capacity.py --tag 20261007-r2 \
  --cancellation-proof build/gsim/memory-capacity-20261007-r1/cancellation/reuse-proof.json
```

- Combined receipt: `build/gsim/memory-capacity-20261007-r2/receipt.json`
  - SHA256 `aef31c2515a63f6260c25dc3d0c6e474f94e1ece28e901500c9cf21dd9e9632c`
- Reused board-model receipt: `build/gsim/frontend-perf-mlp4-20261007-r2/receipt.json`
  - SHA256 `a90b7d43ee7629f4d28fa341f0b27dc0ac4e0ca25922c27ea2347ca1144eaab1`
- Accepted baseline: `build/gsim/frontend-rvc-pair-20261007/receipt.json`
  - SHA256 `d3a7bb26514a243423484f4774ce321572f959b6a59f8b2c2a39f7fb28c72570`
- Exact BIN: `build/gsim/coremark-rvc-20261007/rv64imc/coremark_board.bin`
  - SHA256 `05b9a01d74a03389433ef942fef7056827331be18a91e0795f6456cee51fdac5`
- Exact ELF SHA256 `5aed635e1e8678e0951de2c27ef20eed4051bc6f13a8025da6effee993e4ec26`
- Ordered ROI PCs SHA256 `142a5aafefa1eabaa2b76f5d7c42baa1cb31de1c6fd95384652ea4e936aa84fa`
- Inclusive ROI `0x80200114..0x80200122`.

Receipts contain source/config/model/executable/payload hashes and raw logs.
Starting and candidate source snapshots, delta patch, complete regression
artifacts and runner logs are archived in
`/workspace/shared/valence-mlp4-20261007/`. The prior frontend ZIP remains frozen.
