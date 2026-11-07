#!/usr/bin/env python3
"""Run successive VS-origin trap metadata on the authenticated, already-emitted GSIM platform."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry-binding-root', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--reuse-native-model', type=Path,
                        help='Explicitly reuse the sealed VS-boundary native object; changed or missing inputs fail.')
    parser.add_argument('--output', type=Path, required=True,
                        help='New directory. Existing evidence is never overwritten.')
    args = parser.parse_args()
    candidate = args.entry_binding_root.resolve()
    repo = candidate / 'worktree'
    output = args.output.resolve()
    model = repo / 'build/gsim/hypervisor-platform'
    script = Path(__file__).resolve()
    source = script.parent / 'harness/hypervisor_trap_sequence.cpp'
    # This runner reuses one known emitted model, not an arbitrary rebuilt DUT.
    expected = {
        candidate / 'hypervisor-entry-binding-source-evidence.tar.gz':
            '9af143c47d96fe527d76ea42b96c8c2d1222502a4c8d6f40206368c466eb7fb1',
        candidate / 'entry-run/receipt.json':
            '2633ee379c6509cf7df5b288373d2d1a19d20128475dd39aea4096787d5c8f57',
        candidate / 'entry-run/source-pins-after.json':
            '74e10241d1ed6ff4cb06bdaf0a700ab5405a1002804aae5db0e74808837a1ac0',
        model / 'HypervisorPlatformGsim.h':
            'd948ccc7ddfd7ff4ed93b42ccd3a5a1d58d6d2fcea89c093a8a5935fda01cb11',
        model / 'HypervisorPlatformGsim0.cpp':
            'f2be5fc81091a3f16b102643bc8863879fe2abccca2857de2bd71fdec4f024ed',
        model / 'HypervisorPlatformGsim.fir':
            '8225d8d0538121df53fa8779c25f65740a9268a10db6e73c36006dc685c1c75b',
    }
    reused_object = None
    if args.reuse_native_model is not None:
        prior = args.reuse_native_model.resolve()
        reused_object = prior / 'evidence-final/model.o'
        expected.update({
            prior / 'hypervisor-vs-boundaries-source-evidence.tar.gz':
                'a121399d18b65a660168543820c220878029d0724210f393b6060af1579c28e6',
            prior / 'evidence-final/receipt.json':
                '1bcdd8770ed7124b00a8cad1fd90903931e507b90c0d991ebd7db3b0c779789f',
            prior / 'evidence-final/pins-after.json':
                '0791506e7cbb55f477417a55ef0c301ac856e17d9ff48f3745b0904cc9f3905e',
            reused_object:
                'bc94ef872ebece3a3e4391d9d312ef7338d9eab5257fcbf5d709f77efd14b7d1',
        })
    for path, value in expected.items():
        if digest(path) != value:
            raise RuntimeError(f'Fixed emitted-candidate identity changed: {path}')
    pins = json.loads((candidate / 'entry-run/source-pins-after.json').read_text())
    # Bind the live hardware, fixtures, test helpers and tool setup to the fresh
    # entry's source record before importing or compiling any of them.
    selected = {repo / rel: value for rel, value in pins.items()
                if rel.startswith(('src/main/', 'src/test/', 'simulator/gsim/'))
                or rel in ('build.mill', 'Makefile')}
    for path, value in selected.items():
        if digest(path) != value:
            raise RuntimeError(f'Executed-candidate source identity changed: {path}')
    before = {str(path): value for path, value in {**expected, **selected}.items()}
    before.update({str(script): digest(script), str(source): digest(source)})
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'pins-before.json', before)

    commands = []
    failure = None
    status = 'FAIL_TRAP_SEQUENCE'
    binding = None
    started = time.monotonic()

    def run(argv, name, timeout=900):
        start = time.monotonic()
        samples = []
        stop = None
        peak = 0
        with (output / (name + '.log')).open('w') as log:
            child = subprocess.Popen([str(x) for x in argv], stdout=log,
                                     stderr=subprocess.STDOUT, env=env,
                                     start_new_session=True)
            while child.poll() is None:
                rows = subprocess.check_output(['ps', '-eo', 'pid=,ppid=,rss='], text=True)
                processes = [tuple(map(int, line.split())) for line in rows.splitlines()]
                family = {child.pid}
                while True:
                    expanded = family | {pid for pid, parent, rss in processes if parent in family}
                    if expanded == family:
                        break
                    family = expanded
                rss = sum(rss for pid, parent, rss in processes if pid in family)
                peak = max(peak, rss)
                elapsed = time.monotonic() - start
                samples.append({'seconds': round(elapsed, 3), 'rss_kib': rss})
                if rss > 3584 * 1024:
                    stop = 'process-tree RSS exceeded 3.5 GiB'
                if elapsed > timeout:
                    stop = f'wall time exceeded {timeout} seconds'
                if stop:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                    break
                time.sleep(0.5)
            code = child.wait()
        write_json(output / (name + '-resources.json'), samples)
        commands.append({'argv': [str(x) for x in argv], 'exit': code,
                         'seconds': time.monotonic() - start,
                         'peak_sampled_process_tree_rss_kib': peak,
                         'stop_reason': stop, 'log': name + '.log'})
        if stop:
            raise RuntimeError(name + ': ' + stop)
        return code, (output / (name + '.log')).read_text()

    try:
        selected_bundle = os.environ.get('VALENCE_GSIM_RESET_GRAPH_BUNDLE')
        if selected_bundle is not None and (not selected_bundle or
                Path(selected_bundle).resolve() != args.bundle.resolve()):
            raise RuntimeError('Conflicting explicit bundle selector')
        os.environ['VALENCE_GSIM_RESET_GRAPH_BUNDLE'] = str(args.bundle.resolve())
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(repo / 'simulator/gsim'))
        import run as common
        import gsim_reset_graph_bundle
        gsim, cxx = common.setup(False)
        binding = gsim_reset_graph_bundle.tool_binding(args.bundle, repo)
        write_json(output / 'verified-tool-binding-before.json', binding)
        env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1'}
        flags = ['-std=c++20', '-O1', '-g', '-fbracket-depth=4096',
                 '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        native_object = reused_object or output / 'model.o'
        if reused_object is None:
            code, _ = run([cxx, *flags, '-I' + str(model), '-c',
                           model / 'HypervisorPlatformGsim0.cpp', '-o', native_object], 'model-compile')
            if code:
                raise RuntimeError('Fresh native GSIM model compilation failed')
        else:
            write_json(output / 'native-model-reuse.json', {
                'path': str(native_object), 'sha256': digest(native_object),
                'source': 'Fixed sealed VS-boundary final run, compiled from the same authenticated header/CPP pair.',
                'receipt': str(prior / 'evidence-final/receipt.json'),
                'receipt_sha256': digest(prior / 'evidence-final/receipt.json'),
                'explicit_reuse': True, 'fallback': False})
        code, _ = run([cxx, *flags, '-I' + str(model),
                       '-I' + str(repo / 'simulator/gsim/harness'), source,
                       native_object, '-ldl', '-o', output / 'trap_sequence'], 'driver-compile')
        if code:
            raise RuntimeError('Native trap-sequence driver compilation failed')
        positive = output / 'positive'
        positive.mkdir()
        code, log = run([output / 'trap_sequence', positive], 'positive')
        if code or log.count('TRAP_SEQUENCE_PASS ') != 3 or 'TRAP_SEQUENCES_ALL_PASS' not in log:
            raise RuntimeError('Five successive faults across all three schedules did not pass')
        for mode, marker in [('stale-htval', 'FAIL stale HTVAL'),
                             ('stale-htinst', 'FAIL stale HTINST'),
                             ('stale-gva', 'FAIL stale GVA')]:
            location = output / mode
            location.mkdir()
            code, log = run([output / 'trap_sequence', location, mode], mode)
            if code != 1 or marker not in log:
                raise RuntimeError(mode + ' did not fail at its intended independent comparison')
        after_binding = gsim_reset_graph_bundle.tool_binding(args.bundle, repo)
        write_json(output / 'verified-tool-binding-after.json', after_binding)
        if after_binding != binding:
            raise RuntimeError('Tool/source binding changed during execution')
        status = 'PASS_TRAP_SEQUENCE_THREE_AND_THREE_STALE_CONTROLS'
    except Exception as error:
        failure = str(error)
    after = {path: digest(Path(path)) for path in before}
    unchanged = after == before
    if not unchanged:
        failure = 'Source/model/helper inputs changed during execution'
        status = 'FAIL_INPUT_DRIFT'
    write_json(output / 'pins-after.json', after)
    outputs = {str(p.relative_to(output)): {'sha256': digest(p), 'bytes': p.stat().st_size}
               for p in sorted(output.rglob('*')) if p.is_file()}
    receipt = {'status': status, 'failure': failure, 'seconds': time.monotonic() - started,
               'inputs_unchanged': unchanged, 'source_and_model_pin_count': len(before),
               'native_model_reused': reused_object is not None,
               'commands': commands, 'outputs': outputs,
               'scope': 'Five successive VS-origin faults per DUT, three single-clock schedules, real shared fabric/retirement. '
                        'Authenticated emitted GSIM model, with explicit pinned native reuse or fresh compilation; no Scala/GSIM regeneration. '
                        'No M-origin guest-fault review, independent clocks, publication or full regression. '
                        'Finite sentinel/data-drain completion is not whole-platform quiescence.'}
    write_json(output / 'receipt.json', receipt)
    print(json.dumps({k: receipt[k] for k in ('status', 'failure', 'seconds', 'inputs_unchanged')}, indent=2))
    if failure:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
