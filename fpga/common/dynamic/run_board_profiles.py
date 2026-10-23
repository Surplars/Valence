#!/usr/bin/env python3
"""Exact CPU/fabric profile roundtrip on official native primitives; no synthesis/bit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

BAD = re.compile(r'(?i)\b(?:warning|error|fatal)\b|timing violation')
WARN = re.compile(r'(?i)\bwarning\b|timing violation')
PASS_MARKERS = {p: 'DYNAMIC_BOARD_'+p[:3]+'_'+p[3:]+'_UNISIM_PASS checks=9 exact_words=44 drp_commands=132'
                for p in ('195155', '125125')}
PASS = PASS_MARKERS['195155']
NEGATIVES = {'bad_board_image': 'BOARD_DRP_WRITE_IMAGE',
             'bad_board_rate': 'UNISIM_FREQUENCY_OR_INDEPENDENCE'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('output', type=Path)
    ap.add_argument('--vivado-bin', type=Path, required=True)
    ap.add_argument('--profile', choices=('195155', '125125'), default='195155')
    args = ap.parse_args()
    pass_marker = PASS_MARKERS[args.profile]
    here = Path(__file__).resolve().parent
    out = args.output.resolve()
    if out.exists():
        ap.error('Fresh output directory required')
    ext = '.bat' if os.name == 'nt' else ''
    exe = {t: args.vivado_bin.resolve()/(t+ext) for t in ('xvlog', 'xelab', 'xsim')}
    rtl = [here/x for x in ('native_clock_drp.sv', 'native_clock_gate.sv',
                           'native_dynamic_clock_domain.sv', 'dynamic_clock_unisim_tb.sv')]
    glbl = args.vivado_bin.resolve().parent/'data/verilog/src/glbl.v'
    inputs = [*rtl, glbl, Path(__file__).resolve(), here/'software-parameters.json']
    for path in [*inputs, *exe.values()]:
        if not path.is_file():
            ap.error('Missing native input/tool: '+str(path))
    hashes = {str(p): sha(p) for p in inputs}
    out.mkdir(parents=True)
    report = dict(status='RUNNING', inputs=hashes, vendor_primitives=True,
                  hardware_logic_modified=False, explicit_unused_output_sinks=True,
                  soc=False, routed_sta=False, board=False,
                  profiles=({'boot_return': '0x14280a', 'cpu125': '0x08280a', 'fabric125': '0x08280a'}
                            if args.profile == '125125' else
                            {'boot_return': '0x14280a', 'cpu195': '0x05270a', 'fabric155': '0x0a3e0a'}),
                  timeout_fault_injection=False, cases={}, commands=[])
    start = time.monotonic()

    def run(command, name):
        command = list(map(str, command))
        report['commands'].append(command)
        begin = time.monotonic()
        # Completed commands have a hard wall limit. No detached native processes.
        with (out/name).open('w') as log_file:
            process = subprocess.Popen(command, cwd=out, stdout=log_file, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                else:
                    process.kill()
                process.wait()
                raise RuntimeError('Native command timed out: '+name)
        text = (out/name).read_text(errors='replace')
        return code, text, time.monotonic()-begin

    try:
        code, log, _ = run([exe['xvlog'], '-sv', '--define', 'VALENCE_USE_UNISIM', *rtl, glbl], 'compile.log')
        if code or BAD.search(log):
            raise RuntimeError('Compile failed or warning detected')
        code, log, _ = run([exe['xelab'], 'dynamic_clock_unisim_tb', 'glbl', '-L', 'unisims_ver',
                           '--timescale', '1ns/1ps', '-debug', 'typical', '-mt', '8', '-s', 'board_profiles'], 'elaborate.log')
        if code or BAD.search(log):
            raise RuntimeError('Elaboration failed or warning detected')
        if not re.search(r'(?i)(Vivado|xelab).*2025\.2', log):
            raise RuntimeError('Native elaborator version is not verified 2025.2')
        for case in ('positive', *NEGATIVES):
            command = [exe['xsim'], 'board_profiles', '-runall', '-onerror', 'quit', '-testplusarg', 'board'+args.profile]
            if case != 'positive':
                command += ['-testplusarg', case]
            code, log, elapsed = run(command, case+'.log')
            if case == 'positive':
                if code or pass_marker not in log or BAD.search(log) or log.count('BOARD_DRP_VERIFIED ') != 4:
                    raise RuntimeError('Positive failed or warning/readback coverage missing')
            elif (NEGATIVES[case] not in log or pass_marker in log or
                  not re.search(r'(?i)\bfatal\b', log) or WARN.search(log)):
                raise RuntimeError('Negative did not reject through expected ordinary oracle: '+case)
            report['cases'][case] = dict(status='PASS' if case == 'positive' else 'REJECTED_BY_ORDINARY_ORACLE',
                                         exit_code=code, wall_seconds=elapsed)
        report['status'] = 'PASS_NATIVE_EXACT_'+args.profile[:3]+'_'+args.profile[3:]+'_ROUNDTRIP'
    except BaseException as exc:
        report.update(status='FAIL', error=str(exc))
    finally:
        if hashes != {str(p): sha(p) for p in inputs}:
            report.update(status='FAIL', error='Input drift')
        report['wall_seconds'] = time.monotonic()-start
        report['logs'] = {p.name: sha(p) for p in out.glob('*.log')}
        (out/'receipt.json').write_text(json.dumps(report, indent=2)+'\n')
    print(report['status'])
    if report['status'] == 'FAIL':
        raise SystemExit(report['error'])


if __name__ == '__main__':
    main()
