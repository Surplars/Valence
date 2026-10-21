#!/usr/bin/env python3
"""Source-bound independent-clock timer/debug fixtures; no GSIM CDC claim.

First export platform.FixedTimebaseNativeMain and platform.DebugDmiBoundaryNativeMain
into the two --rtl-root subdirectories timer and debug. --run uses installed XSIM
only; otherwise writes PREPARED_NOT_RUN manifest. No synthesis or board access.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from xsim_invocation import invocation, resolve_tool

ROOT = Path(__file__).resolve().parents[2]

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--rtl-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--tool-dir', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args()
    output = a.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for domain, top, parameter, marker in (
        ('timer', 'fixed_timebase_tb', 'FABRIC_HALF', 'PASS FIXED_TIMEBASE'),
        ('debug', 'debug_dmi_boundary_tb', 'DEST_HALF', 'PASS DEBUG_DMI_BOUNDARY')):
        rtl = sorted((a.rtl_root.resolve() / domain).glob('*.sv'))
        if not rtl:
            p.error('missing exported RTL: ' + domain)
        sources = rtl + [ROOT / 'simulator/cdc' / (top + '.sv')]
        for half in (5, 10, 7):
            cases.append(dict(name=domain + '_' + str(half), top=top,
                parameter=parameter, half=half, marker=marker,
                sources=[dict(path=str(s), sha256=hashlib.sha256(s.read_bytes()).hexdigest()) for s in sources],
                status='PREPARED_NOT_RUN'))
    runner_sources = [Path(__file__).resolve(), Path(__file__).with_name('xsim_invocation.py').resolve()]
    manifest = dict(runner_sources=[dict(path=str(s), sha256=hashlib.sha256(s.read_bytes()).hexdigest()) for s in runner_sources], status='PREPARED_NOT_RUN', scope='native independent edges only; not physical CDC/STA/board acceptance', cases=cases)
    manifest_path = output / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    if not a.run:
        print(manifest_path)
        return
    xvlog, xelab, xsim = (resolve_tool(t, a.tool_dir) for t in ('xvlog', 'xelab', 'xsim'))
    try:
        for case in cases:
            work = output / case['name']
            work.mkdir(exist_ok=True)
            commands = [
                [xvlog, '--sv'] + [s['path'] for s in case['sources']],
                [xelab, case['top'], '-s', 'test_snapshot', '-generic_top',
                    case['parameter'] + '=' + str(case['half']), '-timescale', '1ns/1ps'],
                [xsim, 'test_snapshot', '-runall'],
            ]
            combined = ''
            for i, command in enumerate(commands):
                result = subprocess.run(invocation(command), cwd=work, text=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, timeout=180)
                (work / ('step' + str(i) + '.log')).write_text(result.stdout)
                combined += result.stdout
                if result.returncode:
                    raise RuntimeError(case['name'] + ': command failed; inspect logs')
            if case['marker'] not in combined or 'Fatal:' in combined or 'FATAL' in combined:
                raise RuntimeError(case['name'] + ': missing pass marker or fatal')
            case['status'] = 'PASS'
            manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        manifest['status'] = 'PASS'
    except Exception as error:
        manifest['status'] = 'FAILED_OR_BLOCKED'
        manifest['error'] = str(error)
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(manifest_path)

if __name__ == '__main__':
    main()
