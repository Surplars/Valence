# Experimental final-response flow (component only)

`RegisteredInstructionTranslationEngine.experimentalFinalResponseFlow` defaults
to **false**. The original four-argument JVM constructor remains available. No
CPU call site, platform default, cache, packet capacity, or maintenance policy is
changed. The enabled option is deliberately restricted by constructor guards.

For a non-crossing first physical return, the real old-owner result may be
consumed immediately. If blocked, the unchanged reply registers retain it.
Only an actual result handshake permits same-edge command turnover. New-owner
initialization wins the old receive writes, while the outgoing token remains the
old generation. Physical response ready is unchanged. Cross-page and second-word
returns retain the old path. The fault mask uses already captured permissions;
it is **not** an unconstrained all-state replacement for a live permission mux.

## Standalone profile and reproduction

The fixture explicitly fixes the 13 `OooParams` fields read by the engine or
its enabled-profile guard plus seven public constructor prerequisites (machine-system
mode and the registered request/response boundary dependency chain), listed in
`profile.json` (20 total); all other fields use public
repository defaults. This is not a production CPU configuration. It requires no
private platform resolver, CPU overlay, saved checkpoint, or Library file.

Use Java 21, Scala 2.13.17 / Chisel 7.3.0, FIRTool 1.135.0, sv2v v0.0.13 and
Yosys 0.52. Tools are supplied by the caller, not bundled or downloaded here.

```sh
mill -i IonSoC.compile
mill -i show IonSoC.runClasspath > build/final-runtime.json
mill -i show IonSoC.scalaCompilerClasspath > build/final-compiler.json
# Obtain the installed plugin from IonSoC.scalacPluginClasspath.
python3 simulator/gsim/experiments/final_response/run.py emit \
  --out "$PWD/build/final-response-proof" \
  --runtime-classpath-file build/final-runtime.json \
  --compiler-classpath-file build/final-compiler.json \
  --chisel-plugin /path/to/chisel-plugin.jar \
  --java /path/to/java --firtool /path/to/firtool
python3 simulator/gsim/experiments/final_response/run.py prove \
  --out "$PWD/build/final-response-proof" \
  --sv2v /path/to/sv2v --yosys /path/to/yosys
```

The fresh output path must be below this worktree's `build/`, with no whitespace.
Missing optional resource directories are recorded; missing classes/jars fail.
Each command has a configurable external timeout (default 60 s); SAT additionally
has its fixed 60 s limit. Timeout is UNKNOWN, not success. Preserve failed output
and diagnose it rather than overwriting receipts. Do not run Python with `-O`.

The runner compiles the public source and fixture. A separate **test-only** source
is mechanically derived by reversing exactly the two captured-mask expressions
back to `firstMask`; this is the intermediate retimed reference, not an ideal
model. Three four-module closures are checked against `expected-rtl.json`:
old registered behavior (off), intermediate retimed reference, final captured
permission behavior (on). All source, tool, class origins, and receipts are bound.
A changed tool/profile/output requires investigation, not refreshing hashes.

## What the proof establishes

All 19 actual register vectors (467 Q bits) are cut at real D/Q connections.
Two actual PMP invocations are certified structurally identical, then replaced
by separate shared arbitrary denied bits; they are not conflated with each other.
Every original binary input and Q encoding remains free unless the property
explicitly states the reset-inductive invariant below.

1. **Latency delta**, off versus intermediate: outside early return all raw
   outputs and D agree; blocked early return has identical register capture;
   early payload matches the original next reply data/faults and old token;
   consumption releases the owner; simultaneous new allocation matches the
   original idle initialization; all other outputs remain unchanged.
2. **Captured permission invariant**: reset establishes
   `I = (state != waitFirst || permissionCaptured)`, and every actual next-state
   step preserves it. Under I at non-crossing waitFirst, firstMask equals allowed.
3. **Refinement**, intermediate versus final: every D and non-fault raw output
   agrees unconditionally. Fault outputs agree under I. Blocked replies retain
   the same fault tuple and state transition.
4. Two required negative controls: replacing the observed access fault by only
   its saved value must fail; claiming fault equivalence without I must fail.
   Counterexamples are decoded. Neither is a reachable CPU failure claim.

Off/on are intentionally **not** cycle-by-cycle equivalent. This component
contract is not full-system cancellation/PMP-drain qualification, an architectural
CPU execution test, a performance result, FPGA timing, or a production feature
recommendation. No simulator, CPU benchmark, synthesis, or mapping runs here.
