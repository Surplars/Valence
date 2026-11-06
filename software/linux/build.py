#!/usr/bin/env python3
"""Build the user's clean Linux tree out of tree, with built-in RISC-V KVM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=Path('/home/openion/linux'))
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--firmware', type=Path, required=True, help='qualified board fw_jump.bin')
    a = ap.parse_args()
    source, out = a.source.resolve(), a.output.resolve()
    assert out.is_relative_to(ROOT / 'build') and not out.exists()
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    out.mkdir(parents=True)
    kernel = out / 'linux'
    record = dict(status='BUILDING', linux_revision=revision, commands=[], board_tested=False)

    def run(argv, name):
        argv = list(map(str, argv))
        record['commands'].append(dict(argv=argv, log=name))
        with (out / name).open('w') as stream:
            subprocess.run(argv, cwd=source, stdout=stream, stderr=subprocess.STDOUT, check=True)

    try:
        run(['riscv64-linux-gnu-gcc', '-march=rv64imac_zicsr_zifencei', '-mabi=lp64',
             '-nostdlib', '-nostartfiles', '-static', '-no-pie', '-Wl,--build-id=none',
             '-Wl,-Ttext=0x80000000', HERE / 'kvm-guest.S', '-o', out / 'kvm-guest.elf'], 'guest-build.log')
        run(['riscv64-linux-gnu-objcopy', '-O', 'binary', '-j', '.text', out / 'kvm-guest.elf',
             out / 'kvm-guest.bin'], 'guest-objcopy.log')
        guest = (out / 'kvm-guest.bin').read_bytes()
        (out / 'kvm-guest.h').write_text('static const unsigned char guest_code[] = {' +
            ','.join(hex(v) for v in guest) + '};\n')
        run(['riscv64-linux-gnu-gcc', '-march=rv64gc', '-mabi=lp64d', '-O2', '-static',
             '-Wall', '-Wextra', '-Werror', '-I' + str(out), HERE / 'init.c', '-o', out / 'init'], 'init-build.log')
        initramfs = out / 'initramfs.list'
        initramfs.write_text('dir /dev 755 0 0\nnod /dev/console 600 0 0 c 5 1\n' +
            'dir /proc 755 0 0\ndir /sys 755 0 0\ndir /tmp 1777 0 0\n' +
            'file /init ' + str(out / 'init') + ' 755 0 0\n')
        make = ['make', '-C', source, 'O=' + str(kernel), 'ARCH=riscv', 'CROSS_COMPILE=riscv64-linux-gnu-']
        run(make + ['tinyconfig'], 'config-base.log')
        enable = ['NONPORTABLE', 'PRINTK', 'TTY', 'SERIAL_8250', 'SERIAL_8250_CONSOLE',
            'SERIAL_OF_PLATFORM', 'SERIAL_EARLYCON', 'SERIAL_EARLYCON_RISCV_SBI',
            'BLK_DEV_INITRD', 'BINFMT_ELF', 'DEVTMPFS', 'PROC_FS', 'SYSFS', 'TMPFS',
            'MULTIUSER', 'FUTEX', 'POSIX_TIMERS', 'FPU', 'RISCV_ISA_C', 'RISCV_ISA_V',
            'RISCV_ISA_V_DEFAULT_ENABLE', 'VIRTUALIZATION', 'KVM', 'SIFIVE_PLIC',
            'RD_GZIP', 'INITRAMFS_COMPRESSION_GZIP', 'IKCONFIG', 'IKCONFIG_PROC',
            'CC_OPTIMIZE_FOR_PERFORMANCE']
        disable = ['SMP', 'RISCV_BOOT_SPINWAIT', 'EFI', 'VT', 'DUMMY_CONSOLE',
            'CMDLINE_FORCE', 'INITRAMFS_COMPRESSION_NONE', 'CC_OPTIMIZE_FOR_SIZE']
        edit = [source / 'scripts/config', '--file', kernel / '.config']
        edit += [v for item in enable for v in ['--enable', item]]
        edit += [v for item in disable for v in ['--disable', item]]
        edit += ['--set-val', 'SERIAL_8250_NR_UARTS', '1', '--set-val', 'SERIAL_8250_RUNTIME_UARTS', '1',
                 '--set-str', 'INITRAMFS_SOURCE', str(initramfs), '--set-str', 'LOCALVERSION', '-valence-i1']
        run(edit, 'config-edit.log')
        run(make + ['olddefconfig'], 'config-final.log')
        config = (kernel / '.config').read_text().splitlines()
        for name in ['64BIT', 'MMU', 'RISCV_SBI', 'KVM', 'FPU', 'RISCV_ISA_V', 'SIFIVE_PLIC', 'SERIAL_8250_CONSOLE']:
            assert 'CONFIG_' + name + '=y' in config, name
        assert 'CONFIG_RISCV_BOOT_SPINWAIT=y' not in config
        run(make + ['-j8', 'Image'], 'kernel-build.log')
        image = (kernel / 'arch/riscv/boot/Image').read_bytes()
        assert image[0x30:0x38] == b'RISCV\0\0\0'
        offset, runtime = struct.unpack_from('<QQ', image, 8)
        assert offset == 0x200000 and 0x80200000 + runtime < 0x8fe00000
        firmware = a.firmware.read_bytes()
        assert len(firmware) < 0x200000
        (out / 'opensbi-linux.bin').write_bytes(firmware + bytes(0x200000 - len(firmware)) + image)
        record.update(status='BUILT_NOT_BOOT_QUALIFIED', kernel_runtime_bytes=runtime,
            initramfs='small diagnostic PID1 and a real KVM VS guest MMIO probe',
            final_rootfs='Debian 13 riscv64, not included in this diagnostic image',
            kvm_built_in=True, isa='rv64gc + H/V detected from DT',
            firmware_sha256=sha(a.firmware), config_sha256=sha(kernel / '.config'),
            image_sha256=sha(kernel / 'arch/riscv/boot/Image'), combined_sha256=sha(out / 'opensbi-linux.bin'))
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['source_sha256'] = {str(p.relative_to(ROOT)): sha(p) for p in HERE.iterdir() if p.is_file()}
        (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
    print(record['status'], out, flush=True)

if __name__ == '__main__':
    main()
