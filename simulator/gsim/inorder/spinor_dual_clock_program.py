#!/usr/bin/env python3
"""Run the real CPU/Spinor program using a qualified opt-in explicit-edge GSIM tool."""
import argparse
import os, subprocess, json, re, hashlib, shutil, sys
from pathlib import Path
r = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(r / 'simulator/gsim'))
from gsim_clock_edge_epoch import tool_binding
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tool-receipt', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
o = args.output.resolve()
if o.exists() or not o.is_relative_to(r / 'build'):
    parser.error('fresh output inside clone build/ required')
g = tool_binding(args.tool_receipt)
# Compile the dependency graph before binding sources to generated hardware.
subprocess.run(['mill', '-i', 'SpinorHost.test.runClasspath'], cwd=r, check=True)
o.mkdir(parents=True)
v = json.loads((r / 'out/SpinorHost/test/runClasspath.json').read_text())['value']
cp = os.pathsep.join((str(p) for v in v if (p := Path(v.split(':', 3)[3])).exists()))

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
inputs = [r / 'simulator/gsim/harness/i1_spinor_cpu.cpp', r / 'simulator/gsim/harness/i1_spinor_dual_clock_cpu.cpp', r / 'simulator/gsim/harness/five_stage_coremark.cpp', r / 'simulator/gsim/harness/five_stage.cpp', r / 'build.mill', Path(__file__).resolve(), r / 'simulator/gsim/gsim_clock_edge_epoch.py']
for d in [r / 'integration/spinor', r / 'src/main/scala/core/inorder', r / 'src/main/scala/ip/bus', r / 'build/dependencies/Spinor-e151f80e1da3/src/main/scala', r / 'third_party/berkeley-hardfloat/src/main/scala']:
    inputs += list(d.rglob('*.scala'))
frozen = {str(p.relative_to(r)): sha(p) for p in inputs}
for p in inputs:
    t = o / 'source-at-model' / p.relative_to(r)
    t.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(p, t)
classes = {str(p.relative_to(r)): sha(p)
    for module in ['OrbitalI1', 'SpinorI1', 'SpinorHost', 'OrbitalI1/test', 'SpinorHost/test']
    for p in (r / 'out' / module / 'compile.dest/classes').rglob('*.class')}
receipt = {'compiled_class_sha256': classes, 'status': 'RUNNING_QUALIFIED_EXPLICIT_EDGE_TOOL', 'sources': frozen, 'gsim_sha256': sha(g), 'qualified_tool_receipt': str(args.tool_receipt.resolve()), 'qualified_tool_receipt_sha256': sha(args.tool_receipt.resolve()), 'physical_qualified': False, 'soc_bus_present': False, 'cmu_present': False, 'independent_clock_directed_function_qualified': False, 'commands': []}

def run(a, n, code=0):
    a = list(map(str, a))
    receipt['commands'].append({'argv': a, 'log': n})
    with (o / n).open('w') as f:
        p = subprocess.run(a, cwd=r, env={**os.environ, 'GSIM_CLOCK_EDGES': '1', 'ASAN_OPTIONS': 'detect_leaks=0'}, stdout=f, stderr=subprocess.STDOUT)
    print(n, p.returncode, flush=True)
    if p.returncode != code:
        print((o / n).read_text()[-6000:])
        raise RuntimeError(n)
    return (o / n).read_text()
try:
    top = 'I1SpinorDualClockFixture'
    run(['java', '-cp', cp, 'spinor_integration.I1SpinorDualClockMain', o, '--observe'], 'elaborate.log')
    raw = o / (top + '.fir')
    text = raw.read_text()
    norm = o / (top + '.gsim.fir')
    norm.write_text(''.join((re.sub('\\bold\\b', 'i1_spinor_old', l) if not re.match('\\s*smem\\b', l) else l for l in text.splitlines(True))))
    run([g, '--threads=1', '--dir=' + str(o), norm], 'generate.log')
    flags = ['clang++-19', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(o)]
    parts = sorted(o.glob(top + '[0-9]*.cpp'))
    objects = []
    for part in parts:
        obj = part.with_suffix('.o')
        run([*flags, '-c', part, '-o', obj], part.stem + '-compile.log')
        objects.append(obj)
    run([*flags, *objects, r / 'simulator/gsim/harness/i1_spinor_dual_clock_cpu.cpp', '-o', o / 'run'], 'driver-compile.log')
    receipt['summary'] = run([o / 'run'], 'positive.log')
    if receipt['summary'].count('I1_SPINOR_DUAL_CLOCK_CPU_PASS') != 4:
        raise RuntimeError('missing four cases')
    for opt in ['--inject-value', '--inject-flags']:
        txt = run([o / 'run', opt], opt[2:] + '.log', 1)
        if 'CPU vector independent' not in txt:
            raise RuntimeError('wrong negative failure')
    if any((sha(r / name) != h for name, h in frozen.items())):
        raise RuntimeError('source drift')
    receipt['status'] = 'PASS_REAL_CPU_SPINOR_DUAL_CLOCK_DIRECTED_PROGRAM_FOUR_CASES_TWO_NEGATIVES'
    receipt['independent_clock_directed_function_qualified'] = True
except BaseException as e:
    receipt.update(status='FAIL', error=repr(e))
    raise
finally:
    receipt['artifact_sha256'] = {p.name: sha(p) for p in o.iterdir() if p.is_file() and p.name != 'receipt.json'}
    (o / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(receipt['status'], receipt['summary'], flush=True)
