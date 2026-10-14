# FP conversion sharing component gate

Build this checkout's production and HardFloat classes with the repository's pinned build first. This gate requires Python3, Java/Scala compiler+Chisel plugin/classpath, firtool and Icarus Verilog. It does not build a CPU or synthesize hardware.

Example, from repository root (environment values supplied by your local pinned build):

```
python tests/fp-convert-gate/run.py convert --out out/fp-convert-gate --classpath "$FP_GATE_CLASSPATH" --plugin "$CHISEL_PLUGIN" --firtool "$FIRTOOL" --negative
python tests/fp-convert-gate/run.py misc --out out/fp-misc-gate --classpath "$FP_GATE_CLASSPATH" --plugin "$CHISEL_PLUGIN" --firtool "$FIRTOOL"
python tests/fp-convert-gate/run.py tag64 --out out/fp-tag64-gate --classpath "$FP_GATE_CLASSPATH" --plugin "$CHISEL_PLUGIN" --firtool "$FIRTOOL" --negative
```

FP_GATE_CLASSPATH must contain the current checkout's production classes (including FloatingPointToIntegerShared), pinned HardFloat classes, Scala compiler/runtime and Chisel jars. Supply --java/--iverilog/--vvp when not on PATH. Keep output directories fresh; overwriting is rejected. Compile the two MiscHarness fixture variants separately as the runner does, not together through automatic src/test discovery.

--reuse-rtl DIR explicitly skips compilation/emission and hashes reused native RTL; --vectors FILE reuses deterministic vectors. Receipts label reused-RTL qualification distinctly from fresh-component qualification. Generated vectors, RTL, simulator binaries and receipts belong in local output, not the source patch.

The Python arbitrary-integer oracle has literal anchors and122840 deterministic S/D signed/unsigned cases across five rounding modes, exceptions and boundaries. It is independent of the candidate narrowing logic and host floating point; it is not SoftFloat or exhaustive formal proof. Original32/64 HardFloat conversion instances provide another reference. Actual Misc tests preserve latency2/II3, owner, flush, result backpressure and nonconversion operations. The tag64 fixture checks all upper32 tag bits while index and low tag are identical.

Negative gates modify separate generated copies only: incorrect narrow clipping, incorrect NX suppression, and candidate-only high-tag truncation. Each must fail its semantic assertion; changed emission patterns fail closed for review. The original Misc baseline fixture preserves the pre-sharing implementation under a different class name.

Runner validation during preparation: reused native RTL passed all122840 conversion cases and both semantic negatives,4772 actual Misc requests,60 tag64 requests plus high-tag negative. An independent fresh tag64 wrapper compilation/emission also passed. This validates the explicit-classpath component path, not a fresh full repository build or FPGA mapping. No net LUT saving, frequency gain or full CPU qualification follows from this component gate.
