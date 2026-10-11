#!/usr/bin/env python3
"""Fail-closed, narrow adoption OFF/ON CPU replay. freeze is source-only."""
import argparse, copy, fcntl, hashlib, json, os, pathlib, re, shlex, shutil, subprocess, time
if not __debug__:
    raise SystemExit("Qualification gates require Python assertions; optimized Python is forbidden")
HERE = pathlib.Path(__file__).resolve().parent
CAND = HERE.parent
BASE = CAND.parent
ROOT = CAND / 'cpu-source'
ORIGIN = CAND / 'source'
QUAL = BASE / 'read-prefetch-dirty-retry-candidate/cpu-ab-r1'
OLD = QUAL / 'on/model'
HOST = HERE / 'harness'
FW = BASE / 'cpu-supply-f722/guest'
TOOL = BASE / 'toolchain'
CXX = TOOL / 'sysroot/usr/bin/clang++-19'
GSIM = TOOL / 'gsim-src/build/gsim/gsim'
RECEIPT = HERE / 'receipt.json'
COMMIT = '507c81beefede7ecb806dc5219d65df8591ba5df'
PROD = '0c4beee087d3d4de036406ce3312cc4ff01a1b8c'
WRAPPER = 'src/test/scala/ooo/CpuMatchingBoardProfileGsimMain.scala'

def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

def load(p):
    return json.loads(pathlib.Path(p).read_text())

def write(p, value):
    pathlib.Path(p).write_text(json.dumps(value, indent=2) + '\n')

def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not any(x in p.parts for x in ('out', '__pycache__', '.git'))}

def own():
    paths = [*HERE.glob('*.h'), *HERE.glob('*.cpp'), *HERE.glob('*.py'),
             HERE / 'HOST-CONTRACT.md', *HOST.glob('*')]
    return {str(p.relative_to(HERE)): sha(p) for p in sorted(paths) if p.is_file()}

def check_map(root, values):
    for name, expected in values.items():
        assert sha(root / name) == expected, ('hash drift', str(root / name))

def check_generated(model, item):
    paths = [model / 'BoardSocGsim.h', *sorted(model.glob('BoardSocGsim[0-9]*.cpp'))]
    assert {p.name: sha(p) for p in paths} == item['generated'], 'generated TU/header bytes or file set changed'

def parse(text, prefix):
    rows = [line for line in text.splitlines() if line.startswith(prefix + ' ')]
    assert len(rows) == 1, ('missing/duplicate record', prefix)
    return dict(word.split('=', 1) for word in rows[0].split()[1:])

q = load(QUAL / 'receipt.json')
b = q['modes']['on']
plan = load(CAND / 'cpu-source-plan.json')

def save():
    write(RECEIPT, state)

def guard():
    assert files(ROOT) == state['inputs'], 'source bytes/additions/removals changed'
    assert own() == state['host_inputs'], 'host inputs changed'
    check_map(FW, state['guest'])
    check_map(pathlib.Path('/'), state['tools'])
    check_map(pathlib.Path('/'), state['qualified_inputs'])
    assert q['flags'] == state['flags']
    check_map(OLD, b['generated'])
    check_map(pathlib.Path(b['object_directory']), b['objects'])
    for item in state['modes'].values():
        check_map(pathlib.Path('/'), item.get('dependencies', {}))

def gate():
    a = load(HERE / 'authorization.json')
    proof_path = pathlib.Path(a['focused_receipt'])
    proof = load(proof_path)
    assert a['slot_granted_by_parent'] is True
    assert a['production_checkpoint'] == PROD
    assert a['cpu_source_manifest_sha256'] == sha(HERE / 'source-manifest.json')
    assert a['host_inputs_manifest_sha256'] == sha(HERE / 'host-inputs.json')
    assert a['focused_receipt_sha256'] == sha(proof_path)
    assert proof['status'] == 'PASS_COMPONENT_ONLY', 'focused qualification is not complete'
    for name, expected in state['qualification_bridge'].items():
        assert sha(ORIGIN / name) == expected and proof['inputs'].get(name) == expected, ('focused source bridge', name)
    state['authorization'] = a
    state['focused_bridge'] = {'receipt_sha256': sha(proof_path), 'source_head': proof['source_head'],
                               'production_config_equal': True}

def step(label, argv, expected=0, anchor=None, cwd=ROOT):
    guard()
    attempt = 0
    unique = label
    while (HERE / (unique + '.log')).exists():
        attempt += 1
        unique = label + '-retry-' + str(attempt)
    log = HERE / (unique + '.log')
    print('START', unique, flush=True)
    started = time.monotonic()
    with log.open('x') as output:
        run = subprocess.run(list(map(str, argv)), cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                             env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
    text = log.read_text()
    state['commands'].append({'name': unique, 'argv': list(map(str, argv)), 'cwd': str(cwd),
                              'exit': run.returncode, 'expected': expected, 'seconds': time.monotonic() - started,
                              'log_sha256': sha(log), 'runner_sha256': sha(__file__)})
    save()
    assert run.returncode == expected and (anchor is None or anchor in text), (unique, run.returncode, text[-5000:])
    return text

def constructor(model, adoption):
    profile = load(OLD / 'profile.json')
    profile['profile']['readPrefetchDemandAdoption'] = adoption
    profile['cache']['readPrefetchDemandAdoption'] = adoption
    assert load(model / 'profile.json') == profile, 'complete actual profile drift'
    fabric = load(OLD / 'actual-fabric.json')
    fabric['cache']['readPrefetchDemandAdoption'] = adoption
    assert load(model / 'actual-fabric.json') == fabric, 'complete actual fabric drift'
    assert (model / 'assembly-contract.json').read_bytes() == (OLD / 'assembly-contract.json').read_bytes()
    expected = b['options'] + (['--read-prefetch-demand-adoption'] if adoption else [])
    assert (model / 'options.txt').read_text().splitlines() == expected

def flags(mode, model):
    return [*state['flags'], '-DREAD_PREFETCH_DIRTY_RETRY=1',
            '-DREAD_PREFETCH_DEMAND_ADOPTION=' + str(int(mode == 'on')),
            '-I' + str(model), '-I' + str(FW), '-I' + str(HOST)]

def dependencies(model, mode):
    units = sorted(model.glob('BoardSocGsim[0-9]*.cpp'))
    for p in units:
        assert re.findall(r'^#include.*$', p.read_text(), re.M) == ['#include "BoardSocGsim.h"']
    text = step(mode + '-resolved-includes', [CXX, *state['flags'], '-I' + str(model), '-M', '-MT', 'unit', units[0]])
    paths = {str(pathlib.Path(p).resolve()) for p in shlex.split(text.replace('\\\n', ' ').split(':', 1)[1])}
    paths -= {str(units[0].resolve()), str((model / 'BoardSocGsim.h').resolve())}
    return {name: sha(name) for name in sorted(paths)}

def controls(mode):
    mode_dir = HERE / mode
    for stem in ['passive', 'ledger']:
        binary = mode_dir / ('test-' + stem)
        options = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                   '-DREAD_PREFETCH_DIRTY_RETRY=1', '-DREAD_PREFETCH_DEMAND_ADOPTION=' + str(int(mode == 'on'))]
        step(mode + '-' + stem + '-control-build', [CXX, *options, HERE / (stem + '_negative.cpp'), '-o', binary])
        step(mode + '-' + stem + '-positive', [binary], anchor='PASS', cwd=mode_dir)
        names = (['invalid-payload', 'sum', 'history', 'phase', 'pa', 'source', 'bucket'] if stem == 'passive' else
                 ['dirty', 'token', 'reserved', 'wb', 'pa', 'ack-block', 'payload', 'posted-pa', 'posted-duplicate',
                  'posted-generation', 'posted-missing-install', 'attach-pa', 'attach-ticket', 'attach-duplicate', 'attach-lost-binding'])
        for name in names:
            step(mode + '-' + stem + '-negative-' + name, [binary, '--' + name], 1, 'FAIL', cwd=mode_dir)

def record_case(mode, name, text, work):
    row = {key: parse(text, prefix) for key, prefix in [('result', 'CPU_SV39_RESULT'), ('perf', 'BOARD_IPC'),
           ('oracle', 'CPU_SV39_PASS'), ('fabric', 'FABRIC_IDLE_PASS')]}
    ref = b['cases'][name]
    assert sum(len(ref[k]) for k in row) == 105
    if mode == 'off':
        assert all(row[k] == ref[k] for k in row), 'OFF original 105-field calibration failed'
        assert sha(work / 'axi-events.tsv') == ref['raw']['axi-events.tsv'], 'OFF original complete AXI trace changed'
        row['calibration'] = 'EXACT_105_FIELDS_AND_COMPLETE_AXI_TRACE'
    else:
        assert state['modes']['off']['cases'][name]['calibration'] == 'EXACT_105_FIELDS_AND_COMPLETE_AXI_TRACE'
        for key in ['mode', 'op', 'bytes', 'reps', 'retired', 'pc_hash', 'loads', 'stores', 'lsu_capacity']:
            assert row['result'][key] == ref['result'][key], ('functional drift', key)
        assert row['oracle'] == ref['oracle'], 'byte/reply/checksum oracle drift'
        assert {k: v for k, v in row['fabric'].items() if k != 'samples'} == {k: v for k, v in ref['fabric'].items() if k != 'samples'}
        assert int(row['fabric']['samples']) > int(row['result']['cycles']) + int(row['result']['clean_tail'])
    row['counts'] = parse(text, 'PASSIVE_SUPPLY_COUNTS')
    row['ledger'] = parse(text, 'LEDGER_PASS')
    row['adoption'] = parse(text, 'ADOPTION_PASS')
    row['traffic_regions'] = [parse(line, 'LEDGER_TOTAL') for line in text.splitlines() if line.startswith('LEDGER_TOTAL ')]
    row['adoption_regions'] = [parse(line, 'ADOPTION_TOTAL') for line in text.splitlines() if line.startswith('ADOPTION_TOTAL ')]
    row['raw'] = {n: sha(work / n) for n in ['supply-events.tsv', 'axi-events.tsv']}
    state['modes'][mode]['cases'][name] = row
    save()

ap = argparse.ArgumentParser()
ap.add_argument('stage', choices=['freeze', 'emit', 'generate', 'compile', 'run', 'summarize'])
ap.add_argument('--mode', choices=['off', 'on'])
ap.add_argument('--case', choices=['sv39', 'bare'])
a = ap.parse_args()
if a.stage == 'freeze':
    assert not RECEIPT.exists(), 'freeze is immutable; preserve the earlier attempt'
    assert q['status'] == 'PASS_MATCHING_BOARD_B_OFF_ON_CPU_AB'
    assert b['status'] == 'COPY_TWO_MODES_AND_NEGATIVE_CONTROLS_PASS'
    assert subprocess.check_output(['git', '-C', str(ORIGIN), 'diff', PROD, COMMIT, '--', 'src/main']).strip() == b''
    tree = subprocess.check_output(['git', '-C', str(ORIGIN), 'ls-tree', '-r', COMMIT], text=True).splitlines()
    tracked = [line.split('\t', 1)[1] for line in tree if line.split()[1] == 'blob']
    for name in tracked:
        if name not in plan['wrappers']:
            assert (ROOT / name).read_bytes() == subprocess.check_output(['git', '-C', str(ORIGIN), 'show', COMMIT + ':' + name]), ('tracked source changed', name)
    for name, binding in plan['wrappers'].items():
        origin = pathlib.Path(plan['wrapper_source']) / name
        assert sha(origin) == binding['origin_sha256'] == q['inputs'][name]
        data = origin.read_bytes()
        if name == WRAPPER:
            data = data.replace(b'"--read-prefetch-dirty-retry",', b'"--read-prefetch-dirty-retry", "--read-prefetch-demand-adoption",')
        assert (ROOT / name).read_bytes() == data and sha(ROOT / name) == binding['prepared_sha256']
    assert len(plan['wrappers']) == 6
    source = files(ROOT)
    assert set(source) == set(tracked) | set(plan['wrappers']), 'untracked extra source'
    write(HERE / 'source-manifest.json', source)
    write(HERE / 'host-inputs.json', own())
    required = [QUAL / 'receipt.json', CAND / 'cpu-source-plan.json', HERE / 'source-manifest.json', HERE / 'host-inputs.json']
    required += [OLD / n for n in ['profile.json', 'actual-fabric.json', 'assembly-contract.json', 'options.txt']]
    required += [QUAL / 'on' / case / 'axi-events.tsv' for case in ['bare', 'sv39']]
    for name, expected in q['guest'].items():
        assert sha(FW / name) == expected
    for name, expected in q['tools'].items():
        assert sha(name) == expected
    state = {'schema': 'same-board-adoption-cpu-ab-v1', 'status': 'SOURCE_FROZEN_NO_DUT_WORK',
             'source_commit': COMMIT, 'production_checkpoint': PROD, 'inputs': source,
             'qualification_bridge': {n: h for n, h in source.items() if n.startswith(('src/main/', 'fpga/next/')) or n in ['build.mill', '.mill-version', '.mill-jvm-opts', 'simulator/gsim/fpga_next_board.py']},
             'host_inputs': own(), 'tools': q['tools'], 'guest': q['guest'], 'flags': q['flags'],
             'qualified_inputs': {str(p): sha(p) for p in sorted(required)}, 'wrappers': plan['wrappers'],
             'baseline': {'receipt_sha256': sha(QUAL / 'receipt.json'), 'mode': 'on', 'identity': 'PREVIOUS_QUALIFIED_DISTINCT_IDENTITY'},
             'modes': {mode: {'status': 'FROZEN', 'options': b['options'] + (['--read-prefetch-demand-adoption'] if mode == 'on' else []), 'cases': {}} for mode in ['off', 'on']},
             'commands': [], 'historical_dependency_limit': 'Old qualified historical system-header hashes are not retrospectively available. Current baseline ON include closure was captured after its fresh model build and before runtime. All new builds capture and bind the current resolved dependency closure.'}
    save()
    guard()
    print(state['status'])
    raise SystemExit(0)

state = load(RECEIPT)
guard()
gate()
# Additional fail-closed serialization for this runner. Parent owns the one
# global heavy-work slot across focused, CPU, and native qualification workers.
lock = (HERE / 'runner.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
try:
    if a.stage == 'summarize':
        assert all(m['status'] == 'COPY_TWO_MODES_AND_NEGATIVE_CONTROLS_PASS' for m in state['modes'].values())
        step('analysis', ['python3', HERE / 'analyze_cpu_ab.py'], anchor='ANALYSIS_PASS', cwd=HERE)
        state['status'] = 'PASS_SAME_BOARD_ADOPTION_OFF_ON_CPU_AB'
    else:
        assert a.mode
        mode = a.mode
        m = state['modes'][mode]
        model = HERE / mode / 'model'
        if a.stage == 'emit':
            assert m['status'] == 'FROZEN'
            model.mkdir(parents=True, exist_ok=False)
            step(mode + '-emit', [TOOL / 'bin/mill', '-i', 'IonSoC.test.runMain', 'ooo.CpuMatchingBoardProfileGsimMain', model, *m['options']])
            constructor(model, mode == 'on')
            m['emitted'] = {p.name: sha(p) for p in model.iterdir() if p.is_file()}
            m['status'] = 'EMITTED_FULL_CONSTRUCTOR_MATCH'
        elif a.stage == 'generate':
            assert m['status'] == 'EMITTED_FULL_CONSTRUCTOR_MATCH'
            check_map(model, m['emitted'])
            constructor(model, mode == 'on')
            step(mode + '-generate', [GSIM, '--threads=1', '--cpp-max-size-KB=1024', '--dir=' + str(model), model / 'BoardSocGsim.fir'])
            units = sorted(model.glob('BoardSocGsim[0-9]*.cpp'))
            assert len(units) > 1
            m['generated'] = {p.name: sha(p) for p in [model / 'BoardSocGsim.h', *units]}
            m['qualified_comparison'] = {'header_byte_identical': m['generated']['BoardSocGsim.h'] == b['generated']['BoardSocGsim.h'],
                'byte_identical_tus': [p.name for p in units if sha(p) == b['generated'].get(p.name)],
                'all_generated_bytes_identical': m['generated'] == b['generated'], 'no_semantic_normalization': True}
            m['status'] = 'GENERATED'
        elif a.stage == 'compile':
            assert m['status'] == 'GENERATED'
            check_generated(model, m)
            constructor(model, mode == 'on')
            step(mode + '-actual-host-syntax', [CXX, *flags(mode, model), '-fsyntax-only', HERE / 'cpu_passive_bandwidth.cpp'])
            controls(mode)
            m['dependencies'] = dependencies(model, mode)
            save()
            same_header = m['qualified_comparison']['header_byte_identical']
            reusable = set(m['qualified_comparison']['byte_identical_tus']) if same_header else set()
            reuse = state['authorization'].get('exact_tu_reuse_granted') is True
            if reusable and reuse:
                assert m['dependencies'] == b['reuse_dependency_sha256'], 'qualified/new resolved dependency closure differs'
                assert state['flags'] == q['flags'] and state['tools'] == q['tools']
            else:
                reusable = set()
            m['translation_units'] = {}
            for index, p in enumerate(sorted(model.glob('BoardSocGsim[0-9]*.cpp'))):
                obj = p.with_suffix('.o')
                if p.name in reusable:
                    old_obj = pathlib.Path(b['object_directory']) / obj.name
                    assert sha(old_obj) == b['objects'][obj.name]
                    shutil.copy2(old_obj, obj)
                    provenance = 'REUSED_EXACT_TU_HEADER_FLAGS_TOOL_AND_CURRENT_DEPENDENCIES'
                else:
                    step(mode + '-compile-' + str(index), [CXX, *state['flags'], '-I' + str(model), '-c', p, '-o', obj])
                    provenance = 'FRESH_OFFICIAL_GSIM_SPLIT_SERIAL_COMPILE'
                m['translation_units'][p.name] = {'cpp_sha256': sha(p), 'header_sha256': sha(model / 'BoardSocGsim.h'), 'object_sha256': sha(obj), 'provenance': provenance}
                save()
            m['objects'] = {p.name: sha(p) for p in sorted(model.glob('*.o'))}
            assert len(m['objects']) == len(m['translation_units'])
            objects = [model / n for n in sorted(m['objects'])]
            step(mode + '-host-link', [CXX, *flags(mode, model), HERE / 'cpu_passive_bandwidth.cpp', *objects, '-o', HERE / mode / 'run'])
            m['binary_sha256'] = sha(HERE / mode / 'run')
            m['status'] = 'HOST_CONTROLS_PASS'
        elif a.stage == 'run':
            assert m['status'] == 'HOST_CONTROLS_PASS'
            assert sha(HERE / mode / 'run') == m['binary_sha256']
            check_generated(model, m)
            assert {p.name: sha(p) for p in sorted(model.glob('*.o'))} == m['objects'], 'object file set/bytes changed'
            for vm, name in [(0, 'bare'), (1, 'sv39')]:
                if a.case and a.case != name:
                    continue
                assert name not in m['cases'], 'successful case must not be rerun silently'
                if mode == 'on':
                    assert name in state['modes']['off']['cases'], 'actual OFF calibration must precede ON'
                work = HERE / mode / name
                work.mkdir(exist_ok=False)
                text = step(mode + '-' + name, [HERE / mode / 'run', FW / 'guest.bin', vm, 2, 65536, 2], anchor='CPU_SV39_PASS', cwd=work)
                record_case(mode, name, text, work)
            if set(m['cases']) == {'bare', 'sv39'}:
                for injection, anchor in [('read', 'CPU read data mismatch'), ('memory', 'final copied/stored memory mismatch'), ('trap', 'unexpected CPU trap cause')]:
                    work = HERE / mode / ('negative-' + injection)
                    work.mkdir(exist_ok=False)
                    step(mode + '-negative-' + injection, [HERE / mode / 'run', FW / 'guest.bin', 1, 2, 4096, 1, '--inject-' + injection], 1, anchor, cwd=work)
                m['status'] = 'COPY_TWO_MODES_AND_NEGATIVE_CONTROLS_PASS'
    state.pop('failure', None)
    guard()
    save()
    print('STAGE_PASS', a.stage, a.mode, flush=True)
except Exception as error:
    state['failure'] = {'stage': a.stage, 'mode': a.mode, 'error': str(error)}
    save()
    raise
