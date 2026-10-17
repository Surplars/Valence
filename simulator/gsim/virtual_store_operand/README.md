# Focused test entry points

The Scala entry points are `ooo.VirtualStoreOperandLookaheadConfigMain`, `ooo.VirtualStoreOperandPoolGsimMain`, `ooo.VirtualStoreOperandQualificationVerilogMain`, `ooo.VirtualStoreOperandLookaheadBackendMain`, and the native/board emitters in `VirtualStoreOperandLookaheadMain.scala`. The latter intentionally use the independent production-50cb repair-ON profile; a combined candidate needs its own explicit audited configuration.

Run the constructor check with `mill -i IonSoC.test.runMain ooo.VirtualStoreOperandLookaheadConfigMain`. Emit helper/backend into fresh directories. Backend arguments are `<out> on`; helper emission accepts `<out>`. GSIM generation uses `--threads=1 --cpp-max-size-KB=1024 --dir=<out> <out>/<top>.fir`.

Compile helper `virtual_operand_pool.cpp` with the generated `VirtualStoreOperandPoolGsim*.cpp`, then run normally and with each of `--trust-va-range`, `--truncate-tag`, `--expose-issued-fallback`. Normal must pass; each negative must fail with `independent virtual operand pool mismatch`.

For the static proof, run Yosys on emitted `VirtualStoreOperandQualification.sv` plus `qualification_miter.sv`: `prep -top qualification_miter -flatten; sat -verify -prove ok 1 -show-inputs`.

Compile generated `ReadyStoreQuery77BackendGsim[0-9]*.cpp` once. Link each focused driver to those objects with includes for the model directory, `simulator/gsim/preparation_descriptor`, and `simulator/gsim/ready_store_query77`, using C++20, ASAN/UBSAN, `-fno-sanitize-recover=all`, and `-ldl`. The exact qualified artifact flags were `-std=c++20 -O1 -g0 -fsanitize=address,undefined -fno-sanitize-recover=all`, with `ASAN_OPTIONS=detect_leaks=0`.

New drivers: `virtual_store_operand`, `virtual_store_epoch`, `virtual_store_faults`. The first supports negative flags `--wrong-full-token` and `--early-start`; the second supports `--stale-epoch`. Expected errors respectively: `virtual fallback full-token mismatch`, `virtual fallback produced nonhead launch or physical effect`, `stale epoch used after SATP publication`.

Retained drivers: owner_reuse; ready_all_phase on; normal_fault_overlap; full_kill; recovery_phase_positive; recovery_cancel_negative; reset_clocked; qlive_cancel; proof_control_scenarios; proof_control_block_new; pool_bare_preparation. Retained negative flags and expected errors: ready_all_phase on --mutate-data → independent execution data mismatch; full_kill --mutate-retirement → fault/killed/duplicate retirement; pool_bare_preparation --mutate-bare-address → independent bare resident address mismatch.

Bound builds/tests to available resources and coordinate large model compilation. Do not run an additional standalone full-CPU model for this flag: its performance qualification is held for the coherent combined batch. Saved warm-store guest/harness/model must be reused unchanged for the eventual matched comparison.
