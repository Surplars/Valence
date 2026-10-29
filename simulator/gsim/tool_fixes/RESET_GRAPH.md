# Bounded reset-graph repair

Apply `reset-graph.patch` **after** the existing `init-byte-span.patch` to GSIM
`93b8cd23edd3228807c4f2a08c19c3936a463cb2`. Do not stack the broader historical
`input-vector-init.patch`. `reset-graph-inputs.json` records all 101 final source
hashes and the 13 actual executed fixture/helper hashes. The unchanged
`fixtures/InitByteSpan.{fir,cpp}` and `../harness/gsim_model_storage.h` are reused,
not duplicated. No Valence RTL/reset rewrite is part of this patch.

## Repair and limits

Async CURRENT uses a reset-priority mux with real reset dependencies. Both reset
kinds clamp NEXT after ordinary/partial writes. UInt reset retains its
pre-promotion phase; reset-use types are inferred before register metadata is
repurposed, preserving a shared UInt control's explicit `asAsyncReset` use.
Register-control activation snapshots precede reset processing. Reset references
are protected from replication; initial topology ordering rejects incomplete
visitation. Exact same-reference array holds omit `memcpy`; other copies retain
the existing layout checks.

Five native positives and one exact observer negative passed under ASan/UBSan,
using fresh models and objects from the final tool. Two separate generator-rejection
controls additionally passed; the generator itself is not claimed sanitizer-built. Original old-tool `SYNC_RELEASE_STALE_NEXT` and earlier candidate
`ASSERTED_HOLD_ORACLE` failures remain failures, not extra positives. Intermediate
shared-control typing and array self-copy blockers were repaired without changing
fixed gold. The original managed-network-off FIR subsequently passed its separate
UART/CMU qualification; microtest PASS alone was not used to infer bank PASS.

This is bounded evidence, not general compiler/RTL equivalence, physical CDC,
independent clock timing, or instantaneous setter-edge semantics outside `step()`.
Arbitrary chained UInt reset groups remain unqualified: their live assignment
conditions can depend on another group's same-phase CURRENT writes. Randomized
initialization is not qualified. Array coverage here is a retained three-element
array with dynamic partial writes, not every possible split-array topology.

## Fresh reproduction

Use a clean pinned source checkout, a **new absolute** output directory, a pinned
Clang 19 toolchain and its normal GSIM build dependencies (including Bison/m4).
The snippets below are a reproduction recipe, not a replacement qualification
receipt. Keep original tools/results; never reuse old model objects. Set `repo`,
`upstream`, `out`, and `CXX` to your local paths, then:

```bash
set -euo pipefail
fix="$repo/simulator/gsim/tool_fixes"
test "$(git -C "$upstream" rev-parse HEAD)" = 93b8cd23edd3228807c4f2a08c19c3936a463cb2
test -z "$(git -C "$upstream" status --porcelain --untracked-files=all)"
test ! -e "$out"
mkdir -p "$out/source"
git -C "$upstream" archive HEAD | tar -x -C "$out/source"
(cd "$out/source" && git apply "$fix/init-byte-span.patch" && git apply "$fix/reset-graph.patch")
python3 - "$fix/reset-graph-inputs.json" "$out/source" "$repo" <<'PY'
import hashlib,json,sys
from pathlib import Path
m=json.loads(Path(sys.argv[1]).read_text())
for key,root in [('final_source_sha256',Path(sys.argv[2])),('executed_fixture_sha256',Path(sys.argv[3]))]:
    for name,want in m[key].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==want,name
PY
timeout 900 make -C "$out/source" -j2 CXX="$CXX" GSIM_VERSION=93b8cd23-init-byte-span-reset-graph-r4 build-gsim
gsim="$out/source/build/gsim/gsim"
for top in ResetBaseline AsyncResetGroups InitByteSpan ResetArrays ResetPhases; do
  fixture="$fix/fixtures/reset_graph"
  if test "$top" = InitByteSpan; then fixture="$fix/fixtures"; fi
  model="$out/$top"; mkdir "$model"
  timeout 180 "$gsim" --threads=1 --dir="$model" "$fixture/$top.fir" >"$model/generate.stdout" 2>"$model/generate.stderr"
done
```

Before native compilation, inspect each fresh generated header/CPP: both reset
phases and combined-consumer activation, root-to-derived ordering, held NEXT
priority, actual retained-array layout, absence of identical-pointer `memcpy`,
and real `step()` scheduling must match the fixtures. Successful generation is
not this semantic review. Then compile separately with the same compiler:

```bash
flags=(-std=c++20 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all)
for top in ResetBaseline AsyncResetGroups InitByteSpan ResetArrays ResetPhases; do
  fixture="$fix/fixtures/reset_graph"
  if test "$top" = InitByteSpan; then fixture="$fix/fixtures"; fi
  model="$out/$top"; objects=()
  for cpp in "$model"/"$top"[0-9]*.cpp; do
    obj="${cpp%.cpp}.o"; objects+=("$obj")
    timeout 300 "$CXX" "${flags[@]}" -I"$model" -c "$cpp" -o "$obj"
  done
  timeout 300 "$CXX" "${flags[@]}" -I"$model" -I"$repo/simulator/gsim/harness" -c "$fixture/$top.cpp" -o "$model/host.o"
  timeout 180 "$CXX" "${flags[@]}" "${objects[@]}" "$model/host.o" -ldl -o "$model/run"
  timeout 30 "$model/run" >"$model/stdout" 2>"$model/stderr"
  test ! -s "$model/stderr"
done
```

Require exact single-line positive outputs (InitByteSpan's span is layout-derived):

| Model | Required stdout |
|---|---|
| ResetBaseline | `RESET_BASELINE_PASS cycles=48` |
| AsyncResetGroups | `ASYNC_RESET_GROUPS_PASS held_checks=20 cycles=124` |
| InitByteSpan | `span=<decimal> uncleared=0 tail=0` |
| ResetArrays | `RESET_ARRAYS_PASS checks=24 cycles=97` |
| ResetPhases | `RESET_PHASES_PASS cycles=22` |

Run `AsyncResetGroups/run --mutate-held-observation` once: require exit 1,
empty stdout and exactly two stderr lines, `ASYNC_RESET_MUTANT_REACHED` then
`ASSERTED_HOLD_ORACLE`. For each rejection fixture, use a separate empty output
directory and the same generator command:

| FIR | Expected generator rejection |
|---|---|
| `ResetDependencyCycle.fir` | `incomplete reset/data dependency order` |
| `ResetValueFeedback.fir` | `async reset value has nontrivial CURRENT feedback` |

Both require SIGABRT (Python subprocess return code -6; shell status normally
134), the named diagnostic, and **no generated header/CPP**. A parser error,
other assertion/signal, timeout or sanitizer failure is not an accepted negative.
Assertion backtraces are not stable exact text. Preserve stdout/stderr and exit
status for every command; reject ASan/UBSan/LSan diagnostics in every stage.

The executed qualification used 29 guarded commands, at most four CPUs, 4 GiB
sampled process-tree RSS with 512 MiB reserve, and the per-command limits above.
Use an equivalent process-tree resource/cleanup supervisor when reproducing;
`timeout` alone is not a memory or process-tree identity guard. No hard cgroup
limit was claimed. Record a fresh source/tool/compiler/generated/ABI/result-bound
receipt before using a locally rebuilt tool for additional hardware tests.
