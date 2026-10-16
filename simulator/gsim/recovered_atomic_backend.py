#!/usr/bin/env python3
"""New short integrated acceptance of pinned reconstruction; never reuses historical PASS claims.

Both arms are fresh git archives, with exactly the same observational Scala overlay.
The original decoded/byte/physical-response oracle is unchanged. No posted-cache
merge/ACK, board, timing, full regression, or Linux qualification is claimed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
BASE = '223453bae0185dcc59b9ea5414ddb266e1f5af93'
CANDIDATE = 'e3e1ff348db09c663bbb25bffc59974da7256ccf'
OVERLAY = 'src/test/scala/ooo/RecoveredAtomicBackendGsim.scala'
HOST = 'simulator/gsim/harness/recovered_atomic_backend.cpp'
ORACLE = ['simulator/gsim/harness/preselected_redirect_lifecycle.cpp',
          'simulator/gsim/ready_store_query77/ready_store_query77_backend.cpp',
          'simulator/gsim/ready_store_query77/ready_store_query77_reference.h']
EXPECTED_PRODUCTION = ['BoardSocTop.scala', 'FixedApertureRange.scala', 'FpgaIntegerCore.scala',
    'FpgaNextConfig.scala', 'FpgaNextSocTop.scala', 'InstructionRom.scala',
    'InstructionTranslationAdapter.scala', 'IntegerBackend.scala', 'MachinePlatform.scala',
    'NonBlockingCoherentLineCache.scala', 'PacketFetchPmp.scala', 'RegisteredRequestQueue.scala']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    paths = [*root.glob('src/**/*.scala'), *root.glob('third_party/**/*.scala'),
             root / 'build.mill', root / '.mill-version', root / '.mill-jvm-opts',
             *[root / name for name in ORACLE]]
    return {str(p.relative_to(root)): sha(p) for p in sorted(paths)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--gsim', type=Path, required=True)
    ap.add_argument('--reuse-run', type=Path, help='Reuse completed, source-identical model stages from a failed run')
    a = ap.parse_args()
    output = a.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.nice(10)
    gsim = a.gsim.resolve()
    assert shutil.which('mill') and shutil.which('clang++-19'), 'source scripts/cloud/env.sh first'
    changed = subprocess.check_output(['git', 'diff', '--name-only', BASE, CANDIDATE, '--', 'src/main'],
                                     cwd=ROOT, text=True).splitlines()
    assert changed == ['src/main/scala/core/ooo/' + name for name in EXPECTED_PRODUCTION], changed
    previous = None
    if a.reuse_run:
        a.reuse_run = a.reuse_run.resolve()
        previous = json.loads((a.reuse_run/'receipt.json').read_text())
        assert previous['status'] == 'FAILED_PRESERVE_EVIDENCE', 'reuse only a terminal failed run'
        assert previous['baseline_commit'] == BASE and previous['candidate_commit'] == CANDIDATE
        assert previous['gsim_sha256'] == sha(gsim)
    roots = {}
    for arm, commit in [('baseline', BASE), ('candidate', CANDIDATE)]:
        if previous:
            root = a.reuse_run/(arm+'-source')
            assert inventory(root) == previous['source_inputs'][arm], 'prior snapshot drift'
            assert sha(root/OVERLAY) == sha(ROOT/OVERLAY), 'observer changes require fresh model'
            roots[arm] = root
            continue
        root = output / (arm + '-source')
        root.mkdir()
        archive = output / (arm + '.tar')
        with archive.open('xb') as stream:
            subprocess.run(['git', 'archive', commit], cwd=ROOT, stdout=stream, check=True)
        with tarfile.open(archive) as stream:
            stream.extractall(root, filter='data')
        assert not (root / OVERLAY).exists(), 'observer must be a separately inventoried test-only overlay'
        shutil.copy2(ROOT / OVERLAY, root / OVERLAY)
        roots[arm] = root
    frozen = {arm: inventory(root) for arm, root in roots.items()}
    assert all(frozen['baseline'][name] == frozen['candidate'][name] for name in ORACLE)
    # New driver and entry-point-only adaptation are identical on both arms.
    adapted = output / 'retained_lifecycle.cpp'
    original = (roots['baseline'] / ORACLE[0]).read_text()
    assert original.count('int main(int argc, char **argv)') == 1
    adapted.write_text(original.replace('int main(int argc, char **argv)',
                                       'int retained_lifecycle_main(int argc, char **argv)'))
    driver = output / 'recovered_atomic_backend.cpp'
    shutil.copy2(ROOT / HOST, driver)
    receipt = dict(status='RUNNING', baseline_commit=BASE, candidate_commit=CANDIDATE,
        production_changed=changed, source_inputs=frozen, runner_sha256=sha(Path(__file__)),
        observer_sha256=sha(ROOT / OVERLAY), host_sha256=sha(driver), adapted_lifecycle_sha256=sha(adapted),
        adaptation='Only rename original lifecycle main; original independent oracle unchanged',
        gsim_sha256=sha(gsim), commands=[], arms={}, reused_artifacts=[],
        previous_receipt_sha256=sha(a.reuse_run/'receipt.json') if previous else None,
        exclusions=['posted cache merge/ACK', 'board execution', 'timing', 'Linux', 'full regression'])
    env = dict(os.environ)
    env.update(ASAN_OPTIONS='detect_leaks=0', UBSAN_OPTIONS='halt_on_error=1')

    def save():
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def run(label, command, cwd=ROOT, negative=None):
        assert all(inventory(root) == frozen[arm] for arm, root in roots.items()), 'snapshot source drift'
        assert sha(driver) == receipt['host_sha256'] and sha(adapted) == receipt['adapted_lifecycle_sha256']
        log = output / (label + '.log')
        start = time.monotonic()
        with log.open('x') as stream:
            result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
        text = log.read_text(errors='replace')
        receipt['commands'].append(dict(label=label, command=list(map(str, command)),
            exit=result.returncode, seconds=round(time.monotonic()-start, 3), log_sha256=sha(log)))
        save()
        assert result.returncode == (1 if negative else 0) and (not negative or negative in text), label+'\n'+text[-8000:]
        print(label, 'PASS', flush=True)
        return text

    def completed(label):
        return previous and any(c['label'] == label and c['exit'] == 0 for c in previous['commands'])

    def reuse(label, files):
        assert files and all(path.is_file() for path in files), 'missing reusable artifacts: '+label
        receipt['reused_artifacts'].append(dict(label=label,
            files={str(path): sha(path) for path in files}))
        save()
        print(label, 'REUSED_SOURCE_IDENTICAL', flush=True)

    save()
    try:
        for arm, root in roots.items():
            dest = (a.reuse_run if previous else output) / (arm + '-model')
            top = 'ReadyStoreQuery77BackendGsim'
            if completed(arm+'-emit'):
                reuse(arm+'-emit', [dest/(top+'.fir'), dest/'actual-core.json', dest/'profile-shape.txt'])
            else:
                run(arm+'-emit', ['mill', '-i', '-j', '2', 'IonSoC.test.runMain',
                    'ooo.RecoveredAtomicBackendMain', dest], cwd=root)
            if completed(arm+'-generate'):
                reuse(arm+'-generate', sorted(dest.glob('*.cpp')) + sorted(dest.glob('*.h')))
            else:
                run(arm+'-generate', [gsim, '--threads=1', '--cpp-max-size-KB=1024', '--dir='+str(dest), dest/(top+'.fir')])
            flags = ['clang++-19', '-std=c++20', '-O1', '-g0', '-fsanitize=address,undefined',
                '-fno-sanitize-recover=all', '-I'+str(dest), '-I'+str(output),
                '-I'+str(root/'simulator/gsim/ready_store_query77')]
            objects = []
            for i, source in enumerate(sorted(dest.glob(top+'[0-9]*.cpp'))):
                obj = source.with_suffix('.o')
                if completed(arm+'-compile-'+str(i)):
                    reuse(arm+'-compile-'+str(i), [source, obj])
                else:
                    run(arm+'-compile-'+str(i), [*flags, '-c', source, '-o', obj])
                objects.append(obj)
            assert objects
            binary = dest/'run'
            run(arm+'-link', [*flags, driver, *objects, '-ldl', '-o', binary])
            text = run(arm+'-positive', [binary])
            receipt['arms'][arm] = dict(
                metrics=re.findall(r'^C0_LIFECYCLE_METRICS .*$', text, re.M),
                transport=re.findall(r'^RECOVERED_TRANSPORT .*$', text, re.M),
                actual_core=json.loads((dest/'actual-core.json').read_text()),
                profile_shape=(dest/'profile-shape.txt').read_text().strip(),
                fir_sha256=sha(dest/(top+'.fir')))
            assert len(receipt['arms'][arm]['metrics']) == 4
            assert len(receipt['arms'][arm]['transport']) == 2
            run(arm+'-retirement-negative', [binary, '--mutate-retirement'], negative='fault/killed/duplicate retirement')
            save()
        for field in ['metrics', 'transport', 'actual_core', 'profile_shape']:
            assert receipt['arms']['baseline'][field] == receipt['arms']['candidate'][field], field+' A/B mismatch'
        receipt['status'] = 'PASS_PINNED_RECONSTRUCTION_BACKEND_TRANSPORT_AB'
        save()
    except BaseException as error:
        receipt.update(status='FAILED_PRESERVE_EVIDENCE', failure=str(error))
        save()
        raise


if __name__ == '__main__':
    main()
