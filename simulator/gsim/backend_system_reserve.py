#!/usr/bin/env python3
"""Actual backend CSR/retained-load-proof gate using an existing qualified BoardSocGsim model.

No Scala compilation, model generation, model-object compilation or production edits.
The original qualified model receipt supplies hashes and compile flags; existing
repository snapshots supply unchanged boot, tagged-owner oracle and DDR service.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'board$platform$core$core$core$backend$'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique(items, label):
    assert len(items) == 1, f'{label}: expected exactly one match, got {len(items)}'
    return items[0]


def bind(model, host, output):
    """Resolve actual final FIR controls; absent/ambiguous/object-shape drift fails closed."""
    fir = (model / 'BoardSocGsim.fir').read_text()
    header = (model / 'BoardSocGsim.h').read_text()
    module = unique(re.findall(r'^  module IntegerBackend :.*?(?=^  (?:module|extmodule) |\Z)', fir,
                               re.M | re.S), 'IntegerBackend module')
    mapping = {}

    def member(name):
        full = PREFIX + name
        unique(re.findall(r'^\w+(?:\s+_BitInt\(\d+\))?\s+' + re.escape(full) +
                          r'(?:\[\d+\])?;.*$', header, re.M), full)
        return full

    def final_connect(target):
        all_matches = re.findall(r'^(\s+)connect ' + re.escape(target) + r', ([^\n]+)', module, re.M)
        assert all_matches and all(len(indent) == 4 for indent, _ in all_matches), target
        rhs = [text.split(' @[')[0].strip() for _, text in all_matches]
        # WireDefault(false) plus one unconditional final assignment is allowed.
        assert all(x == 'UInt<1>(0h0)' for x in rhs[:-1]), (target, rhs)
        result = rhs[-1]
        assert re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', result), (target, result)
        return result

    for key, target in {
        'system': 'reserveSystem', 'start': 'lsu.io.start.valid',
        'flush': 'pendingStoreProof.io.flushQueries', 'interrupt': 'interruptDrain',
        'credit_reserve': 'pendingStoreCredit.io.reserve.valid',
        'credit_consume': 'pendingStoreCredit.io.consume.valid',
    }.items():
        driver = final_connect(target)
        mapping[key] = {'target': target, 'driver': driver, 'member': member(driver)}

    # In this pending-proof topology frontierReserve has only its constant-zero
    # assignment. Resolve the remaining named OR operand, rather than guessing
    # an anonymous suffix or silently accepting a different reservation route.
    frontier = re.findall(r'^\s+connect frontierReserve, ([^\n]+)', module, re.M)
    assert len(frontier) == 1 and frontier[0].split(' @[')[0] == 'UInt<1>(0h0)', frontier
    remaining = unique(re.findall(r'^    node reserveMemory = or\((\w+), frontierReserve\)', module, re.M),
                       'reserveMemory zero-frontier OR')
    unique(re.findall(r'^    node ' + re.escape(remaining) +
                      r' = and\(originalMemoryEligible, lsu.io.candidateIssueAvailable\)', module, re.M),
           'candidate reservation term')
    mapping['memory_reserve'] = {'target': 'reserveMemory', 'driver': remaining,
                                'member': member(remaining), 'frontierReserve': 0}
    # All remaining named state/data reads must be real unique typed members.
    raw = sorted(set(re.findall(r'B\(([^)]+)\)', host.read_text())) - {'x'})
    for name in raw:
        member(name)
    intrinsic = unique(re.findall(r'^    node loadPreparedIntrinsicValid = .+$', fir, re.M),
                       'actual bank intrinsic node')
    result = {'fir_sha256': sha(model / 'BoardSocGsim.fir'),
              'header_sha256': sha(model / 'BoardSocGsim.h'), 'controls': mapping,
              'named_members': raw, 'intrinsic_fir': intrinsic,
              'access': 'const read-only accessors; no generated model modification'}
    (output / 'bindings.json').write_text(json.dumps(result, indent=2) + '\n')
    lines = ['#pragma once', 'namespace reserve_probe {']
    lines += [f'template<class D> inline bool {key}(const D& d) {{ return d.{value["member"]}; }}'
              for key, value in mapping.items()]
    lines += ['}']
    (output / 'backend_system_reserve_bindings.h').write_text('\n'.join(lines) + '\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', required=True, type=Path)
    ap.add_argument('--model-receipt', required=True, type=Path,
                    help='qualified combined CPU receipt with objects/generated_inputs/contract')
    ap.add_argument('--output', required=True, type=Path, help='new, nonexistent output directory')
    ap.add_argument('--source-root', type=Path, default=ROOT)
    ap.add_argument('--host-root', type=Path, help='optional qualified service snapshot override')
    ap.add_argument('--cxx', default=os.environ.get('GSIM_CXX', 'clang++-19'))
    ap.add_argument('--cross-prefix', default='riscv64-unknown-elf-')
    ap.add_argument('--check-only', action='store_true', help='validate inputs and generate read-only binding only')
    args = ap.parse_args()
    root = args.source_root.resolve()
    model = args.model.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    host_root = (args.host_root or root / 'simulator/gsim/young_load_seal/posted_join_observation/host').resolve()
    source = root / 'simulator/gsim'
    host = source / 'harness/backend_system_reserve.cpp'
    guest = source / 'payloads/backend_system_reserve.S'
    linker = source / 'payloads/backend_system_reserve.ld'
    receipt = {'status': 'CHECKING', 'commands': [], 'model_rebuilt': False,
               'source_inputs': {str(p.relative_to(root)): sha(p) for p in [host, guest, linker]},
               'model_receipt_sha256': sha(args.model_receipt), 'negative_scope': 'host checker mutations only'}
    def save():
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    save()
    def run(label, argv, expected=0, anchors=()):
        start = time.monotonic()
        env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0', UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
        proc = subprocess.run(list(map(str, argv)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        log = output / (label + '.log')
        log.write_bytes(proc.stdout)
        text = proc.stdout.decode(errors='replace')
        receipt['commands'].append({'label': label, 'argv': list(map(str, argv)), 'exit': proc.returncode,
                                    'seconds': time.monotonic() - start, 'log_sha256': sha(log)})
        save()
        assert proc.returncode == expected and all(x in text for x in anchors), (label, text[-3000:])
        assert 'ERROR: AddressSanitizer' not in text and 'runtime error:' not in text, label
        return text
    try:
        base = json.loads(args.model_receipt.read_text())
        objects = []
        receipt['objects'] = {}
        for entry in base['objects']:
            path = model / Path(entry['unit']).with_suffix('.o').name
            assert sha(path) == entry['sha256'], path
            objects.append(path)
            receipt['objects'][path.name] = entry['sha256']
        assert objects and len(objects) == len(set(objects)), 'missing/duplicate model objects'
        for name in ['BoardSocGsim.fir', 'BoardSocGsim.h']:
            assert sha(model / name) == base['generated_inputs'][name], name
        for name, entry in base['contract']['host_sources'].items():
            assert sha(host_root / name) == entry['sha256'], name
        flags = base['contract']['flags']
        for flag in ['-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-DDDR_MODEL=1',
                     '-DDDR_MULTI_ID_MODEL=1', '-DDDR_BENCHMARK_MODEL=1', '-DBOARD_CPU_HZ=100000000',
                     '-DDDR_READ_CREDITS=8', '-DDDR_READ_LATENCY=32', '-DDDR_READ_BEAT_GAP=1',
                     '-DBOARD_EXPECTED_LSU_ENTRIES=4', '-DTAGGED_STORE_RETURNS=1']:
            assert flag in flags, 'qualified flags missing ' + flag
        assert not any(x.startswith('-I') or x.startswith('@') for x in flags), 'flags must not inject search paths'
        receipt['bindings'] = bind(model, host, output)
        receipt['service_sources'] = base['contract']['host_sources']
        receipt['flags'] = flags
        if args.check_only:
            receipt['status'] = 'INPUT_AND_READONLY_BINDING_PASS'; save(); return
        run('guest-link', [args.cross_prefix + 'gcc', '-march=rv64im_zicsr_zifencei', '-mabi=lp64',
                          '-nostdlib', '-Wl,--no-relax', '-T', linker, guest, '-o', output / 'guest.elf'])
        run('guest-bin', [args.cross_prefix + 'objcopy', '-O', 'binary', output / 'guest.elf', output / 'guest.bin'])
        symbols = run('guest-nm', [args.cross_prefix + 'nm', '-n', output / 'guest.elf'])
        wanted = {'reserve_csr': 'RESERVE_CSR', 'younger_load': 'YOUNGER_LOAD', 'terminal_ecall': 'TERMINAL_ECALL'}
        found = {parts[2]: parts[0] for line in symbols.splitlines()
                 if len(parts := line.split()) == 3 and parts[2] in wanted}
        assert set(found) == set(wanted), 'missing guest symbols'
        (output / 'backend_system_reserve_symbols.h').write_text(''.join(
            f'#define {wanted[name]} 0x{address}ULL\n' for name, address in found.items()))
        # Compile outside the source harness directory: quoted includes must resolve
        # against the verified service snapshot, not an unverified sibling host.
        linked_host = output / 'backend_system_reserve.cpp'
        linked_host.write_bytes(host.read_bytes())
        assert sha(linked_host) == sha(host)
        run('host-link', [args.cxx, *flags, '-I' + str(output), '-I' + str(model), '-I' + str(host_root),
                          '-I' + str(host_root / 'harness'), linked_host, *objects, '-o', output / 'run'])
        run('positive', [output / 'run', output / 'guest.bin'], anchors=[
            'ACTUAL_RESERVE_RETAINED_CERTIFICATE ', 'other_F=0 bind_rise=0', 'ACTUAL_BACKEND_RESERVE_PASS '])
        run('leaked-permit', [output / 'run', output / 'guest.bin', '--leaked-permit'], 1,
            ['NEGATIVE_REACHED leaked_final_permit', 'applied=1 witness=1', 'ORACLE_FINAL_FLUSH_PERMISSION'])
        run('stale-strict', [output / 'run', output / 'guest.bin', '--stale-strict'], 1,
            ['NEGATIVE_REACHED strict_flush_omitted', 'applied=1 witness=1', 'ORACLE_STRICT_FLUSH_PUBLICATION'])
        for entry in base['objects']:
            assert sha(model / Path(entry['unit']).with_suffix('.o').name) == entry['sha256'], 'model changed during test'
        receipt['artifacts'] = {p.name: sha(p) for p in output.iterdir() if p.is_file() and p.name != 'receipt.json'}
        receipt['status'] = 'ACTUAL_BACKEND_SYSTEM_RESERVE_PASS'; save()
    except BaseException as error:
        receipt['status'] = 'FAILED'; receipt['error'] = str(error); save(); raise


if __name__ == '__main__':
    main()
