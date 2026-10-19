#!/usr/bin/env python3
"""Actual emitted top input/connection audit; optional Icarus shell syntax check.

The optional compile deliberately stubs only the emitted top and ignores missing
vendor/IP modules. It is NOT full-board elaboration or vendor primitive proof.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import board_inputs


def check(top, wrapper, compiler=None, production=True):
    rtl = top.read_text(); shell = wrapper.read_text()
    result = board_inputs.port_check(rtl, shell, production=production)
    result.update(scope='source-bound board port audit', physical_qualified=False, vendor_ip_elaborated=False)
    if compiler:
        with tempfile.TemporaryDirectory() as temporary:
            stub = Path(temporary) / 'common_top_ports_only.sv'
            header = rtl.split('module CommonMachinePlatform(', 1)[1].split(');', 1)[0]
            stub.write_text('module CommonMachinePlatform(' + header + '); endmodule\n')
            cmd = [str(compiler), '-g2012', '-tnull', '-i', '-s', 'soc_top_common_ddr', str(wrapper), str(stub)]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if out.returncode:
                raise ValueError('shell syntax/port compile failed: ' + out.stdout + out.stderr)
            result.update(shell_syntax='PASS', command=cmd, diagnostics=out.stdout + out.stderr)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--emitted-top', required=True, type=Path)
    p.add_argument('--iverilog', type=Path)
    p.add_argument('--allow-programmable-port-audit-only', action='store_true')
    a = p.parse_args()
    print(json.dumps(check(a.emitted_top, Path(__file__).parent / 'soc_top_common_ddr.sv', a.iverilog,
                           not a.allow_programmable_port_audit_only), indent=2))
