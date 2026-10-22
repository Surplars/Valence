#!/usr/bin/env python3
"""Isolated real I1 IRQ/atomic epoch tests. Native Icarus, no gate/DRP proof."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE / 'i1_msi_epoch_native.py'
spec = importlib.util.spec_from_file_location('bounded_native_tools', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
FIXTURE = ROOT / 'src/test/scala/platform/CommonI1RuntimeArchitecturalMain.scala'
OLD_FIXTURE = ROOT / 'src/test/scala/platform/CommonI1RuntimeCdcMain.scala'


def inventory(kind):
    paths = [BASE, Path(__file__).resolve(), FIXTURE, OLD_FIXTURE,
             ROOT / 'build.mill', ROOT / 'scripts/cloud/env.sh']
    paths += [HERE / f'i1_{kind}_epoch{suffix}' for suffix in ('.S', '.ld', '_tb.sv')]
    paths += sorted((ROOT / 'src/main/scala').rglob('*.scala'))
    paths += sorted((ROOT / 'src/main/resources').rglob('*.sv'))
    return {str(p.relative_to(ROOT)): base.sha(p) for p in paths}


def guest(kind, out, prefix, record):
    tools = {n: base.tool(prefix + n) for n in ('gcc', 'objcopy', 'nm', 'objdump')}
    record['tools'].update(base.tool_hashes(tools))
    commands = [
        ([tools['gcc'], '-march=rv64ima_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
          '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
          '-T' + str(HERE / f'i1_{kind}_epoch.ld'), HERE / f'i1_{kind}_epoch.S',
          '-o', out / 'guest.elf'], 'guest-build'),
        ([tools['objcopy'], '-O', 'binary', out / 'guest.elf', out / 'guest.bin'], 'guest-binary'),
        ([tools['nm'], '-n', out / 'guest.elf'], 'guest-symbols'),
        ([tools['objdump'], '-d', out / 'guest.elf'], 'guest-disassembly')]
    for cmd, name in commands:
        rc, _ = base.run(cmd, out, name, 60, record)
        if rc:
            raise RuntimeError('guest build failed: ' + name)
    image = (out / 'guest.bin').read_bytes()
    if len(image) > 1024 or len(image) % 4:
        raise RuntimeError('guest must fit explicit 256-word test ROM with whole instructions')
    padded = image + bytes(1024-len(image))
    (out / 'guest.hex').write_text(''.join(f'{int.from_bytes(padded[n:n+4], "little"):08x}\n' for n in range(0, 1024, 4)))
    symbols = {name: int(address, 16) for address, _, name in re.findall(
        r'^([0-9a-fA-F]+)\s+(\w)\s+([A-Za-z_][A-Za-z0-9_]*)$',
        (out / 'guest-symbols.log').read_text(), re.M)}
    if symbols.get('_start') != 0x80000000 or 'guest_fail' not in symbols:
        raise RuntimeError('missing independent guest entry/failure symbols')
    (out / 'guest_symbols.svh').write_text(''.join(
        f"localparam [63:0] PC_{name.upper()} = 64'h{address:016x};\n" for name, address in symbols.items()))
    record['guest'] = dict(image_bytes=len(image), rom_words=256, symbols=symbols,
        artifacts={n: base.sha(out/n) for n in ('guest.elf', 'guest.bin', 'guest.hex', 'guest_symbols.svh')})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind', choices=('irq', 'atomic'), required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--rtl-dir', type=Path, required=True)
    p.add_argument('--emission-receipt', type=Path, required=True)
    p.add_argument('--cross-prefix', default='riscv64-unknown-elf-')
    p.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    p.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    args = p.parse_args()
    if not os.environ.get('VALENCE_CLOUD_ENV'):
        p.error('source scripts/cloud/env.sh first')
    out, rtl = args.out.resolve(), args.rtl_dir.resolve()
    if out.exists() or not out.parent.is_dir():
        p.error('fresh output directory with existing parent required')
    frozen = inventory(args.kind)
    emission = json.loads(args.emission_receipt.read_text())
    if emission.get('status') != 'PASS_EMIT_ONLY':
        p.error('passing fresh emission required')
    for n, h in frozen.items():
        if n.startswith(('src/main/', 'src/test/')) or n == 'build.mill':
            if emission.get('source_sha256', {}).get(n) != h:
                p.error('source-bound emission mismatch: ' + n)
    files = sorted(rtl.glob('*.sv'))
    rtl_hashes = {f.name: base.sha(f) for f in files}
    if not files or rtl_hashes != emission.get('rtl_sha256'):
        p.error('emitted RTL mismatch')
    text = '\n'.join(f.read_text() for f in files)
    for required in ('module CommonI1RuntimeArchitecturalFixture', 'module RuntimeAtomicTestFabric',
                     'module CommonRuntimeEpochBoundary', 'module AtomicMemory', 'module Imsic', '$fatal'):
        if required not in text:
            p.error('missing actual module/assertions: ' + required)
    out.mkdir()
    record = dict(status='RUNNING', kind=args.kind, source_sha256=frozen, rtl_sha256=rtl_hashes,
        tools={}, cases=[], scope='real I1/private caches/Home/APLIC/IMSIC/atomic owners; three unrelated clocks; direct epoch requests; test-only protocol backpressure; no full system ACK, gate, DRP, board or timing qualification',
        emission_receipt=dict(path=str(args.emission_receipt.resolve()), sha256=base.sha(args.emission_receipt)))
    try:
        guest(args.kind, out, args.cross_prefix, record)
        tools = {n: base.tool(getattr(args, n)) for n in ('iverilog', 'vvp')}
        record['tools'].update(base.tool_hashes(tools))
        binary = out/'sim.vvp'
        rc, _ = base.run([tools['iverilog'], '-g2012', '-I', out, '-s', f'i1_{args.kind}_epoch_tb',
            '-o', binary, *files, HERE/f'i1_{args.kind}_epoch_tb.sv'], out, 'compile', 180, record)
        if rc:
            raise RuntimeError('native compile failed')
        record['sim_sha256'] = base.sha(binary)
        command = [tools['vvp'], binary, '+rom='+str(out/'guest.hex')]
        marker = f'I1_{args.kind.upper()}_EPOCH_PASS'
        for name, periods in [('unrelated', (5, 7, 11)), ('reversed', (11, 5, 7))]:
            rc, log = base.run(command+[f'+cpu-half={periods[0]}', f'+fabric-half={periods[1]}', f'+aon-half={periods[2]}'], out, name, 600, record)
            if rc or marker not in log:
                raise RuntimeError('positive architectural epoch test failed: '+name)
        negatives = [('wrong-epc', 'independent IRQ EPC oracle'), ('wrong-claim', 'independent IRQ claim oracle'), ('wrong-service', 'independent IRQ service oracle')] if args.kind == 'irq' else [('wrong-old', 'independent atomic old-value oracle'), ('wrong-final', 'independent atomic final-value oracle'), ('wrong-sc', 'independent post-epoch SC oracle')]
        for name, negative_marker in negatives:
            rc, log = base.run(command+['+'+name], out, name, 300, record)
            if not rc or negative_marker not in log or marker in log:
                raise RuntimeError('negative oracle not rejected: '+name)
        if inventory(args.kind) != frozen or {f.name:base.sha(f) for f in files} != rtl_hashes:
            raise RuntimeError('source/RTL drift')
        for name, entry in record['tools'].items():
            if base.sha(entry['path']) != entry['sha256']:
                raise RuntimeError('tool drift: '+name)
        for name, digest in record['guest']['artifacts'].items():
            if base.sha(out/name) != digest:
                raise RuntimeError('guest drift: '+name)
        record['status'] = 'PASS'
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['logs_sha256'] = {f.name:base.sha(f) for f in out.glob('*.log')}
        (out/'receipt.json').write_text(json.dumps(record, indent=2)+'\n')
        print(record['status']+' receipt='+str(out/'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
