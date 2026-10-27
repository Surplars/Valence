#!/usr/bin/env python3
"""Bound corrected-epoch scalar buffered-proof, rank-selector and PRF-phase checks."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode = True
import run as common
import gsim_initialization_epoch as epoch

SCHEMA = 'valence-buffered-third-rank-components-v1'
PASS = 'PASS_BUFFERED_THIRD_RANK_COMPONENTS'
TOOL_SHA = '128c4853a6584cd1181cff863fc727a824fe132ad3c60f3ba323d46ea3b135fa'
CONTRACT_SHA = 'c34e19593d86e31b9094260171bc56409cd278490def3928037515bb5d71fdfb'
NEGATIVES = {
    'owner': ('sampled_high_tag', 'independent full owner key mismatch'),
    'permission': ('sampled_allowed', 'independent byte permission mismatch'),
    'credit': ('borrow_same_edge_issue', 'independent raw pre-edge R credit mismatch'),
    'row': ('old_destination_cancel', 'independent raw validity mismatch'),
    'bypass': ('unregistered_publication', 'independent current-key publication mismatch'),
    'va': ('saved_VA_self_comparison', 'independent current-key publication mismatch'),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    paths = list((common.ROOT / 'src/main/scala').rglob('*.scala'))
    paths += [common.ROOT / p for p in (
        'src/test/scala/ooo/BufferedLoadProofGsim.scala',
        'src/test/scala/ooo/ThirdMemoryPreparationRankGsim.scala',
        'simulator/gsim/harness/buffered_load_proof.cpp',
        'simulator/gsim/harness/third_memory_preparation_rank.cpp',
        'simulator/gsim/buffered_third_rank_components.py',
        'simulator/gsim/gsim_initialization_epoch.py', 'simulator/gsim/run.py',
        'fpga/common/scala_compile_receipt.py', 'simulator/gsim/config/toolchain.json', 'build.mill')]
    return {str(p.relative_to(common.ROOT)): sha(p) for p in sorted(paths)}


def contract(path):
    path = path.resolve()
    record = json.loads((path / 'manifest.json').read_text())
    if record.get('status') != 'PASS_FINITE_CONTRACT_MODEL_R3_CURRENT_AUTHORITY' or sha(path / 'model.py') != CONTRACT_SHA:
        raise RuntimeError('reviewed r3 current-authority contract required')
    artifacts = {str((path / name).relative_to(common.ROOT)): value for name, value in record['artifacts'].items()}
    for name, value in artifacts.items():
        if sha(common.ROOT / name) != value:
            raise RuntimeError('contract artifact drift: ' + name)
    return {'path': str((path / 'manifest.json').relative_to(common.ROOT)),
        'sha256': sha(path / 'manifest.json'), 'model_path': str((path / 'model.py').relative_to(common.ROOT)),
        'model_sha256': CONTRACT_SHA, 'artifacts': artifacts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-run', action='store_true')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--compile-receipt', type=Path)
    parser.add_argument('--tool-receipt', type=Path)
    parser.add_argument('--contract-directory', type=Path,
        default=common.ROOT / 'build/staged-proof-contract-model-20261025-r3')
    a = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.tag):
        parser.error('fresh filesystem-safe tag required')
    before = inputs()
    model_contract = contract(a.contract_directory)
    if not a.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'source_inputs': len(before), 'model_contract': model_contract}))
        return
    if not a.compile_receipt or not a.tool_receipt or sha(a.tool_receipt) != TOOL_SHA:
        parser.error('bound compile and exact corrected tool receipts required')
    binding = epoch.tool_binding(a.tool_receipt)
    spec = importlib.util.spec_from_file_location('scala_gate', common.ROOT / 'fpga/common/scala_compile_receipt.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    compiled = gate.verify_receipt(a.compile_receipt, common.ROOT)
    cp = os.pathsep.join(compiled['runClasspathEntries'])
    out = common.BUILD / a.tag
    out.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': SCHEMA, 'status': 'RUNNING', 'started_utc': datetime.now(timezone.utc).isoformat(),
        'inputs': before, 'compile_receipt_sha256': sha(a.compile_receipt), 'tool_epoch': binding,
        'model_contract': model_contract, 'tests': {}, 'negatives': {},
        'limits': ['Standalone module/rank/PRF phase checks, not CPU throughput, ISA or source-lifetime integration proof.',
            'Negative controls mutate sampled outputs/protocol observations; no RTL mutant rebuilds are claimed.',
            'Ideal two/three-rank supply measurements are fixture schedules, not predicted real CPU speed.',
            'No physical timing, routed implementation or board qualification.']}
    try:
        cxx, version = common.compiler()
        cxx = shutil.which(cxx)
        if not cxx:
            raise RuntimeError('selected C++ compiler unavailable')
        receipt['compiler'] = {'path': cxx, 'sha256': sha(cxx), 'version': version}
        env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for label, main_class, top, harness, marker in (
            ('module', 'ooo.BufferedLoadProofGsimMain', 'BufferedLoadProofGsim', 'buffered_load_proof.cpp', 'BUFFERED_PROOF_PASS '),
            ('selector', 'ooo.ThirdMemoryPreparationRankGsimMain', 'ThirdMemoryPreparationRankGsim', 'third_memory_preparation_rank.cpp', 'THIRD_RANK_PASS exhaustive_masks_heads=1048576 ')):
            model = out / label
            model.mkdir()
            common.run(['java', '-cp', cp, main_class, model], log=model / 'elaborate.log', timeout=180)
            common.run([binding['gsim']['path'], '--threads=1', '--dir=' + str(model), model / (top + '.fir')],
                log=model / 'generate.log', timeout=600)
            flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(model)]
            host = common.HERE / 'harness' / harness
            common.run([cxx, *flags, '-fsyntax-only', host], log=model / 'real-header-syntax.log', timeout=180)
            receipt.setdefault('real_header_syntax', {})[label] = {'status': 'PASS', 'header_sha256': sha(model / (top + '.h')),
                'harness_sha256': sha(host), 'log_sha256': sha(model / 'real-header-syntax.log')}
            objects = []
            for source in sorted(model.glob(top + '[0-9]*.cpp')):
                obj = source.with_suffix('.o')
                common.run([cxx, *flags, '-c', source, '-o', obj], log=obj.with_suffix('.compile.log'), timeout=600)
                objects.append(obj)
            if not objects:
                raise RuntimeError('generated model objects absent')
            hobj = model / 'host.o'
            common.run([cxx, *flags, '-c', host, '-o', hobj], log=model / 'host-compile.log', timeout=180)
            common.run([cxx, *flags, *objects, hobj, '-ldl', '-o', model / 'run'], log=model / 'link.log', timeout=180)
            common.run([model / 'run'], env=env, log=model / 'test.log', timeout=180)
            text = (model / 'test.log').read_text()
            if marker not in text:
                raise RuntimeError('required independent positive marker absent: ' + label)
            receipt['tests'][label] = {'status': 'PASS', 'log': str((model / 'test.log').relative_to(out)),
                'sha256': sha(model / 'test.log'), 'output': text}
            if label == 'module':
                phase_marker = 'BUFFERED_PROOF_PHASE_PASS cases=7 phase=post_step_pre_edge_observe_then_apply_events'
                if phase_marker not in text or text.count('BUFFERED_PROOF_IDEAL ') != 4:
                    raise RuntimeError('PRF phase or ideal rank comparison missing')
                receipt['tests']['phase'] = {'status': 'PASS', 'marker': phase_marker, 'log_sha256': sha(model / 'test.log')}
                cases = [(kind, '--inject-' + kind, 'BUFFERED_PROOF_INJECTION_REACHED kind=' + kind + ' mutation=' + mutation, rejection)
                    for kind, (mutation, rejection) in NEGATIVES.items()]
            else:
                cases = [('rank', '--inject-rank', 'THIRD_RANK_INJECTION_REACHED sampled_third_owner', 'independent circular third owner mismatch')]
            for kind, flag, reached, rejected in cases:
                result = subprocess.run([str(model / 'run'), flag], capture_output=True, text=True, env=env, timeout=180)
                text = result.stdout + result.stderr
                log = model / ('negative-' + kind + '.log')
                log.write_text(text)
                if result.returncode != 1 or text.count(reached) != 1 or rejected not in text or marker in text or \
                        any(bad in text for bad in ('AddressSanitizer', 'runtime error:', 'Assertion failed:')):
                    raise RuntimeError('negative failed exact independent-oracle rejection: ' + kind)
                receipt['negatives'][kind] = {'status': 'EXPECTED_REJECTION', 'exit_code': result.returncode,
                    'marker': reached, 'rejection': rejected, 'log': str(log.relative_to(out)), 'sha256': sha(log)}
        gate.verify_receipt(a.compile_receipt, common.ROOT)
        if epoch.tool_binding(a.tool_receipt) != binding or contract(a.contract_directory) != model_contract:
            raise RuntimeError('tool/contract evidence drift')
        receipt['status'] = PASS
    except Exception as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        receipt['inputs_unchanged'] = before == inputs()
        if not receipt['inputs_unchanged']:
            receipt['status'] = 'FAIL_INPUT_DRIFT'
        receipt['artifacts'] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*'))
            if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if receipt['status'] != PASS:
        raise RuntimeError(receipt['status'])
    print(json.dumps({'status': receipt['status'], 'receipt': str(out / 'receipt.json'), 'sha256': sha(out / 'receipt.json')}))

if __name__ == '__main__':
    main()
