#!/usr/bin/env python3
"""Narrow unchanged fetch-PMP/Sv39 qualification on explicit current board models.

--prepare is source/model/tool validation only. --execute links four existing
harness/model pairs and runs four positives plus eight existing negatives, in
sequence. It never elaborates or recompiles generated models. Choose fresh
outputs; --audit verifies a completed execution without simulating again.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binding as b
sys.path.insert(0, str(b.GSIM))
import fpga_next_board as board
import run as common
import build_cpu_hot_bandwidth as tool_helper
import build_virtual_load_core as virtual_builder
from virtual_load_board import parse as parse_virtual
import elf_debug_compression as compression

SCHEMA = 'valence-fetch-context-qualification-v1'
PASS = 'PASS_FETCH_HISTORY_CONTEXT_PREFIX_OFF_ON'
LIMITS = [
    'Unchanged independent directed guest/harness oracles; no DUT-derived expected values.',
    'Fetch guest checks cached compressed gate grant/revoke/restore, denied nonexecution and exact mepc/mtval; host checks trap order 9/1/9.',
    'Sv39 MPRV/S-effective DATA translation, warm/cold/chase/4KiB alias, full signature, precise load-page fault, wrong-path retirement/MMIO suppression and drain.',
    'Sv39 guest does not establish instruction-page translation epochs or arbitrary frontend context/interrupt schedules.',
    'The unchanged virtual harness legacy lsu_peak counts slots 0/1 only; no full LSU occupancy claim. Ownership ledger is four-owner.',
    'DMA line depth4/yield0 remains configured but idle. No external DMA/coherence probe injection.',
    'No new RV64GC, atomics, NEMU, hot/64KiB/steady, Linux, FPGA timing/resources or physical board coverage.',
    'Existing terminal RV64GC model smoke is provenance only, not a newly executed test in this narrow suite.',
    'The reused fetch harness context_fprs field is a generic label, not FPR coverage here; s_ecall=3 is the total 9/1/9 trap count.',
    'Cycles are observations, not a performance acceptance gate.',
]
ENV_KEYS = ('PATH', 'CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'LIBRARY_PATH', 'LD_LIBRARY_PATH',
            'COMPILER_PATH', 'GCC_EXEC_PREFIX', 'RISCV_PREFIX', 'ASAN_OPTIONS', 'UBSAN_OPTIONS')


def tools(cxx_name):
    b.require(os.environ.get('RISCV_PREFIX', 'riscv64-unknown-elf-') == 'riscv64-unknown-elf-',
              'unqualified RISCV_PREFIX override')
    os.environ['GSIM_CXX'] = cxx_name
    _, version = common.compiler()
    driver = shutil.which(cxx_name)
    b.require(driver and __import__('re').fullmatch(r'clang\+\+(?:-\d+)?', Path(driver).name),
              'qualified clang++ driver required')
    # Preserve clang++ argv spelling: resolving its symlink changes linkage mode.
    cxx = str(Path(driver).absolute())
    paths, records = tool_helper.toolchain()
    objdump = shutil.which('riscv64-unknown-elf-objdump')
    b.require(objdump, 'missing approved objdump')
    paths['objdump'] = Path(objdump).resolve()
    records['objdump'] = {'name': paths['objdump'].name, 'sha256': b.sha(paths['objdump']),
        'version': subprocess.check_output([paths['objdump'], '--version'], text=True).splitlines()[0],
        'version_source': 'executable --version'}
    for key, suffix in [('cc', 'gcc'), ('objcopy', 'objcopy'), ('objdump', 'objdump'), ('nm', 'nm')]:
        b.require(Path(shutil.which('riscv64-unknown-elf-' + suffix)).resolve() == paths[key],
                  'guest helper tool resolution mismatch: ' + key)
    return cxx, version, paths, records


def contracts(out, cxx, paths, models, compressed):
    fw = out / 'firmware'
    commands = {}
    def add(name, argv, products=(), expected=0, anchor=None):
        commands[name] = {'command': list(map(str, argv)), 'products': list(products),
                          'expected_exit': expected, 'anchor': anchor}
    add('virtual-build', [sys.executable, b.GSIM / 'build_virtual_load_core.py', fw / 'virtual'],
        ['firmware/virtual/' + name for name in ('guest.o', 'guest.elf', 'guest.bin', 'guest.json', 'guest.dis', 'guest.nm')])
    elf, binary = fw / 'fetch-permission.elf', fw / 'fetch-permission.bin'
    add('fetch-permission-build', [paths['cc'], *b.FETCH_FLAGS, '-T', b.ROOT / 'fpga/firmware/sample_app.ld',
        b.ROOT / 'fpga/firmware/fetch_permission_smoke.S', '-o', elf], ['firmware/fetch-permission.elf'])
    add('fetch-permission-bin', [paths['objcopy'], '-O', 'binary', elf, binary], ['firmware/fetch-permission.bin'])
    add('fetch-permission-disassembly', [paths['objdump'], '-d', elf])
    for label, (_, model, objects) in models.items():
        for case in b.CASES:
            name = label + '-' + case
            linked = name + '.uncompressed' if compressed else name
            add(name + '-link', b.link_command(cxx, model, objects, out / linked, case, fw), [linked])
            guest = binary if case == 'fetch-permission' else fw / 'virtual/guest.bin'
            args = ['--fetch-permission'] if case == 'fetch-permission' else []
            add(name + '-run', [out / name, guest, *args], anchor=b.ANCHORS[case])
            for mode, anchor in b.NEGATIVES[case]:
                add(name + '-negative-' + mode, [out / name, guest, *args, '--inject-' + mode], expected=1, anchor=anchor)
    return commands


def virtual_manifest(out, paths, versions):
    directory = out / 'firmware/virtual'
    guest = json.loads((directory / 'guest.json').read_text())
    source, linker = b.GSIM / 'payloads/virtual_load_core.S', b.GSIM / 'payloads/virtual_load_core.ld'
    elf, binary, obj = directory / 'guest.elf', directory / 'guest.bin', directory / 'guest.o'
    # The unchanged helper uses shutil.which spelling, which can include a symlink.
    gcc = shutil.which('riscv64-unknown-elf-gcc')
    flags = ['-march=rv64imac_zicsr_zifencei', '-mabi=lp64', '-mno-relax']
    expected_commands = [list(map(str, [gcc, *flags, '-c', source, '-o', obj])),
        list(map(str, [gcc, *flags, '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
                       '-Wl,-T,' + str(linker), obj, '-o', elf]))]
    b.require(guest.get('status') == 'BUILT_NOT_EXECUTED' and guest.get('elf') == str(elf) and
              guest.get('binary') == str(binary) and b.exact(guest.get('compile_commands'), expected_commands),
              'virtual guest build recipe/path drift')
    b.require(guest.get('toolchain') == versions['cc']['version'], 'virtual guest compiler drift')
    expected_hashes = {str(p.relative_to(b.ROOT)) if p.is_relative_to(b.ROOT) else str(p): b.sha(p)
                       for p in (source, linker, elf, binary)}
    b.require(guest.get('sha256') == expected_hashes, 'virtual guest artifact/source drift')
    symbol_rows = {}
    for line in (directory / 'guest.nm').read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] in virtual_builder.SYMBOLS:
            b.require(parts[2] not in symbol_rows, 'duplicate virtual symbol')
            symbol_rows[parts[2]] = int(parts[0], 16)
    b.require(set(guest.get('symbols', {})) == set(virtual_builder.SYMBOLS) and
              guest['symbols'] == symbol_rows, 'virtual guest symbol drift')
    b.require(guest['symbols']['_start'] == 0x80200000 and 0 < binary.stat().st_size < 65536,
              'virtual guest bounds drift')
    return guest


def audit(out, state, allowed, paths, versions, terminal):
    b.require(state['schema'] == SCHEMA and state['limitations'] == LIMITS, 'qualification schema/scope drift')
    b.require(state['model_elaborations'] == state['generated_model_compiles'] == state['production_changes'] == 0,
              'qualification scope counters drift')
    b.require(set(state['steps']) <= set(allowed), 'unexpected execution step')
    products = {}
    logs = {}
    for name, record in state['steps'].items():
        contract = allowed[name]
        b.require(record['command'] == contract['command'] and record['expected_exit'] == contract['expected_exit'] and
                  type(record['actual_exit']) is int and record['actual_exit'] == contract['expected_exit'] and
                  record['anchor'] == contract['anchor'] and record['status'] == 'PASS', 'execution contract drift: ' + name)
        b.require(set(record['artifacts']) == set(contract['products']), 'execution product inventory drift: ' + name)
        for relative, digest in record['artifacts'].items():
            b.require(b.sha(b.contained(out, relative)) == digest, 'execution product drift: ' + relative)
            products[relative] = digest
        b.require(record['log'] == name + '.log', 'execution log path drift')
        log = b.contained(out, record['log'])
        b.require(b.sha(log) == record['log_sha256'], 'execution log drift: ' + name)
        logs[name] = log.read_text()
        b.clean_log(logs[name], contract['anchor'], bool(contract['expected_exit']))
    if 'virtual-build' in logs:
        guest = virtual_manifest(out, paths, versions)
        b.require(state['guests'].get('virtual') == guest, 'virtual guest receipt drift')
        header = out / 'firmware/virtual_load_guest_symbols.h'
        b.require(header.read_text() == b.header_text(guest), 'virtual header drift')
        products['firmware/virtual_load_guest_symbols.h'] = b.sha(header)
    expected_cases = {label + '-' + case for label in ('off', 'on') for case in b.CASES}
    expected_negatives = {name + '-negative-' + mode for name in expected_cases
                          for mode, _ in b.NEGATIVES[name.split('-', 1)[1]]}
    b.require(set(state['cases']) <= expected_cases and set(state['negative_controls']) <= expected_negatives,
              'case/negative inventory drift')
    for name, case in state['cases'].items():
        contract = allowed[name + '-run']
        executable, guest = map(Path, contract['command'][:2])
        expected = {'status': 'PASS', 'metrics': b.metrics(name.split('-', 1)[1], logs[name + '-run'], parse_virtual),
                    'guest_sha256': b.sha(guest), 'executable_sha256': b.sha(executable)}
        b.require(b.exact(case, expected), 'case/log disagreement: ' + name)
        b.require(name + '-link' in logs, 'case lacks fresh harness link')
        b.require(('fetch-permission-bin' if name.endswith('fetch-permission') else 'virtual-build') in logs,
                  'case lacks guest build')
    for name, record in state['negative_controls'].items():
        b.require(name in logs and record == {'status': 'REJECTED', 'expected_exit': 1, 'anchor': allowed[name]['anchor']},
                  'negative/log disagreement: ' + name)
    if state['compress_debug']:
        for name, proof in state['debug_compression'].items():
            b.require(name in expected_cases and name + '-link' in logs, 'unexpected compression proof')
            receipt = out / (name + '.debug-compression.json')
            b.require(proof == compression.validate_compression_receipt(out / (name + '.uncompressed'), out / name, receipt),
                      'compression proof drift')
            products[name] = b.sha(out / name)
            products[receipt.name] = b.sha(receipt)
        b.require(set(state['cases']) <= set(state['debug_compression']), 'run lacks compressed byte-equivalence proof')
    else:
        b.require(not state['debug_compression'], 'unexpected debug compression')
    b.require(state['artifacts'] == products, 'complete output artifact inventory drift')
    if terminal:
        b.require(set(state['steps']) == set(allowed) and set(state['cases']) == expected_cases and
                  set(state['negative_controls']) == expected_negatives, 'incomplete terminal evidence')
        b.require(state.get('architectural_ab_equivalence') == b.equivalent(state['cases']), 'A/B equivalence drift')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag in ('prepare', 'execute', 'audit'):
        mode.add_argument('--' + flag, action='store_true')
    parser.add_argument('--off-receipt', type=Path, required=True)
    parser.add_argument('--on-receipt', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cxx', default=os.environ.get('GSIM_CXX', 'clang++-19'))
    parser.add_argument('--compress-debug', action='store_true', help='Retain original links; prove only unloaded debug compression changed')
    args = parser.parse_args()
    b.require(__debug__, 'Python -O/PYTHONOPTIMIZE unsupported')
    lock = b.source_lock()
    source_binding = b.v.production_anchor(b.ROOT, b.PRODUCTION, b.HOST, b.PRODUCTION_TREE)
    cxx, compiler, paths, versions = tools(args.cxx)
    b.require({'sha256': b.sha(cxx), 'version': compiler} == lock['host_compiler'],
              'approved host compiler executable/version drift')
    b.require(versions == lock['guest_toolchain'], 'approved guest compiler/binutils/component drift')
    debug_tools = compression.installed_tools() if args.compress_debug else {}
    b.require(not args.compress_debug or {key: {k: v for k, v in item.items() if k != 'path'}
        for key, item in debug_tools.items()} == lock['debug_toolchain'], 'approved debug toolchain drift')
    inputs = board.source_inventory()
    b.require(inputs == lock['model_inputs'], 'complete current model input inventory drift')
    receipts = {'off': args.off_receipt.resolve(), 'on': args.on_receipt.resolve()}
    b.require(receipts['off'] != receipts['on'], 'two distinct explicit model receipts required')
    models, historical = {}, {}
    for label, receipt in receipts.items():
        b.require(b.sha(receipt) == lock['model_receipts'][label], 'qualified current receipt drift: ' + label)
        models[label] = b.v.validate_model(receipt, inputs, compiler, common.LOCK, older_prefix=label == 'on')
        historical[label] = b.historical_evidence(receipt, models[label][0], models[label][2])
    b.include_guard(models)
    out = args.out.resolve()
    b.require(out != b.ROOT and all(not receipt.parent.is_relative_to(out) and not out.is_relative_to(receipt.parent)
                                  for receipt in receipts.values()), 'output overlaps source/model checkpoint')
    frozen_paths = [HERE / name for name in ('run_fixture.py', 'binding.py', 'source_lock.json')]
    frozen_paths += [Path(cxx), Path(sys.executable), *paths.values(),
                     *(Path(item['path']) for item in debug_tools.values())]
    frozen = {str(path): b.sha(path) for path in frozen_paths}
    environment = {key: os.environ.get(key) for key in ENV_KEYS}
    identity = {'schema': SCHEMA, 'limitations': LIMITS, 'source_binding': source_binding,
        'model_inputs': inputs, 'source_lock_sha256': b.sha(HERE / 'source_lock.json'),
        'model_receipts': {label: {'path': str(path), 'sha256': b.sha(path), 'plan': models[label][0]['plan'],
            'historical_evidence': historical[label]} for label, path in receipts.items()},
        'host_compiler': {'driver': cxx, 'sha256': b.sha(cxx), 'version': compiler},
        'guest_tools': {key: {'path': str(paths[key]), **record} for key, record in versions.items()},
        'debug_tools': debug_tools,
        'subprocess_environment_overrides': {'ASAN_OPTIONS': 'detect_leaks=0', 'PYTHONDONTWRITEBYTECODE': '1'},
        'frozen_files': frozen, 'environment': environment, 'compress_debug': args.compress_debug,
        'model_elaborations': 0, 'generated_model_compiles': 0, 'production_changes': 0}
    allowed = contracts(out, cxx, paths, models, args.compress_debug)
    if args.audit:
        state = json.loads((out / 'receipt.json').read_text())
        b.require(all(b.exact(state.get(key), value) for key, value in identity.items()), 'audit input identity drift')
        b.require(state['status'] == PASS, 'audit requires a completed narrow qualification')
    else:
        b.require(not out.exists(), 'fresh output required; use --audit for completed evidence')
        out.mkdir(parents=True)
        state = {**identity, 'status': 'PREPARED_NOT_EXECUTED', 'steps': {}, 'guests': {}, 'cases': {},
                 'negative_controls': {}, 'artifacts': {}, 'debug_compression': {}}
    def save():
        (out / 'receipt.json').write_text(json.dumps(state, indent=2) + '\n')
    def guard():
        b.require(b.source_lock() == lock, 'source lock changed')
        b.require(b.v.production_anchor(b.ROOT, b.PRODUCTION, b.HOST, b.PRODUCTION_TREE) == source_binding,
                  'production/host binding changed')
        b.require(board.source_inventory() == inputs, 'complete model source inventory changed')
        b.require({key: os.environ.get(key) for key in ENV_KEYS} == environment, 'compiler/runtime environment drift')
        for path, digest in frozen.items():
            b.require(b.sha(path) == digest, 'frozen tool/runner changed: ' + path)
        for label, receipt in receipts.items():
            b.require(b.sha(receipt) == lock['model_receipts'][label], 'model receipt changed')
            current = b.v.validate_model(receipt, inputs, compiler, common.LOCK, older_prefix=label == 'on')
            b.require(current[1:] == models[label][1:], 'model path/object inventory changed')
            b.require(b.historical_evidence(receipt, current[0], current[2]) == historical[label], 'model history changed')
        b.include_guard(models, out / 'firmware')
        for name, digest in state['artifacts'].items():
            b.require(b.sha(b.contained(out, name)) == digest, 'output artifact changed: ' + name)
        for name, record in state['steps'].items():
            b.require(b.sha(b.contained(out, record['log'])) == record['log_sha256'], 'output log changed: ' + name)
    def step(name):
        guard()
        contract = allowed[name]
        log = out / (name + '.log')
        b.require(not log.exists(), 'refusing step overwrite')
        print('+ ' + ' '.join(contract['command']), flush=True)
        began = time.monotonic()
        with log.open('x') as stream:
            code = subprocess.run(contract['command'], cwd=b.ROOT, stdout=stream, stderr=subprocess.STDOUT,
                timeout=900, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'PYTHONDONTWRITEBYTECODE': '1'}).returncode
        text = log.read_text()
        b.require(code == contract['expected_exit'], name + ' exit failure:\n' + text[-6000:])
        b.clean_log(text, contract['anchor'], bool(contract['expected_exit']))
        products = {name: b.sha(b.contained(out, name)) for name in contract['products']}
        state['steps'][name] = {'command': contract['command'], 'actual_exit': code,
            'expected_exit': contract['expected_exit'], 'anchor': contract['anchor'], 'status': 'PASS',
            'artifacts': products, 'log': log.name, 'log_sha256': b.sha(log), 'seconds': time.monotonic() - began}
        state['artifacts'].update(products)
        save()
        return text
    guard()
    if args.audit:
        audit(out, state, allowed, paths, versions, True)
        print('PASS_REVALIDATED_NARROW_QUALIFICATION execution=0', out / 'receipt.json')
        return
    save()
    if args.prepare:
        print('PASS_SOURCE_MODEL_PROFILE_RECIPE_TOOL_BINDING_ONLY execution=0', out / 'receipt.json')
        return
    state['status'] = 'RUNNING'
    save()
    try:
        (out / 'firmware').mkdir()
        step('virtual-build')
        guest = virtual_manifest(out, paths, versions)
        state['guests']['virtual'] = guest
        header = out / 'firmware/virtual_load_guest_symbols.h'
        header.write_text(b.header_text(guest))
        state['artifacts']['firmware/virtual_load_guest_symbols.h'] = b.sha(header)
        save()
        for name in ('fetch-permission-build', 'fetch-permission-bin', 'fetch-permission-disassembly'):
            step(name)
        for label in ('off', 'on'):
            for case in b.CASES:
                name = label + '-' + case
                step(name + '-link')
                if args.compress_debug:
                    guard()
                    proof = out / (name + '.debug-compression.json')
                    state['debug_compression'][name] = compression.compress_new(out / (name + '.uncompressed'), out / name, proof)
                    for product in (name, proof.name):
                        state['artifacts'][product] = b.sha(out / product)
                    compression.validate_compression_receipt(out / (name + '.uncompressed'), out / name, proof)
                    save()
                text = step(name + '-run')
                command = allowed[name + '-run']['command']
                state['cases'][name] = {'status': 'PASS', 'metrics': b.metrics(case, text, parse_virtual),
                    'guest_sha256': b.sha(command[1]), 'executable_sha256': b.sha(command[0])}
                save()
                print(name + ' PASS\n' + '\n'.join(line for line in text.splitlines()
                    if line.startswith(('FETCH_PERMISSION_BOARD_PASS', 'VIRTUAL_BOARD_ARCH', 'VIRTUAL_BOARD_PASS'))), flush=True)
                for mode, anchor in b.NEGATIVES[case]:
                    negative = name + '-negative-' + mode
                    step(negative)
                    state['negative_controls'][negative] = {'status': 'REJECTED', 'expected_exit': 1, 'anchor': anchor}
                    save()
        state['architectural_ab_equivalence'] = b.equivalent(state['cases'])
        guard()
        audit(out, state, allowed, paths, versions, True)
        state['status'] = PASS
    except BaseException as error:
        state['status'] = 'FAIL'
        state['error'] = str(error)
        raise
    finally:
        save()
    print(state['status'], out / 'receipt.json', flush=True)


if __name__ == '__main__':
    main()
