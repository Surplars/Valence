# Zero-cycle cleanup verification sources

The selected board entry is `fpga/next/board_final.py`: exact original48 CPU options plus the registered-operand and local-payload-write-enable options, with explicit MAC T1 and JTAG USER2. Generic options remain default OFF.

## Public receipt and local verification

`evidence/public-receipt.json` is a minimal summary of the previously completed component/native/CPU/NEMU qualification. It contains necessary source/configuration fingerprints and opaque hashes for the complete external evidence. Full receipts, raw logs, workspace/toolchain metadata, system-header inventories and generated-object inventories are retained outside Git.

```
python3 simulator/gsim/zero_cycle_cleanup/check_retained.py
python3 simulator/gsim/zero_cycle_cleanup/test_check_retained.py
python3 fpga/next/test_board_final.py
python3 fpga/next/test_board_t1.py
```

The checker validates the pinned public receipt, necessary source bytes, the aggregate production-source closure, exact 50-option extension, product configuration, default-OFF prerequisites and explicit T1/USER2 preflight. The contract tests use mock emitters and a mock synthesis command. None runs a compiler, simulator, synthesis, or physical qualification.

The full qualification outcomes are recorded evidence, not newly established by these local checks. External hashes are references only unless a caller supplies `--evidence-bundle`, `--model-bundle` or `--full-source-bundle`; these optional arguments verify bundle bytes only and do not reexecute or independently validate their hardware results. Obtain the corresponding complete recovery bundle from its owner, then compare its hash before use.

## Reusable component sources

Registered-operand fixtures and independent hosts remain at `src/test/scala/ooo/RegisteredExecutionOperand*` and `simulator/gsim/registered_execution_operands*`. The runner accepts explicit output/toolchain paths for `emit`, `generate` and `sanitized`; `--boundary-only` selects the execution-stage fixture. Its five inherited backend exceptions remain explicit and do not describe the complete production board constructor.

Bridge sources include `BridgePayloadEnablePairGsim.scala`, `LocalPayloadWriteEnableConfigSpec.scala`, `harness/bridge_payload_enable.cpp`, and `harness/bridge_payload_memory.h`. Its source freeze, strict native audit, initialization instrumenter and negative matrix remain beside the portable runner:

```
python3 simulator/gsim/zero_cycle_cleanup/bridge/prepare_source.py --source "$PWD" --output "$FREEZE"
python3 simulator/gsim/zero_cycle_cleanup/bridge/run_gate.py --source "$PWD" --freeze "$FREEZE" --output "$RESULT" --toolchain "$TOOLCHAIN" --stop-after native
```

Set the three caller paths before use. The second command compiles and runs the bounded component, so run it only when that hardware check is intended. It was not rerun for publication. Component results belong to their original frozen sources. Paired simulator initial storage is not hardware reset-state proof. The gate preserves real-mutant oracle anchors, sanitizer checks, two manager geometries and upper-bank native checks.

`native/native_audit.py --off <qualified-baseline-rtl> --on <candidate-rtl> --output <report.json>` audits already generated RTL without generating hardware. It expects the exact 239-module geometry and rejects unreviewed module, state, port or cone changes.

## Qualification limits and rollback

Recorded Sv39/Bare and same-object NEMU results are same-profile non-regression, not new MAC/network concurrency coverage. No mapped LUT, synthesis, STA, implementation, PHY or board result is claimed. Full CPU/native orchestration is an external recovery recipe tied to frozen baseline receipts, not a general clean-checkout test.

For exact original48 rollback, restore the complete source at `611ab7a602d66aaa5435a9f2a4699e31146e65be` and run its original `fpga/next/board_final.py`. The earlier `board_t1.py` entry and physical source contract are unchanged.
