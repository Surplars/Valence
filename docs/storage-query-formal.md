# Reproducing the recovery-query component proof

This is a separate verification asset for the test-only query experiment described
in [storage-query-experiments.md](storage-query-experiments.md). It does not enable
a production option or change the previously qualified storage/query RTL.

## Exact claim

`RecoveryQueryFormalMain.scala` wires the same unconstrained inputs to the
original `ParallelRecoveryAdmission` and the queried subclass. It compares the
entire original bundle, including raw selected payload bits when valid is false,
and compares each new query with the original indexed survival bit. Query age is
exactly modular `queryIndex - head`, truncated to the ROB index width. The fixture
has no input assumptions. ROB16 and ROB32 use every possible index encoding;
there are no unused index codes at these power-of-two capacities. Count/keep
encodings are not restricted to reachable sequential states.

Thus the proof includes external/local both-valid arbitration, tie winner, wrap,
full 64-bit tags, stale tokens and inactive recovery. It is a combinational
helper proof, not a sequential whole-ledger proof, CPU instruction oracle, timing
proof or a demonstration that every possible state is reachable.

## Negative control

The only mutant changes the newly selected recovery boundary test from `<` to
`<=`. Original admission outputs must still match; a query exactly at the kept
prefix boundary must differ. An independent decoder reconstructs the witness
from scalar and vector input values instead of accepting an arbitrary Yosys
failure or a failed command as a successful negative control. Missing/unknown
signals and unrelated output mismatches must fail validation.

## Tool and run discipline

Use the same compiled Scala/Chisel dependency set as the public overlay exporter,
and specify installed `sv2v` and `yosys` tools. Outputs belong in a fresh build
directory. Record source hashes, actual JVM class origins, executable identities,
commands, exits and proof/counterexample receipts. The old private build paths
are not inputs to this runner. An optional caller-selected proof budget must be
reported as UNKNOWN on expiry, never as functional failure or proof success.
No GSIM CPU model, synthesis/P&R, board run or default-profile change is performed.

## Command

First run the documented public export entry in
[`simulator/gsim/experiments/storage_query/README.md`](../simulator/gsim/experiments/storage_query/README.md)
for ROB32, retaining its normal classpaths, plugin path, fresh source files,
commands, class-origin records and `EXPORT_REVIEW.json`. Then, from repo root:

```sh
python3 simulator/gsim/experiments/storage_query/formal.py \
  --repo "$PWD" --out build/storage-query-formal \
  --runtime-classpath-file build/storage-query-classpaths/runtime.txt \
  --compiler-classpath-file build/storage-query-classpaths/compiler.txt \
  --chisel-plugin "$(cat build/storage-query-classpaths/plugin.txt)" \
  --query-classes build/storage-query-export32/query/classes \
  --sv2v "$(command -v sv2v)" --yosys "$(command -v yosys)"
```

`--timeout-seconds` is optional, applies per external command, and defaults to no
automatic termination. A caller choosing a budget must keep UNKNOWN distinct
from proof failure. An arbitrary folder of classes is not accepted: the supplied
query classes must come from a completed matched public export with matching
source hashes and actual class-origin receipts. Production helper and test
fixture origins are checked again during every proof elaboration.

Expected terminal status is `PASS_TWO_FULL_INPUT_PROOFS_AND_PRECISE_NEGATIVE`.
The negative SAT invocation must exit with its expected counterexample status,
not a crash; its witness is then independently checked. Preserve `RESULT.json`,
`BINDING.json`, command receipts, emitted SV and the decoded witness alongside
results. These generated artifacts are not source-tree inputs to commit.

## Fresh public-entry validation (2026-10-30)

The final runner was executed without a timeout using the previously audited
query export classes. Both full-input proofs passed: ROB16 SAT 0.40 s and ROB32
SAT 1.20 s. The ROB16 boundary mutant produced the expected counterexample in
0.23 s, and the independent checker accepted it. Checker self-tests accepted two
valid samples and rejected six malformed or semantically wrong samples.

The witness has head 6, count 14, recovery keep 3, and both requests at index 7,
tag 0, exclusive. External wins the tie and selects keep 2. Query index 8 has
age 2 and must not survive; the mutant wrongly retains it. Query index 7 has
age 1 and survives both. Ordinary outputs remain equal. Count/keep are legal in
this witness, so the negative result is not solely an unreachable-input artifact.
Timing figures above are solver runtime, not hardware timing or performance.
