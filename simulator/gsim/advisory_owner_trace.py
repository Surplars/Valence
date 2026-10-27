#!/usr/bin/env python3
"""Passive whole scalar-port traces; compile/link hosts only, never generate a DUT.

The schema is derived from FIR direction/flip semantics, cross-checked against
all generated scalar getters. Standard payloads are valid-qualified (including
stall cycles). The ONLY ready exception is returnFlow.outputReady with no valid
reply, a deliberately non-contractual unowned readiness signal. No other output
is omitted. These traces are bounded trajectory evidence, not ISA/formal proof.
"""
import difflib
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
import buffered_return_flow_cpu as cpu

R, need, sha = cpu.common.ROOT, cpu.need, cpu.sha
HEADER = R / 'simulator/gsim/harness/advisory_owner_trace.h'
TOP = cpu.raw.TOP


def fir_outputs(text):
    """Fail-closed scalar/bundle top-port parser; vectors/unknown ground types rejected."""
    match = re.search(r'^  (?:public )?module ' + re.escape(TOP) + r' :.*$', text, re.M)
    need(match is not None, 'exact trace top module missing')
    block = text[match.end():]
    end = re.search(r'^  (?:public )?(?:module|extmodule|intmodule) ', block, re.M)
    if end:
        block = block[:end.start()]
    result = {}
    for line in block.splitlines():
        port = re.fullmatch(r'    (input|output) (\w+) : (.*?)(?: @\[.*)?', line)
        if not port:
            continue
        kind, name, typ = port.groups()
        tokens = re.findall(r'\w+|[{}:<>,\[\]]', typ)
        need(''.join(tokens) == re.sub(r'\s+', '', typ), 'unparsed top port type: ' + name)
        pos = 0
        def parse(path, output):
            nonlocal pos
            need(pos < len(tokens), 'truncated FIR port')
            if tokens[pos] == '{':
                pos += 1
                while tokens[pos] != '}':
                    flip = tokens[pos] == 'flip'
                    if flip:
                        pos += 1
                    child = tokens[pos]; pos += 1
                    need(tokens[pos] == ':', 'missing FIR field colon'); pos += 1
                    parse(path + '$$' + child, output != flip)
                    need(tokens[pos] in (',', '}'), 'vector/unknown aggregate unsupported')
                    if tokens[pos] == ',':
                        pos += 1
                pos += 1
            else:
                ground = tokens[pos]; pos += 1
                need(ground in ('UInt', 'SInt', 'Clock', 'Reset', 'AsyncReset'), 'unsupported FIR scalar ' + ground)
                width = 1
                if ground in ('UInt', 'SInt'):
                    need(tokens[pos] == '<', 'unknown scalar width'); pos += 1
                    width = int(tokens[pos]); pos += 1
                    need(tokens[pos] == '>', 'missing scalar width end'); pos += 1
                need(0 < width <= 64, 'trace scalar wider than uint64')
                if output:
                    need(path not in result, 'duplicate FIR output')
                    result[path] = width
        parse(name, kind == 'output')
        need(pos == len(tokens), 'trailing FIR type syntax')
    need(result, 'empty FIR scalar output schema')
    return result


def schema(fir, header):
    outputs = fir_outputs(fir)
    getters = re.findall(r'^uint(8|16|32|64)_t get_([A-Za-z0-9_$]+)\(\);$', header, re.M)
    names = [name for _, name in getters]
    need(len(names) == len(set(names)) and set(names) == set(outputs),
         'FIR outputs and generated scalar getters must match exactly')
    need('returnFlow$$outputReady' in names and 'returnFlow$$outputValid' in names,
         'explicit buffered-return ON observation required')
    result = []
    for width, name in getters:
        need(int(width) >= outputs[name], 'getter width truncates FIR output')
        predicates = []
        for match in re.finditer(r'\$\$bits(?=\$\$|$)', name):
            valid = name[:match.start()] + '$$valid'
            need(valid in names, 'payload lacks explicit validity getter: ' + name)
            predicates.append('d.get_' + valid + '()')
        if name.startswith('row$$normalIssue$$'):
            predicates.insert(0, 'd.get_row$$normalIssued()')
        owner = re.fullmatch(r'supply\$\$owner([0-3])\$\$(?:index|tag)', name)
        if owner:
            predicates.append('((d.get_supply$$states() >> ' + str(int(owner[1])*2) + ') & 3)')
        for side in ('input', 'output'):
            if name.startswith('returnFlow$$' + side + 'Bits$$'):
                predicates.append('d.get_returnFlow$$' + side + 'Valid()')
        if name == 'returnFlow$$outputReady':
            predicates.append('d.get_returnFlow$$outputValid()')
        result.append({'getter': name, 'width': outputs[name], 'when': ' && '.join(predicates) or 'true'})
    need(all(x['when'] == 'true' for x in result if x['getter'].endswith('$$ready')),
         'unexpected ready qualification')
    return result


def trace_header(fields):
    lines = ['#pragma once', '#include "advisory_owner_trace.h"', 'namespace advisory_owner_trace {',
             'template<class D> void Observer::observe(D &d) {']
    for field in fields:
        lines.append('    record((' + field['when'] + ') ? uint64_t(d.get_' + field['getter'] + '()) : uint64_t(0));')
    lines += ['    ++cycles;', '}', '}']
    return '\n'.join(lines) + '\n'


def adapt(kind, source):
    before = source.read_text()
    edits = [('#include "gsim_model_storage.h"\n',
              '#include "gsim_model_storage.h"\n#include "advisory_owner_trace_generated.h"\n')]
    if kind in ('vm', 'load'):
        edits += [('class Run {\n', 'class Run {\n    advisory_owner_trace::Observer exactTrace;\n'),
                  ('returnObserver.observe(dut);', 'returnObserver.observe(dut);exactTrace.observe(dut);'),
                  ('dut.set_reset(false);', 'dut.set_reset(false);exactTrace.initialize(program.name);'),
                  ('sourceObserver.report(std::cout,', 'exactTrace.report(std::cout);sourceObserver.report(std::cout,')]
    elif kind == 'bare':
        edits += [('class Run{\n', 'class Run{\n    advisory_owner_trace::Observer exactTrace;\n'),
                  ('drive(stopped,inspect);dut.step();observe();',
                   'drive(stopped,inspect);dut.step();exactTrace.observe(dut);observe();'),
                  ('dut.set_reset(false);', 'dut.set_reset(false);exactTrace.initialize("bare");'),
                  ('        std::cout<<"BOOTROM_PASS ', '        exactTrace.report(std::cout);\n        std::cout<<"BOOTROM_PASS ')]
    else:
        raise RuntimeError('unknown immutable host kind: ' + kind)
    after = before
    for old, new in edits:
        need(after.count(old) == 1 and new not in after, 'unique passive adapter point: ' + kind + ': ' + old)
        after = after.replace(old, new, 1)
    restored = after
    for old, new in reversed(edits):
        need(restored.count(new) == 1, 'trace adapter inverse point')
        restored = restored.replace(new, old, 1)
    need(restored == before, 'trace adapter changed original functional bytes')
    return after, ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile=str(source), tofile=kind + '_exact_trace.cpp'))


def prepare(model, out, sources):
    model, out = Path(model).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    header, fir = model / (TOP + '.h'), model / (TOP + '.fir')
    fields = schema(fir.read_text(), header.read_text())
    cpu.save(out / 'trace-schema.json', fields)
    (out / 'advisory_owner_trace_generated.h').write_text(trace_header(fields))
    originals = {}
    for kind, source in sources.items():
        source = Path(source).resolve()
        after, diff = adapt(kind, source)
        (out / (kind + '.cpp')).write_text(after)
        (out / (kind + '.diff')).write_text(diff)
        originals[str(source)] = sha(source)
    inputs = {str(p): sha(p) for p in (Path(__file__).resolve(), HEADER, header, fir)} | originals
    plan = {'schema': 'valence-advisory-owner-exact-trace-plan-v1', 'model': str(model),
            'output': str(out), 'kinds': list(sources), 'sources': {k: str(Path(v).resolve()) for k, v in sources.items()},
            'fields_per_cycle': len(fields),
            'scope': 'all scalar outputs, valid-qualified payloads; only invalid returnFlow.outputReady excepted',
            'inputs': inputs, 'new_DUT_compilations': 0,
            'prepared': {str(p): sha(p) for p in out.iterdir() if p.is_file()}}
    cpu.save(out / 'plan.json', plan)
    return plan


def run_prepared(plan, tools, first_build):
    """Explicit caller GO required; only host compilation/link and focused immutable guests."""
    out, model = Path(plan['output']), Path(plan['model'])
    need(plan['schema'] == 'valence-advisory-owner-exact-trace-plan-v1' and
         all(sha(p) == digest for p, digest in (plan['inputs'] | plan['prepared']).items()), 'trace plan drift')
    need(cpu.row.unchanged_artifacts(first_build), 'cached DUT artifacts changed')
    result = {'schema_sha256': sha(out / 'trace-schema.json'), 'fields_per_cycle': plan['fields_per_cycle'],
              'new_DUT_compilations': 0, 'new_host_compilations': 0, 'runs': {}}
    for kind in plan['kinds']:
        obj, binary, log = out / (kind + '.o'), out / (kind + '.run'), out / (kind + '.log')
        need(not any(p.exists() for p in (obj, binary, log)), 'refuse host artifact overwrite')
        flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-I' + str(out), '-I' + str(model), '-I' + str(HEADER.parent)]
        # Bare image.h is intentionally the immutable source-directory image.
        source = Path(plan['sources'][kind])
        need(adapt(kind, source)[0] == (out / (kind + '.cpp')).read_text(), 'passive adapter reconstruction drift')
        flags.append('-I' + str(source.parent))
        cxx = tools['compiler']['command']
        cpu.common.run([cxx, *flags, '-fsyntax-only', out / (kind + '.cpp')], log=out/(kind+'-syntax.log'), timeout=180)
        cpu.common.run([cxx, *flags, '-c', out/(kind+'.cpp'), '-o', obj], log=out/(kind+'-compile.log'), timeout=600)
        cpu.common.run([cxx, *flags, *first_build['DUT_objects'], obj, '-ldl', '-o', binary], log=out/(kind+'-link.log'), timeout=600)
        env = {**cpu.base.runtime_env(), 'A1_OWNER_TRACE_PREFIX': str(out/kind)}
        cpu.common.run([binary, *(['--trace'] if kind == 'load' else [])], env=env, log=log, timeout=180)
        text = log.read_text(); cpu.base.check_log(text)
        records = [dict(part.split('=', 1) for part in line.split()[1:]) for line in text.splitlines()
                   if line.startswith('ADVISORY_OWNER_TRACE ')]
        expected = ['bare'] if kind == 'bare' else list(cpu.raw.VM_CASES if kind == 'vm' else cpu.raw.LOAD_CASES)
        need([r['guest'] for r in records] == expected, 'missing/duplicate/out-of-order trace guest')
        traces = {}
        for record in records:
            path = out / (kind + '-' + record['guest'] + '.bin')
            cycles, count = int(record['cycles']), int(record['fields'])
            need(cycles > 0 and count == cycles * plan['fields_per_cycle'] and path.stat().st_size == count * 8,
                 'incomplete cycle trace')
            traces[record['guest']] = {'path': str(path), 'sha256': sha(path), 'cycles': cycles, 'bytes': count*8}
        functional = '\n'.join(line for line in text.splitlines() if not line.startswith('ADVISORY_OWNER_TRACE ')) + '\n'
        (out/(kind+'-functional.log')).write_text(functional)
        result['runs'][kind] = {'traces': traces, 'log': str(log), 'functional_log': str(out/(kind+'-functional.log')),
                               'functional_sha256': sha(out/(kind+'-functional.log'))}
        result['new_host_compilations'] += 1
    need(cpu.row.unchanged_artifacts(first_build) and
         all(sha(p) == digest for p, digest in (plan['inputs'] | plan['prepared']).items()), 'trace execution mutated bound input')
    result['artifacts'] = {str(p): sha(p) for p in out.iterdir() if p.is_file()}
    cpu.save(out/'receipt.json', result)
    return result


def compare_exact(control, candidate):
    need(control['schema_sha256'] == candidate['schema_sha256'] and
         control['fields_per_cycle'] == candidate['fields_per_cycle'], 'trace schema differs')
    need(control['runs'].keys() == candidate['runs'].keys(), 'trace host set differs')
    total = 0
    for kind, a in control['runs'].items():
        b = candidate['runs'][kind]
        need(Path(a['functional_log']).read_bytes() == Path(b['functional_log']).read_bytes(),
             'owner-only immutable functional/log/cycle regression: ' + kind)
        need(a['traces'].keys() == b['traces'].keys(), 'trace guest set differs')
        for guest, left in a['traces'].items():
            right = b['traces'][guest]
            need(left['cycles'] == right['cycles'] and Path(left['path']).read_bytes() == Path(right['path']).read_bytes(),
                 'owner-only valid-qualified exact cycle trace regression: ' + guest)
            total += left['bytes']
    return {'status': 'PASS_OWNER_ONLY_EXACT_CYCLE_VALID_TRACES_AND_LOGS', 'bytes_per_variant': total,
            'scalar_fields_per_cycle': control['fields_per_cycle'], 'all_guest_cycles_exact': True,
            'invalid_ready_exception': 'returnFlow.outputReady only when outputValid=false'}
