#!/usr/bin/env python3
"""Build pinned upstream OpenSBI and the PS-DDR S-mode acceptance image."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LOAD = 0x80000000
NEXT = 0x80200000
FDT = 0x8fe00000


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=ROOT / 'third_party/opensbi')
    ap.add_argument('--dtc', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    source, out = a.source.resolve(), a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'build'):
        ap.error('fresh output under this clone build/ required')
    lock = json.loads((HERE / 'source-lock.json').read_text())['opensbi']
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if revision != lock['commit'] or subprocess.check_output(
            ['git', 'status', '--porcelain', '--untracked-files=no'], cwd=source, text=True):
        ap.error('clean pinned OpenSBI v1.9 source required')
    out.mkdir(parents=True)
    record = dict(status='BUILDING', opensbi=lock, commands=[], board_tested=False, gsim_tested=False)

    def run(argv, log):
        argv = list(map(str, argv))
        record['commands'].append(dict(argv=argv, log=log))
        with (out / log).open('w') as stream:
            subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)

    try:
        dtb = out / 'valence-ps-ddr.dtb'
        run([a.dtc, '-I', 'dts', '-O', 'dtb', '-o', dtb, HERE / 'valence-ps-ddr.dts'], 'dtc.log')
        run(['riscv64-unknown-elf-gcc', '-march=rv64imac_zicsr_zifencei', '-mabi=lp64',
             '-mcmodel=medany', '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
             '-T', HERE / 'sbi-probe.ld', HERE / 'sbi-probe.S', '-o', out / 'sbi-probe.elf'], 'probe-build.log')
        run(['riscv64-unknown-elf-objcopy', '-O', 'binary', out / 'sbi-probe.elf',
             out / 'sbi-probe.bin'], 'probe-objcopy.log')
        # The config path is resolved from the upstream platform config directory.
        # No upstream file is patched; both variants get separate O= directories.
        config = os.path.relpath(HERE / 'defconfig', source / 'platform/generic/configs')
        for name, options in [('board', 0), ('gsim-quiet', 1)]:
            run(['make', '-j8', '-C', source, 'O=' + str(out / name), 'PLATFORM=generic',
                 'PLATFORM_DEFCONFIG=' + config, 'CROSS_COMPILE=riscv64-linux-gnu-',
                 'PLATFORM_RISCV_ISA=rv64imac_zicsr_zifencei', 'PLATFORM_RISCV_ABI=lp64',
                 'FW_TEXT_START=' + hex(LOAD), 'FW_JUMP=y', 'FW_DYNAMIC=n', 'FW_PAYLOAD=n',
                 'FW_JUMP_ADDR=' + hex(NEXT), 'FW_JUMP_FDT_ADDR=' + hex(FDT),
                 'FW_FDT_PATH=' + str(dtb), 'FW_FDT_PADDING=8192', 'REPRODUCIBLE=y',
                 'FW_OPTIONS=' + str(options)], name + '-build.log')
            fw = out / name / 'platform/generic/firmware/fw_jump.bin'
            elf = fw.with_suffix('.elf')
            symbols = {parts[2]: int(parts[0], 16) for line in subprocess.check_output(
                ['riscv64-linux-gnu-nm', elf], text=True).splitlines()
                if len(parts := line.split()) == 3}
            assert symbols['_fw_start'] == LOAD and symbols['_fw_end'] < NEXT
            embedded = symbols['fw_fdt_bin'] - LOAD
            firmware, probe = fw.read_bytes(), (out / 'sbi-probe.bin').read_bytes()
            assert firmware[embedded:embedded + dtb.stat().st_size] == dtb.read_bytes()
            combined = firmware + bytes(NEXT - LOAD - len(firmware)) + probe
            (out / (name + '-probe.bin')).write_bytes(combined)
        record.update(status='BUILT_NOT_BOOT_QUALIFIED', entry=hex(LOAD), next_entry=hex(NEXT),
                      next_mode='S', dtb_address=hex(FDT), ram_bytes=0x10000000,
                      uart_baud=460800, timebase_hz=300000000, hart_id=0xbeef,
                      gsim_variant='FW_OPTIONS=1 suppresses boot banner only; board FW_OPTIONS=0')
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['sources_sha256'] = {str(p.relative_to(ROOT)): sha(p) for p in HERE.iterdir() if p.is_file()}
        record['artifact_sha256'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
                                    if p.is_file() and (p.suffix in ['.bin', '.elf', '.dtb'] or p.name == '.config')}
        (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
    print(record['status'], out, flush=True)


if __name__ == '__main__':
    main()
