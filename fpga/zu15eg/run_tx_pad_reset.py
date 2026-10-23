#!/usr/bin/env python3
"""Focused TX reset pin test: behavioral Icarus or actual AMD UNISIM, never STA."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def icarus_locals(text):
    # Sequential, non-reentrant always block temporaries. Preserve every RHS and
    # assignment order; declaration initializers must execute on EVERY entry.
    def convert(match):
        declarations, assignments = [], []
        for decl in re.findall(r'automatic logic\s+([^;]+);', match[0]):
            lhs, rhs = decl.split('=', 1)
            name = re.search(r'(\w+)\s*$', lhs)[1]
            declarations.append('logic ' + lhs.strip() + ';')
            assignments.append(name + ' = ' + rhs.strip() + ';')
        return '\n      ' + '\n      '.join(declarations + assignments) + '\n      '
    if text.count('automatic logic') != 8 or 'always @(posedge clock)' not in text:
        raise ValueError('Unexpected standalone codec temporary structure')
    return re.sub(r'(?:\s*automatic logic\s+[^;]+;)+', convert, text)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('codec', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--mode', choices=('behavioral', 'unisim'), required=True)
    ap.add_argument('--vivado-bin', type=Path)
    args = ap.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    codec, out = args.codec.resolve(), args.output.resolve()
    if out.exists():
        ap.error('Fresh output directory required')
    if args.mode == 'unisim' and not args.vivado_bin:
        ap.error('--vivado-bin required for native UNISIM')
    inputs = [codec, Path(__file__).resolve(), here/'tx_pad_reset_tb.sv',
              here/'native_rgmii_trispeed_quarter.sv', here/'native_tx_word_reset_boundary.sv']
    stub = root/'fpga/next/tests/rgmii_behavioral_primitives.sv'
    if args.mode == 'behavioral':
        inputs.append(stub)
    else:
        inputs.append(args.vivado_bin.parent/'data/verilog/src/glbl.v')
    hashes = {str(p): sha(p) for p in inputs}
    out.mkdir(parents=True)
    report = dict(status='RUNNING', mode=args.mode, inputs=hashes,
                  vendor_primitive_models=args.mode == 'unisim', routed_timing=False,
                  board=False, bitstream=False, whole_soc_admission_proven=False, cases={})
    start = time.monotonic()
    def run(command, log):
        r = subprocess.run(list(map(str, command)), cwd=out, capture_output=True, text=True, timeout=120)
        text = r.stdout+r.stderr
        (out/log).write_text(text)
        return r.returncode, text
    try:
        rtl = [here/'native_rgmii_trispeed_quarter.sv', here/'native_tx_word_reset_boundary.sv', here/'tx_pad_reset_tb.sv']
        if args.mode == 'behavioral':
            adapted = out/'TriSpeedRgmiiTx-icarus.sv'
            adapted.write_text(icarus_locals(codec.read_text()))
            report['simulation_adaptation'] = dict(only='8 automatic block temporaries to static declarations plus per-entry assignments', sha256=sha(adapted), native_uses_original=True)
            code, log = run(['iverilog','-g2012','-s','tx_pad_reset_tb','-o','test.vvp',adapted,*rtl,stub], 'compile.log')
        else:
            ext = '.bat' if os.name == 'nt' else ''
            exe = {t:args.vivado_bin/(t+ext) for t in ('xvlog','xelab','xsim')}
            code, log = run([exe['xvlog'],'-sv',codec,*rtl,inputs[-1]], 'compile.log')
            if code or re.search(r'(?i)\b(fatal|error|warning)\b|timing violation', log):
                raise RuntimeError('Native compile failed or warning detected')
            code, log = run([exe['xelab'],'tx_pad_reset_tb','glbl','-L','unisims_ver','-L','secureip','--timescale','1ns/1ps','-mt','8','-debug','typical','-s','tx_reset'], 'elaborate.log')
        if code or (args.mode == 'unisim' and re.search(r'(?i)\b(fatal|error|warning)\b|timing violation', log)):
            raise RuntimeError('Compile/elaboration failed or native warning detected')
        negatives = {'bad_payload':'TX_RESET_FALLING_NIBBLE','bad_control':'TX_RESET_CONTROL',
                     'bad_phase':'TX_RESET_CLOCK_EDGE','bad_reset':'TX_RESET_RELEASE_T0'}
        for case in ('positive', *negatives):
            if args.mode == 'behavioral':
                cmd = ['vvp','test.vvp'] + ([] if case=='positive' else ['+'+case])
            else:
                cmd = [exe['xsim'],'tx_reset','-runall','-onerror','quit'] + ([] if case=='positive' else ['-testplusarg',case])
            code, log = run(cmd, case+'.log')
            if case == 'positive':
                if code or 'TX_PAD_RESET_PASS' not in log or re.search(r'(?i)\b(fatal|error|warning)\b|timing violation',log):
                    raise RuntimeError('Positive failed or vendor warning detected')
                report['summary'] = next(x for x in log.splitlines() if 'TX_PAD_RESET_PASS' in x)
            elif negatives[case] not in log or 'TX_PAD_RESET_PASS' in log or not re.search(r'(?i)fatal',log):
                raise RuntimeError('Ordinary checker did not reject '+case)
            report['cases'][case] = 'PASS' if case == 'positive' else 'REJECTED_BY_ORDINARY_ORACLE'
        report['status'] = 'PASS_'+args.mode.upper()+'_TX_RESET_PINS_ONLY'
    except BaseException as exc:
        report.update(status='FAIL', error=str(exc))
    finally:
        if hashes != {str(p):sha(p) for p in inputs}:
            report.update(status='FAIL', error='Input drift')
        report['wall_seconds'] = time.monotonic()-start
        report['logs'] = {p.name:sha(p) for p in out.glob('*.log')}
        (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'])
    if report['status']=='FAIL':
        raise SystemExit(report['error'])

if __name__=='__main__':
    main()
