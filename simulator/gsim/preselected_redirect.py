#!/usr/bin/env python3
"""One default-off C0 experiment: accepted-token equivalence and matched backend replay.

Explicit existing GSIM binary, fresh output, bounded jobs; no toolchain build or Vivado.
The retained backend oracle is copied unchanged except an observer-only destructor
that prints counters, allowing cycle/traffic comparison without changing admission.
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


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--gsim', type=Path, required=True)
    ap.add_argument('--cxx', default='clang++-19')
    ap.add_argument('--jobs', type=int, choices=range(1, 5), default=4)
    args = ap.parse_args()
    if hasattr(os, 'nice'):
        os.nice(10)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, 'JAVA_TOOL_OPTIONS': '-XX:ActiveProcessorCount='+str(args.jobs),
           'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1'}
    inputs = {p.relative_to(ROOT).as_posix(): sha(p) for p in ROOT.glob('src/**/*.scala')}
    for name in ('simulator/gsim/harness/preselected_redirect.cpp',
                 'simulator/gsim/harness/preselected_redirect_lifecycle.cpp',
                 'simulator/gsim/ready_store_query77/ready_store_query77_backend.cpp',
                 'simulator/gsim/ready_store_query77/ready_store_query77_reference.h',
                 'simulator/gsim/preselected_redirect.py'):
        inputs[name] = sha(ROOT/name)
    receipt = dict(status='RUNNING', source_inputs=inputs, gsim_sha256=sha(args.gsim),
                   commands=[], state_bits_added=0, physical_resources_measured=False,
                   synthesis=False, route=False, board_qualified=False)

    def save():
        (out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')

    def run(label, command, negative=None):
        for name, digest in inputs.items():
            if sha(ROOT/name) != digest:
                raise RuntimeError('source drift: '+name)
        path = out/(label+'.log')
        start = time.monotonic()
        with path.open('x') as log:
            p = subprocess.run(list(map(str, command)), cwd=ROOT, env=env,
                               stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        text = path.read_text(errors='replace')
        receipt['commands'].append(dict(label=label, exit=p.returncode,
            elapsed_seconds=round(time.monotonic()-start, 3), log_sha256=sha(path)))
        save()
        if negative:
            if p.returncode == 0 or negative not in text:
                raise RuntimeError('negative control failed: '+label+'\n'+text[-3000:])
        elif p.returncode:
            raise RuntimeError(label+'\n'+text[-5000:])
        print(label, 'PASS', flush=True)
        return text

    def emit(label, main, directory, *parameters):
        return run(label, ['mill', '-i', '-j', str(args.jobs), 'IonSoC.test.runMain', main,
                           directory, *parameters])

    def model(label, directory, top, host):
        run(label+'-generate', [args.gsim, '--threads=1', '--cpp-max-size-KB=1024',
                               '--dir='+str(directory), directory/(top+'.fir')])
        flags = ['-std=c++20', '-O1', '-g0', '-fsanitize=address,undefined',
                 '-fno-sanitize-recover=all', '-I'+str(directory),
                 '-I'+str(ROOT/'simulator/gsim/ready_store_query77')]
        objects = []
        for index, source in enumerate(sorted(directory.glob(top+'[0-9]*.cpp'))):
            obj = directory/(source.stem+'.o')
            run(label+'-compile-'+str(index), [args.cxx, *flags, '-c', source, '-o', obj])
            objects.append(obj)
        if not objects:
            raise RuntimeError('no generated translation units')
        binary = directory/'run'
        run(label+'-link', [args.cxx, *flags, host, *objects, '-ldl', '-o', binary])
        return binary

    save()
    try:
        run('contracts', ['mill', '-i', '-j', str(args.jobs), 'IonSoC.test.testOnly',
                          'ooo.PreselectedRedirectSpec'])
        component = out/'component'
        emit('component-emit', 'ooo.PreselectedRedirectGsimMain', component)
        fir = (component/'PreselectedRedirectGsim.fir').read_text()
        # Both component modules must remain stateless. Inspect the actual emitted bodies.
        for name in ('RedirectTokenQualification', 'PreselectedRedirectTokenQualification'):
            body = re.search(r'(?ms)^  (?:public )?module '+name+r'\b.*?(?=^  (?:public )?module |\Z)', fir)
            if not body or re.search(r'^\s+reg(?:reset)?\s', body[0], re.M):
                raise RuntimeError('component state/cone audit failed: '+name)
        candidate_body = re.search(r'(?ms)^  (?:public )?module PreselectedRedirectTokenQualification\b.*?(?=^  (?:public )?module |\Z)', fir)[0]
        nodes = dict(re.findall(r'^\s+node\s+(\w+)\s*=\s*(.*)', candidate_body, re.M))
        equalities = {name: expr for name, expr in nodes.items() if expr.startswith('eq(')}
        if len(equalities) != 6:
            raise RuntimeError('expected six complete token comparisons, got '+repr(equalities))
        cones = {}
        for name, expr in equalities.items():
            seen = set()
            def visit(value):
                for token in re.findall(r'[A-Za-z_]\w*(?:\.\w+)*', value):
                    if token in seen:
                        continue
                    seen.add(token)
                    if token in nodes:
                        visit(nodes[token])
            visit(expr)
            if any('Accepted' in token for token in seen):
                raise RuntimeError('late accepted control still feeds equality: '+name)
            cones[name] = sorted(seen)
        receipt['emitted_equality_cones'] = cones
        receipt['structural_scope'] = 'only accepted-system -> token payload mux -> equality removed; other CE cones remain unqualified'
        binary = model('component', component, 'PreselectedRedirectGsim',
                       ROOT/'simulator/gsim/harness/preselected_redirect.cpp')
        receipt['component_result'] = run('component-positive', [binary]).strip()
        for mutation in (1, 2, 3):
            run('component-negative-'+str(mutation), [binary, mutation],
                'independent accepted-token priority/full-tag mismatch')
        host_source = ROOT/'simulator/gsim/ready_store_query77/ready_store_query77_backend.cpp'
        host = out/'observed_backend.cpp'
        text = host_source.read_text()
        anchor = '    void check(bool ok,const std::string &why) const'
        if text.count(anchor) != 1:
            raise RuntimeError('retained observer insertion anchor changed')
        observer = ('    ~Bench() { std::cout << "C0_CASE_METRICS cycles=" << cycle'
                    ' << " retired=" << retired << " accepted=" << accepted'
                    ' << " physical=" << physicalCount << " responses=" << responseCount << "\\n"; }\n')
        host.write_text(text.replace(anchor, observer+anchor))
        receipt['retained_oracle_sha256'] = sha(host_source)
        receipt['observer_host_sha256'] = sha(host)
        arms = {}
        lifecycle = {}
        configs = []
        for arm, switch in (('baseline', '0'), ('candidate', '1')):
            directory = out/arm
            emit(arm+'-emit', 'ooo.PreselectedRedirectBackendMain', directory, switch)
            configs.append(json.loads((directory/'actual-core.json').read_text()))
            executable = model(arm, directory, 'ReadyStoreQuery77BackendGsim', host)
            log = run(arm+'-positive', [executable, 'on'])
            if 'READY_QUERY77_PASS arm=on' not in log:
                raise RuntimeError('missing retained backend oracle PASS')
            arms[arm] = re.findall(r'^C0_CASE_METRICS .*$', log, re.M)
            for mutation, diagnostic in (
                ('--mutate-data', 'independent execution data mismatch'),
                ('--mutate-frozen-pa', 'bound store failed frozen physical handoff')):
                run(arm+'-'+mutation[2:], [executable, 'on', mutation], diagnostic)
            # Link a second independent scenario driver to the SAME model objects.
            life_binary = directory/'lifecycle'
            run(arm+'-lifecycle-link', [args.cxx, '-std=c++20', '-O1', '-g0',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-I'+str(directory), '-I'+str(ROOT/'simulator/gsim/ready_store_query77'),
                ROOT/'simulator/gsim/harness/preselected_redirect_lifecycle.cpp',
                *sorted(directory.glob('*.o')), '-ldl', '-o', life_binary])
            life_log = run(arm+'-lifecycle-positive', [life_binary])
            if 'C0_LIFECYCLE_PASS rows=3 credits=2 lsu=4' not in life_log:
                raise RuntimeError('missing lifecycle oracle PASS')
            lifecycle[arm] = re.findall(r'^C0_LIFECYCLE_METRICS .*$', life_log, re.M)
            run(arm+'-lifecycle-retirement-negative', [life_binary, '--mutate-retirement'],
                'fault/killed/duplicate retirement')
        if configs[0] != configs[1] or len(configs[0]) != 178:
            raise RuntimeError('baseline/candidate configuration mismatch')
        if not arms['baseline'] or arms['baseline'] != arms['candidate']:
            raise RuntimeError('matched cycle/traffic regression: '+repr(arms))
        if len(lifecycle['baseline']) != 4 or lifecycle['baseline'] != lifecycle['candidate']:
            raise RuntimeError('matched lifecycle/throughput regression: '+repr(lifecycle))
        receipt.update(status='PASS_DEFAULT_OFF_C0_COMPONENT_AND_MATCHED_BACKEND',
                       actual_core=configs[0], matched_case_metrics=arms, matched_lifecycle_metrics=lifecycle,
                       performance='identical measured backend cycles and accepted/physical/response counts; no hardware clock speedup measured')
        save()
        print(receipt['status'], flush=True)
    except BaseException as exc:
        receipt['status'] = 'FAILED_PRESERVE_EVIDENCE'
        receipt['failure'] = str(exc)
        save()
        raise


if __name__ == '__main__':
    main()
