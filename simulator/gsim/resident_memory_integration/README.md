# Resident memory payload reuse

The experiment defaults to OFF. The bounded qualified configuration is retained Young69 plus the single `--resident-memory-payload-reuse` option. Younger-load deferral is ON; held-ALU forwarding and raw-MAC handoff are OFF. The exact 69/70 ordered option vectors are in `fpga/next/resident-memory-profile.json`. Current complete products have 175 core and 92 profile fields; the measured Young reference has 173/89. No other preset changes.

## Mechanism and scope

Reuse the existing S payload only while its complete owner token is live. Exclude that owner from fresh selection, retain unchanged recovery/exception/start guards, and use one fresh memory operand/AGU path. No new stage, state, port, cached permission, or change to issue width, ROB/LSU capacity, ISA behavior, or oracle is introduced. Board construction applies the flag after FPGA storage configuration so the existing LVT topology guard sees the final product.

The independent native backend census gives memory operand reads 4 to 2, fresh memory AGUs 2 to 1, and PRF logical addresses including debug 14 to 12. Live PRF outputs/per-bank asynchronous readers are 13 to 11. All 745 backend register declarations and the seven S registers/203 bits are unchanged. These are component structure counts, not mapped whole-SoC resources. The ready/selection/PRF/AGU path family and the new owner-exclusion control cost remain.

## Recorded qualification (2026-10-13)

- Component P1: independent per-cycle owner/payload oracle, 1,867 cycles, 355 starts, 894 next captures, 442 reuses, maximum 16 consecutive starts; seven diagnostic-specific negative controls pass.
- Component P2: real compressed expansion/decode/backend/rename/LSU path, 3,896 cycles on each side, 448 accepted/retired instructions and 444 load starts/requests; complete OFF/ON traces match. Full-ROB unaccepted bad inputs do not assert. Accepted noncanonical load source2 reaches the production assertion on each lane only with reuse ON. C++ hosts retain ASan/UBSan.
- Integration entry: one Scala compile, 21 focused pure Scala tests and actual OFF/ON board construction with complete core/backend/ledger equality, exact typed historical projection, one resident selector ON and none OFF.
- Whole CPU: one new ON model, 36 model objects, original phase-0 DDR read32/beat-gap1/eight-read-credit service law. Bare COPY is 179,571 inclusive cycles and Sv39 COPY is 191,618, unchanged from Young. All 105 result fields are retained. Complete stdout, AXI and supply traces are byte-identical. Bare conserves 162 real posted joins, ACKs and drains; Sv39 has none. Three original and four join-observation negative controls reject at their required diagnostics.
- The same 36 objects pass hot/compressed NEMU, three PC/GPR/memory negative controls, and short/word PMP precise traps. No new OFF model, guest build, reference build or NEMU resynchronization. NEMU GPR checking is at the complete retirement-edge boundary, not intermediate lane state.

No cycle speedup was observed. No LUT/FF, Fmax, routed timing, board/CDC, full ISA or Linux qualification is claimed. Joint resident+held-ALU or resident+raw-MAC execution is not qualified. The source-entry profile and reference retain their original preparation-status fields and `dynamic_qualification=false`: those immutable compatibility fields certify source/configuration binding, not all future executions. The completed bounded run above is separate evidence.

## Source and evidence identity

The corrected-B logical base is tree `f3dcb88dd4adb981b5cabe605610f8187aaaa0eb`; commit ancestry must be selected by the publisher. Publication preserves all production and existing Scala test bytes from the qualified integration snapshot. It adds the previously verified component fixture sources unchanged and changes only source-metadata storage, fixture loading and this documentation.

`reference-young69.json` is the byte-exact measured profile (SHA-256 `d251587fae19feb796e00f8e80b9cd25649d564f006c221b54f8ab08b9fbfc83`); `reference-young69-field-order.json` pins all ordered names (`5dbfc47d8a8490e99da18c36915964b0f0ded73a8d31d9bb99744750c0d1048f`). The compact v2 compatibility file reconstructs complete source maps from the pinned immutable held-ALU contract plus explicit reviewed deltas. Full path inventory, every file hash, original JSON immutability, complete field types/order and literal-false historical projections are still checked.

Recovery bundles are retained separately, never committed as build artifacts:

- Component recovery: `memory-resident-reuse-components-r1.tar.gz`; see its retained member manifest and independent native census.
- Integrated source recovery: `resident-memory-entry-qualified-delta-r1.tar.gz`, SHA-256 `8e73c4f7032d7aeb0025dd1dd81135eb24f4becb024625c88473a974c041c6cb`.
- Whole-CPU recovery: `resident-memory-whole-cpu-qualified-r1.tar.gz`, SHA-256 `24fce9f17ea335fcd035953e41014ec5d22bdd1e0acd8d6234709ab42b6fc9b9` (43,607,241 bytes). It includes all model objects, raw traces, host/guest inputs and immutable receipts. COPY receipt: `6abc4a24b819c8ad27d1e7cf150de3b536f7fd0b9a6a0fa0536e662131477b1f`; same-object receipt: `c61fab0b6b9f8998c4d421cba8e4de677a665bb098aa8b881a88e5406fbfdcfe`; terminal review: `f16c4a56bdf999f5a4dbdb5ff684e135ad39be0467d400236a8ee6d6f05cfab3`.

## Portable focused entry points

From the repository root, with the documented pinned Mill/JDK/GSIM toolchain on PATH:

```
mkdir -p build
PYTHONDONTWRITEBYTECODE=1 python3 fpga/next/test_resident_memory_entry.py
PYTHONDONTWRITEBYTECODE=1 python3 fpga/next/test_young_load_seal_source_bridge.py
PYTHONDONTWRITEBYTECODE=1 python3 fpga/next/tests/test_mac_raw_handoff_entry.py --source-root . --report build/resident-raw-entry.json
mill -i -j 1 IonSoC.test.compile
mill -i -j 1 IonSoC.test.runMain ooo.ResidentMemoryIntegrationConstructorMain OUT/constructors
```

Use a fresh output directory outside this source tree or under ignored `build/`; complete source-closure checks reject unknown source leaves. Existing completed validation must not be overwritten or rerun merely for publication. The constructor entry checks both OFF and ON; it does not build a simulator.

The portable unchanged component emitters are `soc.core.ooo.ResidentMemoryPairGsimMain OUT/p1`, `ooo.ResidentMemoryEntryGsimMain OUT/p2-off off`, `ooo.ResidentMemoryEntryGsimMain OUT/p2-on on`, and `ooo.ResidentMemoryBackendNativeMain OUT/native-{off,on} {off,on}` through `IonSoC.test.runMain`. Their independent hosts are `simulator/gsim/harness/resident_memory_pair.cpp` and `resident_memory_entry.cpp`; compile against their respective generated headers/translation units with C++20, `-O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all`. Exact positive/negative runtime arguments, GSIM flags and reference receipts are retained in the component recovery bundle. These commands are reproduction guidance, not evidence of a new publication run.

`ooo.ResidentMemoryIntegrationFullCpuMain OUT` is the exact ON-only CPU emitter. Reuse the preserved run and objects for investigation. A new CPU or physical run requires a separately bounded purpose; this publication does not launch one.
