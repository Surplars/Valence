#!/usr/bin/env python3
"""Portable narrow CPU replay; every execution is a fresh current-source qualification.

Use --list-required to request the exact immutable external evidence bundle.
Stages: freeze, guest, constructor, emit, generate, compile, run, negatives, summarize.
After the common stages, emit/generate/compile require --mode old or new; run requires
--case sv39, bare or burst-locked. The two original laws and final byte/reply oracle
are pinned to the measured host. No historical run grant or old object is accepted.
This prepared adapter and any compact-source observer bridge remain unqualified.
"""
import argparse
import fcntl
import importlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

import bound_store_replay_common as common
from bound_store_host_binding import verify as verify_host_binding
from bound_store_service_oracle import verify_service

ROOT = Path(__file__).resolve().parents[2]
PLAN = 'read-prefetch-store-hold-r1/cpu-on-plan-r3/'
REFERENCE_MANIFEST_SHA256 = 'd5ef92d545f946ecfe93744d58427bd79ad834c053793c6c446e70c7ea4d7ef8'
CASES = {'sv39': ('original', 1), 'bare': ('original', 0), 'burst-locked': ('burst', 1)}
SOURCE_HASHES = {
    'simulator/gsim/payloads/cpu_sv39_bandwidth.S': 'a848bd50b7f05f3c52d3c99bc371867680da2b8a66e4f920468a36191a67b548',
    'simulator/gsim/payloads/cpu_hot_bandwidth.ld': '2cfe49e3b32898376c4888b6901c1a71bc12d68ea8f4dce2dfae0aa2d535ca46',
}
BURST_HASHES = {
    'board_ddr_benchmark.h': '9eab2ec96e1a03cbb09dceb0aefd636be4588728a0fd0992d6bbad6c78c082d9',
    'fake_axi.h': '8cb3b112dd9342075e163790f25c629d0e31bbb018e11157c7752f9966d6dff6',
    'law_controls_r2.cpp': 'a7d9353a2a7667750488f793f8dde7f7cd60623d60bd4da5f4ceae926744055d',
}


def load(path):
    return json.loads(Path(path).read_text())


def parse(text, prefix):
    lines = [line for line in text.splitlines() if line.startswith(prefix + ' ')]
    assert len(lines) == 1, ('missing/duplicate record', prefix)
    pairs = [word.split('=', 1) for word in lines[0].split()[1:]]
    assert len(dict(pairs)) == len(pairs), ('duplicate field', prefix)
    return dict(pairs)


def capture(text, work, reference, exact=False, burst=False):
    row = {key: parse(text, prefix) for key, prefix in (
        ('result', 'CPU_SV39_RESULT'), ('perf', 'BOARD_IPC'), ('oracle', 'CPU_SV39_PASS'),
        ('fabric', 'FABRIC_IDLE_PASS'), ('counts', 'PASSIVE_SUPPLY_COUNTS'),
        ('ledger', 'LEDGER_PASS'), ('adoption', 'ADOPTION_PASS'))}
    assert sum(len(row[k]) for k in ('result', 'perf', 'oracle', 'fabric')) == 105
    for key in row:
        assert row[key].keys() == reference[key].keys(), ('field universe', key)
    for key in ('mode', 'op', 'bytes', 'reps', 'retired', 'pc_hash', 'loads', 'stores', 'lsu_capacity'):
        assert row['result'][key] == reference['result'][key], ('architecture', key)
    assert row['oracle'] == reference['oracle'], 'full final-byte/reply/checksum oracle changed'
    for key, value in reference['fabric'].items():
        if key != 'samples' and not key.endswith('_held_cycles'):
            assert row['fabric'][key] == value, ('fabric service', key)
    assert row['counts']['req_fire'] == reference['counts']['req_fire']
    assert row['adoption']['attached'] == row['adoption']['actual_cpu_response']
    row['raw'] = {name: common.sha(work / name) for name in ('axi-events.tsv', 'supply-events.tsv')}
    if exact:
        assert all(row[k] == reference[k] for k in ('result', 'perf', 'oracle', 'fabric')), 'OLD/Bare exact 105-field calibration changed'
        raw_reference=reference.get('raw', reference.get('raw_sha256'))
        assert raw_reference is not None and all(name in raw_reference for name in row['raw']), 'exact reference lacks complete AXI/supply trace hashes'
        for name,digest in row['raw'].items():
            assert digest==raw_reference[name], 'OLD/Bare complete trace changed: '+name
    if burst:
        row['service'] = verify_service(work / 'axi-events.tsv')
    for prefix in ('LEDGER_TOTAL', 'ADOPTION_TOTAL', 'LEDGER_REASON', 'LEDGER_CROSS', 'ADOPTION_CROSS', 'PASSIVE_OPPORTUNITY_BUCKET', 'PASSIVE_SUPPLY_WITNESS'):
        row[prefix] = [parse(line, prefix) for line in text.splitlines() if line.startswith(prefix + ' ')]
    row['inclusive_cycles'] = int(row['result']['cycles']) + int(row['result']['clean_tail'])
    row['performance_verdict'] = 'REVIEW_REQUIRED_NO_AUTOMATIC_SPEEDUP_CLAIM'
    return row


def checked_references(root, manifest):
    missing = []
    for name, expected in manifest.items():
        path = root / name
        if not path.is_file():
            missing.append(f'{name} sha256={expected}')
        elif common.sha(path) != expected:
            raise ValueError('reference digest mismatch: ' + name)
    if missing:
        raise ValueError('missing immutable reference artifacts under --reference-root; supply exact files:\n' + '\n'.join(missing))


def verify_model_closure(out, artifacts):
    """Check each generated model's full input inventory before any later command."""
    for mode in ('old', 'new'):
        folder = out / mode / 'model'
        prefix = mode + '/model/'
        bound = {name[len(prefix):]: digest for name, digest in artifacts.items() if name.startswith(prefix)}
        if bound:
            common.verify_model_inputs(folder, bound)
        elif folder.exists():
            assert not any(p.is_file() for p in folder.rglob('*')), 'unbound new model input'


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('stage', nargs='?', default='freeze', choices=('freeze', 'guest', 'constructor', 'emit', 'generate', 'compile', 'run', 'negatives', 'summarize'))
    parser.add_argument('--list-required', action='store_true')
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--mode', choices=('old', 'new'))
    parser.add_argument('--case', choices=tuple(CASES))
    parser.add_argument('--riscv-gcc', type=Path)
    parser.add_argument('--riscv-objcopy', type=Path)
    parser.add_argument('--riscv-nm', type=Path)
    common.add_paths(parser, ROOT)
    args = parser.parse_args()
    root = args.source_root.resolve()
    resources = root / 'simulator/gsim/bound_store_prefetch'
    assert common.sha(resources/'reference-artifacts-v1.json')==REFERENCE_MANIFEST_SHA256,'immutable reference manifest changed; explicit review required'
    manifest = load(resources / 'reference-artifacts-v1.json')['files']
    if args.list_required:
        print(json.dumps({'status': 'EXTERNAL_ARTIFACT_REQUEST', 'files': manifest}, indent=2))
        return
    if args.reference_root is None:
        parser.error('missing --reference-root PATH; use --list-required for exact filenames and SHA-256 digests')
    reference_root = args.reference_root.resolve()
    try:
        checked_references(reference_root, manifest)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.output is None:
        parser.error('--output is required')
    out = args.output.resolve()
    if args.stage in ('emit', 'generate', 'compile', 'run', 'negatives') and args.mode is None:
        parser.error('--mode old|new is required for this stage')
    if args.mode is not None and args.stage not in ('emit','generate','compile','run','negatives'):
        parser.error('--mode is only valid for emit/generate/compile/run/negatives')
    if args.case is not None and args.stage != 'run':
        parser.error('--case is only valid for run')
    if args.stage == 'run' and args.case is None:
        parser.error('--case sv39|bare|burst-locked is required for run')
    tools = common.tool_paths(args, parser)
    for role, executable in (('riscv_gcc', 'gcc'), ('riscv_objcopy', 'objcopy'), ('riscv_nm', 'nm')):
        path = getattr(args, role) or (args.toolchain_root / ('sysroot/usr/bin/riscv64-unknown-elf-' + executable) if args.toolchain_root else None)
        if path is None or not path.is_file() or not os.access(path, os.X_OK):
            parser.error('missing executable: --' + role.replace('_', '-') + ' PATH')
        tools[role] = path.absolute()
    if args.activate:
        if not args.activate.is_file():
            parser.error('missing --activate script: ' + str(args.activate))
        tools['activate'] = args.activate.resolve()
    contract = load(reference_root / (PLAN + 'contract.json'))
    guest_reference = load(reference_root / 'cpu-supply-f722/runtime-guest-receipt.json')
    host_source = root / 'simulator/gsim/prefetch_demand_adoption/cpu_snapshot'
    common.verify_artifacts(host_source, contract['host17'])
    common.verify_artifacts(root, SOURCE_HASHES)
    common.verify_artifacts(resources / 'burst_locked', BURST_HASHES)
    assert guest_reference['artifacts_sha256'] == contract['guest3']
    sys.path.insert(0, str(root / 'fpga/next'))
    old_entry = importlib.import_module('board_pmp_publication')
    new_entry = importlib.import_module('board_bound_store_prefetch')
    options = {'old': old_entry.native_options(), 'new': new_entry.native_options()}
    profiles = {'old': old_entry.expected_constructor(), 'new': new_entry.expected_constructor()}
    assert options['new'] == contract['native_options_on'], 'new options require explicit reviewed contract update'
    assert options['old'] == options['new'][:-5], 'rollback must be published PMP, not B2 without hold'
    fabrics = {mode: load(reference_root / (PLAN + 'expected-' + name + '-fabric.json')) for mode, name in (('old', 'published'), ('new', 'on'))}
    assert all(fabrics[m]['cpu'] == profiles[m]['core'] and fabrics[m]['cache'] == profiles[m]['cache'] for m in options), 'complete profile/fabric expectation requires a reviewed bridge'
    extras = [Path(__file__), root/'simulator/gsim/bound_store_host_binding.py', root/'simulator/gsim/bound_store_service_oracle.py', *resources.rglob('*'), *host_source.rglob('*'), *root.glob('fpga/next/*.py'), *root.glob('fpga/next/*.json')]
    extras += [root / name for name in SOURCE_HASHES]
    sources = common.source_inputs(root, extras)
    binding = common.tool_binding(tools)
    if args.preflight_only:
        print(json.dumps({'status': 'PREFLIGHT_ONLY_NOT_QUALIFIED', 'source_inputs': sources, 'tools': binding, 'references': manifest, 'options': options, 'cases': CASES, 'new_models': 2, 'historical_objects_reused': False}, indent=2))
        return
    receipt_path = out / 'receipt.json'
    if args.stage == 'freeze':
        out.mkdir(parents=True, exist_ok=False)
        state = {'schema': 'bound-store-portable-cpu-v1', 'status': 'FROZEN_NOT_QUALIFIED', 'source_inputs': sources, 'tools': binding, 'references': manifest, 'options': options, 'commands': [], 'stages': {}, 'artifacts': {}, 'dependencies': {}, 'cases': {'old': {}, 'new': {}}, 'qualification_inherited': False}
        receipt_path.write_text(json.dumps(state, indent=2) + '\n')
        print(state['status'])
        return
    state = load(receipt_path)
    assert state['schema'] == 'bound-store-portable-cpu-v1'
    def save():
        temporary = receipt_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(receipt_path)
    def guard():
        assert state['source_inputs'] == common.source_inputs(root, extras), 'source drift'
        assert state['tools'] == common.tool_binding(tools), 'tool drift'
        assert state['references'] == manifest
        checked_references(reference_root, manifest)
        common.verify_artifacts(out, state['artifacts']) if state['artifacts'] else None
        verify_model_closure(out, state['artifacts'])
        for name, expected in state['dependencies'].items():
            assert common.sha(name) == expected, ('resolved compiler dependency drift', name)
    def command(label, argv, cwd=root, expected=0, anchor=None):
        guard()
        log = out / (label + '.log')
        assert not log.exists(), 'preserve previous stage evidence; freeze fresh output'
        argv = list(map(str, argv))
        executed = argv
        if args.activate:
            executed = ['/bin/bash', '--noprofile', '--norc', '-c', 'source "$1"; shift; exec "$@"', 'bound-store-replay', str(args.activate.resolve()), *argv]
        start = time.monotonic()
        with log.open('x') as stream:
            result = subprocess.run(executed, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1'})
        text = log.read_text()
        state['commands'].append({'label': label, 'argv': argv, 'exit': result.returncode, 'expected_exit': expected, 'seconds': time.monotonic() - start, 'log_sha256': common.sha(log)})
        save()
        assert result.returncode == expected and (anchor is None or anchor in text), (label, text[-3000:])
        assert not re.search(r'ERROR: AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer', text), label
        return text
    def retain(path):
        state['artifacts'][str(path.relative_to(out))] = common.sha(path)
    def dependencies(path):
        for name in shlex.split(path.read_text().replace('\\\n', ' ').split(':', 1)[1]):
            resolved = (root / name).resolve()
            state['dependencies'][str(resolved)] = common.sha(resolved)
    def require(stage):
        assert state['stages'].get(stage) == 'PASS', 'required stage: ' + stage
    key = '-'.join(filter(None, (args.stage, args.mode, args.case)))
    with (out / '.stage.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = load(receipt_path)
        assert 'first_failure' not in state and key not in state['stages'], 'fresh output required after failure/repeat'
        guard()
        state['stages'][key] = 'RUNNING'
        save()
        try:
            model = out / str(args.mode) / 'model'
            guest = out / 'guest'
            if args.stage == 'guest':
                guest.mkdir()
                command('guest-build', [tools['riscv_gcc'], '-march=rv64im_zicsr_zifencei', '-mabi=lp64', '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax', '-Wl,--build-id=none', '-T', root/'simulator/gsim/payloads/cpu_hot_bandwidth.ld', root/'simulator/gsim/payloads/cpu_sv39_bandwidth.S', '-o', guest/'guest.elf'])
                command('guest-bin', [tools['riscv_objcopy'], '-O', 'binary', guest/'guest.elf', guest/'guest.bin'])
                text = command('guest-symbols', [tools['riscv_nm'], '-n', guest/'guest.elf'])
                symbols = {}
                for line in text.splitlines():
                    words = line.split()
                    if len(words) == 3 and words[2] in ('bw_begin', 'bw_end', 'bw_drain', 'bw_done'):
                        symbols[words[2]] = int(words[0], 16)
                assert symbols == guest_reference['symbols']
                (guest/'cpu_sv39_symbols.h').write_text(''.join(f'#define {k.upper()} {v}ULL\n' for k,v in symbols.items()))
                common.verify_artifacts(guest, contract['guest3'])
                for name in contract['guest3']:retain(guest/name)
            elif args.stage == 'constructor':
                for mode in ('old', 'new'):
                    target = out / ('constructor-' + mode)
                    command('constructor-' + mode, [tools['mill'], '-i', '-j', '1', 'IonSoC.test.runMain', 'ooo.FpgaNextProfileMain', target, *options[mode]])
                    assert load(target/'profile.json') == profiles[mode], 'complete constructor mismatch'
                    retain(target/'profile.json')
            elif args.stage == 'emit':
                require('constructor');model.mkdir(parents=True)
                command('emit-' + args.mode, [tools['mill'], '-i', '-j', '1', 'IonSoC.test.runMain', 'ooo.CpuMatchingBoardProfileGsimMain', model, *options[args.mode]])
                assert load(model/'profile.json') == profiles[args.mode]
                assert load(model/'actual-fabric.json') == fabrics[args.mode]
                assert (model/'options.txt').read_text().splitlines() == options[args.mode]
                assembly_hashes={digest for name,digest in contract['baseline_bindings'].items() if name.endswith('/cpu/model/assembly-contract.json')}
                assert len(assembly_hashes)==1 and common.sha(model/'assembly-contract.json') in assembly_hashes,'complete assembly contract changed'
                for path in model.iterdir():
                    if path.is_file():retain(path)
            elif args.stage == 'generate':
                require('emit-' + args.mode)
                command('generate-' + args.mode, [tools['gsim'], '--threads=1', '--cpp-max-size-KB=1024', '--dir=' + str(model), model/'BoardSocGsim.fir'])
                assert list(model.glob('BoardSocGsim[0-9]*.cpp')), 'generated model missing'
                for path in [model/'BoardSocGsim.h', *model.glob('BoardSocGsim[0-9]*.cpp')]:retain(path)
            elif args.stage == 'compile':
                require('generate-' + args.mode);require('guest')
                verify_host_binding(model, reference_root/(PLAN+'baseline-temporary-semantic-audit.json'), host_source)
                for member in load(reference_root/(PLAN+'header-audit.json'))['required_host_members']:
                    assert re.search(r'\b' + re.escape(member) + r'\b', (model/'BoardSocGsim.h').read_text()), ('host field requires reviewed bridge', member)
                flags = contract['cxx_flags'] + ['-I' + str(model)]
                objects = []
                for index, unit in enumerate(sorted(model.glob('BoardSocGsim[0-9]*.cpp'))):
                    obj=unit.with_suffix('.o');dep=unit.with_suffix('.d')
                    command(f'compile-{args.mode}-{index}', [tools['cxx'], *flags, '-MD', '-MF', dep, '-c', unit, '-o', obj])
                    objects.append(obj);dependencies(dep);retain(obj);retain(dep);save()
                for law in ('original', 'burst'):
                    host = out / args.mode / (law + '-host');host.mkdir()
                    for name in contract['host17']:
                        target=host/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(host_source/name,target)
                    if law=='burst':shutil.copyfile(resources/'burst_locked/board_ddr_benchmark.h',host/'harness/board_ddr_benchmark.h')
                    for path in host.rglob('*'):
                        if path.is_file():retain(path)
                    hostflags = [*flags, '-DREAD_PREFETCH_DIRTY_RETRY=1', '-DREAD_PREFETCH_DEMAND_ADOPTION=1', '-I'+str(guest), '-I'+str(host/'harness')]
                    dep=host/'host.d';binary=out/args.mode/('run-'+law)
                    command(f'link-{args.mode}-{law}', [tools['cxx'], *hostflags, '-MD', '-MF', dep, host/'cpu_passive_bandwidth.cpp', *objects, '-o', binary])
                    dependencies(dep);retain(dep);retain(binary);save()
                control=out/args.mode/'law-controls';(control/'on-host/harness').mkdir(parents=True)
                for name in ('law_controls_r2.cpp','fake_axi.h'):shutil.copyfile(resources/'burst_locked'/name,control/name)
                shutil.copyfile(resources/'burst_locked/board_ddr_benchmark.h',control/'on-host/harness/board_ddr_benchmark.h')
                binary=control/'run'
                command('law-controls-build-'+args.mode,[tools['cxx'],*contract['cxx_flags'],control/'law_controls_r2.cpp','-o',binary])
                command('law-controls-positive-'+args.mode,[binary],anchor='LAW_CONTROLS_PASS cases=5')
                for name,anchor in [('unlock','interleaved or reordered burst ID'),('held-data','held R payload changed'),('last-release','held LAST payload/RESP changed or burst released early')]:
                    command('law-controls-'+args.mode+'-'+name,[binary,'--inject-'+name],expected=1,anchor=anchor)
                for path in control.rglob('*'):
                    if path.is_file():retain(path)
            elif args.stage == 'run':
                require('compile-'+args.mode)
                if args.mode=='new':require('run-old-'+args.case)
                law,mode=CASES[args.case];work=out/args.mode/args.case;work.mkdir()
                text=command('run-'+args.mode+'-'+args.case,[out/args.mode/('run-'+law),guest/'guest.bin',mode,2,65536,2],cwd=work,anchor='CPU_SV39_PASS')
                baseline=load(reference_root/'read-prefetch-store-hold-r1/cpu-burst-locked-r1/receipt.json')['cases']['off'] if law=='burst' else contract['baseline_cases'][args.case]
                state['cases'][args.mode][args.case]=capture(text,work,baseline,exact=args.mode=='old' or args.case=='bare',burst=law=='burst')
                for name in ('axi-events.tsv','supply-events.tsv'):retain(work/name)
            elif args.stage == 'negatives':
                require('run-'+args.mode+'-sv39')
                for injection,anchor in [('read','CPU read data mismatch'),('memory','final copied/stored memory mismatch'),('trap','unexpected CPU trap cause')]:
                    work=out/args.mode/('negative-'+injection);work.mkdir()
                    command('negative-'+args.mode+'-'+injection,[out/args.mode/'run-original',guest/'guest.bin',1,2,4096,1,'--inject-'+injection],cwd=work,expected=1,anchor=anchor)
            else:
                for mode in ('old','new'):
                    require('negatives-'+mode)
                    for case in CASES:require('run-'+mode+'-'+case)
                old_assembly=out/'old/model/assembly-contract.json';new_assembly=out/'new/model/assembly-contract.json'
                assert old_assembly.read_bytes()==new_assembly.read_bytes(),'assembly drift'
                state['comparisons']={case:{'old_inclusive':state['cases']['old'][case]['inclusive_cycles'],'new_inclusive':state['cases']['new'][case]['inclusive_cycles']} for case in CASES}
            guard();state['stages'][key]='PASS'
            state['status']='PASS_NARROW_TWO_LAW_CPU_REPLAY' if args.stage=='summarize' else 'PASS_'+key.upper()+'_ONLY'
            save();print(state['status'])
        except BaseException as error:
            state['status']='STOPPED_FIRST_FAILURE';state['first_failure']={'stage':key,'message':str(error)};save();raise


if __name__ == '__main__':
    main()
