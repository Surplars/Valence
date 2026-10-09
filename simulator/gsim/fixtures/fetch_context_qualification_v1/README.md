# Narrow fetch-history context/PMP qualification

Source-only fixture for production `2288c7f008e9d6440e8a28e339da28152b54892a`, host anchor `4cbebc9c5ffc8d7af6220cc513ebf81a16c09145` (descendant host-only commits allowed before a run). The fixed selected whole-board pair has fetch history **ON on both**, LSU4, physical ingress ON, DMA line depth4/yield0 configured but idle. Only older-prefix retirement differs.

## Coverage and preserved recipes

Four fresh harness links, four positive runs, and eight existing negatives, executed sequentially in one granted heavy slot:

- OFF/ON `fetch_permission_smoke.S` + unchanged `rv64gc_board.cpp --fetch-permission`: grant/revoke/restore execute at the same cached compressed gate. The independent guest checks denied nonexecution and exact mepc/mtval; the host checks trap order 9/1/9 and compressed retirement. Existing `--inject-mismatch` negative on each model.
- OFF/ON unchanged `virtual_load_core.S/.ld`, unchanged builder, and unchanged `virtual_load_board.cpp`: Sv39 MPRV/S-effective DATA warm/cold/chase, page alias, precise page fault, wrong-path retirement and MMIO suppression, one allowed LSR read, full signature, ownership conservation and drain. Existing signature/trap/marker negatives on each model.

Compiler, guest and linker arguments follow `cpu_retire_prefix_representative.py`; the virtual link removes `DDR_BENCHMARK_MODEL` just as its approved recipe does. No production, shared harness, guest or oracle source is changed. All four-owner ownership checks use `BACKEND_OWNER_COUNT=4`. The original virtual `lsu_peak` metric counts only slots 0/1; the runner deliberately does not rewrite that passive counter and makes no full-LSU occupancy claim.

The fetch harness's generic printed `context_fprs=32` is not new FPR coverage; its `s_ecall=3` counts all three traps, whose causes are 9/1/9. Sv39 here exercises data translation, not arbitrary instruction-page translation epochs. No additional RV64GC/atomic/NEMU, hot/64KiB/steady, Linux, physical FPGA timing/resource or board coverage. No performance gate.

## Binding

- Explicit OFF/ON receipt paths, pinned exact terminal receipt digests, all 469 current model inputs and all retained source/oracle/guest hashes.
- Reuses the frozen read-only `../cpu_order_replay_history_v1/strict_validation.py` (SHA256 `64159d5bec73d7cfb2569131918a30c5c001a992be0918714469a27d22125bdd`). This dependency must accompany the fixture.
- Strict complete generated file inventory, all object/header/FIR/C++ bytes and all historical model artifacts, commands, steps, success/negative logs and toolchain.
- Pinned approved host compiler, RISC-V GCC/binutils and as/ld/cc1 executable hashes and versions. Explicit clang++ spelling is preserved. Python and compiler/runtime environment are frozen per run.
- Recipes come from source, never executable receipt argv. Model trees may be relocated intact using explicit receipt arguments; historical absolute command paths remain evidence only.
- Fresh outputs only; no resume, no old receipt/executable rewrite, no model elaboration/compilation or setup/install. Final `--audit` rechecks input/artifact/log/command/result closure and A/B architectural agreement.
- Optional `--compress-debug` retains each original freshly linked executable. The existing approved helper verifies executable headers, loadable bytes, program headers, all non-debug sections/symbols, decompressed DWARF, sanitizer symbols and main source symbolization before execution. It does not strip debug or alter model objects.

## Commands

From the repository root, use the already approved cached toolchain:

```sh
export VALENCE_CLOUD_ENV=/workspace/scratch/41e4a649bb60/Valence/simulator/build/cloud-env
source scripts/cloud/env.sh
FIX=simulator/gsim/fixtures/fetch_context_qualification_v1
OFF=build/gsim/fpga-next-board-cpu-fetch-history-on-r1/receipt.json
ON=build/gsim/fpga-next-board-cpu-fetch-history-prefix-on-r1/receipt.json
python3 -B "$FIX/test_validation.py"
python3 -B "$FIX/run_fixture.py" --prepare --off-receipt "$OFF" --on-receipt "$ON" \
  --out build/gsim/fetch-context-prepare-r1 --compress-debug
```

Preparation executes only lightweight provenance and tool-version reads and writes its metadata. It does not build guests, link harnesses or run models. Preparation and execution require distinct fresh output directories.

After one heavy slot is granted:

```sh
python3 -B "$FIX/run_fixture.py" --execute --off-receipt "$OFF" --on-receipt "$ON" \
  --out build/gsim/fetch-context-history-prefix-r1 --compress-debug
```

After terminal success, using the same tool environment and option:

```sh
python3 -B "$FIX/run_fixture.py" --audit --off-receipt "$OFF" --on-receipt "$ON" \
  --out build/gsim/fetch-context-history-prefix-r1 --compress-debug
```

Expected suite status: `PASS_FETCH_HISTORY_CONTEXT_PREFIX_OFF_ON`. This means the four fresh positives and all eight sensitivity negatives actually ran and the exact virtual architectural/ROI traces agree. The historical model RV64GC smoke is separately labeled provenance, not rerun coverage.

## Source-only verification at handoff

19 unittest cases PASS, with subcases for context/profile-option additions/removals/type drift, missing/changed model files, altered oracle/guest source, extra artifacts, compiler/source changes, every missing step, changed command/log, sanitizer output, negative false success and result parsing. Syntax checks PASS. Exact current OFF/ON model preflight PASS with debug-compression tool binding, `execution=0`. No heavy model/harness compilation or simulation was performed by the preparation worker.
