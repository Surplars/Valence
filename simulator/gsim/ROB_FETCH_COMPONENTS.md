# Reproducible ROB/fetch component entry

`run_rob_fetch_components.py` is an explicit-stage GSIM component runner. It
never compiles production implicitly, never emits a CPU, and never invokes
physical implementation. `emit`, `generate`, `build`, and `run` are separate
commands. All source/test/host/catalog paths are repository-relative. Tool,
classpath, model and output locations are caller-supplied.

## Scope and activation

The component constructors retain `bankedCompletionPayload=false` and
`compactCacheKeys=false` defaults. The paired wrappers explicitly enable their
candidate side. The current strict two-wide board integration separately
selects `IntegerBackend.qualifiedBankedCompletionPayload` and
`MachinePlatform.qualifiedCompactFetchKeys`; its actual-enable audit belongs to
the combined CPU/board entry. A component result cannot establish that enable,
CPU execution, board qualification, mapped resources, or timing improvement.

`rob_fetch_public_inputs.json` pins the 11 unchanged Scala/C++/oracle leaves.
`rob_fetch_qualified_models.json` pins the original isolated ROB and fetch source
closures, original qualification/compile/case/freeze receipt hashes, and every
root-level model artifact including its host binary. It contains hashes and
relative names only. No model or binary is distributed here.

The catalog deliberately describes historical isolated source snapshots. A
newer combined source tree, even with only unrelated changes, is not silently
substituted. Use the exact corresponding source snapshot for historical replay,
or produce a fresh model from the new complete source closure. A successful
replay says `reusedQualifiedModel=true`, `productionRecompiled=false`,
`gsimRegenerated=false`, and `hostRebuilt=false`.

## Replay an already qualified model

Set `REPO` to its matching source snapshot plus these public test/host leaves,
`MODEL` to the existing model directory, and `OUT` to a fresh output directory.
The runner itself can be invoked from any current working directory.

```sh
python3 simulator/gsim/run_rob_fetch_components.py run \
  --repo-root "$REPO" --model-dir "$MODEL" \
  --qualified-model rob-s16-positive --out "$OUT"
```

The ROB positive host is invoked without arguments and must produce all four
primitive-size markers (4/8/16/32), the payload oracle, the unchanged retirement
oracle, and the final pair marker. ROB negatives alone use `--payload-only`.

Catalog cases:

- `rob-s16-positive`, `rob-s16-wrong-writer-map`, `rob-s16-missing-allocation-zero`
- `keys-s4-positive`, `keys-s16-positive`, `keys-s256-positive`
- `native-s4-positive`, `native-s16-positive`
- `unstaged-s16-positive`, `no-window-s16-positive`
- `keys-s16-wrong-boundary-borrow`, `native-s16-stale-capture-enabled`

For a negative, first materialize a real one-file Scala mutation outside `REPO`:

```sh
python3 simulator/gsim/run_rob_fetch_components.py mutate \
  --repo-root "$REPO" --kind wrong-writer-map --out "$MUTANT"
python3 simulator/gsim/run_rob_fetch_components.py run \
  --repo-root "$REPO" --model-dir "$NEGATIVE_MODEL" \
  --qualified-model rob-s16-wrong-writer-map --mutation-dir "$MUTANT" --out "$OUT"
```

The generated source and declaration must match the exact original and mutated
source hashes in the qualified model. Generating that source does not claim it
was newly compiled. Sanitizer/runtime errors and missing oracle markers fail.
The stale-capture negative intentionally triggers the original paired hardware
assertion, and additionally requires the exact live-row/stale-owner witness.
An arbitrary nonzero exit, compiler error, or unrelated assertion is insufficient.

## Fresh explicit stages

A successful isolated Scala compiler receipt is the input to `bind-classpath`.
Standard Mill does not produce this receipt schema automatically. The following
opt-in recipe creates fresh isolated main/test classes and the required receipt
from a checkout. It runs real Scala compilation and writes PASS only after both
compiler processes succeed; it was not executed during this packaging change.

Set `REPO`, a fresh `CLASS_BUILD`, `MODE` (`rob` or a fetch mode), `JAVA`,
`JAVA_SHA256`, `CHISEL_PLUGIN`, and `CHISEL_PLUGIN_SHA256`. `DEPS_CP` is the
path-separated pinned Scala/Chisel compiler/runtime JARs plus the existing
HardFloat classes, with no application classes. `RESOURCE_CP` optionally adds
non-class resource directories. For a source negative, first run `mutate` above
and additionally set `KIND` and `MUTANT`; the compiler input list replaces that
one production source instead of compiling both definitions.

```sh
python3 - <<'PYCOMPILE'
import hashlib, json, os, subprocess, zipfile
from pathlib import Path

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

root = Path(os.environ['REPO']).resolve()
out = Path(os.environ['CLASS_BUILD']).resolve()
java = Path(os.environ['JAVA']).resolve()
plugin = Path(os.environ['CHISEL_PLUGIN']).resolve()
assert sha(java) == os.environ['JAVA_SHA256']
assert sha(plugin) == os.environ['CHISEL_PLUGIN_SHA256']
deps = [Path(p).resolve() for p in os.environ['DEPS_CP'].split(os.pathsep)]
for p in deps:
    names = ([str(f.relative_to(p)) for f in p.rglob('*.class')]
             if p.is_dir() else zipfile.ZipFile(p).namelist())
    assert not any(n.startswith(('soc/', 'ooo/')) for n in names)
catalog = json.loads((root / 'simulator/gsim/rob_fetch_qualified_models.json').read_text())
group = 'rob' if os.environ.get('MODE', 'rob') == 'rob' else 'fetch'
main = sorted((root / 'src/main/scala').rglob('*.scala'))
tests = [root / p for p in catalog['sourceClosures'][group]
         if p.startswith('src/test/scala/') and p.endswith('.scala')]
kind = os.environ.get('KIND', 'positive')
if kind != 'positive':
    mutation_root = Path(os.environ['MUTANT']).resolve()
    mutation = json.loads((mutation_root / 'mutation.json').read_text())
    assert mutation['kind'] == kind
    old = root / mutation['sourceRelativePath']
    replacement = mutation_root / mutation['sourceRelativePath']
    assert sha(old) == mutation['candidateSourceSha256']
    assert sha(replacement) == mutation['mutantSourceSha256']
    assert old in main
    main = [replacement if p == old else p for p in main]
inputs = {str(p): sha(p) for p in [*main, *tests]}
out.mkdir(parents=True, exist_ok=False)
for phase, sources in [('main', main), ('test', tests)]:
    destination = out / ('classes-' + phase)
    destination.mkdir()
    cp = deps if phase == 'main' else [out / 'classes-main', *deps]
    command = [str(java), '-Xmx4g', '-XX:ActiveProcessorCount=2',
               '-Dchisel.project.root=' + str(root), '-cp', os.pathsep.join(map(str, deps)),
               'scala.tools.nsc.Main', '-language:reflectiveCalls', '-deprecation',
               '-feature', '-Xcheckinit', '-Ymacro-annotations', '-Xplugin:' + str(plugin),
               '-classpath', os.pathsep.join(map(str, cp)), '-d', str(destination),
               *map(str, sources)]
    with (out / ('compile-' + phase + '.log')).open('x') as log:
        subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
assert inputs == {str(p): sha(p) for p in [*main, *tests]}
resources = [root / 'src/main/resources', root / 'src/test/resources']
resources += [Path(p).resolve() for p in os.environ.get('RESOURCE_CP', '').split(os.pathsep) if p]
cp = [out / 'classes-test', out / 'classes-main', *deps, *[p for p in resources if p.exists()]]
receipt = {'status': 'PASS_ISOLATED_COMPONENT_CLASSES', 'old_application_classpath': False,
           'sources': inputs, 'classpath': list(map(str, cp)),
           'classes': {str(p.relative_to(out)): sha(p) for p in out.rglob('*.class')}}
(out / 'compile.json').write_text(json.dumps(receipt, indent=2) + '\n')
PYCOMPILE
COMPILE_RECEIPT="$CLASS_BUILD/compile.json"
```

The existing isolated compiler flow records `status`, `sources`, `classes`,
`classpath`, and `old_application_classpath=false`. This binding command checks
those actual source/class bytes and automatically produces the portable
`classpath.json`; do not hand-author a success declaration. The receipt's first
two classpath entries are the isolated test and main classes directories, in
that order. `CP` must match its ordered classpath, omitting only nonexistent
resource entries. No old application classes may occur in a dependency or in a
second application entry. Application class duplicates are rejected.

```sh
CP="$(python3 - "$COMPILE_RECEIPT" <<'PY'
import json, os, sys
from pathlib import Path
r = json.loads(Path(sys.argv[1]).read_text())
print(os.pathsep.join(p for p in r['classpath'] if Path(p).exists()))
PY
)"
python3 simulator/gsim/run_rob_fetch_components.py bind-classpath \
  --repo-root "$REPO" --mode rob --compile-receipt "$COMPILE_RECEIPT" \
  --classpath "$CP" --out "$BOUND_CP"
python3 simulator/gsim/run_rob_fetch_components.py emit \
  --repo-root "$REPO" --mode rob --classpath "$CP" \
  --classpath-manifest "$BOUND_CP/classpath.json" \
  --java "$JAVA" --java-sha256 "$JAVA_SHA256" \
  --firtool "$FIRTOOL" --firtool-sha256 "$FIRTOOL_SHA256" --out "$MODEL"
python3 simulator/gsim/run_rob_fetch_components.py generate \
  --repo-root "$REPO" --model-dir "$MODEL" \
  --gsim "$GSIM" --gsim-sha256 "$GSIM_SHA256"
python3 simulator/gsim/run_rob_fetch_components.py build \
  --repo-root "$REPO" --model-dir "$MODEL" \
  --cxx "$CXX" --cxx-sha256 "$CXX_SHA256"
python3 simulator/gsim/run_rob_fetch_components.py run \
  --repo-root "$REPO" --model-dir "$MODEL" --out "$OUT"
```

Tool hashes come from the selected pinned toolchain. `bind-classpath` verifies
all compiled production Scala sources against the repository and binds the
public fixtures. Fresh negatives require a successful isolated compiler receipt
that actually compiled the generated replacement source, with every other
production source and test unchanged. Pass the same `--kind` and
`--mutation-dir` to binding/emission, and `--mutation-dir` to subsequent stages.
This runner does not manufacture compiler success or compile an overlay over an
unverified application classpath.

For fetch, use `--mode keys|native|unstaged|no-window --sets N` at binding/emission.
The exact emitters are:

- `ooo.RobCompletionPayloadGsimMain OUTPUT`
- `ooo.CompactFetchCacheKeysGsimMain OUTPUT SETS`
- `ooo.CompactFetchFrontendGsimMain OUTPUT SETS [unstaged|no-window]`

The build uses `CACHE_SETS=N`, `FETCH_WINDOW=(mode != no-window)`, and
`FETCH_STAGED=(mode == native)`. The ROB top has fixed wrapper geometry.
`verify` checks the same model/source binding without executing a binary.
Fresh-model declarations are generated stage-by-stage; historical reuse must
select the immutable catalog rather than supplying a fabricated reuse manifest.

## Validation of this public entry

All 12 catalog cases were actually replayed through this public host entry.
The four source mutants were freshly generated and matched the original
qualified mutated-source hashes. Both original isolated compile receipts were
successfully converted with `bind-classpath`. Rejection tests covered changed
source hashes/closure, changed binary hashes, undeclared model units, arbitrary
reuse manifests, missing mutations, old application classes on the dependency
classpath, incomplete positive markers, missing stale-owner witness, sanitizer
failures, compiler-only failure text, and zero-exit negatives.

The public entry validation did not compile production Scala, emit new GSIM,
compile C++, run a new combined CPU, or run a board/physical flow. Fresh emit,
generate, and build support is provided but was not executed for this packaging
change. Coverage remains the original component coverage: frontend N4/N16,
key-helper N4/N16/N256, PMP entry 0 programmed, other PMP entries OFF, and no
independent-payload-capture/window-without-history claim.
