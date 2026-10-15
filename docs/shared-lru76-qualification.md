# Opt-in shared-LRU76 candidate

## Publication dependency and status

This is an opt-in candidate after the corrected fourth-resource74 package. The verified parent is086ca3ac1637f2fac6e325efdf81573de7494dc2 (tree e76ab6b9f86531e5ee6f693730e3a9d0fc27b1e7). Apply the corrected74 four-file package first: IntegerBackend, AreaFourthResourceMain, area-fourth-resource74-profile.json and its qualification document. The74 package was pending an explicit upload approval when this local source-only package was prepared. Neither package is claimed published here.

Historical73/defaults stay unchanged. Shared-future75 is retained as an experimental comparison profile; it regressed this Bare COPY and is not a selected default. Shared-LRU76 appends only --store-prefetch-lru-victim to75, retaining177 core fields,94 profile fields, original geometry/credits/clocks/service and ordered options. New factory parameters default false. Shared-store-write restoration uses the original complete board predicates, original exact concurrency branch, and a separately permitted normalized branch requiring shared memory state plus future reservation plus LRU. Historical75 remains shared-write=false; exact73/74 behavior remains unchanged.

## Qualified scope

One fresh76 CPU model (38 generated C++ translation units), actual constructor/profile/fabric gates and seven positive/eight designated negative short runtime gates passed. Runtime used unchanged DDR32/read credits8/beatgap1/stalls/guest. Held causal capture780/accept781 remains exact. Actual shared Home lookup, future reservation, LRU, restored shared-store-write, bounded multiplier and shared memory-address witnesses pass. Independent runtime evidence review passed, SHA256 b6c8c0b5621c25d4d5dfd429e1c53442d7e81ca17813a52e861daa939079d9a6. Aggregate qualification SHA256 a1474ba9e4a83028bc19bc649378f67a20630ac9eac7771ccf71bf166fbf16a0.

Inclusive kernel+clean-tail COPY at100MHz,131072 payload bytes:
- Bare:173171 cycles,72.182987MiB/s; +3.69577% throughput versus corrected74 and +9.83767% versus75.
- Sv39:184440 cycles,67.772717MiB/s; +3.89178% versus corrected74, unchanged versus75.

Bare eliminates670 actual source rereads versus75:5360 fewer accepted read beats/42880 bytes; write beats remain18440 including cleanup. Source demand reads704->34, read-prefetch stays2014; rapid rereads670->0. Every classified owner AR is matched to physical AXI events. Sv39 traffic remains unchanged. This is not a universal cache-policy claim. No synthesis, mapped area, routed timing, native-board or physical qualification is claimed.

## Host policy and failure provenance

A hardcoded clean-first historical supply guard initially rejected valid store-LRU selection. The failure is preserved, not counted as a positive. The new host macro STORE_PREFETCH_LRU_VICTIM defaults false and changes only full-set store-origin preference; invalid-first/read clean-first/token consumption/full-PA/opposite-token protection and victim identity assertions remain. Three4096-case original/OFF/ON pure-host passes, six wrong-LRU/PA/protection negative cases and whole preprocessed OFF-guard equality support the change. CPU host observes actual residency/replacement; independent history Policy is used in component/pure-host tests, not claimed as a new CPU history reconstruction.

A held-host link initially mixed identical headers at different physical paths. A single cloned include tree fixed linkage without changing source assertions or the successful COPY/NEMU/PMP runs. The remaining held positive/two negatives were resumed against the same38 objects. Reproduction must avoid mixing header trees; use one staged host and verify compiler dependency output.

## Portable source/configuration reproduction

Use the documented repository toolchain (`simulator/gsim/README.md`). No machine-specific paths are embedded in these commands. Run from repository root, with Mill, Python3, GSIM and clang++19 available. These commands are opt-in and do not alter defaults.

```sh
mill -i IonSoC.test.runMain ooo.SharedLru76ConfigMain
mill -i IonSoC.test.runMain ooo.SharedFuture75FactoryConfigMain
mill -i IonSoC.test.runMain ooo.SharedLru76FactoryConfigMain
python3 simulator/gsim/shared_lru76/prepare_host.py --output build/shared-lru76-host --host-tests --cxx clang++-19
```

`prepare_host.py` copies only hash-verified repository source inputs and the already-published COPY guest into a fresh output directory. Without --host-tests it only stages files. The tests use ASAN/UBSAN; leak detection is disabled consistently with the recorded sandbox environment. It neither emits nor runs a CPU.

Emit the exact option order, not a set or hand-typed partial list:

```python
import json, subprocess
from pathlib import Path
profile = json.loads(Path('fpga/next/shared-lru76-profile.json').read_text())
subprocess.run(['mill', '-i', 'IonSoC.test.runMain', 'ooo.SharedLru76CpuMain',
                'build/shared-lru76-model', *profile['on_options']], check=True)
```

The actual audit must report all six optimizations true and177/94/76. Use fresh output; do not substitute old compiled CPU objects. To reproduce the two COPY positives after the actual constructor audit:

```sh
gsim --threads=1 --cpp-max-size-KB=1024 --dir=build/shared-lru76-model build/shared-lru76-model/BoardSocGsim.fir
```

```python
import json, os, subprocess
from pathlib import Path
stage = Path('build/shared-lru76-host').resolve()
model = Path('build/shared-lru76-model').resolve()
actual = json.loads((model / 'actual-shared-lru76.json').read_text())
assert actual['storePrefetchLruVictim'] is True and actual['sharedStoreWriteData'] is True
flags = json.loads((stage / 'host-flags.json').read_text())
assert '-DSTORE_PREFETCH_LRU_VICTIM=1' in flags
flags += ['-I'+str(p) for p in (stage/'guest', stage/'host', stage/'host/harness', model)]
units = sorted(model.glob('BoardSocGsim[0-9]*.cpp'))
assert units
for unit in units:
    subprocess.run(['clang++-19', *flags, '-c', str(unit), '-o', str(unit.with_suffix('.o'))], check=True)
binary = stage / 'copy-run'
deps = stage / 'copy-host.d'
subprocess.run(['clang++-19', *flags, str(stage/'host/cpu_passive_bandwidth.cpp'),
                *map(str, (p.with_suffix('.o') for p in units)), '-MD', '-MF', str(deps),
                '-o', str(binary)], check=True)
assert str(stage/'host/supply_ledger.h') in deps.read_text()
for mode in (0, 1):
    work = stage / ('copy-bare' if mode == 0 else 'copy-sv39')
    work.mkdir()
    env = {**os.environ, 'ASAN_OPTIONS':'detect_leaks=0', 'UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    with (work/'result.log').open('w') as log:
        subprocess.run([str(binary), str(stage/'guest/guest.bin'), str(mode), '2', '65536', '2'],
                       cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
```

These portable steps reproduce configuration/factory/host-policy and COPY coverage only. They are not presented as a standalone reproduction of the separately retained seven-positive/eight-negative/NEMU/PMP/held full qualification; that also requires the corresponding original guests, references and fresh read-only bindings. No generated models,RTL,objects,binaries or workstation manifests belong in this package.
