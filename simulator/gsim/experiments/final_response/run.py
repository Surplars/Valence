#!/usr/bin/env python3
"""Export the standalone fetch engine and prove its latency-delta/refinement contract.

No CPU, simulator, synthesis, platform resolver, or private evidence is required.
All generated evidence stays in a fresh caller-selected build directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def classpath(path):
    text = path.read_text().strip()
    if text.startswith('{') or text.startswith('['):
        value = json.loads(text)
        values = value['value'] if isinstance(value, dict) else value
        values = [x.split(':', 3)[3] if x.startswith(('qref:', 'ref:')) else x for x in values]
    else:
        values = text.split(os.pathsep)
    assert values, 'empty classpath'
    for x in values:
        p = Path(x).resolve()
        if not p.exists():
            allowed = {root / suffix for root in [REPO, REPO / 'third_party/berkeley-hardfloat']
                       for suffix in ['compile-resources', 'src/main/resources']}
            assert p in allowed, 'missing classpath input: ' + x
    return os.pathsep.join(values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['emit', 'prove'])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--runtime-classpath-file', type=Path)
    parser.add_argument('--compiler-classpath-file', type=Path)
    parser.add_argument('--chisel-plugin', type=Path)
    parser.add_argument('--java', default='java')
    parser.add_argument('--firtool')
    parser.add_argument('--sv2v')
    parser.add_argument('--yosys')
    parser.add_argument('--timeout-seconds', type=float, default=60)
    args = parser.parse_args()
    assert args.timeout_seconds > 0
    out = args.out.resolve()
    assert out.is_relative_to(REPO / 'build'), 'output must be below this repository build/'
    assert not any(c.isspace() for c in str(out)), 'Yosys work path must not contain whitespace'
    tools = {}
    for key in (['java', 'firtool'] if args.stage == 'emit' else ['sv2v', 'yosys']):
        raw = getattr(args, key)
        resolved = shutil.which(raw) if raw else None
        assert resolved, 'explicit installed tool required: ' + key
        tools[key] = str(Path(resolved).resolve())
    env = dict(os.environ)
    if args.stage == 'emit':
        assert not out.exists(), 'fresh output directory required'
        out.mkdir(parents=True)
        env['CHISEL_FIRTOOL_PATH'] = str(Path(tools['firtool']).parent)
    else:
        assert out.is_dir() and not (out / 'PROOF_STARTED.json').exists()
        export = json.loads((out / 'EXPORT.json').read_text())
        assert export['status'] == 'PASS_STANDALONE_MATCHED_EXPORT'
        for path in export['absent_classpath']:
            assert not Path(path).exists(), 'previously absent classpath appeared: ' + path
        for p, h in export['files'].items():
            assert sha(p) == h, p
        with (out / 'PROOF_STARTED.json').open('x') as f:
            json.dump({'export_sha256': sha(out / 'EXPORT.json')}, f)
        proof_tools = {path: sha(path) for path in tools.values()}
        write(out / 'PROOF_TOOL_BINDING.json', proof_tools)
    commands = out / 'commands'
    commands.mkdir(exist_ok=True)

    def run(name, argv, expected=0, stdout_path=None):
        argv = list(map(str, argv))
        startfile = commands / (name + '.started.json')
        with startfile.open('x') as f:
            json.dump({'argv': argv, 'timeout_seconds': args.timeout_seconds}, f)
        stdout_path = stdout_path or commands / (name + '.stdout')
        stderr_path = commands / (name + '.stderr')
        began = time.monotonic()
        timed_out = False
        with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
            try:
                result = subprocess.run(argv, cwd=REPO, env=env, stdout=stdout, stderr=stderr,
                                        timeout=args.timeout_seconds)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code, timed_out = None, True
        write(commands / (name + '.receipt.json'), {
            'argv': argv, 'exit': code, 'expected_exit': expected, 'timeout': timed_out,
            'seconds': time.monotonic() - began, 'stdout': str(stdout_path),
            'stdout_sha256': sha(stdout_path), 'stderr_sha256': sha(stderr_path)})
        assert not timed_out and code == expected, 'UNKNOWN or unexpected exit: ' + name
        return stdout_path.read_text(), stderr_path.read_text()

    if args.stage == 'emit':
        assert args.runtime_classpath_file and args.compiler_classpath_file and args.chisel_plugin
        cp = classpath(args.runtime_classpath_file)
        compiler = classpath(args.compiler_classpath_file)
        absent = sorted({str(Path(x).resolve()) for x in (cp + os.pathsep + compiler).split(os.pathsep)
                         if not Path(x).exists()})
        write(out / 'ABSENT_CLASSPATH.json', absent)
        plugin = args.chisel_plugin.resolve()
        assert plugin.is_file()
        source = REPO / 'src/main/scala/core/ooo/mmu/RegisteredInstructionTranslationEngine.scala'
        fixture = HERE / 'FinalResponseMain.scala'
        bound = [source, fixture, plugin, args.runtime_classpath_file, args.compiler_classpath_file,
                 *HERE.glob('*.py'), HERE / 'profile.json', HERE / 'expected-rtl.json']
        for name in cp.split(os.pathsep) + compiler.split(os.pathsep):
            p = Path(name)
            if not p.exists():
                continue
            bound.extend(p.rglob('*.class') if p.is_dir() else [p])
        bound.extend(Path(x) for x in tools.values())
        write(out / 'INPUT_BINDING.json', {str(p.resolve()): sha(p) for p in bound})
        # Reference is a mechanically derived test-only variant, never a CPU overlay.
        reference = out / 'reference-source'
        reference.mkdir()
        text = source.read_text()
        for field in ['responseError', 'responsePageFault']:
            old = '(io.physical.' + field + ' & allowed)'
            new = '(io.physical.' + field + ' & firstMask)'
            assert text.count(old) == 1
            text = text.replace(old, new)
        refsource = reference / source.name
        refsource.write_text(text)
        classes = out / 'classes'
        refclasses = out / 'reference-classes'
        for name, cls, src in [('compile', classes, source), ('compile-reference', refclasses, refsource)]:
            cls.mkdir()
            run(name, [tools['java'], '-cp', compiler, 'scala.tools.nsc.Main', '-classpath', cp,
                '-Xplugin:' + str(plugin), '-language:reflectiveCalls', '-d', cls, src, fixture])
        expected = json.loads((HERE / 'expected-rtl.json').read_text())
        rtl = out / 'rtl'
        rtl.mkdir()
        for role in ['off', 'reference', 'on']:
            cls = refclasses if role == 'reference' else classes
            dest = rtl / role
            log = out / (role + '.class-load.log')
            run(role + '-emit', [tools['java'], '-Xmx3g', '-XX:ActiveProcessorCount=4',
                '-Xlog:class+load=info:file=' + str(log), '-cp', str(cls) + os.pathsep + cp,
                'fetchresponsequalification.FinalResponseMain', dest, 'off' if role == 'off' else 'on'])
            for name in ['fetchresponsequalification.FinalResponseMain$',
                         'soc.core.ooo.RegisteredInstructionTranslationEngine',
                         'soc.core.ooo.InstructionFetchTransactionBoundary']:
                rows = [x for x in log.read_text().splitlines() if name + ' source:' in x]
                assert len(rows) == 1 and 'file:' + str(cls) + '/' in rows[0], rows
            profile = json.loads((HERE / 'profile.json').read_text())
            assert json.loads((dest / 'component-profile.json').read_text()) == {k: str(v).lower() for k, v in profile.items()}
            actual = {p.name: sha(p) for p in dest.glob('*.sv')}
            assert actual == expected[role], 'tool/profile/module drift: ' + role
        files = {str(p): sha(p) for p in out.rglob('*') if p.is_file()}
        for p, h in json.loads((out / 'INPUT_BINDING.json').read_text()).items():
            assert sha(p) == h, p
        files.update(json.loads((out / 'INPUT_BINDING.json').read_text()))
        for path in absent:
            assert not Path(path).exists(), path
        write(out / 'EXPORT.json', {'status': 'PASS_STANDALONE_MATCHED_EXPORT',
                                    'absent_classpath': absent, 'files': files})
        return

    lowered = out / 'lowered'
    lowered.mkdir()
    for role in ['off', 'reference', 'on']:
        paths = sorted((out / 'rtl' / role).glob('*.sv'))
        run(role + '-sv2v', [tools['sv2v'], '-DSYNTHESIS', *paths], stdout_path=lowered / (role + '.v'))
        ys = lowered / (role + '.ys')
        ys.write_text(f'read_verilog {lowered / (role + ".v")}\nhierarchy -check -top RegisteredInstructionTranslationEngine\nproc\nflatten\nmemory_map\nopt_clean\ncheck -assert\nwrite_json {lowered / (role + "-netlist.json")}\n')
        run(role + '-lower', [tools['yosys'], '-s', ys])
    run('prepare-proof', [sys.executable, HERE / 'prepare_proof.py', out])
    proof = out / 'proof'
    jobs = json.loads((proof / 'JOBS.json').read_text())
    for job in jobs:
        name = job['name']
        stdout, stderr = run(name, [tools['yosys'], '-s', proof / (name + '.ys')], job['expected_exit'])
        targets = [line for line in stdout.splitlines() if line.startswith('Import proof-constraint:')]
        assert targets == ['Import proof-constraint: \\' + name + " = 1'1"], 'missing/incorrect proof target: ' + name
        if job['expected_exit'] == 0:
            assert not stderr and 'SUCCESS!' in stdout, name
        else:
            assert stderr.strip() == 'ERROR: Called with -verify and proof did fail!'
            assert (proof / (name + '-cex.json')).is_file()
    run('decode-negatives', [sys.executable, HERE / 'decode_negative.py', proof])
    for path in export['absent_classpath']:
        assert not Path(path).exists(), path
    for path, digest in proof_tools.items():
        assert sha(path) == digest, path
    for path, digest in export['files'].items():
        assert sha(path) == digest, path
    write(out / 'RESULT.json', {
        'status': 'PASS_COMPONENT_LATENCY_DELTA_AND_INDUCTIVE_CAPTURED_PERMISSION',
        'state_groups': 19, 'state_bits': 467,
        'tools': {name: {'path': path, 'sha256': sha(path)} for name, path in tools.items()},
        'negative': 'Saved-fault observation mutation and actual unrestricted-Q refinement counterexample; not reachable CPU failures.',
        'limits': 'Component only, binary RTL domain. Off/on intentionally differ in latency. No CPU enable, integration, timing, Fmax, or new runtime workload claim.',
        'files': {str(p): sha(p) for p in out.rglob('*') if p.is_file()}})



if __name__ == '__main__':
    main()
