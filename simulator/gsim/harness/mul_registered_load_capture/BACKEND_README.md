# Registered-load MUL capture: portable backend contracts

This directory is a **source checkpoint**, not a copy of machine-local runtime gates.
`backend_host.cpp` is byte-identical to the final corrected component host; its original
static-preparation comment is intentionally retained. `pending_store_proof_reference.h`
is the byte-identical independent raw-instruction/byte-memory/PTE helper. Both includes
are relative/local: generated `MulLoadOperandCaptureBackendGsim.h` and the helper here.
No machine-local absolute include or archived executable is required by the sources.
The host remaps the helper's data pages into the actual fourth-profile RAM aperture at
0x80200000; copying the helper does not change that independent fixture setup.

## Scope and historical evidence

The fixture instantiates production IntegerBackend, decode, data translation, response
buffer and Sv39 translation service. Raw instruction renames, full `(index, uint64 tag)`
owners, independent arithmetic and memory values, actual MUL capture/start, accepted
completion and retirement/kill are checked. It is **not** a complete CPU/cache/fabric
performance model. OFF is `FullR1M3EfficiencyRefactor4`; ON is
`FullR1M3MulLoadOperandCaptureExperiment`, with only registered-MUL-load-capture enabled.
Context-owned instruction prefetch and load nomination are OFF in both. Data next-line
prefetch remains true as in the fourth baseline; “prefetch OFF” does not describe that
separate cache setting.

`cases.json` contains 13 positive templates, each carrying its exact OFF and ON
original descriptor, and two candidate-only observer descriptors. Expand
`positive_cases[].variants.{off,on}` plus `observer_cases` to recover the exact 28
original descriptors, including arguments, expected exits, required/forbidden markers,
empty positive stderr and the whole negative stderr regex. Every positive must exit 0;
missing witness exits 2 and is **never** accepted. Each observer must exit exactly 1,
match the entire prescribed stderr (only decimal cycle varies), and emit no PASS.
The observer mutations change only a host-captured token/value, not RTL authorization.

The accepted component set was **26 positive + 2 observer cases**, assembled from 10
initial-host PASS receipts and 18 corrected-host runs. One initial page-fault host
contract failure was preserved: Native `error` is aggregate and includes a page fault.
The final host changes only `error == e.error` to `error == (e.error || e.page)`;
pageFault, cause 13, tval, invalid-PTE service, no physical data request and no dependent
MUL start remain strict. Thus there were 29 actual case invocations including the old
failure, not 28 clean first attempts. Relocation does not relabel their source epochs.

Actual original tests witnessed left/right/both-source capture, WAW, ROB generation
reuse, original-ready MUL/DIV priority, precise fault and legal branch cancellation.
The wrapped ON case recorded 40 captures; that is not an IPC or bandwidth forecast.
Maximum observed multiplier credit was 7. Count8/pop, CDB-held LSU-result and late
rejection counters remained zero. Dedicated old-result consume/replacement identity,
surviving late-reject retry and attributable ALU-ticket loss were not measured. Do not
claim those gaps closed by source copying or by the short continuity checks below.

## Pinned tool qualification

Use Mill **1.1.7**, Scala **2.13.17**, Chisel **7.3.0**, and GSIM revision
**93b8cd23edd3228807c4f2a08c19c3936a463cb2** with the repository
`simulator/gsim/tool_fixes/init-byte-span.patch`, SHA256
`f17fe768c9b4665b310dc632e64333ae3d4e336521f60981f1ec7faaebc31c11`.
The original native epoch used Clang **19.1.7**, ASan and UBSan. Deterministic
initialization is qualified; randomized initialization is not. Version strings alone
are insufficient: preserve exact tool sources/binaries, compiler/runtime dependencies,
JVM/classpath, initialization-fix and qualification-receipt hashes. Use the repository
initialization-epoch verification protocol with a receipt matching its schema, or the
independently reviewed restored-tool qualification contract. Do not present an older
machine's receipt as proof of a new binary or bypass a failed initialization test.
The guard/reset sequence in this host is not a substitute for the GSIM initializer fix.
No Verilator, legacy emulation fallback, broad regression or synthesis is implied.

## Fresh model workflow (parameterized, not an execution admission)

Set `REPO` to this checkout, `HOST` to this directory, and `OUT` to a new empty output
root. `JAVA`, `QUALIFIED_TEST_CP`, `GSIM` and `CXX` come from a qualified tool receipt;
do not silently use unrelated system tools. A coherent Scala compile/source/classpath
receipt, scoped configuration checks and full-hierarchy combinational-loop review
precede GSIM generation. Each variant requires its own output directory because both
have the same top and generated C++ type:

```bash
"$JAVA" -Xmx3g -XX:ActiveProcessorCount=2 -cp "$QUALIFIED_TEST_CP" \
  ooo.MulLoadOperandCaptureBackendGsimMain "$OUT/off" off
"$JAVA" -Xmx3g -XX:ActiveProcessorCount=2 -cp "$QUALIFIED_TEST_CP" \
  ooo.MulLoadOperandCaptureBackendGsimMain "$OUT/on" on
# MODEL_DIR is exactly one of the fresh OFF/ON directories.
"$GSIM" --threads=1 --dir="$MODEL_DIR" \
  "$MODEL_DIR/MulLoadOperandCaptureBackendGsim.fir"
```

Review actual generated header/CPP ABI and CURRENT/NEXT step semantics before native
compilation. In particular check full 64-bit tags, 4-bit ROB indices, 6-bit physical
sources/destinations, 48-bit ready mask, scalar row/slot interfaces, registered capture
phase and reset/initialization byte span. Generation exit zero is not behavior PASS.
The class name is `SMulLoadOperandCaptureBackendGsim` in both models.

After appropriate admission, command shapes for each model are:

```bash
CXXFLAGS=(-std=c++20 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all)
"$CXX" "${CXXFLAGS[@]}" -I"$MODEL_DIR" \
  -c "$MODEL_DIR/MulLoadOperandCaptureBackendGsim0.cpp" -o "$MODEL_DIR/dut.o"
"$CXX" "${CXXFLAGS[@]}" -I"$MODEL_DIR" -I"$HOST" \
  -c "$HOST/backend_host.cpp" -o "$MODEL_DIR/host.o"
"$CXX" -fsanitize=address,undefined "$MODEL_DIR/host.o" "$MODEL_DIR/dut.o" \
  -ldl -o "$MODEL_DIR/run"
# MODE must match that object's profile; examples are NOT a replacement for descriptors.
"$MODEL_DIR/run" ready-variants --profile="$MODE"
"$MODEL_DIR/run" source1 --profile=on --observer-high-tag
```

The last example intentionally exits 1 and requires its exact negative descriptor.
A descriptor-aware runner must preserve original timeout, exit, markers, stderr and
sanitizer checks, record raw streams plus command/source/tool/executable hashes, and
reject `COVERAGE_NOT_REACHED`. Use the reviewed sequential two-CPU / sampled 4-GiB
process-tree RSS / 512-MiB reserve guard; report unavailable cgroups honestly. The
maximum command bound is 900 seconds; each case retains its 120-second bound. The
historical environment was `ASAN_OPTIONS=detect_leaks=0:abort_on_error=1` and
`UBSAN_OPTIONS=halt_on_error=1`, not a clean LeakSanitizer claim. Never overwrite failed
attempts or repeat unchanged model generation to mask a failure.

## Post-seal relocation continuity proposal

For this byte-identical path relocation alone, do **not** regenerate or rebuild either
DUT object. A new independent hostbuild gate must bind the two existing correct-profile
headers/objects, their original generated/object/ABI/source/tool receipts, and these
relocated host/helper bytes. Compile one new host per header and link to its matching
unchanged object in fresh output directories. An actual-executable case gate then
admits only six positive descriptors:

- OFF `ready-variants`;
- ON `source1`, `source2`, `same-producer`, `load-error`, `page-fault`.

These check include/path continuity, not a rerun of all 28 or new coverage of the gaps.
Keep exact original expectations and compare raw results with their historical
matching-model case only as an additional read-only continuity check. Queue native
work behind an active mapping job rather than stealing its resource allocation.
This is a proposed short check, not a claim it has run or a portable authorization to
reuse arbitrary objects. Fresh checkouts need the qualified fresh-model flow above.
