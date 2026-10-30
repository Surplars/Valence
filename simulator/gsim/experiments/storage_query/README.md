# Storage / recovery-query experiment reproduction

This is a **test-only supported reproduction entry**, not production query plumbing
or a default-profile promotion. Production `RenameRob` exposes a default-off
`experimentalCompletionDataStorage` constructor argument. The storage overlay
alone enables that argument; the query overlay additionally substitutes the
parallel recovery helper and two completion-age queries. Neither changes
`OooParams`, enables split-tag arithmetic, adds pipeline stages, nor changes
capacity/throughput contracts. Supported matched pairs are ROB/PRF 16/48 and
32/64, both LSU4; the measured query CPU comparison used 32/64.

The two small patches and subclass are copied from the tested experiment.
`base_hashes.json` pins the three affected production source files, patch assets,
and exact generated source bytes. `prepare.py` refuses drift, patch fuzz,
overwriting an existing output directory, and output outside repository `build/`.
No giant backend source copy, compiled class, simulator model, RTL, local report,
or private artifact identity belongs in this directory. Future source changes
require explicit re-review and requalification; do not merely refresh hashes.

## Source-only check

From repository root (Python 3.9+):

```sh
python3 simulator/gsim/experiments/storage_query/test_prepare.py
python3 simulator/gsim/experiments/storage_query/prepare.py \
  --out build/storage-query-source-check
```

The latter creates `storage/IntegerBackend.scala` and three query sources in a
fresh directory. It neither compiles nor runs hardware. The two unit tests cover
exact generation, context mismatch, source drift, existing output and forbidden
output rejection. They are not simulation or equivalence proofs.

## Isolated Scala compile and ordinary tile export

First build the normal, unmodified-default project using its supported tools:

```sh
mill -i IonSoC.test.compile
mill -i show IonSoC.test.runClasspath
mill -i show IonSoC.scalaCompilerClasspath
mill -i show IonSoC.scalacPluginClasspath
```

Review the recorded missing entries: only nonexistent optional resource directories
may be omitted; missing classes or dependency jars mean the build is incomplete.
Use the matching Scala compiler and Chisel compiler plugin from that build
(currently Scala 2.13.17 / Chisel 7.3.0), not a system `scalac` with unknown
versions. Java and the project's firtool must be available. The following reads
Mill's generated classpath metadata, retaining absolute paths on **this** machine:

```sh
mkdir -p build/storage-query-classpaths
python3 - <<'PY'
import json, os
from pathlib import Path
out = Path('build/storage-query-classpaths')
missing = {}
def paths(target):
    values = json.loads(Path('out/' + target + '.json').read_text())['value']
    entries = [v.split(':', 3)[3] for v in values]  # Mill qref:v1:hash:absolute-path
    missing[target] = [p for p in entries if not Path(p).exists()]
    return [p for p in entries if Path(p).exists()]
(out / 'runtime.txt').write_text(os.pathsep.join(paths('IonSoC/test/runClasspath')) + '\n')
(out / 'compiler.txt').write_text(os.pathsep.join(paths('IonSoC/scalaCompilerClasspath')) + '\n')
plugins = [p for p in paths('IonSoC/scalacPluginClasspath') if '/chisel-plugin_' in p.replace('\\', '/')]
assert len(plugins) == 1
(out / 'plugin.txt').write_text(plugins[0] + '\n')
(out / 'missing-entries.json').write_text(json.dumps(missing, indent=2) + '\n')
print('Review omitted nonexistent Mill resource directories:', missing)
PY
python3 simulator/gsim/experiments/storage_query/run.py \
  --repo "$PWD" --out build/storage-query-export32 \
  --runtime-classpath-file build/storage-query-classpaths/runtime.txt \
  --compiler-classpath-file build/storage-query-classpaths/compiler.txt \
  --chisel-plugin "$(cat build/storage-query-classpaths/plugin.txt)" --rob 32
```

`run.py` compiles only the isolated overlay sources into each role's own
`classes/`; it never writes `src/` or shared `out/`. Runtime classpath order is
**role overlay classes first, normal test runtime classpath second**, with no
other experiment overlay. Java class-load logs are checked: the storage backend
and query backend/ledger/subclass must come from their role classes; the inherited
helper and storage ledger must come from normal `out/IonSoC/compile.dest/classes`.
These checks reject stale overlay precedence; always build normal classes first.
It invokes the existing
`platform.CommonA1CapacityTileMain <fresh-output> 32 64` (or `16 48`). This exports
plain `CommonA1CpuTile`, not a GSIM observation wrapper. It checks identical SV
file sets, exactly `RenameRob.sv` and `ParallelRecoveryAdmission.sv` changed,
and byte-identical effective parameters/configuration/CPU identity JSON.
Constructor overrides are deliberately *not* encoded by those unchanged profile
JSONs: keep the overlay `IDENTITY.json`, classpath and commands beside exports.
All command exits and stdout/stderr are recorded; there is no wall-clock or
memory-triggered automatic termination. Stop on any failed check.

For a GSIM CPU emitter, use the **same role-first classpath** and the established
GSIM fixture/driver with identical traffic and service laws on both sides; never
mix query classes into a production-default test or the storage denominator.
This script does not build/run GSIM models or launch synthesis. Previous helper
full-input proofs and one short matched CPU test do not replace fresh validation
after source/tool changes. A successful `EXPORT_REVIEW.json` means matched
export only, not simulation, physical timing, Fmax, or board qualification.
