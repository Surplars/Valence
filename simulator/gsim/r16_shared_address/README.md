# Exact R16 shared-memory-address-state gate

This is a source-only preservation and reproduction entry for the already reviewed,
bounded ROB16/PRF48/LSU4/tag64 two-issue component gate. The sealed positive result is
`PASS_EXACT_R16_SCOPED_GSIM_PAIR`, supplemented by
`PASS_FULL_WIDTH_SUPPLEMENT_AND_BIT64_NEGATIVE`; the separate real-source lane mutation is rejected
by the unchanged independent payload oracle. `sharedMemoryAddressState` remains
**default OFF**. No production file, preset, flag, capacity or timing constraint is
changed by this increment. There is no CPU, NEMU, board or physical qualification.

## Published files and binding

- `src/test/scala/ooo/R16SharedAddressNative.scala`: byte-exact native census wrapper.
- `src/test/scala/core/ooo/R16SharedAddressGsim.scala`: byte-exact scalar-port GSIM
  wrapper. The older top-level Vec ABI is unsupported; pinned GSIM generated
  invalid C++ for it. Do not substitute that wrapper.
- This directory's `host.cpp`, `initialize.h`, `snapshot.h` and
  `snapshot-contract.json`: byte-exact final host/initialization and corrected
  full-width scalar contracts from the width supplement.
- `compare.py` and `WIDTH_CORRECTION.md`: sealed full-width comparator and explicit
  correction of the original low-64-bit-only observation of 32 UInt65 PMP outputs.
  `WIDTH_REVIEW.md` independently reviews that correction and its bounded claim.
- `../compile_r16_shared_address.py`: pinned Mill dependency binding and fresh
  isolated HardFloat/production/test compilation; no existing application classes.
- `../run_r16_shared_address.py`: explicit fresh-class or frozen-input verification, bounded model
  build, and exact fixed-seed run entry. It never compiles production hardware,
  enables an option in a preset, emits a CPU, invokes Vivado or invokes Verilator.
- `../test_r16_shared_address.py`: host-only rejection tests; no hardware tool run.
- `qualified_inputs.json`: committed source/class/dependency/model hashes,
  complete 177-field actual constructor products, scalar ABI, evidence mapping,
  expected witness counts and output hashes. These are metadata, not build products.
- `FAILURE_HISTORY.md` and `INDEPENDENT_REVIEW.md`: byte-exact sealed historical
  accounts. Relative artifact names in these preserved documents refer to the
  original evidence layout described below, not files shipped in this directory.

The manifest binds all 244 source inputs and all 988 original main/test classes,
plus HardFloat classes, resources and dependency JARs. Its classpath is an exact,
ordered inventory. Unexpected files, duplicate application classes and application
fallback classes inside dependency entries fail closed. The absent original test
resources directory is omitted; no fallback classpath is added. Every public test
source is checked against its original bytes. `byteExactPublicationMap` maps each
relocated source to its proven original; `originalEvidence` records the retained
receipts, native audit, generation scripts, qualified results and negative.

Important identities:

- Final host SHA-256: `ba2b970d3c31f7b8402dc877e2e9c94c9491a57d4d4943682d133cf8367e8fb6`
- Scalar fixture SHA-256: `994ff9040a57ad1c49bee99767e0a4cbbb3d15047052fb56d110b350f5c68f9b`
- Original qualification SHA-256: `a8b248f44f4e1d982e755a32ad10c23fa1bf772617aae6577f01ae8f4b11755b`
- Full-width qualification SHA-256: `bf10b6b0528c892d5b31e945c307f5550429d5d6e778b975c67a6983a05a9314`
- Full-width supplemental receipt SHA-256: `94cc75d90b380b02d1e39178b2a34d35cd4ab2b66e2899b886a94300ac42a1e2`
- Full-width positive trace SHA-256: `4624bed05032ed2c748adcaa22d81a49a83fa28775e1f2bbe3e5501fe5adc2d8`

## Fresh source path: no private classes or model inputs

Python 3.10+, the repository-supported JDK 21/Mill 1.1.7 environment and pinned
Maven dependencies are required. See `simulator/gsim/README.md` and, when applicable,
`scripts/cloud/README.md` for supported setup. This path compiles all required
application and HardFloat classes from public source. It accepts **new** class
hashes and does not pretend they are the historical binaries.

The source baseline is explicitly commit
`2fa6a4b320814ad2b142d5bf0009c1d2d5475233`, tree
`35d748735d08200d4eea9e397d401b56d463addb`. A newer checkout may contain another
reviewed default-OFF candidate, including the multiplier change at `55b8d6ee`.
That source is not silently substituted. Use a new detached worktree for this
controlled historical experiment; public runner/host/wrapper files remain in the
current checkout. No source hash refresh or option change is necessary.

From the current repository containing this public entry:

```sh
REPO="$PWD"
SOURCE="$REPO/../valence-r16-source-2fa6a4b"
test ! -e "$SOURCE" && git worktree add --detach "$SOURCE" 2fa6a4b320814ad2b142d5bf0009c1d2d5475233
# Stop if that command fails; do not overwrite or reuse an unrelated directory.
(cd "$SOURCE" && mill -i show IonSoC.test.resolvedMvnDeps)
(cd "$SOURCE" && mill -i show IonSoC.test.scalaCompilerClasspath)
(cd "$SOURCE" && mill -i show IonSoC.test.scalacPluginClasspath)
python3 "$REPO/simulator/gsim/compile_r16_shared_address.py" bind-deps \
  --repo-root "$SOURCE" --out "$REPO/build/r16-fresh-dependencies"
JAVA="$(command -v java)"
sha256() { python3 -c 'import hashlib,pathlib,sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$1"; }
python3 "$REPO/simulator/gsim/compile_r16_shared_address.py" compile \
  --repo-root "$SOURCE" --deps-dir "$REPO/build/r16-fresh-dependencies" \
  --java "$JAVA" --java-sha256 "$(sha256 "$JAVA")" \
  --out "$REPO/build/r16-fresh-classes"
python3 "$REPO/simulator/gsim/run_r16_shared_address.py" verify \
  --repo-root "$SOURCE" --classes-dir "$REPO/build/r16-fresh-classes"
```

Mill resolves JARs only in these commands; it does not compile the application or
execute a test. `bind-deps` reads its ordinary `out/IonSoC/test` metadata and verifies
all 43 dependency/compiler/plugin JAR identities against their committed hashes.
`--mill-metadata-root PATH` may select already resolved metadata from the same pinned
build configuration. This is a cache convenience, never a classpath for old
application classes. JARs containing `soc/`, `ooo/` or precompiled `hardfloat/`
classes are rejected. No cloud-specific path is required by the public entry.

`compile` performs real isolated compilation of 18 vendored HardFloat sources,
all 207 production sources, the selected 37 profile/test dependencies and two
byte-exact public wrappers. The production and HardFloat source inventories must
match exactly, including absence of added Scala sources. It records source hashes,
JARs, Java executable/version, command exits, logs, resources and every newly
produced class. It writes `PASS_FRESH_ISOLATED_CLASSES` only after all three compiler
processes succeed and input hashes are rechecked. This is compilation, not hardware
elaboration or behavioral qualification. The fixed source inventory defines the
selected historical baseline; build/run receipts additionally name its commit/tree.

To produce new bounded models, first use the supported GSIM setup for this source
worktree. The following commands are optional and were not executed during this
publication repair:

```sh
GSIM_CXX=clang++-19 make -C "$SOURCE" gsim-setup
GSIM="${VALENCE_GSIM_SOURCE:-$SOURCE/simulator/build/gsim-src}/build/gsim/gsim"
CXX="$(command -v clang++-19)"
python3 "$REPO/simulator/gsim/run_r16_shared_address.py" build \
  --repo-root "$SOURCE" --classes-dir "$REPO/build/r16-fresh-classes" \
  --java "$JAVA" --java-sha256 "$(sha256 "$JAVA")" \
  --gsim "$GSIM" --gsim-sha256 "$(sha256 "$GSIM")" \
  --cxx "$CXX" --cxx-sha256 "$(sha256 "$CXX")" \
  --gsim-setup-receipt "$SOURCE/build/gsim/toolchain-used.json" \
  --out "$REPO/build/r16-fresh-model"
python3 "$REPO/simulator/gsim/run_r16_shared_address.py" run \
  --repo-root "$SOURCE" --classes-dir "$REPO/build/r16-fresh-classes" \
  --build-dir "$REPO/build/r16-fresh-model" --out "$REPO/build/r16-fresh-runtime"
```

Fresh builds verify the setup receipt against the repository's GSIM revision lock,
record explicit local tool hashes, emit only the bounded scalar-port OFF/ON pair,
check both complete 177-field constructor products and all 382 scalar ABI signatures,
and compile the unchanged host. They do not require historical class hashes.
The C++ flags are `-std=c++20 -O1 -g -fsanitize=address,undefined
-fno-sanitize-recover=all`. Runtime disables LeakSanitizer because the historical
ptrace environment did not support it; ASan/UBSan remain enabled. A host OS/runtime
is not claimed to be hermetic. Native SV census is not rerun by these commands.

`build` reports `BUILT_NOT_RUN`. A subsequent fresh positive execution can report
`PASS_FRESH_EXACT_R16_FULL_WIDTH_COMPONENT_PAIR`; it is a new qualification with
`productionRecompiled=true` and `reusedQualifiedBinary=false`. It must independently
reach the exact witness counts and full-width trace hash. Historical runtime
success is never copied into a new class/model receipt. The fresh path currently
qualifies the positive pair only; a new real-source mutant run is not implied by
it. The historical wrong-lane mutant remains separately audited/replayable below.

Each `--out` must be new. `--timeout N` bounds each subprocess (default 600 seconds).
Class/source/resource/dependency and model inventories are rechecked before/after
runs. Fresh and frozen class modes cannot be combined. There is no arbitrary
classpath, source-baseline refresh, profile, seed or success-marker override.

## Optional historical binary audit/replay

Historical artifacts are not needed by the fresh path above. If an independently
provided archive is available, `FROZEN` may point to its original relative layout:
`timing-batch-r5/build-inputs/`, `timing-batch-r6/area-third-combined-r1/`, and the
`r16-shared-address-native-r1`, `r16-shared-address-gsim-r2`,
`r16-shared-address-lanes-negative-r1` and `r16-shared-address-width-supplement-r1`
evidence directories. The catalog lists exact required paths/hashes. No download
location is implied. Classes/models/objects/executables/logs/traces are not committed.

```sh
python3 "$REPO/simulator/gsim/run_r16_shared_address.py" verify-frozen \
  --repo-root "$SOURCE" --frozen-root "$FROZEN"
python3 "$REPO/simulator/gsim/run_r16_shared_address.py" verify-negative \
  --repo-root "$SOURCE" --frozen-root "$FROZEN"
python3 "$REPO/simulator/gsim/run_r16_shared_address.py" run-frozen \
  --repo-root "$SOURCE" --frozen-root "$FROZEN" --out "$REPO/build/r16-historical-replay"
python3 "$REPO/simulator/gsim/run_r16_shared_address.py" run-negative-frozen \
  --repo-root "$SOURCE" --frozen-root "$FROZEN" --out "$REPO/build/r16-historical-negative"
```

Verification checks original source/class/model bindings, all 50 reused model
objects, supplemental binaries and comparator controls; it reports
`FROZEN_INPUTS_VERIFIED_NOT_RUN`. Frozen replay uses only catalogued exact binaries.
These records establish historical bounded evidence, not a new source compile.

## Publication validation

The fresh compiler was actually executed using the exact historical source closure
and previously resolved, hash-verified Mill JAR metadata from the same build.mill.
All 18+207+37+2 inputs compiled into 1,059 fresh isolated classes. The compiler receipt,
source-selection sidecar and raw logs are retained outside the publication files.
No old application or HardFloat class directory was used. A fresh Maven resolution
was not run during this repair; the documented standard Mill tasks are the public
resolution route. Fresh class receipts pass the public runner's `verify` stage.

Host-only tests cover source/dependency/class drift, fallback classes, ABI widths,
missing witnesses, sanitizer failures, wrong negatives, empty/truncated traces and
bit64 observation. Run them without hardware tools:

```sh
python3 -m unittest discover -s simulator/gsim -p test_r16_shared_address.py -v
```

Historical frozen inputs and saved full-width runtime results were also checked
read-only. The relocated fresh hardware emit/generate/C++/runtime stages remain
unexecuted. The historical separate generation and full-width relink/run receipts
remain the only hardware execution evidence for this publication.

## Sealed result and limitations

Each side reached 1,930 cycles, 449 accepted/397 retired/52 canceled instructions,
58 ordinary-load starts, 109 authorized preparation writes, two actual distinct-row
load+rank0+rank1 write edges, four replay selections, one atomic start, twelve killed
delayed captures, eighteen recoveries and 433 later row-generation reuses. All 16
rows were used. There were 157 requests and exactly 157 replies, and 10,635
valid-payload state checks. A noncanonical serial virtual load, a prechecked virtual
load and a prepared virtual store with VA `0x80401000` versus PA `0x80201000` were
reached. All 244 original public output scalars are compared at their declared width every cycle (276 words): valid bits
remain visible; invalid payloads use only their own validity contract, with the
head-profile payload gated by head validity. Observation signals are checked by the
state oracle separately. Full-width positive OFF/ON traces and raw logs are identical.

The original snapshot narrowed 32 UInt65 PMP regionLow/regionEnd fields before
comparison and therefore did not check their bit64. The historical review and
old trace hash do not establish full-width comparison. The published corrected
serializer writes the high word before narrowing; its separate serializer-only
control flips exactly regionEnd0 bit64 and the trace comparator rejects it. Actual
positive DUT high bits were zero throughout; this proves observation sensitivity,
not a positive high-bit-one DUT traffic witness. The wrong-lane source negative
still fails independently after relinking with the corrected serializer.

The separate real-source negative changes only the shared ordinary-load lane write
from `actualLanes` to `actualLanes ^ 1.U`; the unchanged host fails at the first
incorrect row payload with exit 1 and `FAIL independent row payload mismatch`.
Compilation failure, DUT assertion, trace mismatch or sanitizer failure cannot
substitute for that negative. There is no dropped-token source-negative claim.

The native audit removes 32 declared load-only scalars / 1,104 bits; only
`IntegerBackend.sv` differs among 101 SV files. Shared address/lane rows gain a
third writer alternative and a replay consumer. These are declared-state results,
not measured mapped FF/LUT savings, electrical fanout or STA. No CPU or FPGA result
is inherited from historical R64/PRF64 tests.

Explicitly outside scope: positive write-precheck/frozen-bound-store transport;
real Sv39 walks, permission denial, translation faults, stale epochs or IRQs;
forced bit63 generations; manufactured impossible same-row allocate/write; refetch
of canceled instructions; whole-machine memory ordering; CPU/NEMU/ISA compliance;
physical timing/resources, CDC, PHY and board behavior. The replay oracle observes
DUT check-valid/live/pending/authorization gates and independently checks accepted
owners, canonical payload and oldest match; it is not a second full scheduler.
The synthetic memory service is not a general independent ordering oracle.

Early exploratory failures were console-only and are explicitly summarized in
`FAILURE_HISTORY.md`; no raw transcripts were reconstructed. The invalid Vec ABI,
OFF/ON lane-layout adaptation, LeakSanitizer limitation and three corrected host
assumptions are retained. In particular, inactive noncanonical-load payload is not
a valid PA claim, and a direct head store need not have prepared saved VA. No
production fix was made for those host/fixture issues.
