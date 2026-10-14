# Timing-closure focused tests

These are the retained independent tests for registered load-result readiness and the default-OFF frozen-store checked-flow experiment. They are component/backend gates, not a full regression, CPU performance suite or physical signoff. [Status and coverage limits](timing-closure-candidate-20261014.md) remain authoritative. Importing the test files does not itself constitute a fresh run.

## Test sources

| Gate | Scala main | Generated top | Independent host |
|---|---|---|---|
| P1 protocol | `ooo.LoadReadyProtocolGsimMain` | `LoadReadyProtocolGsim` | `load_ready_protocol.cpp` |
| P1 direct LSU | `ooo.LoadReadyDirectGsimMain` | `LoadReadyDirectGsim` | `load_ready_direct.cpp` |
| P2 actual backend | `soc.core.ooo.LoadReadyBackendGsimMain` | `LoadReadyBackendGsim` | `load_ready_backend.cpp` |
| Frozen adapter | `soc.core.ooo.FrozenCheckedFlowGsimMain` | `FrozenCheckedFlowGsim` | `frozen_checked_flow.cpp` |

Scala fixtures are in `src/test/scala/ooo`; hosts are in `simulator/gsim/harness`. P1 uses `LoadReadyP1Params`. P2 uses `LoadReadyBackendBaseGsim` and the real production backend. Frozen uses the existing `PendingStoreProofFixture` and independent `pending_store_proof_reference.h`; no additional helper copy is required. Top-level package names differ intentionally, without duplicate class definitions.

Configuration-only checks:

```sh
mill -i -j 1 IonSoC.test.testOnly \
  ooo.LoadReadyP1ConfigSpec \
  soc.core.ooo.LoadReadyBackendConfigSpec \
  ooo.FrozenCheckedFlowConfigSpec
```

The historical P2 schema had 176 OooParams fields. In the 177-field combined tree, the added frozen-flow flag must be explicitly false in both P2 modes; existing complete-product equality except registeredLoadResultReady remains required. Keep this schema-only adaptation separate from the original dynamic results.

## Explicit GSIM rerun template

Use the repository's supported/pinned Mill, GSIM and C++ toolchain. Set `GSIM` and `CXX` to those executables; no simulator installation or fallback is implied. Use a fresh output directory per variant and preserve failed logs. Example for P1 protocol ON:

```sh
out=build/gsim/load-ready-protocol-on
top=LoadReadyProtocolGsim
host=simulator/gsim/harness/load_ready_protocol.cpp
test ! -e "$out" || exit 1
mill -i -j 1 IonSoC.test.runMain ooo.LoadReadyProtocolGsimMain "$out" 1
"$GSIM" --threads=1 --cpp-max-size-KB=1024 --dir="$out" "$out/$top.fir"
mkdir "$out/objects"
for src in "$out"/"$top"[0-9]*.cpp; do
  test -f "$src" || exit 1
  "$CXX" -std=c++20 -O1 -g -fsanitize=address,undefined \
    -fno-sanitize-recover=all -I"$out" -c "$src" \
    -o "$out/objects/$(basename "${src%.cpp}").o" || exit 1
done
"$CXX" -std=c++20 -O1 -g -fsanitize=address,undefined \
  -fno-sanitize-recover=all -I"$out" "$host" "$out"/objects/*.o -ldl -o "$out/run"
ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  "$out/run" --enabled=1
```

The archived runs used ASan+UBSan with leak detection disabled because LeakSanitizer was unavailable under ptrace. This is not a leak-validation PASS. On a supported environment, leakage may be tested separately; do not silently alter the reported sanitizer scope.

For P1 direct and P2, substitute the corresponding main/top/host. Emit each with output directory then `0` or `1`, and run the host with the matching `--enabled=0` or `--enabled=1`. P1 direct exercises both registerStart settings inside one model. P2 defaults to all fixed scenarios; `--case=contention|selected|isolation|recovery|mixed|throughput|faults` selects the recorded groups.

Frozen emission takes output directory, feature `0|1`, and queued-head mux `0|1`. Run all four combinations when requalifying that experiment. Its host reads the emitted feature from the actual wrapper and takes no `--enabled` option.

## Same-object negative controls

Reuse each passing model and binary. A rejected run is valid only if the named mutation reaches its intended independent checker or original protocol assertion. A sanitizer error, crash, unknown argument, or P2 exit 3 (`NOT_REACHED`) is not a passing negative.

- P1 protocol ON: `--mutate=holder-value`, `holder-token`, `nonordinary-ready`, `handoff-write`, `old-new-cross-pair`, `fault-publication`, `second-publication`, `publication-destination`, `cancelled-resurrection`, `incoming-publication`, `reserve-loses`. Check `REACHED_NEGATIVE` and the specific independent comparison failure.
- P1 direct ON: `--mutate-capture-drop`, `--mutate-capture-add`, `--mutate-result-data`, `--mutate-token-high`, `--mutate-post-phase`, `--mutate-store-initial-cause`. Repeat the final cause control OFF. Check the actual-corruption marker and the specific complete metadata/result/phase obligation.
- P2 ON: `--mutate=wrong-fulltoken`, `wrong-captured-data`, `false-nonordinary`, `missing-prf-handoff`, `reserve-priority`, `killed-owner-revival`, `unselected-mispair`. Check `LOAD_READY_MUTATION_APPLIED` and the corresponding `LOAD_READY_ORACLE_FAIL ... applied=1`; keep event-bound response service unchanged.
- Frozen, each of four variants: host mutations `--mutate-token`, `--mutate-data`, `--mutate-handoff`, `--mutate-checked-token`, `--mutate-handle`; malformed protocol cases `--size4` through `--size7`, `--mask`, `--va`, `--offset`, `--pa-high`, `--pa-range`, `--unaligned`, `--request-size`, `--atomic`; live-context cases `--flush-live`, `--pmp-live`, `--vm-live`. Require the original specific host/protocol rejection, not simply a nonzero exit.

Use the immutable source-file SHA-256 provenance accompanying the release to distinguish the original measured fixtures, the P1 stage-specific host repair, and the P2 schema-only adaptation. Generated FIR/SV/C++ models, compiled objects, binaries, local caches, private recovery receipts and machine-specific paths are not source deliverables.
