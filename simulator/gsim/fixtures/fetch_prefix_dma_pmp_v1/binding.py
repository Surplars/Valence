"""Exact, source-bound contracts for unchanged executed CPU DMA/data-PMP gates."""
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import sys
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
GSIM = ROOT / 'simulator/gsim'
PRODUCTION = '2288c7f008e9d6440e8a28e339da28152b54892a'
HOST = '722a629fae1200074b363d84f431b77cda4e2560'
TREE = 'c6e69b6b539bc36285b602a39fae32cb76ea012c'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preflight_sources():
    lock = json.loads((HERE / 'source_lock.json').read_text())
    if (lock.get('schema'), lock.get('production'), lock.get('host'), lock.get('production_tree')) != (
            'valence-fetch-prefix-dma-pmp-source-lock-v1', PRODUCTION, HOST, TREE):
        raise RuntimeError('source lock identity drift')
    for relative, digest in lock['sources'].items():
        path = ROOT / relative
        if (Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink() or
                hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise RuntimeError('retained source/oracle/guest drift: ' + relative)
    return lock


# Validate reused Python sources before importing any of them.
LOCK = preflight_sources()
history = load('dma_pmp_frozen_history_binding', GSIM / 'fixtures/fetch_context_qualification_v1/binding.py')
v = history.v
require, sha, exact, contained = v.require, v.sha, v.exact, v.contained
sys.path.insert(0, str(GSIM))
import run as common
import fpga_next_board as board
import build_cpu_hot_bandwidth as tool_helper
import cpu_retire_prefix_data_pmp as pmp
dma_build = load('dma_pmp_original_dma_builder', GSIM / 'fixtures/cpu_dma_execute/build_guest.py')
dma_run = load('dma_pmp_original_dma_driver_binding', GSIM / 'fixtures/cpu_dma_execute/run_fixture.py')
CASES = ('dma', 'pmp')
NEGATIVES = {
    'dma': [('destination', 'independent DMA destination generation mismatch'),
            ('route', 'physical ingress route prediction mismatch'),
            ('return-token', 'backend return full-token lineage corruption'),
            ('read-region', 'unexpected guest RAM read region')],
    'pmp': list(pmp.NEGATIVES.items()),
}
ANCHORS = {'dma': 'EXEC_CPU_DMA_PASS', 'pmp': 'DATA_PMP_BOARD_PASS'}
GUEST_SOURCES = {
    'dma': {'guest.S': 'simulator/gsim/fixtures/cpu_dma_execute/cpu_dma_execute.S',
            'guest.ld': 'simulator/gsim/fixtures/cpu_dma_execute/cpu_dma_execute.ld'},
    'pmp': {'guest.S': 'simulator/gsim/payloads/cpu_flow_data_pmp.S',
            'guest.ld': 'simulator/gsim/payloads/cpu_hot_bandwidth.ld'},
}
GUEST_PROFILE = {'dma': dma_build.PROFILE,
                 'pmp': {'march': 'rv64im_zicsr_zifencei', 'mabi': 'lp64', 'base': 0x80200000,
                         'denied_s_reads': 1, 'denied_mprv_reads': 1, 'traps': 3}}
GUEST_SCHEMA = 'valence-fetch-prefix-dma-pmp-portable-guests-v1'
GUEST_PASS = 'PASS_PORTABLE_GUEST_BUILD_ONLY'


def clean_log(text, anchor=None, negative=False):
    history.clean_log(text, anchor, negative)
    if negative:
        require(not any(x in text for x in ANCHORS.values()), 'negative reported success')


def model_pair(receipts, compiler):
    require(set(receipts) == {'off', 'on'} and receipts['off'] != receipts['on'],
            'two distinct explicit model receipts required')
    inputs = board.source_inventory()
    require(exact(inputs, LOCK['model_inputs']), 'complete current model input inventory drift')
    models, evidence = {}, {}
    for side, path in receipts.items():
        require(sha(path) == LOCK['model_receipts'][side], 'qualified model receipt drift: ' + side)
        models[side] = v.validate_model(path, inputs, compiler, common.LOCK, older_prefix=side == 'on')
        evidence[side] = history.historical_evidence(path, models[side][0], models[side][2])
        dma_run.check_schema(models[side][1])
    return models, evidence


def include_guard(models, guest_root=None):
    history.include_guard(models)
    require(not (GSIM / 'harness/guest_symbols.h').exists(), 'source symbol-header shadow')
    for _, model, _ in models.values():
        require(not (model / 'guest_symbols.h').exists(), 'model symbol-header shadow')
    if guest_root:
        require(set(p.name for p in (guest_root / 'pmp').iterdir()) <= {
            'sources', 'guest.o', 'guest.elf', 'guest.bin', 'guest_symbols.h',
            'assemble.log', 'link.log', 'binary.log', 'symbols.log'}, 'guest include shadow')


def guest_commands(case, paths):
    flags = ['-march=rv64im_zicsr_zifencei', '-mabi=lp64', '-mno-relax']
    # Same recipes and unchanged source bytes as the retained independent builders.
    link = [paths['cc'], *flags, '-nostdlib', '-nostartfiles', '-Wl,--no-relax']
    link += ['-Wl,--build-id=none', '-T', 'sources/guest.ld'] if case == 'dma' else ['-Wl,-T,sources/guest.ld']
    return {
        'assemble': [str(x) for x in [paths['cc'], *flags, '-c', 'sources/guest.S', '-o', 'guest.o']],
        'link': [str(x) for x in [*link, 'guest.o', '-o', 'guest.elf']],
        'binary': [str(paths['objcopy']), '-O', 'binary', 'guest.elf', 'guest.bin'],
        'symbols': [str(paths['nm']), '-n', 'guest.elf'],
    }


def guest_symbols(case, text):
    if case == 'pmp':
        return pmp.parse_symbols(text)
    symbols = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] in dma_build.SYMBOLS:
            require(fields[2] not in symbols, 'duplicate DMA symbol')
            symbols[fields[2]] = int(fields[0], 16)
    require(set(symbols) == dma_build.SYMBOLS and symbols['_start'] == 0x80000000, 'DMA symbol layout drift')
    return symbols


def symbol_file(case, symbols):
    return ('symbols.txt', dma_build.symbol_text(symbols)) if case == 'dma' else (
        'guest_symbols.h', pmp.symbol_header(symbols))


def guest_audit(directory, paths, versions):
    state = json.loads(contained(directory, 'manifest.json').read_text())
    require(state.get('schema') == GUEST_SCHEMA and state.get('status') == GUEST_PASS, 'unfinished guest bundle')
    require(exact(state.get('profile'), GUEST_PROFILE), 'guest profile drift')
    require(exact(state.get('toolchain'), versions) and exact(state.get('gsim_lock'), common.LOCK), 'guest toolchain drift')
    require(state.get('builder_sha256') == sha(HERE / 'build_guests.py') and
            state.get('binding_sha256') == sha(__file__), 'guest builder binding drift')
    require(set(state.get('cases', {})) == set(CASES), 'guest case inventory drift')
    expected_files = {'manifest.json'}
    for case in CASES:
        record = state['cases'][case]
        root = contained(directory, case)
        sources = {name: sha(ROOT / original) for name, original in GUEST_SOURCES[case].items()}
        require(exact(record.get('sources'), sources), 'guest original source drift')
        for name, digest in sources.items():
            require(sha(contained(root, 'sources/' + name)) == digest, 'copied guest source drift')
        commands = guest_commands(case, paths)
        require(set(record.get('steps', {})) == set(commands), 'guest step inventory drift')
        artifacts = {}
        for name, argv in commands.items():
            step = record['steps'][name]
            expected = {'command': [Path(argv[0]).name, *argv[1:]], 'exit': 0, 'log': name + '.log'}
            require(all(exact(step.get(k), value) for k, value in expected.items()), 'guest command/exit drift: ' + name)
            text = contained(root, step['log']).read_text()
            require(sha(root / step['log']) == step.get('log_sha256'), 'guest log drift')
            clean_log(text)
            if name == 'symbols':
                symbols = guest_symbols(case, text)
        filename, header = symbol_file(case, symbols)
        require(exact(record.get('symbols'), symbols) and (root / filename).read_text() == header, 'guest symbol/header drift')
        size = (root / 'guest.bin').stat().st_size
        base, limit = (0x80000000, 128 * 1024) if case == 'dma' else (0x80200000, 16384)
        require(0 < size < limit and all(type(value) is int and base <= value < base + size for value in symbols.values()),
                'guest image/symbol bounds drift')
        for name in ('guest.o', 'guest.elf', 'guest.bin', filename):
            artifacts[name] = sha(contained(root, name))
        require(exact(record.get('artifacts'), artifacts), 'guest artifact inventory/content drift')
        expected_files |= {case + '/' + name for name in (*artifacts, *(name + '.log' for name in commands),
                                                            *('sources/' + name for name in sources))}
    actual = set()
    for item in directory.rglob('*'):
        require(not item.is_symlink(), 'guest bundle symlink')
        if item.is_file():
            actual.add(item.relative_to(directory).as_posix())
    require(actual == expected_files, 'complete guest file inventory drift')
    return state


def link_command(case, cxx, model, objects, out, guests):
    extra = ['-DPHYSICAL_INGRESS_FLOW=1'] if case == 'dma' else ['-I' + str(guests / 'pmp')]
    source = GSIM / ('fixtures/cpu_dma_execute/cpu_dma_execute.cpp' if case == 'dma' else 'harness/cpu_flow_data_pmp.cpp')
    ceiling = 300000 if case == 'dma' else 100000
    return list(map(str, [cxx, *history.CXX_FLAGS, *history.BOARD_FLAGS,
        '-DBOARD_CYCLE_LIMIT=' + str(ceiling) + 'ULL', *extra, '-I' + str(model),
        '-I' + str(GSIM / 'harness'), source, *objects, '-ldl', '-o', out]))


def metrics(case, text):
    clean_log(text, ANCHORS[case])
    if case == 'pmp':
        return pmp.parse_result(text)
    rows = [line for line in text.splitlines() if line.startswith('EXEC_CPU_DMA_PASS')]
    require(len(rows) == 1, 'missing/ambiguous DMA result')
    pairs = [word.split('=', 1) for word in rows[0].split()[1:]]
    require(all(len(p) == 2 for p in pairs) and len({p[0] for p in pairs}) == len(pairs), 'duplicate/malformed DMA result')
    fields = dict(pairs)
    numeric = {'descriptors', 'success', 'injected_read_error', 'restart', 'cycles', 'retired', 'cpu_ram_while_dma',
        'scratch_reads_while_dma', 'scratch_writes_while_dma', 'dirty_source_state_cycles', 'dirty_destination_state_cycles',
        'dirty_source_checked_beats', 'dirty_destination_checked_beats', 'lsu_entries', 'lsu_resident_peak',
        'terminal_live_owners', 'complete_owner_drain', 'dma_resident_slots_peak', 'verified_cpu_loads',
        'physical_ingress_flow', 'physical_ingress_passes', 'packet_dma', 'mac_cdc'}
    require(set(fields) == numeric | {'stop_abort'} and fields['stop_abort'] == 'unsupported', 'DMA result field inventory drift')
    require(all(re.fullmatch(r'[0-9]+', fields[k]) for k in numeric), 'invalid DMA numeric field')
    result = {k: int(fields[k]) for k in numeric}
    fixed = {'descriptors': 4, 'success': 3, 'injected_read_error': 1, 'restart': 1, 'lsu_entries': 4,
             'terminal_live_owners': 0, 'complete_owner_drain': 1, 'physical_ingress_flow': 1, 'packet_dma': 0, 'mac_cdc': 0}
    require(all(result[k] == value for k, value in fixed.items()), 'DMA required result witness drift')
    require(0 < result['cycles'] < 300100 and 2 <= result['dma_resident_slots_peak'] <= 4 and
            1 <= result['lsu_resident_peak'] <= 4, 'DMA bounds drift')
    require(all(result[k] > 0 for k in numeric - set(fixed) - {'cycles', 'dma_resident_slots_peak', 'lsu_resident_peak'}),
            'DMA nonzero witness missing')
    return result


def toolchain(cxx_name='clang++-19'):
    import os
    import shutil
    require(os.environ.get('RISCV_PREFIX', 'riscv64-unknown-elf-') == 'riscv64-unknown-elf-', 'unqualified RISCV_PREFIX')
    for name in ('CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'LIBRARY_PATH', 'LD_LIBRARY_PATH',
                 'COMPILER_PATH', 'GCC_EXEC_PREFIX', 'PYTHONOPTIMIZE'):
        require(not os.environ.get(name), 'unqualified tool environment: ' + name)
    os.environ['GSIM_CXX'] = cxx_name
    _, version = common.compiler()
    found = shutil.which(cxx_name)
    require(found and re.fullmatch(r'clang\+\+(?:-\d+)?', Path(found).name), 'qualified clang++ driver required')
    cxx = str(Path(found).absolute())  # Preserve driver name rather than invoking the clang symlink target.
    require(os.environ.get('CPATH') in (None, '', str(Path(cxx).parents[1] / 'include')),
            'unqualified include search path')
    paths, versions = tool_helper.toolchain()
    require(exact({'sha256': sha(cxx), 'version': version}, LOCK['host_compiler']), 'approved host compiler drift')
    require(exact(versions, LOCK['guest_toolchain']), 'approved guest compiler/binutils drift')
    return cxx, version, paths, versions
