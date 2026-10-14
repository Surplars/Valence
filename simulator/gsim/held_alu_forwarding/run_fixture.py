#!/usr/bin/env python3
"""Explicit bounded observer host link/run using externally supplied model objects."""
import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from check_fixture import HERE, check, read, sha
from binding_memory_verify import verify
from prepare_inputs import generated_guests, generated_controls

def save(path, data): path.write_text(json.dumps(data, indent=2)+'\n')

def main():
    if sys.flags.optimize: raise SystemExit('Python assertions must remain enabled')
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('action', choices=['link', 'run'])
    p.add_argument('--mode', choices=['off', 'on'], required=True)
    p.add_argument('--off-model', type=Path, required=True)
    p.add_argument('--on-model', type=Path, required=True)
    p.add_argument('--toolchain', type=Path, required=True, help='Explicit activation shell script')
    p.add_argument('--cxx', type=Path, required=True, help='Explicit host C++ compiler')
    p.add_argument('--bindings', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--inputs', type=Path, help='Output of prepare_inputs.py, required for run')
    p.add_argument('--case')
    p.add_argument('--control', choices=['value', 'owner', 'replacement', 'trap', 'stale_response'])
    p.add_argument('--trace', action='store_true', help='Use passive trace host (ON only)')
    a = p.parse_args()
    check()
    for key in ['off_model', 'on_model', 'toolchain', 'cxx', 'bindings', 'out']:
        setattr(a, key, getattr(a, key).resolve())
    assert not a.out.is_relative_to(HERE.parents[2]), 'runtime products must be outside source'
    assert not a.bindings.is_relative_to(HERE.parents[2]), 'generated bindings must be outside source'
    assert a.off_model != a.on_model and (not a.trace or a.mode == 'on')
    model = a.off_model if a.mode == 'off' else a.on_model
    contract = read(HERE/'build-contract.json')
    identity = contract['historical_model_identity'][a.mode]
    assert sha(model/'BoardSocGsim.h') == identity['header_sha256'], 'matching historical model header required'
    assert sha(model/'BoardSocGsim.fir') == identity['fir_sha256'], 'matching historical model FIR required'
    suffix = 'on' if a.mode == 'on' else 'retained_a'
    mappings = [a.bindings/('binding_memory_'+suffix+'.json'), a.bindings/('binding_memory_core_'+suffix+'.json')]
    for mapping in mappings: verify(mapping, model)
    # Generated readers must be exact emit() output from the verified maps.
    from binding_memory_generate import emit as memory_emit, specification as memory_spec
    from binding_memory_core_generate import emit as core_emit, specification as core_spec
    for mapping, specification in zip(mappings, [memory_spec(), core_spec()]):
        fields = read(mapping)['fields']
        assert len(fields) == len(specification)
        for field, expected in zip(fields, specification):
            assert {key: field[key] for key in expected} == expected, 'incomplete or altered field specification'
            assert not field['required'] or field['status'] == 'PROVEN', 'required binding unproven'
    memory_header = a.bindings/('binding_memory_'+suffix+'.h')
    core_header = a.bindings/('binding_memory_core_'+suffix+'.h')
    assert memory_header.read_text() == memory_emit(read(mappings[0]))
    assert core_header.read_text() == core_emit(read(mappings[1]), memory_header.name)
    expected_generators = [('generator_sha256', HERE/'binding_memory_generate.py')]
    assert read(mappings[0])['generator_sha256'] == sha(expected_generators[0][1])
    assert read(mappings[1])['generator_sha256'] == sha(HERE/'binding_memory_core_generate.py')
    objects = [model/n for n in contract['model_object_names']]
    bound_files = [model/'BoardSocGsim.h', model/'BoardSocGsim.fir', *objects, a.toolchain, a.cxx, *mappings, memory_header, core_header]
    fingerprints = {str(path): sha(path) for path in bound_files}
    runtime = {'schema': 'held-alu-explicit-runtime-binding-v1', 'mode': a.mode, 'trace': a.trace,
               'fixture_manifest_sha256': sha(HERE/'manifest.json'), 'files': fingerprints,
               'model_scope': contract['scope'], 'no_new_model_compilation': True}
    a.out.mkdir(parents=True, exist_ok=True)
    label = a.mode + ('-trace' if a.trace else '')
    executable = a.out/('run-'+label)
    binding = a.out/('runtime-binding-'+label+'.json')
    if a.action == 'link':
        assert not executable.exists() and not binding.exists(), 'preserve previous host link'
        shared = HERE.parent/'young_load_seal/posted_join_observation'
        flags = contract['flags'] + ['-DB1_ENABLED='+str(int(a.mode == 'on'))]
        flags += ['-I'+str(d) for d in [model, a.bindings, HERE, shared, shared/'host', shared/'host/harness']]
        source = HERE/('directed_trace_host.cpp' if a.trace else 'directed_host.cpp')
        command = [a.cxx, *flags, source, *objects, '-o', executable]
        work = a.out
        log = a.out/('link-'+label+'.log')
    else:
        assert a.inputs and a.case
        assert read(binding) == {**runtime, 'executable_sha256': sha(executable)}, 'runtime binding changed'
        allowed = read(HERE/'schedule.json')['case_order'] + ['D1-bare-p0-x2-gated']
        assert a.case in allowed, 'only frozen bounded cases permitted'
        if a.control:
            cases = {'value': 'D1-bare-p0-x2-gated', 'owner': 'D1-bare-p0-x2-gated',
                     'replacement': 'D1-bare-p0', 'trap': 'D3head-bare-p0', 'stale_response': 'D2-bare-p0'}
            assert a.mode == 'on' and a.case == cases[a.control], 'undeclared control case'
            assert a.trace == (a.control in ['value', 'owner'])
        elif a.trace:
            assert a.case in ['D1-bare-p0', 'D6div-bare-p0', 'D1-bare-p0-x2-gated']
        guests = generated_guests()
        guest_name = 'corrected.bin' if a.case == 'D1-bare-p0-x2-gated' else 'original.bin'
        guest, inputs = a.inputs.resolve()/guest_name, a.inputs.resolve()/(a.case+'.txt')
        assert guest.read_bytes() == guests[guest_name]
        assert inputs.read_bytes() == generated_controls()[a.case]
        command = [executable, guest, inputs] + ([a.control] if a.control else [])
        label += '-'+a.case + ('-negative-'+a.control if a.control else '')
        work = a.out/label
        work.mkdir(exist_ok=False)
        log = a.out/(label+'.log')
    assert not log.exists(), 'preserve previous attempt log'
    argv = ['/bin/bash', '--noprofile', '--norc', '-c', 'source "$1"; shift; exec "$@"',
            'held-alu', str(a.toolchain), *map(str, command)]
    timeout = False
    with log.open('xb') as stream:
        child = subprocess.Popen(argv, cwd=work, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
              env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1', 'POSTED_JOIN_OBSERVATION_INJECT': ''})
        try: child.wait(timeout=120)
        except subprocess.TimeoutExpired:
            timeout = True
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
    text = log.read_text()
    clean = not re.search(r'ERROR: AddressSanitizer|runtime error:|UndefinedBehaviorSanitizer|LeakSanitizer', text)
    unchanged = all(sha(Path(name)) == digest for name, digest in fingerprints.items())
    receipt = {'argv': argv, 'exit': child.returncode, 'timeout': timeout, 'timeout_seconds': 120,
               'sanitizer_clean': bool(clean), 'bound_files_unchanged': unchanged, 'log_sha256': sha(log)}
    passed = child.returncode == 0 and not timeout and clean and unchanged
    if a.action == 'run':
        if a.control:
            diagnostic = next(r['diagnostic'] for r in read(HERE/'evidence/results.json')['records'] if r.get('control') == a.control)
            applied = 'B1_MUTATION_APPLIED name='+a.control in text
            passed = child.returncode == 1 and applied and diagnostic in text and not timeout and clean and unchanged
            receipt['status'] = 'PASS_EXPECTED_REJECTION' if passed else 'NOT_REACHED' if not applied else 'FAIL'
        else:
            parsed = re.findall(r'^B1_DIRECTED_CASE (\{.*\})$', text, re.M)
            passed = passed and len(parsed) == 1 and 'B1_DIRECTED_FUNCTIONAL_PASS' in text
            receipt['status'] = 'PASS_FUNCTIONAL' if passed else 'FAIL'
            if parsed: receipt['case'] = json.loads(parsed[-1])
    else: receipt['status'] = 'PASS_HOST_LINK' if passed else 'FAIL'
    save(log.with_suffix('.json'), receipt)
    assert passed, 'bounded host operation failed; preserved log and receipt'
    if a.action == 'link': save(binding, {**runtime, 'executable_sha256': sha(executable)})
    print(json.dumps(receipt, indent=2))

if __name__ == '__main__': main()
