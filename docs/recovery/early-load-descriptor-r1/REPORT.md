# Default-off early-load descriptor experiment

## Status and source

`earlyLoadPreparationDescriptor` is an opt-in, default-false constructor flag. It reserves only ordinary-load metadata before operand readiness; the existing registered Q-to-PRF/AGU-to-S cut, stores, architectural launch permissions, token/epoch cancellation and PRF interfaces remain. Ready work can preempt waiting Q. The flag requires the registered descriptor, owner-local readiness, parallel ready updates and LVT PRF; release presets and the 179/96 parameter products are unchanged.

Original experiment: `d913657c3721c6b4a528b2b5b7ac170fe9513c54`; robust valid-D factor: `dc821f169be8506c7ac29f2236f08cd9a775935f`. The source overlay targets published dev `67565b63178700616550d401a32e21721ede9437`, tree `472b29f17c32459ab15a2147b5103cf82390fb2a`, staged using tree-equivalent local base `03bca865bd349da945da812a3f3522d3f917a720`. Existing descriptor fixtures were already on that base. The overlaid `src` tree and reused fixture bytes match the qualified experiment; packaging validation did not rerun models or constitute new dev-branch runtime qualification.

## Measured benefit, bounded scope

On the matched native-port 100 MHz service model, the same warmed 64-byte pointer ring with 512 retired loads takes **4096 → 3584 cycles**, with dependent accepted LSU-start gaps **8 → 7**. Independent loads remain **762 → 762**. Architectural work/hash/checksum matches, with zero ROI cache misses and DDR traffic. The existing registered descriptor remains enabled; this does not restore the descriptor-OFF independent result or explain the historical full board regression.

A separate one-iteration, 2,000-byte CoreMark diagnostic on the same two reused models takes **579,035 → 569,968 guest ticks**, 9,067 fewer (1.5659%). All five CRC checks pass; the 345,530 retired instructions and PC/instruction hashes match, with no UART MMIO in the ROI. Guest compiler: GCC 14.2, `-O3 -march=rv64im_zicsr_zifencei -mabi=lp64`. The duration is below the official minimum, so this is **not a CoreMark score**, the historical GCC 13.2/3,000-iteration board image, or a physical board prediction.

These measurements belong to V1. The robust factor was validated as an equivalent next-state expression rather than rerunning the board models or relabeling old measurements.

## Functional and equivalence evidence

The robust selector passed 1,048,872 independent checks and three mutation negatives. Sixteen real-backend scenarios plus three architectural-oracle negatives passed with ASan/UBSan and live equality/lifetime assertions. Coverage includes producer completion while waiting, exact ready-token Q replacement then S preparation, physical/ROB reuse, redirect/IRQ/reset, transfer/refill, store fallback/priority, faults and system drain. A waiting-Q SATP case proves exact-token cancellation and no stale recapture/transfer/start across an actual authorization epoch **5 → 6**. Waiting-Q FP epoch and exact wake/epoch coincidence were not separately forced.

The retained default-off selector passed 1,148,866 checks; lifetime mutation checks reject changed mapping, range, reservation, invalid producer write and ready-source rewrite. The narrower direct-backend fixture uses `backendNaturalAlignedPmp=false`; the separate native-matched board audit verifies PMP=true. These component cases do not replace full-system qualification.

The robust factor is `F || ((qR || qW) && !(qR && sGo))`, where F is fresh-valid and sGo is the original resident-transfer condition. Actual-native SAT proves it equals the original next state without assumptions, including arbitrary overlapping ready/wait boundaries. The actual native killed-owner ⇒ common-clear implication is also proved; capture/transfer/payload keep their original distinct kill guards. The initial simplified factor failed the stronger unrestricted-state gate and remains preserved, not qualified.

## Mixed mapped result: no STA claim

One identical-policy, no-wide-LUT map compared the same **1,359 + 78 semantic outputs**, including all descriptor/staging controls and PRF address/data auxiliaries. Primitive-depth values are structural counts, not delay estimates:

| Path or observation | Repair ON | V1 early Q | Robust factor |
|---|---:|---:|---:|
| owner-ready1 → descriptor Valid | 12 | 19 | 12 |
| owner-ready2 → descriptor Valid | 12 | 19 | 13 |
| descriptor-Q → descriptor Valid | 14 | 20 | 15 |
| ready1 → descriptor payload enable | 18 | 19 | 17 |
| ready1 → staging controls | 19 | 19 | 18 |
| Q/S ordinary maximum | 24 | 23 | 22 |
| cache global maximum | 32 | 33 | 35 |

The selected union uses **28,922 → 28,371 LUTs (−551)**; CARRY4 remains 717. Four PRF address observations worsen **1 → 2**. Unrelated cache generic cones are byte-structurally unchanged but reshaped by the shared mapping; their **32 → 35** result is still a residual, not a blanket nonregression claim. `freshAge` no longer reaches actual descriptor Valid D/SRST.

Full-native inventory remains 91,586 Q bits and 733,350 memory bits; descriptor payload/valid stays **275+1**, with **12 PRF reads and eight issue payload groups**. The mapped export is a combinational selected union, not a full-chip FF/RAM implementation. There is no routed timing, ns, Fmax, new 100 MHz qualification, Vivado/bitstream, board release, Linux or full regression claim. The frozen +0.006 ns margin does not transfer.

## Portable focused runner

The seven added C++ files are byte-identical to the qualified final fixtures. Existing `simulator/gsim/preparation_descriptor/*.cpp`, the independent `ready_store_query77_reference.h`, and the default-off selector harness are reused directly; no copied oracle or generated model is included.

Run only when focused execution is intended, using explicit installed tool paths and two disjoint fresh directories:

```sh
python3 simulator/gsim/early_load_descriptor/run.py \
  --repo "$PWD" --mill "$MILL" --gsim "$GSIM" --cxx "$CXX" \
  --models "$FRESH_MODELS" --out "$FRESH_RESULTS" --suite all
```

`--suite helpers` emits/checks the early selector, lifetime checker and retained default-off selector. `--suite backend` emits/checks the focused backend, five new waiting-load cases, eleven retained cases and three negatives. The runner serially emits, generates, compiles and runs only these affected models; it does not emit the board/native top, run CoreMark, download tools or map hardware. It refuses existing output roots, hashes source/tool inputs across stages and never reuses old generated objects. Each command has a configurable 600-second timeout with process-group cleanup. It does not implement the archived aggregate-RSS watchdog; use an external memory limit when reproducing that resource envelope. Java/cache/tool environment is caller-provided.

Dependencies: Python 3; the repository Mill/JDK environment; pinned GSIM; a C++20 compiler with ASan/UBSan (qualified with clang++ 19). Scala entries are `EarlyLoadDescriptorGsimMain`, `EarlyLoadSourceLifetimeGsimMain`, `PreparationDescriptorGsimMain`, and `EarlyLoadPreparationBackendMain`. Backend fixtures include the existing `observed_backend.cpp` and `ready_store_query77_reference.h`; the retained case names are listed in `run.py`. Runtime logs/objects/manifests go only to the explicit output paths. This source-only packaging was checked with Python parsing/`--help`, byte/hash comparison and host `-fsyntax-only` against sealed headers; no DUT was rebuilt or rerun.

## Evidence references (separately retained, not bundled)

SHA-256 identifiers bind the archived receipts; large JSON, logs, FIR/RTL, maps, objects and binaries are intentionally absent from this overlay:

- Hot seal, `early-load-descriptor-qualification-r1/native-hot-seal.json`: `20dd6edde14884138691acea5b1ca84c015bc8e688a6f3e1c0180c234f63803e`.
- CoreMark seal, `coremark-diagnostic-early-load-r1/coremark-diagnostic-seal.json`: `878134a5cdbd55f02af9c8b5ee4bcd37273f48ad854ca0eb96e4edf262b93612`.
- Robust focused release, `early-load-valid-factor-r2-robust/functional-release.json`: `09f99cf5f1057c569b4afbc9ce3e051193b5b0c4d7d0e7f02c61075a3dc14d8d`.
- Fresh actual-native SAT log, `early-load-valid-factor-r2-robust/timing-screen-r1/actual-valid-proof/sat.log`: `b27c98129f621d3ea888449098e961ce9aa8bbeaa96877a677000bd611110739`.
- Mapped result, `early-load-valid-factor-r2-robust/timing-screen-r1/RESULT.md`: `b1a99e5b699a5472e8dafdbf1bca875aa1b1b6051207d965e74f0d79a8c9258d`.
- Final mapped receipt, `early-load-valid-factor-r2-robust/timing-screen-r1/final-receipt.json`: `c0ba3fb9b8bd243c18b45442d87d0b5acfa1cf6dbba7b680bff395cd7d9b6a82`.
