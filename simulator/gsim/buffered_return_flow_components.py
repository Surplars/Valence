#!/usr/bin/env python3
"""One frozen compile receipt; actual local queue and consumer chain OFF/ON GSIM checks.

No Mill compilation, tool download or CPU build. The consumer fixture excludes DTA
permission and canonical forwarding; full CPU integration needs its own gates.
"""
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
from translated_response_flow import NEGATIVES as LOCAL_NEGATIVES

SCHEMA = 'valence-buffered-return-flow-components-v1'
PASS = 'PASS_BUFFERED_RETURN_FLOW_COMPONENTS'
TOOL_SHA = '128c4853a6584cd1181cff863fc727a824fe132ad3c60f3ba323d46ea3b135fa'
MODEL_SHA = 'd73c7c4ec39434260ae5550de534d97b4cbb9e1541edb2c790b651748bebd430'
ADDENDUM_SHA = '6463484a5264dcede858bea1e299ca8686bc59f9f555f34d1b9aa972fd9c3730'
CHAIN_NEGATIVES = {'tag': 'chain full64 completion owner', 'data': 'chain independent data mismatch',
                  'cause': 'chain independent cause mismatch', 'tval': 'chain independent tval mismatch'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def need(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def inputs():
    files = list((common.ROOT / 'src/main/scala').rglob('*.scala'))
    files += [common.ROOT / p for p in (
        'src/test/scala/ooo/TranslatedResponseFlowGsim.scala',
        'src/test/scala/ooo/BufferedReturnChainGsim.scala',
        'simulator/gsim/harness/translated_response_flow.cpp',
        'simulator/gsim/harness/buffered_return_chain.cpp',
        'simulator/gsim/harness/gsim_model_storage.h',
        'simulator/gsim/buffered_return_flow_components.py',
        'simulator/gsim/translated_response_flow.py',
        'simulator/gsim/gsim_initialization_epoch.py', 'simulator/gsim/run.py',
        'fpga/common/scala_compile_receipt.py', 'simulator/gsim/config/toolchain.json', 'build.mill')]
    return {str(p.relative_to(common.ROOT)): sha(p) for p in sorted(files)}


def contract(directory):
    directory = directory.resolve()
    path = directory / 'receipt.json'
    need(sha(path) == MODEL_SHA, 'reviewed independent model receipt required')
    need(sha(directory / 'REVIEW-ADDENDUM.md') == ADDENDUM_SHA, 'model independence limits addendum required')
    record = json.loads(path.read_text())
    need(record['status'] == 'PASS_ABSTRACT_MODEL_ONLY', 'abstract model qualification changed')
    artifacts = {str(path): sha(path), str(directory / 'REVIEW-ADDENDUM.md'): ADDENDUM_SHA}
    for name, expected in record['files'].items():
        need(sha(directory / name) == expected, 'model artifact drift: ' + name)
        artifacts[str(directory / name)] = expected
    return {'path': str(path), 'sha256': sha(path), 'artifacts': artifacts,
            'limits': 'independent queue/token model; shared cancellation policy is not implementation proof'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-run', action='store_true')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--compile-receipt', type=Path)
    parser.add_argument('--tool-receipt', type=Path)
    parser.add_argument('--contract-directory', type=Path,
                        default=common.ROOT / 'build/return-flow-contract-model-20261025-r1')
    args = parser.parse_args()
    need(re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'fresh filesystem-safe tag required')
    before, model_contract = inputs(), contract(args.contract_directory)
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'inputs': before, 'model_contract': model_contract}))
        return
    need(args.compile_receipt and args.tool_receipt and sha(args.tool_receipt) == TOOL_SHA,
         'current compile and exact corrected epoch receipts required')
    binding = epoch.tool_binding(args.tool_receipt)
    spec = importlib.util.spec_from_file_location('scala_gate', common.ROOT / 'fpga/common/scala_compile_receipt.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    compiled = gate.verify_receipt(args.compile_receipt, common.ROOT)
    cp = os.pathsep.join(compiled['runClasspathEntries'])
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': SCHEMA, 'status': 'RUNNING', 'inputs': before,
               'compile_receipt_sha256': sha(args.compile_receipt), 'tool_epoch': binding,
               'model_contract': model_contract, 'tests': {}, 'negatives': {},
               'started_utc': datetime.now(timezone.utc).isoformat(),
               'limits': ['Local queue and real consumer-chain components, not full CPU/DTA permission qualification.',
                          'Chain uses legal ordinary physical access; canonical forwarding is not exercised.',
                          'Negatives damage sampled completion/queue observations, not rebuilt RTL mutants.']}
    try:
        cxx, version = common.compiler()
        cxx = shutil.which(cxx)
        need(cxx is not None, 'pinned compiler unavailable')
        receipt['compiler'] = {'path': cxx, 'sha256': sha(cxx), 'version': version}
        env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for mode in (0, 1):
            for kind, top, main_class, harness, marker in (
                ('local', 'TranslatedResponseFlowGsim', 'ooo.TranslatedResponseFlowGsimMain',
                 'translated_response_flow.cpp', 'TRANSLATED_RESPONSE_FLOW_PASS '),
                ('chain', 'BufferedReturnChainGsim', 'ooo.BufferedReturnChainGsimMain',
                 'buffered_return_chain.cpp', 'BUFFERED_RETURN_CHAIN_PASS ')):
                need(before == inputs(), 'source changed after component freeze')
                label = kind + ('_on' if mode else '_off')
                model = out / label
                model.mkdir()
                common.run([binding['java']['path'], '-cp', cp, main_class, model, str(mode)],
                           log=model / 'elaborate.log', timeout=180)
                common.run([binding['gsim']['path'], '--threads=1', '--dir=' + str(model), model / (top + '.fir')],
                           log=model / 'generate.log', timeout=600)
                shutil.copyfile(common.HERE / 'harness/gsim_model_storage.h', model / 'gsim_model_storage.h')
                flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                         '-fno-sanitize-recover=all', '-I' + str(model)]
                if kind == 'local':
                    flags += ['-DRESPONSE_FLOW_ENABLED=' + str(mode)]
                host = common.HERE / 'harness' / harness
                common.run([cxx, *flags, '-fsyntax-only', host], log=model / 'real-header-syntax.log', timeout=180)
                objects = []
                for source in sorted(model.glob(top + '[0-9]*.cpp')):
                    obj = source.with_suffix('.o')
                    common.run([cxx, *flags, '-c', source, '-o', obj], log=obj.with_suffix('.compile.log'), timeout=600)
                    objects.append(obj)
                need(objects, 'generated DUT object set empty')
                hobj = model / 'host.o'
                common.run([cxx, *flags, '-c', host, '-o', hobj], log=model / 'host-compile.log', timeout=180)
                common.run([cxx, *flags, *objects, hobj, '-ldl', '-o', model / 'run'], log=model / 'link.log', timeout=180)
                common.run([model / 'run'], env=env, log=model / 'test.log', timeout=120)
                output = (model / 'test.log').read_text()
                need(marker in output, 'positive independent marker missing: ' + label)
                if kind == 'chain':
                    need(output.count('BUFFERED_RETURN_CHAIN_CASE ') == 7, 'all actual chain cases required')
                receipt['tests'][label] = {'status': 'PASS', 'log': str((model / 'test.log').relative_to(out)),
                                          'sha256': sha(model / 'test.log'), 'output': output}
                negatives = LOCAL_NEGATIVES if kind == 'local' else CHAIN_NEGATIVES
                for fault, rejection in negatives.items():
                    flag = '--inject-' + fault if kind == 'local' else fault
                    result = subprocess.run([str(model / 'run'), flag], capture_output=True, text=True, env=env, timeout=120)
                    output = result.stdout + result.stderr
                    log = model / ('negative-' + fault + '.log')
                    log.write_text(output)
                    need(result.returncode == 1 and rejection in output and marker not in output and
                         not any(s in output for s in ('AddressSanitizer', 'runtime error:', 'Assertion failed:')),
                         'negative exact failure mismatch: ' + label + '/' + fault)
                    if kind == 'chain':
                        need(output.count('CHAIN_INJECTION_REACHED kind=' + fault) == 1, 'chain negative not reached')
                    receipt['negatives'][label + '_' + fault] = {'status': 'EXPECTED_REJECTION',
                        'exit_code': result.returncode, 'rejection': rejection,
                        'log': str(log.relative_to(out)), 'sha256': sha(log)}
        gate.verify_receipt(args.compile_receipt, common.ROOT)
        need(epoch.tool_binding(args.tool_receipt) == binding and contract(args.contract_directory) == model_contract,
             'tool/model binding changed')
        receipt['status'] = PASS
    except Exception as error:
        receipt['status'], receipt['error'] = 'FAIL', str(error)
        raise
    finally:
        receipt['inputs_unchanged'] = before == inputs()
        if not receipt['inputs_unchanged']:
            receipt['status'] = 'FAIL_INPUT_DRIFT'
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        receipt['artifacts'] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*'))
                                if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    need(receipt['status'] == PASS, receipt['status'])
    print(json.dumps({'status': PASS, 'receipt': str(out / 'receipt.json'), 'sha256': sha(out / 'receipt.json')}))


if __name__ == '__main__':
    main()
