# Fixed common-host branch/control fixture v1

This is a test-only envelope around the unchanged
`simulator/gsim/payloads/branch-program.S`. It is a newly qualified common-host
fixture, **not reproduction of a historical GCC bare-core binary**. It changes no
RTL, default feature flags, memory service or published profile. No installation,
network fetch, hardware generation, simulator launch or fallback is automatic.

## Contract and independent reference

The guest is RV64I/LP64, uncompressed and unrelaxed, with entry/text at
`0x80200000` inside 128 KiB RAM. The common two-instruction ROM trampoline at
`0x80000000` is unchanged; its x31 write remains architectural. The original
branch body is textually included, not rewritten. The wrapper appends a retiring
ROI-end NOP, a completion NOP, terminal EBREAK and 128 speculative padding NOPs.
ROI is half-open `[roi_begin, roi_end)` and excludes boot/tail. EBREAK must trap
once with cause 3 and tval equal terminal PC; it is not a retired instruction.
Illegal words on wrong paths may never become successful completion. Owner/channel
drain and no post-terminal retirement remain required.

`source-reference/source_reference.py` independently interprets the fixed source
operations and encodes their bytes; it imports neither DUT nor repo ISA logic.
Its result was sealed before comparison with the separate existing software
ISA through `isa-reference/branch_isa.h`. The latter deliberately does not weaken
or call the CoreMark-specific completion check. The two references agree on the
entire 240-event architectural trace, all GPRs, 236-instruction ROI and terminal
metadata. `source-gold.h` is the sealed source-side trace, not DUT-derived output.
`host/branch_gold.h` checks every reference event and final state against it.

Original qualification used 21 Python semantic/checker test groups, 31 actual
ELF/transcript corruption cases, separate ISA envelope negatives and a C++ gold
checker. Portability reproduction is a connection/byte-continuity check, not a
fresh CPU performance sample or broader ISA qualification. The fixture contains
no load/store/MUL work; it does not establish general application or MUL benefit.

The original [matched result](results/matched-result.json) is unchanged: both
OFF and ON took **319 ROI cycles and 359 whole-work cycles**, a **0%** equal-clock
cycle improvement. See the [qualification report](../../../../docs/common-a1-branch-control-fixture.md)
for the retained checks and limitations. The portable recipe below does not
repeat that CPU measurement or establish frequency/board performance.

## Pinned tools and guest reproduction

`pinned-inputs.json` records the source checkpoint/tree, fixture/shared-source
hashes, exact generated OFF/ON model hashes, approved object receipt identities,
and tool/guest identities. The guest compiler is Debian Clang 19.1.7 and linker is
Debian LLD 19.1.7, package version `1:19.1.7-3+b1`. The LLD package was verified
against signed official Debian metadata and extracted only to a workspace;
dependencies reused the hash-verified native closure. Package/metadata hashes
are retained in the pins. No claim is made that an arbitrary same-version binary
or incomplete runtime closure is equivalent.

Provide the already qualified tool paths and runtime library environment:

```sh
F="$REPO/simulator/gsim/fixtures/branch_control_common_v1"
export PYTHONDONTWRITEBYTECODE=1
# CXX, LINKER, NM and LD_LIBRARY_PATH refer to the qualified local tool closure.
python3 "$F/build_guest.py" --cxx "$CXX" --linker "$LINKER" --nm "$NM" \
  --out "$OUT/guest"
```

The output must be fresh/empty. Both original and wrapper are assembled once;
the wrapper is linked once. The script verifies tool bytes/version, executable
ELF/layout, original body preservation and independent source encoding, then
requires **exact existing ELF and symbol-text hashes**. Failure is retained and
must be investigated; never update pins merely to bless drift. The linker must
be invoked as `ld.lld` or `ld.lld-19`: resolving that symlink to generic `lld`
breaks flavor selection. Host GNU `nm -n` is separately byte/version pinned.
An ET_REL object is never treated as executable.

## Software-only portability checks

```sh
H="$REPO/simulator/gsim/harness"
python3 "$F/test_build_guest.py"
python3 "$F/source-reference/test_source_reference.py"
"$CXX" -std=c++20 -O1 -g -fsanitize=address,undefined \
  -fno-sanitize-recover=all -I"$F/isa-reference" \
  -I"$H/context_fetch_prefetch/shared" -I"$H" \
  "$F/isa-reference/isa_reference.cpp" -o "$OUT/isa-reference"
ASAN_OPTIONS=detect_leaks=0 "$OUT/isa-reference" \
  "$OUT/guest/branch-common.elf" "$OUT/guest/branch-common.symbols" \
  > "$OUT/isa-events.json"
python3 "$F/source-reference/source_reference.py" \
  --source "$REPO/simulator/gsim/payloads/branch-program.S" \
  --elf "$OUT/guest/branch-common.elf" --compare "$OUT/isa-events.json" \
  --out "$OUT/dual-reference.json" --header-out "$OUT/reproduced-source-gold.h"
cmp "$F/source-reference/source-gold.h" "$OUT/reproduced-source-gold.h"
python3 "$F/source-reference/test_linked_qualification.py" \
  --elf "$OUT/guest/branch-common.elf" --reference "$OUT/isa-events.json" \
  --out "$OUT/negative-checks"
"$CXX" -std=c++20 -O1 -g -fsanitize=address,undefined \
  -fno-sanitize-recover=all -I"$F/host" -I"$F/isa-reference" \
  -I"$F/source-reference" -I"$H/context_fetch_prefetch/shared" -I"$H" \
  "$F/host/check_gold.cpp" -o "$OUT/check-gold"
ASAN_OPTIONS=detect_leaks=0 "$OUT/check-gold" \
  "$OUT/guest/branch-common.elf" "$OUT/guest/branch-common.symbols"
```

These commands run software references only, not a GSIM model. Use a bounded
execution guard and the qualified sanitizer environment. The historical closure
disabled LSAN because of its host limitation; ASAN and UBSAN were tested.

## Host-only compile/link template — no CPU launch

Select `ROLE=control` or `candidate`, the exact generated `MODEL` directory,
matching compiled `OBJECT`, and its byte-pinned `OBJECT_RECEIPT`. Then:

```sh
python3 "$F/check_model_binding.py" --role "$ROLE" --model-dir "$MODEL" \
  --object "$OBJECT" --receipt "$OBJECT_RECEIPT" --out "$OUT/$ROLE-binding.json"
"$CXX" -std=c++20 -O1 -g -fsanitize=address,undefined \
  -fno-sanitize-recover=all -I"$F/aliases/$ROLE" -I"$MODEL" \
  -I"$F/host" -I"$F/isa-reference" -I"$F/source-reference" \
  -I"$H/context_fetch_prefetch/shared" -I"$H" \
  -c "$F/host/branch_common.cpp" -o "$OUT/$ROLE-host.o"
"$CXX" -fsanitize=address,undefined "$OUT/$ROLE-host.o" "$OBJECT" \
  -ldl -o "$OUT/$ROLE-host"
```

Check every exit status before the next command. The binding check is read-only:
it verifies fixture/shared input hashes, exact generated C++/header, role, compiler
flags, object and original qualification receipt. Missing or changed objects
fail closed; there is no regeneration/recompile fallback. Fresh object bytes at
another source/tool/path epoch need a new explicit resource/qualification gate,
not silently revised pins. The original r2 objects were freshly rebuilt from
restored, byte-qualified generated sources; they were **not historical object
reuse**.

CPU execution requires an independent reviewed run gate and external resource
limits. Its fixed input contract is `ELF SYMBOLS branch-control-v1 100000`, with
negative modes `mutate` and `trapmutate`; this README intentionally does not
launch it. The matched boundary keeps 3-cycle first response latency, 8-byte
beats, 16 live entries and existing ownership/backpressure rules. Any future
comparison must report equal-work ROI and whole-work cycles, drain and all I/D
traffic, retaining regressions. No CoreMark rerun, RTL change, map/Fmax/board
claim, Linux expansion or broad regression belongs to this fixture recipe.
