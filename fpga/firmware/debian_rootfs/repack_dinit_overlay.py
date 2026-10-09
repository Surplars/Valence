#!/usr/bin/env python3
"""Repack three reviewed UART startup files into a fresh cpio, without a tree copy."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import stat
import subprocess

from build_rootfs import sha, validate_output
from audit_dinit_delivery import decode_newc, require

HERE = Path(__file__).resolve().parent
REPLACEMENTS = {
    'usr/local/libexec/valence-uart-irq-init': 'dinit/uart-irq-init',
    'usr/local/sbin/boot-diagnose': 'dinit/boot-diagnose',
    'usr/local/libexec/valence-dinit-ready': 'dinit/ready',
}


def overlay(blob, replacements):
    entries, _ = decode_newc(blob)
    require(set(replacements) <= entries.keys(), 'overlay targets must already exist')
    for name in replacements:
        f = entries[name][0]
        require(stat.S_ISREG(f[1]) and f[4] == 1, 'overlay only regular single-link helpers')
    output, offset, changed = bytearray(), 0, []
    while offset + 110 <= len(blob):
        require(blob[offset:offset + 6] == b'070701', 'invalid cpio overlay header')
        fields = [int(blob[offset + 6 + i*8:offset + 14 + i*8], 16) for i in range(13)]
        name_end = offset + 110 + fields[11]
        name = blob[offset + 110:name_end - 1].decode().removeprefix('./')
        body = (name_end + 3) & ~3
        end = (body + fields[6] + 3) & ~3
        if name == 'TRAILER!!!':
            output.extend(blob[offset:end])
            output.extend(bytes((-len(output)) % 512))
            break
        if name in replacements:
            data = replacements[name]
            fields[6] = len(data)
            output.extend(b'070701' + b''.join(f'{value:08x}'.encode() for value in fields))
            output.extend(blob[offset + 110:body])
            output.extend(data)
            output.extend(bytes((-len(output)) % 4))
            changed.append(name)
        else:
            output.extend(blob[offset:end])
        offset = end
    require(set(changed) == set(replacements), 'not all overlay entries replaced')
    result = bytes(output)
    after, _ = decode_newc(result)
    require(after.keys() == entries.keys(), 'overlay changed the archive entry set')
    for name, (old_fields, old_data) in entries.items():
        new_fields, new_data = after[name]
        if name in replacements:
            require(new_data == replacements[name], 'overlay content mismatch: ' + name)
            old_fields = old_fields.copy(); old_fields[6] = len(new_data)
        else:
            require(new_data == old_data, 'unrelated archive data changed: ' + name)
        require(new_fields == old_fields, 'archive metadata changed: ' + name)
    return result, sum(len(replacements[name]) - len(entries[name][1]) for name in replacements)


def repack(source, output):
    source, output = validate_output(source), validate_output(output)
    record_path = source / 'rootfs-build.json'
    original = json.loads(record_path.read_text())
    require(original.get('stage') == 'packed' and original.get('init_system') == 'dinit'
            and original.get('console_profile') == 'uart-irq', 'expected completed Dinit UART rootfs')
    original_archive = source / original['archive']['path']
    require(original_archive.parent.resolve() == source and sha(original_archive) == original['archive']['sha256'],
            'source archive path or hash mismatch')
    replacements = {name: (HERE / relative).read_bytes() for name, relative in REPLACEMENTS.items()}
    blob, delta = overlay(original_archive.read_bytes(), replacements)
    output.mkdir(parents=True, exist_ok=False)
    archive = output / 'debian13-riscv64-dinit-vl100.cpio'
    archive.write_bytes(blob)
    compressed = archive.with_suffix('.cpio.lz4')
    with compressed.open('xb') as stream:
        subprocess.run(['lz4', '-l', '-9', '-c', archive], stdout=stream, check=True)
    require(subprocess.check_output(['lz4', '-d', '-c', compressed]) == blob, 'LZ4 overlay round-trip mismatch')
    packages = source / 'packages.tsv'
    require(sha(packages) == original['packages_sha256'], 'source package identity changed')
    (output / 'packages.tsv').write_bytes(packages.read_bytes())
    record = copy.deepcopy(original)
    record.update(stage='packed', board_verified=False,
        archive=dict(path=archive.name, bytes=archive.stat().st_size, sha256=sha(archive)),
        compressed=dict(path=compressed.name, bytes=compressed.stat().st_size, sha256=sha(compressed)),
        rootfs_file_bytes=original['rootfs_file_bytes'] + delta,
        uart_readiness_gate=False,
        uart_warning_continues_dinit=True, uart_irq_runtime_verified=False,
        overlay=dict(source_record_sha256=sha(record_path), source_archive_sha256=sha(original_archive),
                     replaced_entries=list(REPLACEMENTS), unrelated_entries_and_metadata_unchanged=True,
                     source=str(source), no_package_install=True, no_rootfs_tree_copy=True))
    for relative in REPLACEMENTS.values():
        record['sources'][relative] = sha(HERE / relative)
    record['sources'][Path(__file__).name] = sha(Path(__file__))
    record['checks'] = 'preserved signed-seed package/module closure; three helper overlay + LZ4 round-trip; not board execution'
    (output / 'rootfs-build.json').write_text(json.dumps(record, indent=2) + '\n')
    print('DINIT_UART_V4_OVERLAY_PACKED_NOT_BOARD_VERIFIED', archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-out', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repack(args.source_out, args.out)
