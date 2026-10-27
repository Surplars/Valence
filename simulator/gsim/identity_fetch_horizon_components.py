#!/usr/bin/env python3
"""Identity fetch component gates. Default is source-only preflight.
--emit uses an already frozen unified Scala compile receipt, never invokes Mill.
--build-run consumes that immutable emission; four component models, no CPU DUT.
Failed receipts/artifacts are retained and cannot be overwritten by another attempt.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
import run as common
import gsim_initialization_epoch as epoch

KINDS = {
    'raw': ('IdentityFetchHorizonGsim', 'identity_fetch_horizon.cpp'),
    'supply': ('IdentityFetchHorizonSupplyGsim', 'identity_fetch_horizon_supply.cpp'),
}
LIMITS = [
    'Supply integration uses explicit synthetic 128KiB RAM and 128KiB ROM; not Common fabric/MMIO endpoints',
    'Raw scheduler oracle checks frontend only; supply byte oracle checks integrated transport separately',
    'Not CPU trap selection, retirement, PBMT/canonical CPU qualification, FPGA timing or performance',
    'Negative controls mutate observations, not production RTL',
]

def need(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read(p):
    return json.loads(Path(p).read_text())

def save(p, obj):
    Path(p).write_text(json.dumps(obj, indent=2) + '\n')

def scala_gate():
    spec = importlib.util.spec_from_file_location('identity_horizon_scala_gate', common.ROOT/'fpga/common/scala_compile_receipt.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate

def inputs():
    files = scala_gate().compile_source_paths(common.ROOT)
    files += list(common.HERE.rglob('*.py')) + list((common.HERE/'harness').rglob('*'))
    files += list((common.HERE/'m2_data_translation').rglob('*'))
    files += list((common.HERE/'a1_fetch_supply').rglob('*'))
    files += [common.ROOT/'fpga/common/scala_compile_receipt.py']
    return {str(p.relative_to(common.ROOT)): sha(p) for p in sorted(set(files)) if p.is_file()}

def preflight():
    for top, host in KINDS.values():
        text = (common.ROOT/'src/test/scala/ooo'/f'{top}.scala').read_text()
        need('fetchThirdPacketLookahead = enabled' in text, 'fixture missing real candidate flag ' + top)
        need('transactionSlots = 2' in text or 'private val transactionSlots = 2' in text,
             'fixture missing unchanged two-owner declaration ' + top)
        need((common.HERE/'harness'/host).is_file(), 'missing host ' + host)
    supply = (common.ROOT/'src/test/scala/ooo/IdentityFetchHorizonSupplyGsim.scala').read_text()
    need('testRamBytes = BigInt(128 * 1024)' in supply and
         'SideEffectFreeFetchRange(config.ramBase, testRamBytes)' in supply and
         'ramBytes = testRamBytes' in supply, 'supply RAM proof boundary drift')
    return inputs()

def artifacts(out, excluded):
    return {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*'))
            if p.is_file() and p.name not in excluded}

def emit(a, tools, before):
    compiled = scala_gate().verify_receipt(a.compile_receipt, common.ROOT)
    out = common.BUILD/a.tag
    out.mkdir(parents=True, exist_ok=False)
    r = {'schema': 'identity-fetch-horizon-component-emission-v1', 'status': 'RUNNING',
         'inputs': before, 'tool_epoch': tools, 'compile_receipt': str(a.compile_receipt.resolve()),
         'compile_receipt_sha256': sha(a.compile_receipt), 'new_DUT_builds': 0, 'limits': LIMITS}
    try:
        for kind, (top, _) in KINDS.items():
            for enabled in (0, 1):
                target = out/f'{kind}-{enabled}'
                target.mkdir()
                common.run([tools['java']['path'], '-cp', os.pathsep.join(compiled['runClasspathEntries']),
                            'ooo.'+top+'Main', target, str(bool(enabled)).lower()],
                           log=target/'elaborate.log', timeout=300)
                need((target/(top+'.fir')).is_file(), 'missing emitted component')
        scala_gate().verify_receipt(a.compile_receipt, common.ROOT)
        r['status'] = 'PASS_IDENTITY_FETCH_HORIZON_COMPONENT_EMISSION'
    except BaseException as error:
        r.update(status='FAIL', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        r['inputs_unchanged'] = inputs() == before
        if not r['inputs_unchanged']:
            r['status'] = 'FAIL_SOURCE_DRIFT'
        r['artifacts'] = artifacts(out, {'emit-receipt.json'})
        save(out/'emit-receipt.json', r)
    print(r['status'])

def parse_supply(log):
    rows = {}
    for line in log.splitlines():
        if not line.startswith('IDENTITY_FETCH_SUPPLY scenario='):
            continue
        values = dict(item.split('=', 1) for item in line.split()[1:])
        name = values.pop('scenario')
        need(name not in rows, 'duplicate scenario')
        rows[name] = {key: int(value) for key, value in values.items()}
        row = rows[name]
        need(sum(row[f'consumed{i}'] for i in range(3)) == row['work_cycles'], 'cycle partition')
        need(row['consumed1'] + 2*row['consumed2'] == row['verified'], 'work partition')
        need(row['vmax_inflight'] <= 2, 'more than two accepted owners')
    need(len(rows) == 11 and 'PASS IDENTITY_FETCH_SUPPLY' in log, 'missing supply completion')
    return rows

def build_run(a, tools, before):
    out = common.BUILD/a.tag
    ep = out/'emit-receipt.json'
    e = read(ep)
    need(e['status'] == 'PASS_IDENTITY_FETCH_HORIZON_COMPONENT_EMISSION' and e['inputs_unchanged'] and
         e['inputs'] == before and e['tool_epoch'] == tools, 'frozen component emission required')
    need(sha(a.compile_receipt) == e['compile_receipt_sha256'], 'different unified compile receipt')
    scala_gate().verify_receipt(a.compile_receipt, common.ROOT)
    need(all(sha(out/p) == v for p, v in e['artifacts'].items()), 'emission artifact drift')
    need(not (out/'receipt.json').exists(), 'fresh build attempt only; preserve failures')
    r = {'schema': 'identity-fetch-horizon-components-v1', 'status': 'RUNNING', 'inputs': before,
         'tool_epoch': tools, 'compile_receipt_sha256': sha(a.compile_receipt),
         'emit_receipt_sha256': sha(ep), 'tests': {}, 'negative_controls': [],
         'new_DUT_builds': 0, 'limits': LIMITS}
    def seal():
        save(out/'receipt.json', r)
    seal()
    try:
        for kind, (top, host_name) in KINDS.items():
            for enabled in (0, 1):
                label = f'{kind}-{enabled}'
                target = out/label
                need(not (target/'run').exists(), 'component binary already exists')
                common.run([tools['gsim']['path'], '--threads=1', '--dir='+str(target), target/(top+'.fir')],
                           log=target/'generate.log', timeout=600)
                host = common.HERE/'harness'/host_name
                flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                         '-I'+str(target), '-DIDENTITY_HORIZON_ENABLED='+str(enabled)]
                cxx = tools['compiler']['command']
                sources = sorted(target.glob(top+'[0-9]*.cpp'))
                need(sources, 'no actual GSIM translation units')
                common.run([cxx, *flags, '-fsyntax-only', host], log=target/'syntax.log', timeout=180)
                objects = []
                for source in [*sources, host]:
                    obj = target/(source.stem+'.o')
                    common.run([cxx, *flags, '-c', source, '-o', obj], log=target/(source.stem+'-compile.log'), timeout=600)
                    objects.append(obj)
                binary = target/'run'
                common.run([cxx, *flags, *objects, '-ldl', '-o', binary], log=target/'link.log', timeout=600)
                r['new_DUT_builds'] += 1
                seal()
                env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
                common.run([binary], env=env, log=target/'test.log', timeout=180)
                log = (target/'test.log').read_text()
                need(('PASS_IDENTITY_HORIZON ' if kind == 'raw' else 'PASS IDENTITY_FETCH_SUPPLY') in log,
                     'component missing final completion')
                if kind == 'supply':
                    r['tests'][label] = {'status': 'PASS', 'scenarios': parse_supply(log)}
                    negatives = [('--inject-pc', 'consumed PC duplicated, skipped, or from old path'),
                                 ('--inject-data', 'instruction differs from independent memory bytes'),
                                 ('--inject-tval', 'fault tval is not first failing required parcel'),
                                 ('--inject-source', 'D without source owner')]
                else:
                    r['tests'][label] = {'status': 'PASS', 'summary': log.strip()}
                    negatives = [('address', 'old-state address/mask'), ('held', 'old-state address/mask'),
                                 ('data', 'mixed-width instruction bytes'), ('fault', 'precise selected word fault')]
                    if enabled:
                        negatives += [('third', 'offer-valid')]
                for option, diagnostic in negatives:
                    result = subprocess.run([str(binary), option], env=env, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, timeout=180)
                    path = target/('negative-'+option.lstrip('-')+'.log')
                    path.write_text(result.stdout)
                    need(result.returncode == 1 and diagnostic in result.stdout and
                         not any(x in result.stdout for x in ('AddressSanitizer', 'runtime error:')),
                         'negative missed intended witness '+label+' '+option)
                    r['negative_controls'].append({'model': label, 'option': option, 'diagnostic': diagnostic,
                                                   'log_sha256': sha(path)})
                seal()
        off, on = r['tests']['supply-0']['scenarios'], r['tests']['supply-1']['scenarios']
        need(set(off) == set(on), 'supply scenario set differs')
        comparisons = {}
        for name in off:
            for key in ('verified', 'faults', 'instruction_hash'):
                need(off[name][key] == on[name][key], 'architectural byte-stream mismatch '+name+' '+key)
            excluded = name.startswith('rom') or name.startswith('sv39')
            if excluded:
                need(off[name] == on[name], 'ROM/VM must retain exact two-horizon traces and timings '+name)
            comparisons[name] = {'exact_excluded_horizon': excluded,
                                 'before_cycles': off[name]['work_cycles'], 'after_cycles': on[name]['work_cycles'],
                                 'same_external_traffic': all(off[name][k] == on[name][k]
                                                            for k in ('gets', 'dbeats', 'get_extent_hash'))}
        r['comparisons'] = comparisons
        need(epoch.tool_binding(a.tool_receipt) == tools, 'tool epoch drift')
        scala_gate().verify_receipt(a.compile_receipt, common.ROOT)
        r['status'] = 'PASS_IDENTITY_FETCH_HORIZON_COMPONENTS'
    except BaseException as error:
        r.update(status='FAIL', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        r['inputs_unchanged'] = inputs() == before
        if not r['inputs_unchanged']:
            r['status'] = 'FAIL_SOURCE_DRIFT'
        r['artifacts'] = artifacts(out, {'receipt.json'})
        seal()
    print(r['status'])

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--emit', action='store_true')
    mode.add_argument('--build-run', action='store_true')
    ap.add_argument('--tag')
    ap.add_argument('--compile-receipt', type=Path)
    ap.add_argument('--tool-receipt', type=Path)
    a = ap.parse_args()
    before = preflight()
    if not a.emit and not a.build_run:
        print('PASS_IDENTITY_FETCH_HORIZON_COMPONENT_SOURCE_PREFLIGHT_ONLY inputs='+str(len(before)))
        return
    need(a.tag and re.fullmatch(r'[A-Za-z0-9_-]+', a.tag), 'safe fresh tag required')
    need(a.compile_receipt and a.tool_receipt, 'unified compile and tool epoch receipts required')
    tools = epoch.tool_binding(a.tool_receipt)
    if a.emit:
        emit(a, tools, before)
    else:
        build_run(a, tools, before)

if __name__ == '__main__':
    main()
