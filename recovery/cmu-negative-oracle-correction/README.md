# Narrow native negative-oracle correction

## Result and boundary

The corrected monitors passed a bounded replay against the exact historical emitted RTL: **three matched positive controls passed; five affected negatives failed the ordinary checker at the intended site**. `summary.json` and `{r10,r11,r12}/replay-r1/receipt.json` contain the results and exact commands, input/tool/RTL hashes, and original receipt references. The logs are retained beside each new receipt. Simulator binaries remain under `out/`.

This is **historical RTL monitor-sensitivity evidence**, not current-production-source qualification, a new full regression, or a physical CDC/clock-gating/DRP/board claim. Current sources differ from the historical emission inventories in 10 (r10), 11 (r11), and 10 (r12) files; every difference is disclosed in the new receipt. The original runners' strict source checks have not been weakened or used with mismatching sources. No Mill command, production/Scala/RTL edit, original-receipt edit, or upload was performed.

## Precisely affected historical claims

1. `recovery/cmu-frequency-r10-three-clock/component-receipt.json`, `negative_oracle_checks.negative-2` (line 8554). Its exact original TB SHA256 is `68b696260dd9e09b6cf20d606ba72c65934c076006e63c9c8e8ab62d17863ad1`. In that TB, `simulator/cdc/runtime_epoch_boundary_tb.sv:189` ORed `negative==2` directly into the receipt failure predicate. The original log proves that the special branch failed, not that a corrupted receipt observation was rejected. The other token negative at original line 242 changes the expected token before its ordinary comparison and is not affected.
2. `recovery/cmu-frequency-r11-controller-cleanup/component-receipt.json`, `cases` entries `negative-completion` and `negative-quiesce` (lines 389 and 406). Exact original TB SHA256: `441a02e3bb9c511ed4bb0c4ae05f7e502e4a5597ca6197eb4664956cb9316045`, recovered verbatim from `3c50e88:simulator/cdc/clock_rate_cleanup_tb.sv`. Original lines 126–127 use separate negative-only assertions, after the untouched ordinary ownership assertion at lines 124–125. These show an alternate expected-value check rejected, but do not establish sensitivity of the ordinary checker.
3. `recovery/cmu-frequency-r12-qualification-timeout/component-receipt.json`, `cases` entries `negative-completion` and `negative-quiesce` (lines 391 and 408). Exact original TB SHA256: `3a70638a33c2583c1c8be87cb477445a1eaa640e5f9b601559680ffb7f32ce31`. The same separate negative-only checks occur at original `simulator/cdc/clock_rate_cleanup_tb.sv:131–132`, after the ordinary check at lines 129–130.
4. Separately assigned to the network worker: `recovery/cmu-frequency-r16-network-admission/native-final/receipt.json`, `negative_oracle_checks.negative-2` (line 1105). Original TB SHA256: `8e4dca061b52e17688c01fa82737405a8f129ee61417af420bc35f705b6d6687`. Original `simulator/cdc/network_packet_runtime_tb.sv:137` ORed `negative==2` directly into the retained-status idle failure. Its negatives 1 and 3 mutate expected payload bytes/data at original lines 204 and 236 before the ordinary payload comparisons and are not affected by this defect. This directory does not claim to replay or correct r16.

All historical receipts and their results remain immutable. These narrow qualifications do not invalidate the historical positive runs, which still exercised their ordinary assertions. Previously archived diagnostic FAIL/interrupted receipts are not converted into acceptance evidence.

## Corrections and replay

- r10: a monitor-only `observed_result_seen` alias receives a false receipt observation for negative 2. The ordinary receipt predicate consumes it, with no negative flag in the failure predicate.
- r11/r12: monitor-only `observedCompleted` / `observedQuiesce` values are corrupted, then passed through the same `check_pending` predicate as the positive control. No alternate negative-only assertion remains. A conditional diagnostic display is inside the already-failing ordinary branch; it cannot cause failure by itself. The original runner's marker compatibility is preserved.
- The working-tree r10 and current r12 TBs contain these changes. r11's incompatible historical interface is preserved only as a baseline/corrected snapshot here, not misrepresented as the current TB.
- Each `baseline_tb.source.sv` is checked against the immutable original receipt's TB hash. The tiny `monitor-only.patch` explains the correction. `manifest.json` freezes original receipt and baseline/corrected TB hashes.
- `replay.py` verifies the original emission receipt hash and all RTL files, requiring exact directory inventory equality, plus the complete original Icarus/VVP tool chain hashes. It compiles only a corrected TB against the original emitted RTL. All bound inputs and the complete RTL inventory are rechecked after execution. The affected original negative logs were also rehashed during the audit and matched the old receipts.
- Frozen RTL used: r10 `out/cmu-frequency-r10/component-rtl` (6 files); r11 `out/cmu-frequency-r11/component-v3-rtl` (3 files); r12 `out/cmu-frequency-r12/component-rtl` (3 files).

Reproduction from this checkout, choosing a fresh output directory:

```sh
source scripts/cloud/env.sh
mkdir -p out/cmu-negative-oracle-correction
python3 recovery/cmu-negative-oracle-correction/replay.py --output out/cmu-negative-oracle-correction/replay-r2
```

The original exact tool paths and frozen RTL must still exist and hash-match. Missing/drifted inputs are a failure, not permission to regenerate or relabel evidence. A 90-second limit, process-group termination, and the existing 4 GiB disk floor apply to each native process.

Fresh **current-source** qualification is separate work. After authorized centralized emission and fresh source/RTL binding receipts, the current emitters are `mill --no-server IonSoC.test.runMain platform.CommonRuntimeEpochBoundaryMain OUT 64 128` and `mill --no-server IonSoC.test.runMain platform.ClockRateCleanupComponentMain OUT`. Their existing native runners are `simulator/cdc/test_runtime_epoch_boundary.py RTL OUTPUT --emission-receipt RECEIPT` and `simulator/cdc/test_clock_rate_cleanup.py RTL OUTPUT --emission-receipt RECEIPT` with the prepared `--iverilog` / `--vvp` paths. These commands were not run by this correction.

## Inspected controls without this bypass defect

- r10 I1 `i1-receipt.json`: wrong-store/data alter the expected retired value at `simulator/gsim/common/i1_runtime_cdc_tb.sv:122,143`; wrong-IRQ alters the expected bitmap at line 336, consumed by the ordinary comparison. Hashes match the receipt.
- r11 I1 `i1-receipt.json`: exact historical source recovered from `3c50e88` matches TB hash `161a66d2862f1ff90c2546ff9b62f47e998cfc64748b241a539bb52edcb93b96`; expected-value/bitmap perturbations occur at historical lines 141,162,261. The historical runner hash also matches. r12 I1 `i1-receipt.json` matches current TB/runner hashes; corresponding mutations are at lines 150,171,282.
- r13 `atomic-receipt.json`: old/final/SC expected-value perturbations at `simulator/gsim/common/i1_atomic_epoch_tb.sv:170,175,184`. `irq-receipt.json`: EPC/claim/service expected-value perturbations at `simulator/gsim/common/i1_irq_epoch_tb.sv:133,194,209`. Both TB hashes match their receipts.
- r14 `native-receipt.json`: `simulator/cdc/debug_admission_tb.sv:267` changes expected DMI reply, compared at lines 71–72. Its drain negative at line 257 invokes the same external outstanding-owner predicate (`checkProof`, lines 104–108) at a deliberately unsafe point, with a real offered RAM owner established at line 255. The negative flag only affects the diagnostic marker, not that predicate. This validates the owner predicate, not a mutation of the normal held/terminal-trigger gating at line 111. TB/runner hashes match.
- r15 `native-final/receipt.json`: `simulator/gsim/common/i1_runtime_debug_tb.sv:245` perturbs the expected DMI reply ledger before comparison at lines 249–252; line 433 perturbs the expected fabric prepare count within the existing no-old-owner-progress check. TB/runner hashes match. These are expected-value sensitivity checks, not observed-DUT fault injection or a direct force-fatal branch.

No broader claim about all oracle completeness follows from this targeted audit.

Read-only bundle/input verification without a simulation:

```sh
source scripts/cloud/env.sh
python3 recovery/cmu-negative-oracle-correction/verify.py
```

This verifies manifest/baseline/patch bindings, every archived log, complete original RTL inventories, historical tools, original receipt immutability, replay runner/helper hashes, and current corrected TB/snapshot equality. Publish this directory's `.md`, `.json`, `.py`, `.sv`, `.patch`, and `.log` files only; no `__pycache__`, simulator binaries, or generated RTL is part of the publication list.
