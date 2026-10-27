#!/usr/bin/env python3
"""Fresh real-DTA comparison: legal equality plus explicit raw-invalid rejection."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys

import run as common
import registered_raw_certified_flow as prior
import guarded_natural_dta_host as hostgen

TOP = 'RegisteredRawCertifiedFlowGsim'
MAIN = 'ooo.GuardedNaturalDtaGsimMain'
PREFIX = 'REGISTERED_RAW_CERTIFIED_FLOW'
ROOT = common.ROOT
HERE = common.HERE

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(ok, text):
    if not ok: raise ValueError(text)

def compare(a, b):
    require(a['metrics'] == b['metrics'], 'legal continuous supply/backpressure metrics changed')
    require(a['histograms'] == b['histograms'], 'legal physical latency histograms changed')
    require(a['cases'].keys() == b['cases'].keys(), 'case sets differ')
    changed = {'pte_rights_canonical_shape_remap', 'guarded_identity_spill'} | {
        'guarded_raw_route_' + str(i) for i in range(6)}
    for name in a['cases']:
        if name not in changed:
            require(a['cases'][name] == b['cases'][name], 'legal case differs: ' + name)
        else:
            x, y = a['cases'][name], b['cases'][name]
            require(x['accepted'] == y['accepted'] == x['returned'] == y['returned'], 'changed case lost an owner')
            count = 1 if name == 'pte_rights_canonical_shape_remap' else (24 if name == 'guarded_identity_spill' else 6)
            require(y['faults'] - x['faults'] == count and x['physical'] - y['physical'] == count,
                    'new raw-invalid contract delta differs: ' + name)
            require(x['certificates'] == y['certificates'], 'raw-invalid acquired canonical authority')
    require(len(a['cases']) == 23, 'expected original15 plus8 strict boundary cases')
    return {'equal_legal_cases': sorted(set(a['cases']) - changed),
            'new_standalone_rejection_cases': sorted(changed),
            'legal_metrics_and_histograms_exact': True}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--gsim', type=Path)
    ap.add_argument('--compile-receipt', type=Path)
    ap.add_argument('--tool-receipt', type=Path)
    ap.add_argument('--build-run', action='store_true')
    args = ap.parse_args()
    require(re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'unsafe tag')
    derived = hostgen.derive()
    if not args.build_run:
        print('PASS_GUARDED_NATURAL_DTA_SOURCE_PREFLIGHT'); return
    require(args.gsim and args.compile_receipt and args.tool_receipt,
            'qualified GSIM epoch and bound compile receipt required')
    import gsim_initialization_epoch as epoch
    tool_binding = epoch.tool_binding(args.tool_receipt)
    require(args.gsim.resolve() == Path(tool_binding['gsim']['path']).resolve(),
            'GSIM executable differs from qualified tool epoch')
    spec = importlib.util.spec_from_file_location('compile_gate', ROOT/'fpga/common/scala_compile_receipt.py')
    gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
    gate.verify_receipt(args.compile_receipt, ROOT)
    out = common.BUILD/args.tag; out.mkdir(parents=True, exist_ok=False)
    host = out/'guarded_natural_dta_host.cpp'; host.write_text(derived)
    gsim = args.gsim.resolve(strict=True); cxx, compiler = common.compiler()
    compiler_path = Path(shutil.which(str(cxx)) or cxx).resolve()
    files = sorted((ROOT/'src/main/scala').rglob('*.scala')) + sorted((ROOT/'src/test/scala').rglob('*.scala')) + [
        Path(__file__), Path(epoch.__file__), HERE/'guarded_natural_dta_host.py', HERE/'registered_raw_certified_flow.py',
        HERE/'harness/registered_raw_certified_flow.cpp', HERE/'harness/guarded_natural_dta_cases.inc',
        HERE/'harness/virtual_load_test_memory.h', HERE/'m2_data_translation/oracle.h', HERE/'run.py']
    before = {str(p.relative_to(ROOT)): sha(p) for p in files}
    r = {'schema': 'valence-guarded-natural-dta-v1', 'status': 'RUNNING', 'sources': before,
         'tool_epoch': tool_binding, 'tool_receipt': str(args.tool_receipt.resolve()),
         'tool_receipt_sha256': sha(args.tool_receipt),
         'gsim_sha256': sha(gsim), 'compiler': compiler, 'compiler_sha256': sha(compiler_path),
         'compile_receipt_sha256': sha(args.compile_receipt), 'models': {}, 'negative_controls': [],
         'derived_host_sha256': sha(host), 'sealed_host_sha256': hostgen.BASE_SHA,
         'scope': 'Real DTA/DTLB16; legal-domain equality plus deliberately new raw-invalid access error. No CPU/ISA/PPA claim.'}
    def save(): (out/'receipt.json').write_text(json.dumps(r, indent=2)+'\n')
    save()
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
    try:
        for label, enabled in [('control', 0), ('guarded', 1)]:
            target = out/label; target.mkdir()
            result = {'status': 'RUNNING'}; r['models'][label] = result; save()
            common.run(['mill', '-i', 'IonSoC.test.runMain', MAIN, target, label], log=target/'elaborate.log')
            fir = target/(TOP+'.fir'); result['fir_sha256'] = sha(fir)
            common.run([gsim, '--threads=1', f'--dir={target}', fir], log=target/'generate.log')
            flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                     '-I'+str(target), '-I'+str(HERE/'harness'), '-DGUARDED_NATURAL_DTA='+str(enabled)]
            common.run([cxx, *flags, '-fsyntax-only', host], log=target/'header-syntax.log')
            generated = sorted(target.glob(TOP+'[0-9]*.cpp')); require(generated, 'no model source')
            objects = []
            for source in [*generated, host]:
                obj = target/(source.stem+'.o')
                common.run([cxx, *flags, '-c', source, '-o', obj], log=target/(source.stem+'-compile.log'))
                objects.append(obj)
            binary = target/'run'; common.run([cxx, *flags, *objects, '-ldl', '-o', binary], log=target/'link.log')
            common.run([binary], env=env, timeout=120, log=target/'test.log')
            log = (target/'test.log').read_text()
            require(log.count(PREFIX+'_PASS enabled=0') == 1, 'missing original contract final pass')
            result.update(status='PASS', metrics=prior.rows(log, PREFIX+'_METRIC', 'scenario'),
                cases=prior.rows(log, PREFIX+'_CASE', 'name'), histograms=prior.histograms(log),
                binary_sha256=sha(binary), header_sha256=sha(target/(TOP+'.h')),
                generated={p.name: sha(p) for p in generated}, objects={p.name: sha(p) for p in objects},
                log_sha256=sha(target/'test.log'))
            save()
            for flag, marker, diagnostics in [
                ('--inject-pa', 'INJECT '+PREFIX+' physical PA', ['independent physical PA/order mismatch']),
                ('--inject-data', 'INJECT '+PREFIX+' response data', ['independent ordered response data mismatch']),
                ('--inject-fault', 'INJECT '+PREFIX+' response fault', ['independent ordered fault classification mismatch']),
                ('--inject-canonical', 'INJECT '+PREFIX+' canonical attribution', ['independent canonical certificate attribution mismatch']),
                ('--inject-hint', 'INJECT GUARDED_NATURAL_DTA checked hint', ['independent captured next-line permission mismatch']),
            ]:
                r['negative_controls'].append({'model': label, **prior.poison(binary, target, flag, marker, diagnostics)})
                save()
            r['negative_controls'].append({'model': label, **prior.poison(binary, target, '--force-undrained-flush',
                'INJECT '+PREFIX+' undrained flush', ['VM/PMP/SFENCE context changes must drain accepted prechecked loads before changing authorization',
                'VM/PMP/SFENCE changes must drain accepted canonical stores and overlapping adapter work'], hardware=True)})
            save()
        r['comparison'] = compare(r['models']['control'], r['models']['guarded'])
        require(before == {str(p.relative_to(ROOT)): sha(p) for p in files}, 'source drift')
        require(host.read_text() == hostgen.derive(), 'derived independent driver drift')
        require(sha(gsim) == r['gsim_sha256'] and sha(compiler_path) == r['compiler_sha256'], 'tool drift')
        require(sha(args.tool_receipt) == r['tool_receipt_sha256'] and
                epoch.tool_binding(args.tool_receipt) == tool_binding, 'qualified tool epoch drift')
        gate.verify_receipt(args.compile_receipt, ROOT)
        r['status'] = 'PASS_GUARDED_NATURAL_DTA'; save(); print(r['status'])
    except Exception as e:
        r.update(status='FAIL', error=str(e)); save(); raise

if __name__ == '__main__': main()
