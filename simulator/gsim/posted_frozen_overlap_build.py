"""Fresh source-bound two-model qualification; fail-closed reuse of its own manifest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TOP = 'PostedFrozenOverlapChainGsim'
SCHEMA = 'posted-frozen-original-models-v1'
FLAGS = ['-std=c++20', '-O1', '-g0', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-DTAGGED_STORE_RETURNS=1']

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def hashes(paths):
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}

def sources():
    # Full production and test Scala closure, build inputs, and host oracle closure.
    paths = set(ROOT.glob('src/**/*.scala')) | set(ROOT.glob('project/**/*'))
    paths |= {ROOT / x for x in ['build.mill', '.mill-version', '.mill-jvm-opts',
        'simulator/gsim/harness/posted_frozen_overlap_chain.cpp',
        'simulator/gsim/harness/tagged_store_return_oracle.h',
        'simulator/gsim/harness/board_ddr_multiid.h', 'simulator/gsim/posted_frozen_overlap_build.py']}
    return hashes(p for p in paths if p.is_file())

def tools():
    names = {'gsim': os.environ.get('GSIM', '/workspace/scratch/41e4a649bb60/recovery-gsim-r1/source/build/gsim/gsim'),
             'cxx': os.environ['GSIM_CXX'], 'mill': shutil.which('mill'), 'java': shutil.which('java')}
    identity = {k: {'path': str(Path(v).absolute()), 'resolved_path': str(Path(v).resolve()),
                    'sha256': digest(Path(v).resolve())} for k, v in names.items()}
    # The cloud Mill entry is a shell launcher: bind its executable distribution,
    # Java runtime and resolved compiler/elaboration dependency jars as well.
    mill_dir = Path(names['mill']).resolve().parent
    payload = mill_dir / 'mill-dist'
    if payload.is_file():
        identity['mill_distribution'] = {'path': str(payload), 'sha256': digest(payload)}
    java_home = Path(names['java']).resolve().parents[1]
    for relative in ['lib/modules', 'lib/server/libjvm.so']:
        path = java_home / relative
        if path.is_file():
            identity['java_' + relative] = {'path': str(path), 'sha256': digest(path)}
    jars = set()
    for file in (ROOT / 'out/IonSoC').rglob('*Classpath.json'):
        for entry in json.loads(file.read_text()).get('value', []):
            if isinstance(entry, str) and entry.endswith('.jar'):
                path = Path(entry.split(':', 3)[-1])
                if path.is_file():
                    jars.add(path)
    if not jars:
        raise ValueError('missing resolved Mill dependency inventory; compile Scala once before qualification')
    identity['dependency_jars'] = {str(path): digest(path) for path in sorted(jars)}
    identity['java_options_sha256'] = hashlib.sha256(os.environ.get('JAVA_TOOL_OPTIONS', '').encode()).hexdigest()
    return identity

def validate(manifest, current_sources, current_tools, revision, model_root):
    if manifest.get('schema') != SCHEMA or manifest.get('status') != 'FRESH_BUILD_PASS':
        raise ValueError('missing/unverified legacy original manifest')
    if manifest['source_revision'] != revision or manifest['sources'] != current_sources:
        raise ValueError('original source revision/closure changed; refusing relabel')
    if manifest['tools'] != current_tools or manifest['flags'] != FLAGS:
        raise ValueError('original tool identity/flags changed')
    actual = hashes(p for p in model_root.rglob('*') if p.is_file())
    if manifest['models'] != actual:
        raise ValueError('original FIRRTL/model/header/object/executable inventory changed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-root', default='build/gsim/posted-frozen-overlap-bound-r4')
    parser.add_argument('--qualification', default='fresh')
    parser.add_argument('--reuse-models', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    base = ROOT / args.build_root
    model_root = base / 'models'
    manifest_path = base / 'original-model-manifest.json'
    logs = base / args.qualification
    logs.mkdir(parents=True, exist_ok=False)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    src, tool = sources(), tools()
    receipt = dict(status='RUNNING', source_revision=revision, sources=src, tools=tool, steps=[])
    def save():
        (logs / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    def run(label, command, negative=False):
        print(label, flush=True)
        with (logs / (label + '.log')).open('w') as output:
            result = subprocess.run(list(map(str, command)), stdout=output, stderr=subprocess.STDOUT,
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}, timeout=900)
        receipt['steps'].append(dict(label=label, command=list(map(str, command)), exit=result.returncode))
        save()
        text = (logs / (label + '.log')).read_text()
        if negative:
            assert result.returncode == 1 and 'ACTUAL_CORRUPTION' in text and 'POSTED_FROZEN_CHAIN_FAIL' in text, label
        else:
            assert result.returncode == 0, label
    try:
        if args.reuse_models:
            original = json.loads(manifest_path.read_text())  # Missing/legacy manifests fail closed.
            validate(original, src, tool, revision, model_root)
            receipt['original_manifest_sha256'] = digest(manifest_path)
            receipt['original_source_revision'] = original['source_revision']
        else:
            assert not manifest_path.exists() and not model_root.exists(), 'fresh build requires new model directory'
            for side, option in [('off', '0'), ('on', '1')]:
                directory = model_root / side
                directory.mkdir(parents=True)
                run(side + '-emit', [tool['mill']['path'], '-i', 'IonSoC.test.runMain',
                    'ooo.' + TOP + 'Main', directory, option])
                run(side + '-generate', [tool['gsim']['path'], '--threads=1', '--cpp-max-size-KB=1024',
                    '--dir=' + str(directory), directory / (TOP + '.fir')])
                objects = []
                for cpp in sorted(directory.glob(TOP + '[0-9]*.cpp')):
                    obj = cpp.with_suffix('.o')
                    run(side + '-compile-' + cpp.stem, [tool['cxx']['path'], *FLAGS, '-I' + str(directory), '-c', cpp, '-o', obj])
                    objects.append(obj)
                assert objects
                run(side + '-link', [tool['cxx']['path'], *FLAGS, '-I' + str(directory),
                    ROOT / 'simulator/gsim/harness/posted_frozen_overlap_chain.cpp', *objects, '-ldl', '-o', directory / 'run'])
            assert sources() == src and tools() == tool, 'inputs changed during original build'
        for side in ['off', 'on']:
            executable = model_root / side / 'run'
            run(side + '-cases', [executable])
            for mutation in ['early', 'stale', 'owner', 'duplicate', 'generation', 'data']:
                run(side + '-negative-' + mutation, [executable, '--mutate-' + mutation], True)
        assert sources() == src and tools() == tool, 'qualification inputs changed'
        if not args.reuse_models:
            original = dict(schema=SCHEMA, status='FRESH_BUILD_PASS', source_revision=revision,
                sources=src, tools=tool, flags=FLAGS, models=hashes(p for p in model_root.rglob('*') if p.is_file()))
            manifest_path.write_text(json.dumps(original, indent=2) + '\n')
            receipt['original_manifest_sha256'] = digest(manifest_path)
        receipt['status'] = 'PASS_COMBINED_COMPONENT_ONLY'
        receipt['logs'] = hashes(logs.glob('*.log'))
    except BaseException as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        save()

if __name__ == '__main__':
    main()
