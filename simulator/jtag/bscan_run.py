#!/usr/bin/env python3
"""Optional native BSCAN interface test; never installs tools or invokes Verilator."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / 'src/main/resources/debug/ValenceJtagDebugPort.sv',
         ROOT / 'src/main/resources/debug/ValenceBscanDebugPort.sv',
         ROOT / 'simulator/jtag/bscan_user_tb.sv']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/jtag/bscan-native')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'status': 'blocked', 'native_multiclock_verified': False,
              'amd_unisim_verified': False, 'physical_cdc_signoff': False,
              'board_verified': False,
              'sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in FILES}}
    iverilog = shutil.which(os.environ.get('IVERILOG', 'iverilog'))
    vvp = shutil.which(os.environ.get('VVP', 'vvp'))
    code = 77
    try:
        if not iverilog or not vvp:
            report['blocker'] = 'Icarus Verilog and vvp not found; no tool installed or fallback simulator run.'
        else:
            commands = [[iverilog, '-g2012', '-Wall', '-s', 'bscan_user_tb', '-o',
                         str(out / 'bscan.vvp'), *map(str, FILES)],
                        [vvp, str(out / 'bscan.vvp')]]
            for name, command in zip(('compile', 'run'), commands):
                result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, timeout=120)
                (out / (name + '.log')).write_text(result.stdout)
                if result.returncode:
                    raise RuntimeError(f'{name} failed: {result.stdout}')
            if 'PASS BSCAN_USER' not in result.stdout:
                raise RuntimeError('Missing explicit BSCAN test PASS')
            report.update(status='passed', native_multiclock_verified=True,
                          result=result.stdout.strip())
            code = 0
    except Exception as error:
        report.update(status='failed', error=str(error))
        code = 1
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
