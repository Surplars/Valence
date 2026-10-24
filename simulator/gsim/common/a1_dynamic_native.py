#!/usr/bin/env python3
"""Source-bound A1 experimental full platform; behavioral primitives, not physical qualification."""
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--sv2v', required=True)
    ap.add_argument('--model-from', type=Path, help='Reuse a passing source-identical smoke model for one full roundtrip')
    args = ap.parse_args()
    out = args.out.resolve()
    if out.exists():
        ap.error('fresh evidence directory required')
    out.mkdir(parents=True)
    back = [ROOT / 'fpga/common/dynamic' / (n + '.sv') for n in
            ['behavioral_primitives', 'native_clock_gate', 'native_clock_drp', 'native_dynamic_clock_domain']]
    phy = ROOT / 'simulator/cdc/rtl8211f_pin_model.sv'
    tb = HERE / 'a1_dynamic_roundtrip_tb.sv'
    paths = sorted((ROOT / 'src/main/scala').rglob('*.scala'))
    paths += sorted((ROOT / 'src/main/resources').rglob('*.sv'))
    paths += [ROOT / 'src/test/scala/platform/CommonA1DynamicMain.scala',
              ROOT / 'src/test/scala/platform/CommonDynamicRoundtripMain.scala',
              HERE / 'a1_dynamic_roundtrip.S', HERE / 'i1_runtime_network.ld',
              Path(__file__), HERE / 'i1_msi_epoch_native.py', tb, phy, *back]
    hashes = lambda: {str(p.relative_to(ROOT)): base.sha(p) for p in paths}
    record = dict(status='RUNNING', source_sha256=hashes(), tools={}, cases=[],
                  experimental_A1_only=True, physical_qualified=False, board_verified=False,
                  scope='actual common A1/DDR/MMIO/CMU/epoch/network; behavioral MMCM and PHY; no UNISIM or STA')
    tools = {n: base.tool(v) for n, v in [('mill','mill'),('sv2v',args.sv2v),('iverilog','iverilog'),('vvp','vvp'),
             ('gcc','riscv64-unknown-elf-gcc'),('objcopy','riscv64-unknown-elf-objcopy'),('nm','riscv64-unknown-elf-nm')]}
    record['tools'].update(base.tool_hashes(tools))
    def run(cmd, name, seconds):
        rc, log = base.run(cmd, out, name, seconds, record)
        if rc:
            raise RuntimeError(name + ' failed: ' + log[-1500:])
        return log
    try:
        if args.model_from:
            model = args.model_from.resolve()
            old = json.loads((model / 'receipt.json').read_text())
            if old['status'] != 'PASS_A1_FULLCHAIN_SMOKE' or old['source_sha256'] != hashes():
                raise RuntimeError('passing source-identical smoke receipt required')
            for path, sha in old['model_artifacts'].items():
                if base.sha(Path(path)) != sha:
                    raise RuntimeError('model artifact drift: ' + path)
            if old['tools'] != record['tools']:
                raise RuntimeError('tool drift since smoke')
            record['model_artifacts'] = old['model_artifacts']
            record['guest_symbols'] = old['guest_symbols']
            record['first_words'] = old['first_words']
            record['reused_smoke_receipt_sha256'] = base.sha(model / 'receipt.json')
        else:
            model = out
            run([tools['gcc'], '-march=rv64ima_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany', '-mno-relax',
                 '-nostdlib', '-nostartfiles', '-Wl,--no-relax', '-T' + str(HERE / 'i1_runtime_network.ld'),
                 HERE / 'a1_dynamic_roundtrip.S', '-o', out / 'guest.elf'], 'guest-build', 60)
            run([tools['objcopy'], '-O', 'binary', out / 'guest.elf', out / 'guest.bin'], 'guest-binary', 60)
            symbols = run([tools['nm'], '-n', out / 'guest.elf'], 'guest-symbols', 60)
            record['guest_symbols'] = {name: int(address,16) for address, _, name in re.findall(
                r'^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$', symbols, re.M)}
            raw = (out / 'guest.bin').read_bytes()
            if len(raw) > 2048 or len(raw) % 4:
                raise RuntimeError('guest exceeds independently linked ROM section')
            raw = raw.ljust(32768 * 4, b'\0')
            words = [int.from_bytes(raw[n:n+4], 'little') for n in range(0,len(raw),4)]
            banks = [out / f'bank{i}.hex' for i in range(2)]
            for i, bank in enumerate(banks):
                bank.write_text(''.join(f'{v:08x}\n' for v in words[i::2]))
            record['first_words'] = words[:2]
            run([tools['mill'], '-i', 'IonSoC.test.runMain', 'platform.CommonA1DynamicMain', out / 'rtl', *banks], 'emit', 600)
            rtl = sorted((out / 'rtl').glob('*.sv'))
            definitions = ['-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1','-DENABLE_INITIAL_MEM_=1']
            run([tools['iverilog'], *definitions, '-E', '-o', out / 'preprocessed.sv', *rtl], 'preprocess', 180)
            original = (out / 'preprocessed.sv').read_text()
            reads = re.findall(r'\$readmemh\s*\(\s*"([^"]+)"', original)
            if reads != [str(p) for p in banks] or not original.count('$fatal'):
                raise RuntimeError('missing ROM binding or production assertions')
            lowered = run([tools['sv2v'], '--exclude=SeverityTask', out / 'preprocessed.sv'], 'lower', 180)
            for token in ('$fatal', '$error'):
                if original.count(token) != lowered.count(token):
                    raise RuntimeError('severity count changed: ' + token)
            record['severity_counts'] = {token: lowered.count(token) for token in ('$fatal','$error')}
            (out / 'lowered.v').write_text(lowered)
            run([tools['iverilog'], *definitions, '-s', 'dynamic_roundtrip_tb', '-o', out / 'test.vvp',
                 out / 'lowered.v', *back, phy, tb], 'compile', 180)
            artifacts = [*rtl, *banks, out / 'guest.elf', out / 'guest.bin', out / 'preprocessed.sv', out / 'lowered.v', out / 'test.vvp']
            record['model_artifacts'] = {str(p):base.sha(p) for p in artifacts}
        symbols = record['guest_symbols']; first = record['first_words']
        cmd = [tools['vvp'], '-i', model / 'test.vvp', f'+done_pc={symbols["guest_done"]:x}',
               f'+fail_pc={symbols["guest_fail"]:x}', f'+rom0_first={first[0]:x}', f'+rom1_first={first[1]:x}']
        if not args.model_from:
            cmd += ['+telemetry_smoke']
        log = run(cmd, 'roundtrip' if args.model_from else 'smoke', 600 if args.model_from else 300)
        expected = 'A1_ROUNDTRIP_PASS' if args.model_from else 'TELEMETRY_SMOKE_PASS'
        if expected not in log:
            raise RuntimeError('missing independent terminal banner')
        if hashes() != record['source_sha256']:
            raise RuntimeError('source drift during acceptance')
        for path, sha in record['model_artifacts'].items():
            if base.sha(Path(path)) != sha:
                raise RuntimeError('model artifact drift during acceptance')
        record['status'] = 'PASS_A1_FULLCHAIN_ROUNDTRIP' if args.model_from else 'PASS_A1_FULLCHAIN_SMOKE'
    except Exception as exc:
        record['status'] = 'FAIL'; record['error'] = str(exc)
        raise
    finally:
        (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')

if __name__ == '__main__':
    main()
