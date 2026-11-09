# Experimental parallel ingress authorization (component only)

The default-off `DataTranslationAdapter.experimentalParallelIngressAuthorization`
constructor option evaluates legacy and physical-ingress next-line authorization
in parallel, then selects the result using the unchanged physical-ingress offer.
It does not add a queue, credit, cycle, state bit, port, or CPU configuration flag.
The previous nine-argument JVM constructor is retained. The single-helper observer
returns `None` when enabled, rather than misleading callers about the selected arm.

This standalone fixture constructs all 209 `OooParams` fields explicitly. It does
not resolve a platform profile or require private CPU/Spec overlays. Its restricted
32 ROB / 64 physical register / 4 memory-entry profile, eight adapter entries,
16 PMP entries, and registered checked path are intentional. The production CPU
call site and defaults are unchanged. This is not a supported production CPU
configuration or a general proof for other parameter combinations.

## Reproduce

Use the repository's normal Scala/Chisel build first (Scala 2.13.17, Chisel 7.3.0),
Java 21 and FIRTool 1.135.0. The proof uses sv2v v0.0.13 and Yosys 0.52
(as identified by the resulting tool receipts); tool binaries are not included.
No Verilator, GSIM native model, CPU workload, or FPGA synthesis is invoked.

```sh
mill -i IonSoC.compile
mill -i show IonSoC.runClasspath > build/parallel-runtime.json
mill -i show IonSoC.scalaCompilerClasspath > build/parallel-compiler.json
# Select the installed Chisel plugin jar from IonSoC.scalacPluginClasspath.
python3 simulator/gsim/experiments/parallel_ingress/run.py emit \
  --out "$PWD/build/parallel-ingress-proof" \
  --runtime-classpath-file build/parallel-runtime.json \
  --compiler-classpath-file build/parallel-compiler.json \
  --chisel-plugin /path/to/chisel-plugin.jar \
  --java /path/to/java --firtool /path/to/firtool
python3 simulator/gsim/experiments/parallel_ingress/run.py prove \
  --out "$PWD/build/parallel-ingress-proof" \
  --sv2v /path/to/sv2v --yosys /path/to/yosys
```

Classpath files accept a colon-separated classpath or Mill JSON (`value` array,
including Mill `ref` and cached `qref` paths). Missing Mill resource-only directories inside the
repository are recorded and must stay absent; missing jars or classes fail closed.
Use paths without whitespace for the Yosys scripts.
The fresh output directory is mandatory; failed/timeout attempts remain intact.
A timeout is UNKNOWN, not a counterexample or PASS. The default per-command limit
is 60 seconds and can be explicitly changed with `--timeout-seconds`.

`profile.json` and `expected-rtl.json` are compact reproducibility fixtures, not
external evidence dependencies. Export verifies all 209 parameter values and all
nine SystemVerilog modules on both sides against these fixtures. A changed tool
or elaboration must be investigated, not silently accepted by updating hashes.
The runner records actual class origins, source/dependency/tool hashes, commands,
exits and both streams under `build/`; no generated output belongs in a commit.

## Proof boundary

The proof pairs all actual state groups by complete Q aliases and matching FF
parameters, sharing arbitrary Q and every original input encoding. It compares
all original outputs, every D and CLK, and the complete initialization relation.
No valid-input, reachable-state, legal-PMP, stable-PMP, or CPU-lifecycle assumption
is introduced. The helper theorem checks the actual ordered combinational DAG,
including exhaustive definedness checks for variable `shiftx` indices. One SAT
job proves all selected helper inputs; a second proves the remaining output and
state equations with independent helper result symbols. Their composition is the
full adapter theorem, not a theorem inferred from a few transactions.

The negative control inverts only the candidate physical-valid observation at a
fully fixed zero input/Q valuation. Its counterexample is independently decoded
against both actual original valid cones. It tests the observation chain; it is
**not** an RTL mutation or a helper-implementation negative control.

No CPU execution or physical timing is established by this public experiment.
This component proof is not an end-to-end speedup, routed Fmax, timing guarantee,
or publicly supported production CPU configuration.
