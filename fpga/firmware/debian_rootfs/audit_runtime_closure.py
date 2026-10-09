#!/usr/bin/env python3
"""Read-only packed-rootfs symlink and RV64 ELF closure audit; no guest execution."""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import struct

from audit_dinit_delivery import decode_newc, require, require_no_retired_tools

CRITICAL = ('/bin/sh', '/usr/bin/awk', '/usr/bin/nawk', '/usr/bin/mount',
    '/usr/sbin/modprobe', '/usr/bin/stty', '/usr/bin/grep', '/usr/bin/sleep',
    '/usr/bin/hostname', '/usr/sbin/dinit', '/usr/sbin/agetty', '/usr/bin/login',
    '/usr/bin/bash', '/etc/localtime', '/var/run', '/usr/lib/ssl/cert.pem',
    '/usr/lib/ssl/openssl.cnf')
LIBRARIES = ('usr/lib/riscv64-linux-gnu', 'lib/riscv64-linux-gnu', 'usr/lib', 'lib')
RUNTIME_LINKS = {'dev/fd': 'proc/self/fd', 'dev/stdin': 'proc/self/fd/0',
                 'dev/stdout': 'proc/self/fd/1', 'dev/stderr': 'proc/self/fd/2'}


def resolve(entries, name, *, allow_runtime=False):
    pending, resolved, links = deque(name.split('/')), [], 0
    while pending:
        part = pending.popleft()
        if not part or part == '.':
            continue
        if part == '..':
            require(bool(resolved), 'symlink escapes root: ' + name)
            resolved.pop()
            continue
        resolved.append(part)
        current = '/'.join(resolved)
        if current not in entries:
            full = '/'.join(resolved + list(pending))
            if allow_runtime and full in RUNTIME_LINKS.values():
                return full
            raise RuntimeError('missing packed target: ' + current + ' from ' + name)
        fields, body = entries[current]
        if stat.S_ISLNK(fields[1]):
            links += 1
            require(links <= 40, 'symlink cycle/depth: ' + name)
            target = body.decode()
            require(not target.startswith('/workspace/'), 'build-host link: ' + name)
            resolved.pop()
            if target.startswith('/'):
                resolved.clear()
            pending.extendleft(reversed(target.split('/')))
    return '/'.join(resolved)


def elf_dependencies(data):
    require(len(data) >= 64 and data[:6] == b'\x7fELF\x02\x01', 'not ELF64 little endian')
    kind, machine = struct.unpack_from('<HH', data, 16)
    require(machine == 243, 'non-RISC-V ELF in rootfs')
    if kind == 1:  # matched kernel modules are separately hashed by the delivery audit
        return None
    require(kind in (2, 3), 'unexpected runtime ELF type')
    require(struct.unpack_from('<I', data, 48)[0] & 6 == 4, 'runtime ELF is not LP64D')
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, count = struct.unpack_from('<HH', data, 54)
    require(phsize == 56 and phoff + count * phsize <= len(data), 'ELF program-header bounds')
    segments = [struct.unpack_from('<IIQQQQQQ', data, phoff + n * phsize) for n in range(count)]
    interpreter, dynamic = None, []
    for segment in segments:
        stype, _, offset, _, _, size, _, _ = segment
        require(offset + size <= len(data), 'ELF segment bounds')
        if stype == 3:
            interpreter = data[offset:offset + size].rstrip(b'\0').decode()
        if stype == 2:
            require(size % 16 == 0, 'ELF dynamic size')
            for pos in range(offset, offset + size, 16):
                tag, value = struct.unpack_from('<QQ', data, pos)
                if tag == 0:
                    break
                dynamic.append((tag, value))
    needed, search = [], []
    if dynamic:
        strings = dict(dynamic).get(5)
        strlen = dict(dynamic).get(10)
        require(strings is not None and strlen is not None, 'ELF missing dynamic strings')
        matches = [s for s in segments if s[0] == 1 and s[3] <= strings and strings + strlen <= s[3] + s[5]]
        require(len(matches) == 1, 'ELF dynamic string mapping')
        segment = matches[0]
        base = segment[2] + strings - segment[3]
        def string(offset):
            require(offset < strlen, 'ELF dynamic string offset')
            end = data.find(b'\0', base + offset, base + strlen)
            require(end >= 0, 'ELF unterminated dynamic string')
            return data[base + offset:end].decode()
        needed = [string(value) for tag, value in dynamic if tag == 1]
        search = [path for tag, value in dynamic if tag in (15, 29) for path in string(value).split(':')]
    return dict(interpreter=interpreter, needed=needed, search=search)


def audit(blob):
    entries, linked = decode_newc(blob)
    require_no_retired_tools(entries)
    require('usr/lib/valence/busybox' not in entries, 'unused custom BusyBox present')
    require(not any(p.startswith('.valence-build-tools') for p in entries), 'build helper shipped')
    links = 0
    for name, (fields, _) in entries.items():
        if stat.S_ISLNK(fields[1]):
            links += 1
            result = resolve(entries, name, allow_runtime=name in RUNTIME_LINKS)
            if name in RUNTIME_LINKS:
                require(result == RUNTIME_LINKS[name], 'changed runtime API link: ' + name)
    for name in CRITICAL:
        resolve(entries, name)
    uid = sorted({f[2] for f, _ in entries.values()})
    require(uid == [0], 'unexpected packed ownership')
    f, _ = entries['dev/console']
    require(stat.S_ISCHR(f[1]) and f[9:11] == [5, 1], 'bad console device metadata')
    def content(name):
        fields, body = entries[name]
        return body or linked.get((fields[7], fields[8], fields[0]), b'')
    closure, deps = {}, 0
    for name, (fields, body) in entries.items():
        if not stat.S_ISREG(fields[1]):
            continue
        body = body or linked.get((fields[7], fields[8], fields[0]), b'')
        if not body.startswith(b'\x7fELF'):
            continue
        row = elf_dependencies(body)
        if row is None:
            require(name.endswith('.ko'), 'non-module relocatable ELF shipped: ' + name)
            continue
        if row['interpreter']:
            interpreter = resolve(entries, row['interpreter'])
            require(content(interpreter).startswith(b'\x7fELF'), 'non-ELF runtime interpreter: ' + interpreter)
        origin = str(PurePosixPath(name).parent)
        paths = [p.replace('${ORIGIN}', origin).replace('$ORIGIN', origin).lstrip('/') for p in row['search']]
        dependencies = {}
        for needed in row['needed']:
            found = None
            for directory in paths + list(LIBRARIES):
                try:
                    target = resolve(entries, directory + '/' + needed)
                except RuntimeError:
                    continue
                if stat.S_ISREG(entries[target][0][1]):
                    require(content(target).startswith(b'\x7fELF'), 'non-ELF dependency: ' + target)
                    found = target
                    break
            require(found is not None, 'unresolved dependency: ' + name + ' -> ' + needed)
            dependencies[needed] = found
            deps += 1
        closure[name] = dict(interpreter=row['interpreter'], dependencies=dependencies)
    helper = entries['usr/local/libexec/valence-uart-irq-init'][1]
    return dict(status='packed_link_and_rv64_runtime_closure_passed_not_board_verified',
        archive_sha256=hashlib.sha256(blob).hexdigest(), archive_entries=len(entries),
        symlinks_audited=links, runtime_elfs_audited=len(closure), dynamic_dependencies_resolved=deps,
        all_file_uids=uid, file_gids=sorted({f[3] for f, _ in entries.values()}),
        dev_console='character 5:1', bootstrap_sha256=hashlib.sha256(helper).hexdigest(),
        critical_paths_resolved=list(CRITICAL), runtime_api_links=RUNTIME_LINKS,
        runtime_elf_closure=closure, board_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.archive.read_bytes())
    result['audit_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.receipt.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print('ROOTFS_RUNTIME_CLOSURE_PASS_NOT_BOARD_VERIFIED', result['runtime_elfs_audited'],
          result['dynamic_dependencies_resolved'], args.receipt)
