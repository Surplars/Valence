# FP conversion-sharing GSIM component gates

GSIM is the repository's only supported hardware simulator. This runner emits FIR, generates GSIM C++, and runs independent C++ hosts. It does not invoke Icarus, Verilator, ChiselSim, or a whole CPU build. Historical SystemVerilog fixtures from an earlier test commit, if still present in this directory, are unreferenced archival test sources; they are not active supported entry points. Previous Icarus result records remain historical Icarus evidence and are not relabeled GSIM.

Build this checkout's production/HardFloat classes with the pinned repository build first. Supply its Scala compiler/runtime+Chisel+production+HardFloat classpath and Chisel compiler plugin explicitly. Fresh output directories are required.

```
python tests/fp-convert-gate/run.py convert --out out/fp-convert-gsim --classpath "$FP_GATE_CLASSPATH" --plugin "$CHISEL_PLUGIN" --gsim "$GSIM" --cxx "$GSIM_CXX" --negative
python tests/fp-convert-gate/run.py misc --out out/fp-misc-gsim --classpath "$FP_GATE_CLASSPATH" --plugin "$CHISEL_PLUGIN" --gsim "$GSIM" --cxx "$GSIM_CXX"
python tests/fp-convert-gate/run.py tag64 --out out/fp-tag64-gsim --classpath "$FP_GATE_CLASSPATH" --plugin "$CHISEL_PLUGIN" --gsim "$GSIM" --cxx "$GSIM_CXX" --negative
```

Set --java if needed. --vectors FILE can reuse deterministic generated inputs; otherwise the runner invokes make_vectors.py into its output directory. --shared-source FILE may explicitly identify the same-checkout FloatingPointToIntegerShared.scala used for source negatives. The default source path is repository-relative. Runtime classpaths must describe the same production checkout; never mix unqualified stale application classes. Generated FIR/C++, binaries, vectors and local receipts are output artifacts, not source changes.

## Preserved checks

- Conversion gate:122840 deterministic S/D signed/unsigned cases, all five rounding modes, zeros/subnormals/NaN/sNaN/infinity and32/64-bit boundaries. Candidate and independent original HardFloat32/64 instances both compare to the same Python exact-integer oracle/anchors used before migration. Oracle and vector bytes are unchanged. This is not SoftFloat or exhaustive formal proof.
- Actual Misc tag16:4772 transactions;4485 retired;166 prepared flushes;121 result flushes;435 explicit held-result cycles;130 nonconversion operations;6 illegal-rounding cases;3967 II3 checks. Candidate is compared to the frozen original Misc implementation. Nonconversions retain differential smoke coverage rather than a new independent numerical oracle.
- Actual Misc tag64:60 directed transactions;44 retired;8 prepared/8 result flushes;30 held-result cycles;26 nonconversions;6 illegal-rounding cases;19 II3 checks. Same index5/lowtag0x1235 and walking upper32 tag bits expose truncation; captured64-bit owner tag and4-bit index are checked independently. This is not exhaustive tag/index exploration.
- Both Misc configurations enforce latency2, no same-cycle refill, held value/flags/owner, exact baseline ready/valid and final/next-transaction idle of BOTH formats. The latter catches leaks across S/D switching and after the last transaction.

GSIM samples combinational outputs for the edge before updating state. The C++ host preserves cycle-counted latency/II3; result-flush cases hold the visible result for an extra observation edge, then assert flush/resultReady/requestValid together. This still tests result/flush coincidence with refill forbidden; it is not a claim of identical simulator timestamp waveforms.

## Source negatives

Separate compiled copies change only (1) candidate narrow clipping, (2) candidate NX suppression on invalid/overflow, or (3) candidate-only high-tag input bits. Original HardFloat references, original Misc baseline and numerical oracle remain unchanged. Numerical mutants fail CANDIDATE_MISMATCH at rows18645/77155; tag truncation fails MISC_BASELINE_MISMATCH. Compilation/generation errors and sanitizer failures cannot satisfy a negative; the runner checks the semantic rejection marker and rejects ORACLE_BASELINE_MISMATCH.

All three positive gates and all three source negatives have been run through FIR→GSIM with ASan/UBSan. This is focused component qualification only. Production logic, prior CPU qualification, mapped resources and timing are not rebuilt or reattributed by this test-only migration.
