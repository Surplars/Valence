#!/usr/bin/env python3
"""Bounded initial raw-index noninterference using sealed 7daf DUT objects only.

--prepare writes fresh host adapters, an exhaustive scalar output trace schema,
and a sealed plan. --run-prepared requires those exact bytes and explicit GO.
No Scala, GSIM generation, DUT compilation, generator edit or original host edit.
"""
import argparse
import difflib
import json
import os
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
import buffered_third_rank_cpu as donor

R, need, sha, read = donor.common.ROOT, donor.need, donor.sha, donor.read
HERE = R / 'simulator/gsim'
REFERENCE = R / 'build/gsim/buffered-third-rank-cpu-20261025-r3-host-recovery/receipt.json'
REFERENCE_SHA = '98ef619db33d8ea546802c4fa3480b492bf9cf2e9ec1469b8052998419608c05'
CONTROL = donor.CANDIDATE
HEADER = HERE / 'harness/buffered_index_initial_state_observer.h'
ROW_HEADER = HERE / 'harness/buffered_return_flow_observer.h'


def schema(header):
    getters = re.findall(r'^uint(?:8|16|32|64)_t get_([A-Za-z0-9_$]+)\(\);$', header, re.M)
    need(getters and len(getters) == len(set(getters)), 'unique scalar public output schema required')
    names = set(getters)
    result = []
    for name in getters:
        predicates = []
        # Every protocol payload is defined on VALID, including a stalled beat.
        for match in re.finditer(r'\$\$bits(?=\$\$|$)', name):
            valid = name[:match.start()] + '$$valid'
            need(valid in names, 'payload lacks explicit validity getter: ' + name)
            predicates.append('d.get_' + valid + '()')
        if name.startswith('row$$normalIssue$$'):
            # This is a passive accepted normal-memory-issue event, not a Decoupled port.
            predicates.insert(0, 'd.get_row$$normalIssued()')
        owner = re.fullmatch(r'supply\$\$owner([0-3])\$\$(?:index|tag)', name)
        if owner:
            predicates.append('((d.get_supply$$states() >> ' + str(int(owner[1])*2) + ') & 3)')
        result.append({'getter': name, 'when': ' && '.join(predicates) or 'true'})
    # Never drop controls or silently ignore a missing field.
    need(all(x['when'] == 'true' for x in result if x['getter'].endswith('$$ready') or
             (x['getter'].endswith('$$valid') and '$$bits' not in x['getter'] and
              not x['getter'].startswith('row$$normalIssue$$'))), 'unconditional ready/valid gate drift')
    return result


def trace_header(fields):
    lines = ['#pragma once', '#include "buffered_index_initial_state_observer.h"',
             'namespace buffered_index_initial_state {',
             'template<class D> void Observer::traceOutputs(D &d) {']
    for x in fields:
        lines.append('    record((' + x['when'] + ') ? uint64_t(d.get_' + x['getter'] + '()) : uint64_t(0));')
    lines += ['}', '}']
    return '\n'.join(lines) + '\n'


def adapt(kind, original):
    before = original.read_text()
    edits = [('#include "buffered_source_lifetime_observer.h"\n',
              '#include "buffered_source_lifetime_observer.h"\n#include "index_initial_trace.h"\n'),
             ('class Run {\n', 'class Run {\n    buffered_index_initial_state::Observer initialIndex;\n'),
             ('sourceObserver.observe(dut);', 'sourceObserver.observe(dut);initialIndex.observe(dut);'),
             ('sourceObserver.report(std::cout,', 'initialIndex.report(std::cout,program.name);sourceObserver.report(std::cout,')]
    reset = 'dut.set_reset(false);'
    edits.append((reset, reset + 'initialIndex.initialize(dut,program.name);'))
    after = before
    for a, b in edits:
        need(after.count(a) == 1, 'unique initial adapter point: ' + kind + ': ' + a)
        after = after.replace(a, b, 1)
    restored = after
    for a, b in reversed(edits):
        need(restored.count(b) == 1, 'inverse initial adapter point')
        restored = restored.replace(b, a, 1)
    need(restored == before, 'original functional code changed')
    return after, ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                             fromfile=str(original), tofile=kind + '_initial_index.cpp'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--tool-receipt', type=Path, required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--run-prepared', action='store_true')
    args = ap.parse_args()
    need(sha(REFERENCE) == REFERENCE_SHA, 'sealed 7daf baseline receipt changed')
    receipt = read(REFERENCE)
    tools = donor.epoch.tool_binding(args.tool_receipt)
    need(tools == receipt['tools_before'], 'identical corrected GSIM epoch required')
    model = REFERENCE.parent / CONTROL
    record = receipt['models'][CONTROL]
    verified = donor.verify_build(model, tools['compiler']['command'], Path(record['first_build']['host']))
    need(verified == record['first_build'], 'sealed cached generated objects changed')
    header = model / 'CommonA1VmPipelineGsim.h'
    generated = ''.join(p.read_text() for p in sorted(model.glob('CommonA1VmPipelineGsim*.cpp')))
    for suffix in ('', '$NEXT'):
        declaration = 'uint8_t tile$core$core$core$backend$queue$$renamed$$token$$index' + suffix + '[16]; // width = 4,'
        need(declaration in header.read_text(), 'exact OFF ROB16 raw index CURRENT/NEXT layout required')
    need('memcpy(tile$core$core$core$backend$queue$$renamed$$token$$index, tile$core$core$core$backend$queue$$renamed$$token$$index$NEXT, 16 * sizeof' in generated,
         'verified pre-evaluation NEXT to CURRENT transfer required')
    need(len(re.findall(r'queue\$\$renamed\$\$token\$\$index\$NEXT\[[^\]]+\] = ', generated)) == 2,
         'exact sole two accepted rename writer layout required')
    out = args.output.resolve()
    if args.prepare:
        out.mkdir(parents=True, exist_ok=False)
        fields = schema(header.read_text())
        donor.save(out / 'trace-schema.json', fields)
        (out / 'index_initial_trace.h').write_text(trace_header(fields))
        for kind in ('vm', 'load'):
            source = Path(receipt['host_adapters'][kind]['adapter'])
            need(sha(source) == receipt['host_adapters'][kind]['adapter_sha256'], 'sealed source adapter changed')
            adapted, diff = adapt(kind, source)
            (out / (kind + '.cpp')).write_text(adapted)
            (out / (kind + '.diff')).write_text(diff)
        donor.save(out / 'plan.json', {'schema': 'buffered-index-initial-state-plan-v1',
            'scope': 'selected reset-started traces with arbitrary unreset raw index initial values; not universal noninterference',
            'patterns': ['zero', 'slot', '15-slot', 'slot-xor-10'],
            'fresh_model': 'every guest Run constructs its own zero-storage Model then drives original two reset steps',
            'tools': tools, 'new_DUT_compilations': 0,
            'inputs': {str(p): sha(p) for p in (REFERENCE, header, HEADER, ROW_HEADER, Path(__file__).resolve())},
            'prepared': {str(p): sha(p) for p in out.iterdir() if p.is_file()}})
        print('PREPARED_ONLY_NO_BUILD_OR_RUN')
        return
    plan = read(out / 'plan.json')
    need(plan['tools'] == tools and all(sha(p) == d for p, d in {**plan['inputs'], **plan['prepared']}.items()),
         'frozen initial-state plan drift')
    report = {'schema': 'buffered-index-initial-state-v1', 'status': 'RUNNING', 'new_DUT_compilations': 0,
              'plan_sha256': sha(out / 'plan.json'), 'runs': {}}
    donor.save(out / 'receipt.json', report)
    try:
        for kind in ('vm', 'load'):
            obj, binary = out / (kind + '.o'), out / (kind + '.run')
            need(not obj.exists() and not binary.exists(), 'do not overwrite old host build')
            flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                     '-I'+str(out), '-I'+str(model), '-I'+str(HERE/'harness')]
            cxx = tools['compiler']['command']
            donor.common.run([cxx, *flags, '-fsyntax-only', out/(kind+'.cpp')], log=out/(kind+'-syntax.log'), timeout=180)
            donor.common.run([cxx, *flags, '-c', out/(kind+'.cpp'), '-o', obj], log=out/(kind+'-compile.log'), timeout=600)
            donor.common.run([cxx, *flags, *verified['DUT_objects'], obj, '-ldl', '-o', binary], log=out/(kind+'-link.log'), timeout=600)
            results = []
            for pattern in range(4):
                log = out / (kind + '-' + str(pattern) + '.log')
                env = {**donor.base.runtime_env(), 'A1_INDEX_INITIAL_PATTERN': str(pattern),
                       'A1_INDEX_TRACE_PREFIX': str(out / (kind + '-' + str(pattern)))}
                donor.common.run([binary], env=env, log=log, timeout=180)
                text = log.read_text(); donor.base.check_log(text)
                rows = [dict(kv.split('=',1) for kv in line.split()[1:]) for line in text.splitlines()
                        if line.startswith('INDEX_INITIAL_STATE ')]
                need(len(rows) == 2 and len({r['name'] for r in rows}) == 2, 'two exact guests and trace records required')
                for r in rows:
                    need(r.pop('pattern') == str(pattern), 'pattern not applied')
                    need(all(int(r[k]) > 0 for k in ('cycles','allocations','live_checks')), 'empty valid-domain coverage')
                functional = '\n'.join(x for x in text.splitlines() if not x.startswith('INDEX_INITIAL_STATE '))
                trace_paths = [out / (kind + '-' + str(pattern) + '-' + r['name'] + '.bin') for r in rows]
                need(all(p.is_file() and p.stat().st_size > 0 for p in trace_paths), 'exact cycle trace missing')
                if pattern:
                    for r, path in zip(rows, trace_paths):
                        zero = out / (kind + '-0-' + r['name'] + '.bin')
                        need(path.read_bytes() == zero.read_bytes(), 'byte-exact cycle/control/valid-payload trace differs; no automatic exceptions')
                results.append({'rows': rows, 'functional': functional})
                report['runs'][kind+'-'+str(pattern)] = {'rows':rows, 'log_sha256':sha(log)}
                donor.save(out / 'receipt.json', report)
            need(all(r == results[0] for r in results[1:]),
                 'initial-state output/control/valid-payload or original functional trace differs; DO NOT weaken schema')
        report['status'] = 'PASS_BOUNDED_INITIAL_INDEX_NONINTERFERENCE'
        report['cycle_trace_bytes_exact'] = True
    except BaseException as e:
        report['status'] = 'FAIL'; report['error'] = str(e); raise
    finally:
        report['artifacts'] = {str(p.relative_to(out)): sha(p) for p in out.iterdir() if p.is_file() and p.name != 'receipt.json'}
        donor.save(out / 'receipt.json', report)
    print(report['status'])

if __name__ == '__main__':
    main()
