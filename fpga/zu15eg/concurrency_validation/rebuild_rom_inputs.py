#!/usr/bin/env python3
"""Recover exact ROM bytes, then assemble fresh BMG with hash-proven fixed IP.

No installation, Vivado launch, bitstream or hardware access. Generated DCPs have
fresh provenance; they are never asserted to match the unavailable historical DCP.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from stage_local_candidate import checked_file, sha
from verify_dev_sources import verify_dev_sources

HERE = Path(__file__).resolve().parent
FIXED_FOLDERS = ('mig', *('ip-build/' + tree + '/sources_1/ip/' + name
    for tree in ('board_ip.srcs', 'board_ip.gen')
    for name in ('clk_wiz_ddr', 'axi_clock_converter_ddr')))


def fixed_hashes(expected):
    return {p: h for p, h in expected['sha256'].items()
            if any(p.startswith(folder + '/') for folder in FIXED_FOLDERS)}


def verify_fixed(root, expected):
    required = fixed_hashes(expected)
    if not required:
        raise RuntimeError('empty fixed-IP contract')
    actual = set()
    for folder in FIXED_FOLDERS:
        directory = root / folder
        if not directory.is_dir() or directory.is_symlink():
            raise RuntimeError('missing/linked fixed-IP directory: ' + folder)
        for path in directory.rglob('*'):
            if path.is_symlink():
                raise RuntimeError('linked fixed-IP input: ' + str(path))
            if path.is_file(): actual.add(path.relative_to(root).as_posix())
    if actual != set(required):
        raise RuntimeError('fixed-IP inventory mismatch')
    for name, digest in required.items(): checked_file(root, name, digest)
    return required


def prepare_rom(binary, output, expected):
    if binary.is_symlink():
        raise RuntimeError("linked ROM input")
    binary = binary.resolve()
    if not binary.is_file() or sha(binary) != expected['sha256']['firmware/bootrom.bin']:
        raise RuntimeError('recovered ROM does not match exact historical binary')
    if output.exists():
        raise RuntimeError('preserve existing files; choose a fresh ROM output root')
    data = binary.read_bytes()
    if len(data) != expected['rom_word_audit']['binaryBytes']:
        raise RuntimeError('unexpected ROM size')
    words = [int.from_bytes(data.ljust(131072, b'\0')[n:n + 4], 'little') for n in range(0, 131072, 4)]
    coe = ('memory_initialization_radix=16;\nmemory_initialization_vector=\n' +
           ',\n'.join(f'{word:08x}' for word in words) + ';\n').encode('ascii')
    if hashlib.sha256(coe).hexdigest() != expected['sha256']['firmware/bootrom.coe']:
        raise RuntimeError('reconstructed COE differs from historical word image')
    (output / 'firmware').mkdir(parents=True)
    (output / 'firmware/bootrom.bin').write_bytes(data)
    (output / 'firmware/bootrom.coe').write_bytes(coe)
    (output / 'rom-recovery.json').write_text(json.dumps({'status': 'EXACT_ROM_RECOVERED_BMG_NOT_BUILT',
        'binary_sha256': sha(output / 'firmware/bootrom.bin'), 'binary_bytes': len(data),
        'coe_sha256': sha(output / 'firmware/bootrom.coe'), 'historical_dcp_reused': False}, indent=2)+'\n')


def assemble(args, expected, contract):
    root, repo, fixed, rtl = (p.resolve() for p in (args.output, args.repo, args.fixed, args.rtl))
    if not root.is_dir() or any((root / p).exists() for p in ('rtl', 'board', 'scripts', 'mig', 'inputs.json')):
        raise RuntimeError('use only the fresh recovered-ROM/BMG root; preserve any existing assembled candidate')
    binding = verify_dev_sources(repo, args.commit, HERE / 'integrated-source-sha256.json')
    required = verify_fixed(fixed, expected)
    for name in ('firmware/bootrom.bin', 'firmware/bootrom.coe'):
        checked_file(root, name, expected['sha256'][name])
    variant = contract['variants'][args.variant]
    if {p.name for p in rtl.glob('*.sv')} != set(variant['rtl_sha256']):
        raise RuntimeError('RTL inventory differs from selected variant')
    for name, digest in variant['rtl_sha256'].items(): checked_file(rtl, name, digest)
    sources = {}
    import subprocess
    for target, entry in contract['source_map'].items():
        source = checked_file(repo, entry['repo_path'], entry['sha256'])
        blob = subprocess.check_output(['git', '-C', str(repo), 'show', args.commit + ':' + entry['repo_path']])
        if hashlib.sha256(blob).hexdigest() != entry['sha256']:
            raise RuntimeError('committed board/script differs: ' + entry['repo_path'])
        sources[target] = source
    # No old BMG is read/copied. Audit the newly synthesized MIF/DCP against
    # all 32768 words of the exact recovered binary, including zero padding.
    audit_name = "fpga/firmware/audit_bootrom.py"
    audit_hash = "9592524dee734b4317b2e010bd9c4d9530a0c0d8de6f29fe18a810c3e5502c0e"
    checked_file(repo, audit_name, audit_hash)
    audit_blob = subprocess.check_output(["git", "-C", str(repo), "show", args.commit + ":" + audit_name])
    if hashlib.sha256(audit_blob).hexdigest() != audit_hash:
        raise RuntimeError("committed ROM auditor differs")
    sys.path.insert(0, str(repo / 'fpga/firmware'))
    from audit_bootrom import audit
    xci = root / 'ip-build/board_ip.srcs/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.xci'
    if xci.is_symlink() or not xci.is_file() or xci.stat().st_size == 0:
        raise RuntimeError('missing fresh BMG XCI')
    rom = root / 'ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0'
    rom_audit = audit(root / 'firmware/bootrom.bin', rom / 'blk_mem_gen_0.mif', rom / 'blk_mem_gen_0.dcp', 'menu')
    for name in required:
        if (root / name).exists(): raise RuntimeError('refuse to overwrite generated/fixed input: ' + name)
    for name, digest in required.items():
        target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixed / name, target); checked_file(root, name, digest)
    for target, source in sources.items():
        dest = root / target; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, dest)
        if sha(dest) != sha(source): raise RuntimeError('source copy changed: ' + target)
    (root / 'rtl').mkdir()
    for name, digest in variant['rtl_sha256'].items():
        shutil.copy2(rtl / name, root / 'rtl' / name); checked_file(root / 'rtl', name, digest)
    inventory = {}
    for folder in ('rtl', 'board', 'scripts', 'firmware', 'mig', 'ip-build/board_ip.srcs', 'ip-build/board_ip.gen'):
        for p in sorted((root / folder).rglob('*')):
            if p.is_symlink(): raise RuntimeError('linked generated input: ' + str(p))
            if p.is_file(): inventory[p.relative_to(root).as_posix()] = sha(p)
    state = {'status': 'STAGED_FRESH_BMG_EXACT_ROM_NOT_IMPLEMENTED', 'variant': args.variant,
        'source_binding': binding, 'parameters_after_output': variant['parameters_after_output'],
        'cpu_precheck': variant['cpu_precheck'], 'fixed_ip_files_reused_by_exact_hash': len(required),
        'fixed_ip_root': str(fixed), 'rom_word_audit': rom_audit, 'historical_rom_binary_reproduced': True,
        'historical_rom_dcp_reused': False, 'cpu_checkpoint_reused': False, 'bit_generated': False,
        'board_verified': False, 'routed_timing_verified': False, 'candidate_sha256': inventory,
        'limits': ['Fresh BMG DCP hash is current provenance, not historical DCP identity.',
                   'Native build must still verify IP config, clocks, ROM INIT and physical timing.']}
    (root / 'inputs.json').write_text(json.dumps(state, indent=2)+'\n')
    print(json.dumps({'status': state['status'], 'fixed_ip_files': len(required),
                      'rom_sha256': rom_audit['binarySha256'], 'fresh_rom_dcp_sha256': rom_audit['romDcpSha256']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare-rom'); prep.add_argument('--binary', type=Path, required=True)
    prep.add_argument('--output', type=Path, required=True)
    fixed = commands.add_parser('verify-fixed'); fixed.add_argument('--fixed', type=Path, required=True)
    final = commands.add_parser('assemble')
    for flag in ('output', 'repo', 'fixed', 'rtl'): final.add_argument('--' + flag, type=Path, required=True)
    final.add_argument('--commit', required=True)
    final.add_argument('--variant', choices=('baseline', 'resource', 'integrated-off', 'integrated-on'), required=True)
    args = parser.parse_args()
    expected = json.loads((HERE / 'expected-local-inputs.json').read_text())
    if args.command == 'prepare-rom':
        prepare_rom(args.binary, args.output.resolve(), expected)
        print('PASS_EXACT_ROM_RECOVERY; run existing build_netboot_rom.tcl locally in this fresh root next')
    elif args.command == 'verify-fixed':
        print(json.dumps({'status': 'PASS_FIXED_IP_HASHES_ONLY', 'files': len(verify_fixed(args.fixed.resolve(), expected))}))
    else: assemble(args, expected, json.loads((HERE / 'EXPORT-RECEIPT.json').read_text()))


if __name__ == '__main__':
    main()
