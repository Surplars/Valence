"""Install an exact private performance-tools receipt into a staged Debian root."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import struct

ALLOWED = tuple(PurePosixPath(p) for p in ('/usr/local/bin', '/usr/local/lib/valence-tools',
                                          '/usr/local/share/valence-tools'))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def install_tools(directory, root, installed_packages):
    directory, root = Path(directory).resolve(), Path(root).resolve()
    receipt = directory / 'tools-build.json'
    data = json.loads(receipt.read_text())
    if (data.get('schema') != 1 or data.get('stage') != 'tools_ready_host_qemu_only' or
        data.get('target') != dict(architecture='riscv64', isa='rv64gc', abi='lp64d')):
        raise RuntimeError('Unexpected performance tools contract')
    if set(data['required_debian_packages']) - set(installed_packages):
        raise RuntimeError('Missing required Debian performance-tool packages')
    plan, destinations = [], set()
    for entry in data['files']:
        relative, target = PurePosixPath(entry['path']), PurePosixPath(entry['destination'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise RuntimeError('Unsafe tools input path')
        source = directory.joinpath(*relative.parts)
        if source.is_symlink() or not source.is_file() or directory not in source.resolve().parents:
            raise RuntimeError('Tools input escapes its immutable bundle')
        if not target.is_absolute() or '..' in target.parts or not any(p in target.parents for p in ALLOWED):
            raise RuntimeError('Unsafe tools install destination')
        output = root.joinpath(*target.parts[1:])
        if root not in output.resolve().parents or output.exists() or output.is_symlink() or output in destinations:
            raise RuntimeError('Tools destination escapes root or overwrites an existing file')
        if source.stat().st_size != entry['bytes'] or digest(source) != entry['sha256']:
            raise RuntimeError('Performance tool content differs from receipt')
        mode = entry['mode']
        if mode not in ('0755', '0644'):
            raise RuntimeError('Unexpected tool permissions')
        kind, linkage = entry['kind'], entry['linkage']
        if kind == 'elf':
            header = source.read_bytes()[:64]
            if (len(header) != 64 or header[:6] != b'\x7fELF\x02\x01' or
                struct.unpack_from('<H',header,18)[0] != 243 or
                struct.unpack_from('<I',header,48)[0] & 6 != 4 or
                linkage != 'static' or entry.get('needed') != [] or mode != '0755'):
                raise RuntimeError('Tool must be declared static RV64 LP64D ELF')
            contents = source.read_bytes()
            phoff = struct.unpack_from('<Q', header, 32)[0]
            phsize, phnum = struct.unpack_from('<HH', header, 54)
            if phsize < 56 or not phnum or phoff + phsize * phnum > len(contents):
                raise RuntimeError('Malformed ELF program headers')
            if any(struct.unpack_from('<I',contents,phoff+i*phsize)[0] in (2,3) for i in range(phnum)):
                raise RuntimeError('Performance tool unexpectedly needs dynamic loading')

        elif kind == 'python':
            if linkage != 'python3-stdlib' or entry.get('needed') != [] or mode != '0755':
                raise RuntimeError('Unexpected Python tool runtime')
        elif kind not in ('license', 'document') or mode != '0644' or linkage != 'none' or entry.get('needed') != []:
            raise RuntimeError('Unknown performance tool type')
        destinations.add(output)
        plan.append((source, output, int(mode,8)))
    # All files and paths are checked before any filesystem mutation.
    for source, output, mode in plan:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output)
        output.chmod(mode)
    return dict(receipt_sha256=digest(receipt), files=data['files'],
                required_debian_packages=data['required_debian_packages'],
                clockmon_snapshot_profiles=data.get('clockmon_snapshot_profiles', {}),
                qualification='host/QEMU only; no SoC performance qualification')
