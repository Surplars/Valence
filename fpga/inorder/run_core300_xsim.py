#!/usr/bin/env python3
"""Windows Vivado xsim, real cached CPU, official CoreMark; emit independent-oracle replay traces."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = Path(r'E:\VM\Share\Valence-rtl\Valence-InOrder').resolve()
VIVADO = Path(r'E:\Xilinx\2025.2\Vivado\bin')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--payload-sha256', required=True)
    parser.add_argument('--reuse-build', type=Path, help='Reuse a source-identical completed xvlog/xelab build')
    parser.add_argument('--debug-control', action='store_true', help='Reference control diagnostic only')
    args = parser.parse_args()
    rtl, output = args.rtl.resolve(), args.output.resolve()
    if output.exists() or not output.is_relative_to(ALLOWED) or not rtl.is_relative_to(ALLOWED):
        parser.error('designated Windows root and fresh output required')
    if sha(args.payload) != args.payload_sha256:
        parser.error('official fixed CoreMark binary mismatch')
    output.mkdir(parents=True)
    build = args.reuse_build.resolve() if args.reuse_build else output / 'build'
    if args.reuse_build:
        if not build.is_relative_to(ALLOWED) or not (build/'xsim.dir/i1_coremark300').exists():
            parser.error('compiled build must remain inside designated root')
    else:
        build.mkdir()
    sources = sorted(rtl.glob('*.sv'))
    if not sources:
        raise RuntimeError('missing generated RTL')
    sources += [ROOT / 'fpga/inorder/coremark300_tb.sv']
    frozen = {str(path): sha(path) for path in sources}
    for path in sources:
        if args.reuse_build:
            if sha(build/path.name) != sha(path):
                raise RuntimeError('compiled source drift: '+path.name)
        else:
            shutil.copy2(path, build / path.name)
    image = args.payload.read_bytes()
    if len(image) > 65536:
        raise RuntimeError('CoreMark image too large')
    image += bytes(73728-len(image))
    image_path = output / 'coremark.mem'
    image_path.write_text(''.join(f'{value:02x}\n' for value in image))
    receipt = {'status': 'RUNNING', 'scope': 'real Windows xsim RTL simulation; independent ISA replay required separately',
               'clock_hz': 300000000, 'clock_precision': '1fs', 'source_sha256': frozen,
               'payload_sha256': args.payload_sha256, 'commands': [], 'samples': [], 'oracle_pending': True,
               'timing_qualified': False, 'formal_score': False, 'reused_build': str(build) if args.reuse_build else None,
               'runner_sha256': sha(Path(__file__))}

    def save():
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')

    def run(argv, log, timeout):
        argv = [str(value) for value in argv]
        receipt['commands'].append({'cwd': str(build), 'argv': argv})
        save()
        with log.open('w') as stream:
            result = subprocess.run(' '.join('\"'+value+'\"' for value in argv), cwd=build, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        text = log.read_text(errors='replace')
        if result.returncode or re.search(r'(?m)^\s*(?:Fatal:|FATAL:|ERROR:)', text):
            raise RuntimeError('xsim stage failed: '+str(log))
        return text

    try:
        if not args.reuse_build:
            run([VIVADO/'xvlog.bat', '-sv', '-work', 'xil_defaultlib',
                 *(['-d', 'I1_TRACE_DEBUG'] if args.debug_control else []),
                 *[path.name for path in build.glob('*.sv')]], output/'xvlog.stdout.log', 300)
            run([VIVADO/'xelab.bat', '-mt', 'off', '-timescale', '1ns/1fs',
                 'xil_defaultlib.coremark300_tb', '-s', 'i1_coremark300'], output/'xelab.stdout.log', 300)
        for latency in [1, 12]:
            folder = output / ('latency-'+str(latency))
            folder.mkdir()
            trace = folder/'cpu.trace'
            ram = folder/'final-ram.mem'
            text = run([VIVADO/'xsim.bat', 'i1_coremark300', '-runall', '-onerror', 'quit',
                '-log', folder/'xsim.log', '-wdb', folder/'cpu.wdb', '-testplusarg', 'LATENCY='+str(latency),
                '-testplusarg', 'IMAGE='+image_path.as_posix(), '-testplusarg', 'TRACE='+trace.as_posix(),
                '-testplusarg', 'FINAL_RAM='+ram.as_posix()],
                folder/'xsim.stdout.log', 900)
            match = re.search(r'XSIM_COREMARK_DONE cycles=(\d+) retired=(\d+) latency=(\d+)', text)
            if not match or int(match[3]) != latency or not trace.exists() or not ram.exists():
                raise RuntimeError('missing completed bounded CPU simulation: '+str(folder))
            receipt['samples'].append({'latency': latency, 'cycles': int(match[1]), 'retired': int(match[2]),
                'trace': str(trace), 'trace_sha256': sha(trace), 'trace_bytes': trace.stat().st_size,
                'final_ram': str(ram), 'final_ram_sha256': sha(ram)})
            save()
            print('XSIM completed', latency, 'cycles', match[1], 'retired', match[2], flush=True)
        for name, digest in frozen.items():
            if sha(Path(name)) != digest:
                raise RuntimeError('source drift: '+name)
        receipt['status'] = 'PASS_XSIM_COREMARK_TRACE_ONLY_ORACLE_PENDING'
    except BaseException as error:
        receipt.update(status='FAIL', error=repr(error))
        raise
    finally:
        save()
    print(json.dumps({'status': receipt['status'], 'receipt': str(output/'receipt.json')}, indent=2))


if __name__ == '__main__':
    main()
