# Context-owned instruction prefetch: portable cache contracts

This is a source checkpoint, not a portable copy of machine-local admission gates.
`context_cache.cpp` is a **byte-identical** copy of the qualified last-stale seed-only
component host. Its first-line DRAFT comment is retained solely to preserve that byte
identity; the historical original passed 31 positive cases for each of flat and banked
cache. The newly located source has not thereby been recompiled or requalified.
`cases.json` carries the exact 31 original case argument/exit/marker/stderr descriptors
once, plus both variant argument lists. All 62 are positive contracts; the older
age/buffer/translation negative tests are not included or claimed as rerun here.
`contract_oracle.h` is the shared independent owner/PMP/byte-memory oracle. The host
includes only local/generated headers; no old workspace absolute include is needed.

## Tool and source qualification

Use the repository-pinned Mill **1.1.7**, Scala **2.13.17**, Chisel **7.3.0**, and GSIM
revision **93b8cd23edd3228807c4f2a08c19c3936a463cb2** with the repository
`simulator/gsim/tool_fixes/init-byte-span.patch` (SHA256
`f17fe768c9b4665b310dc632e64333ae3d4e336521f60981f1ec7faaebc31c11`).
Only deterministic initialization is qualified; randomized initialization is not.
The observed native epoch was Clang **19.1.7** with ASan/UBSan. A version string alone
is not enough: pin actual compiler/runtime dependencies, JVM, Scala classpath, GSIM
source/binary, fix and qualification regression hashes in a fresh receipt. Use
`simulator/gsim/gsim_initialization_epoch.py` tool-binding verification; explicitly set
`VALENCE_GSIM_INIT_RECEIPT` to that receipt, and do not substitute unqualified system
binaries or suppress initialization checks. Read the parent GSIM/tool-fix documentation.

## Fresh model workflow (parameterized recipe, not an execution gate)

`REPO` is this checkout; `HOST` is this directory; `OUT` must be new and empty.
`JAVA`, `QUALIFIED_TEST_CP`, `GSIM` and `CXX` come from the verified local tool receipt,
not implicit PATH assumptions. A coherent fresh Scala compile plus source/classpath
receipt and whole-hierarchy combinational-loop checks precede generation. Example
command shapes, each to be invoked through the reviewed bounded command guard:

```
"$JAVA" -Xmx4G -XX:ActiveProcessorCount=2 -cp "$QUALIFIED_TEST_CP" \
  ooo.ContextOwnedInstructionPrefetchGsimMain "$OUT/flat"
"$JAVA" -Xmx4G -XX:ActiveProcessorCount=2 -cp "$QUALIFIED_TEST_CP" \
  ooo.ContextOwnedInstructionPrefetchGsimMain "$OUT/banked" --banked-instruction-data
"$GSIM" --threads=1 --dir="$MODEL_DIR" "$MODEL_DIR/ContextOwnedInstructionPrefetchGsim.fir"
```

`MODEL_DIR` is one variant's output. Verify actual generated CPP/header ABI and phase
semantics before C++: scalar PMP configuration inputs 8 bits/address inputs 54 bits,
full source/owner widths, held payload, observer taps, initialized span and current/NEXT
state. Never equate generation exit zero with passing a behavioral contract.

For each model, use these command shapes (CXXFLAGS is an array, not shell text):

```
CXXFLAGS=(-std=c++20 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all)
"$CXX" "${CXXFLAGS[@]}" -I"$MODEL_DIR" -c "$MODEL_DIR/ContextOwnedInstructionPrefetchGsim0.cpp" -o "$MODEL_DIR/dut.o"
"$CXX" "${CXXFLAGS[@]}" -I"$MODEL_DIR" -I"$HOST" -c "$HOST/context_cache.cpp" -o "$MODEL_DIR/host.o"
"$CXX" -fsanitize=address,undefined "$MODEL_DIR/host.o" "$MODEL_DIR/dut.o" -ldl -o "$MODEL_DIR/run"
"$MODEL_DIR/run" basic
```

A descriptor-aware runner must supply every `cases.json` argument list, verify exact
exit=0, required marker and empty stderr, reject sanitizer diagnostics, and retain
stdout/stderr/started/terminal receipts plus source/tool/executable hashes. There is no
stdout/cycle equality assertion between variants; report observed differences. Use the
reviewed sequential 2-CPU / sampled 4-GiB process-tree RSS / 512-MiB reserve guard;
report cgroup unavailability honestly, preserve failures, never overwrite attempts.
Historical sanitizer environment was `ASAN_OPTIONS=detect_leaks=0:abort_on_error=1`,
`UBSAN_OPTIONS=halt_on_error=1`; disabling leak checks was disclosed, not a clean-LSan
claim. No Verilator, CPU benchmark, broad regression or PPA work is implied.

## Post-seal path-only validation proposal

For this relocation alone, do **not** regenerate or recompile DUTs. A new independent
host-only gate can bind both already-qualified cache headers/objects and original
object/ABI/source/tool receipts, the relocated host/oracle hashes, and a fresh output
directory. Compile the relocated host once per header and link against its matching
unchanged DUT object (never mix flat/banked objects). Run only `basic` and the four
`last-stale-*` cases per variant (10 positive checks), after the reviewer admits actual
new executable hashes. Preserve exact descriptor expectations. This is a proposed
minimal path/include continuity check, not authorization or a claim it has run.
A fresh checkout needs the full fresh-model workflow above; old absolute machine-local
gates are evidence of the original run, not portable execution authority. Relocation
belongs to a post-seal source epoch and must not relabel the older DUT build epoch.
