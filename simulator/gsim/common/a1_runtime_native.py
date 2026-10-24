#!/usr/bin/env python3
"""Bounded real A1 + common Home/APLIC/IMSIC/CDC epoch acceptance.

Production RTL is emitted unchanged, then standard sv2v conversion preserves
severity tasks for Icarus. No physical clock gating, STA, or board claim.
"""
import argparse
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('epoch_tools', HERE / 'i1_msi_epoch_native.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def custom_guest(out, source, words, symbols, record):
    compiler = base.tool('riscv64-unknown-elf-gcc')
    objcopy = base.tool('riscv64-unknown-elf-objcopy')
    nm = base.tool('riscv64-unknown-elf-nm')
    record['tools'].update(base.tool_hashes({'gcc': compiler, 'objcopy': objcopy, 'nm': nm}))
    commands = [([compiler, '-march=rv64imafd_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
                  '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
                  '-T' + str(HERE / 'i1_runtime_network.ld'), source, '-o', out / 'guest.elf'], 'guest-build'),
                ([objcopy, '-O', 'binary', out / 'guest.elf', out / 'guest.bin'], 'guest-binary'),
                ([nm, '-n', out / 'guest.elf'], 'guest-symbols')]
    for cmd, name in commands:
        rc, _ = base.run(cmd, out, name, 60, record)
        if rc:
            raise RuntimeError('guest failed: ' + name)
    raw = (out / 'guest.bin').read_bytes()
    if len(raw) > words * 4 or len(raw) % 4:
        raise RuntimeError('guest outside actual ROM geometry')
    data = raw.ljust(words * 4, b'\0')
    (out / 'guest.hex').write_text(''.join(f'{int.from_bytes(data[i:i+4], "little"):08x}\n' for i in range(0, len(data), 4)))
    addresses = {name: int(address, 16) for address, _, name in re.findall(
        r'^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$', (out / 'guest-symbols.log').read_text(), re.M)}
    (out / 'guest_symbols.svh').write_text(''.join(
        f"localparam [63:0] PC_{name.upper()} = 64'h{addresses[name]:016x};\n" for name in symbols))
    record['guest'] = dict(image_bytes=len(raw), rom_words=words, symbols=addresses,
                          artifacts={name: base.sha(out / name) for name in ['guest.elf','guest.bin','guest.hex','guest_symbols.svh']})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--sv2v', required=True)
    ap.add_argument('--suite', choices=('epoch', 'wfi', 'arithmetic', 'atomic', 'fp'), default='epoch')
    args = ap.parse_args()
    out = args.out.resolve()
    if out.exists():
        ap.error('fresh evidence directory required')
    out.mkdir(parents=True)
    paths = list((ROOT / 'src/main/scala').rglob('*.scala'))
    paths += [ROOT / 'src/test/scala/platform/CommonA1RuntimeCdcMain.scala',
              HERE / 'a1_runtime_cdc_tb.sv', Path(__file__), HERE / 'i1_msi_epoch.S',
              HERE / 'i1_msi_epoch.ld', HERE / 'i1_msi_epoch_native.py',
              HERE / 'a1_wfi_runtime.S', HERE / 'a1_wfi_runtime_tb.sv', HERE / 'a1_runtime_guest.S',
              HERE / 'i1_runtime_network.ld', HERE / 'a1_atomic_epoch.S', HERE / 'a1_atomic_epoch_tb.sv', HERE / 'a1_fp_runtime.S', HERE / 'a1_fp_runtime_tb.sv',
              ROOT / 'src/test/scala/platform/CommonI1RuntimeArchitecturalMain.scala']
    hashes = lambda: {str(p.relative_to(ROOT)): base.sha(p) for p in paths}
    record = dict(status='RUNNING', source_sha256=hashes(), tools={}, cases=[], board_verified=False,
                  scope='real two-wide A1/common fabric/three-clock epoch and independent MSI/RAM retirement ledger; no rate backend or physical gate')
    try:
        tb = HERE / ('a1_wfi_runtime_tb.sv' if args.suite == 'wfi' else 'a1_runtime_cdc_tb.sv')
        top = 'a1_wfi_runtime_tb' if args.suite == 'wfi' else 'a1_runtime_cdc_tb'
        emitter = 'CommonA1WfiRuntimeMain' if args.suite == 'wfi' else 'CommonA1RuntimeCdcNativeMain'
        if args.suite == 'fp':
            tb = HERE / 'a1_fp_runtime_tb.sv'; top = 'a1_fp_runtime_tb'; emitter = 'CommonA1WfiRuntimeMain'
        if args.suite == 'atomic':
            tb = HERE / 'a1_atomic_epoch_tb.sv'; top = 'a1_atomic_epoch_tb'; emitter = 'CommonA1AtomicRuntimeMain'
        if args.suite == 'epoch':
            base.guest(out, 'riscv64-unknown-elf-', record)
        elif args.suite == 'fp':
            custom_guest(out, HERE / 'a1_fp_runtime.S', 256, ['fp_dcheck','fp_scheck','guest_fail','idle_wfi','irq_claim','irq_external','irq_timer','irq_mret'], record)
        elif args.suite == 'atomic':
            custom_guest(out, HERE / 'a1_atomic_epoch.S', 256, ['amo_d','check_d','guest_done','guest_fail'], record)
        elif args.suite == 'arithmetic':
            custom_guest(out, HERE / 'a1_runtime_guest.S', 64, base.SYMBOLS, record)
        else:
            custom_guest(out, HERE / 'a1_wfi_runtime.S', 256,
                         ['guest_fail','idle_wfi','irq_claim','irq_external','irq_timer','irq_mret'], record)
        tools = {n: base.tool(v) for n, v in [('mill','mill'),('sv2v',args.sv2v),('iverilog','iverilog'),('vvp','vvp')]}
        record['tools'].update(base.tool_hashes(tools))
        rc, _ = base.run([tools['mill'], '-i', 'IonSoC.test.runMain',
                          'platform.' + emitter, out / 'rtl'], out, 'emit', 600, record)
        if rc:
            raise RuntimeError('actual A1/common fixture emission failed')
        files = sorted((out / 'rtl').glob('*.sv'))
        record['emitted_rtl_sha256'] = {str(p): base.sha(p) for p in files}
        original = '\n'.join(p.read_text() for p in files)
        rc, lowered = base.run([tools['sv2v'], '--exclude=SeverityTask', *files], out, 'lower', 180, record)
        if rc or not original.count('$fatal'):
            raise RuntimeError('assertion-preserving standard lowering failed')
        for token in ('$fatal', '$error'):
            if original.count(token) != lowered.count(token):
                raise RuntimeError('severity task count changed: ' + token)
        lowered_path = out / 'lowered.v'
        lowered_path.write_text(lowered)
        record['lowered_sha256'] = base.sha(lowered_path)
        rc, _ = base.run([tools['iverilog'], '-g2012', '-I', out, '-s', top, '-o',
                          out / 'test.vvp', lowered_path, tb], out, 'compile', 180, record)
        if rc:
            raise RuntimeError('native compile failed')
        record['sim_sha256'] = base.sha(out / 'test.vvp')
        cases = [('unrelated', []), ('reversed', ['+cpu-half=11', '+fabric-half=5', '+aon-half=7']),
                            ('negative-data', ['+wrong-data']), ('negative-store', ['+wrong-store']),
                            ('negative-irq', ['+wrong-irq'])]
        if args.suite == 'wfi':
            cases = [('unrelated', []), ('reversed', ['+cpu-half=11', '+fabric-half=5', '+aon-half=7']), ('negative-irq', ['+wrong-irq'])]
        if args.suite == 'arithmetic':
            cases = [('arithmetic', ['+arithmetic']), ('equal-old-completion', ['+arithmetic', '+fence-equal'])]
        if args.suite == 'atomic':
            cases = [('atomic', []), ('negative-old', ['+wrong-old']), ('negative-final', ['+wrong-final'])]
        if args.suite == 'fp':
            cases = [('fp', []), ('negative-fp', ['+wrong-fp'])]
        for name, extra in cases:
            rc, log = base.run([tools['vvp'], '-i', out / 'test.vvp', '+rom=' + str(out / 'guest.hex'), *extra],
                               out, name, 180, record)
            negative = name.startswith('negative-')
            banner = {'epoch': 'A1_RUNTIME_CDC_PASS', 'wfi': 'A1_WFI_RUNTIME_PASS', 'arithmetic': 'A1_RUNTIME_ARITHMETIC_PASS', 'atomic': 'A1_ATOMIC_EPOCH_PASS', 'fp': 'A1_FP_RUNTIME_PASS'}[args.suite]
            if (not negative and (rc or banner not in log)) or (
                    negative and (rc == 0 or 'independent' not in log)):
                raise RuntimeError('unexpected native result: ' + name)
        if hashes() != record['source_sha256']:
            raise RuntimeError('source drift during acceptance')
        record['status'] = 'PASS_A1_RUNTIME_NATIVE_' + args.suite.upper()
    except Exception as exc:
        record['status'] = 'FAIL'
        record['error'] = str(exc)
        raise
    finally:
        (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    main()
