#!/usr/bin/env python3
"""Read-only proof that two ELF64 executables differ only in debug compression.

This tool neither links nor rewrites a binary. It fails closed on changed loaded
bytes (except the loader-unused e_shoff relocation), program headers, non-debug
sections, symbols, or decompressed DWARF. Use
only with a new uncompressed/compressed link pair; preserve both old proofs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib
import shutil
import subprocess

COMPRESSED = 0x800
ALLOC = 2
NOBITS = 8
MAX_DEBUG_BYTES = 128 * 1024 * 1024


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def portion(data, offset, size):
    require(0 <= offset <= len(data) and 0 <= size <= len(data) - offset, 'ELF range outside file')
    return data[offset:offset + size]


def decode_debug(data, flags, alignment):
    if not flags & COMPRESSED:
        require(len(data) <= MAX_DEBUG_BYTES, 'debug section exceeds bounded size')
        return data, alignment
    require(len(data) >= 24, 'short ELF64 compression header')
    kind, reserved, size, original_alignment = struct.unpack_from('<IIQQ', data)
    require(kind == 1 and reserved == 0 and size <= MAX_DEBUG_BYTES, 'unsupported debug compression header')
    require(original_alignment == 0 or original_alignment & (original_alignment - 1) == 0,
            'invalid original debug alignment')
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(data[24:], size + 1)
    require(len(decoded) == size and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
            'debug decompression length/trailer mismatch')
    return decoded, original_alignment


def parse(data):
    require(len(data) >= 64 and data[:7] == b'\x7fELF\x02\x01\x01', 'requires ELF64 little-endian version1')
    h = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    _, typ, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstr = h
    require(typ in (2, 3) and machine == 62 and version == 1 and ehsize == 64,
            'requires an x86-64 executable/shared ELF')
    require(phsize == 56 and 0 < phnum < 128 and shsize == 64 and 0 < shnum < 4096 and 0 < shstr < shnum,
            'unsupported ELF header geometry')
    phbytes = portion(data, phoff, phsize * phnum)
    programs = [struct.unpack_from('<IIQQQQQQ', phbytes, i * phsize) for i in range(phnum)]
    loaded = []
    for p in programs:
        if p[0] == 1:
            require(p[5] <= p[6], 'load file size exceeds memory size')
            segment = bytearray(portion(data, p[2], p[5]))
            # The section table follows the nonloaded debug data. Its location
            # changes during compression and is encoded in the ELF header,
            # which usually belongs to the first PT_LOAD segment. e_shoff is
            # not an instruction/data/symbol change; all other bytes remain exact.
            for offset in range(max(p[2], 40), min(p[2] + p[5], 48)):
                segment[offset - p[2]] = 0
            loaded.append(sha(segment))
    require(loaded, 'ELF has no loadable segments')
    shbytes = portion(data, shoff, shsize * shnum)
    headers = [struct.unpack_from('<IIQQQQIIQQ', shbytes, i * shsize) for i in range(shnum)]
    string_header = headers[shstr]
    names = portion(data, string_header[4], string_header[5])
    sections = {}
    for index, s in enumerate(headers):
        name_offset, section_type, section_flags, address, offset, size, link, info, alignment, entsize = s
        require(name_offset < len(names), 'invalid section name offset')
        end = names.find(b'\0', name_offset)
        require(end >= 0, 'unterminated section name')
        name = names[name_offset:end].decode('ascii')
        require(name not in sections, 'duplicate ELF section name')
        contents = b'' if section_type == NOBITS else portion(data, offset, size)
        sections[name] = {'index': index, 'type': section_type, 'flags': section_flags,
            'address': address, 'size': size, 'link': link, 'info': info,
            'alignment': alignment, 'entsize': entsize, 'data': contents}
    return {'header_identity': [data[:16].hex(), typ, machine, version, entry, flags, ehsize,
                               phoff, phsize, phnum, shsize, shnum, shstr],
            'program_headers': programs, 'loaded_sha256': loaded, 'sections': sections,
            'sha256': sha(data), 'bytes': len(data)}


def compare(before, after):
    require(before['header_identity'] == after['header_identity'], 'executable ELF header identity changed')
    require(before['program_headers'] == after['program_headers'], 'program headers changed')
    require(before['loaded_sha256'] == after['loaded_sha256'], 'loadable executable bytes changed')
    a, b = before['sections'], after['sections']
    require(set(a) == set(b), 'section inventory changed')
    compressed = []
    for name in a:
        old, new = a[name], b[name]
        require({k: old[k] for k in ('index', 'type', 'address', 'link', 'info', 'entsize')} ==
                {k: new[k] for k in ('index', 'type', 'address', 'link', 'info', 'entsize')},
                'section semantics changed: ' + name)
        if name.startswith('.debug_'):
            require(not old['flags'] & (ALLOC | COMPRESSED) and not new['flags'] & ALLOC,
                    'debug section must be unloaded and initially uncompressed: ' + name)
            require(old['flags'] == new['flags'] & ~COMPRESSED, 'debug flags changed: ' + name)
            old_data, old_align = decode_debug(old['data'], old['flags'], old['alignment'])
            new_data, new_align = decode_debug(new['data'], new['flags'], new['alignment'])
            require(old_data == new_data and old_align == new_align, 'decompressed DWARF changed: ' + name)
            if new['flags'] & COMPRESSED:
                compressed.append({'section': name, 'before_bytes': old['size'], 'after_bytes': new['size'],
                                   'uncompressed_sha256': sha(old_data)})
        else:
            require(old == new, 'non-debug section changed: ' + name)
    require(compressed, 'no debug section was compressed')
    for symbol in (b'__asan_init\0', b'__ubsan_handle_'):
        require(any(symbol in item['data'] for name, item in b.items() if name in ('.strtab', '.dynstr')),
                'missing sanitizer runtime symbols')
    require('.symtab' in a and '.debug_info' in a and '.debug_line' in a, 'symbol/DWARF information missing')
    return {'status': 'PASS_DEBUG_COMPRESSION_ONLY',
            'before_sha256': before['sha256'], 'after_sha256': after['sha256'],
            'before_bytes': before['bytes'], 'after_bytes': after['bytes'],
            'load_segments': len(before['loaded_sha256']), 'compressed_sections': compressed,
            'allowed_non_debug_metadata_change': 'ELF e_shoff and nonloaded section file offsets only',
            'limits': ['Read-only byte equivalence proof, not a new execution result.',
                       'Symbol tables and decompressed DWARF are unchanged; debugger/symbolizer runtime remains a separate check.']}


def installed_tools():
    result = {}
    for name in ('objcopy', 'nm', 'addr2line'):
        found = shutil.which(name)
        require(found is not None, 'missing installed debug tool: ' + name)
        path = Path(found).resolve()
        version = subprocess.check_output([str(path), '--version'], text=True).splitlines()[0]
        result[name] = {'path': str(path), 'sha256': sha(path.read_bytes()), 'version': version}
    return result


def symbol_proof(before, after, tools):
    commands = []
    def run(command):
        p = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        commands.append({'command': command, 'exit': p.returncode, 'output': p.stdout})
        require(p.returncode == 0, 'debug symbol tool failed: ' + p.stdout)
        return p.stdout
    nm = run([tools['nm']['path'], '--defined-only', str(before)])
    rows = [r.split() for r in nm.splitlines() if len(r.split()) == 3 and r.split()[2] == 'main']
    require(len(rows) == 1 and rows[0][1] in ('T', 't'), 'unique main symbol missing')
    address = '0x' + rows[0][0]
    before_line = run([tools['addr2line']['path'], '-e', str(before), '-f', '-C', address])
    after_line = run([tools['addr2line']['path'], '-e', str(after), '-f', '-C', address])
    require(before_line == after_line and before_line.startswith('main\n') and '??' not in before_line,
            'compressed executable lost main source symbolization')
    return {'address': address, 'source': before_line}, commands


def compress_new(before, after, receipt):
    """Compress only a newly linked input into two fresh, separately retained outputs."""
    before, after, receipt = (Path(x).resolve() for x in (before, after, receipt))
    require(before.is_file() and not after.exists() and not receipt.exists(), 'compression requires fresh outputs')
    require(len({before, after, receipt}) == 3, 'compression input/output aliases')
    original = before.read_bytes()
    tools = installed_tools()
    command = [tools['objcopy']['path'], '--compress-debug-sections=zlib-gabi', str(before), str(after)]
    p = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    require(p.returncode == 0, 'debug compression failed: ' + p.stdout)
    require(before.read_bytes() == original, 'compression modified input')
    result = compare(parse(original), parse(after.read_bytes()))
    symbols, commands = symbol_proof(before, after, tools)
    require(installed_tools() == tools, 'debug tool executable/version changed')
    result.update(schema='valence-new-debug-compression-v1', tool_sha256=sha(Path(__file__).read_bytes()),
                  before_path=str(before), after_path=str(after), tools=tools, symbolization=symbols,
                  commands=[{'command': command, 'exit': p.returncode, 'output': p.stdout}, *commands])
    receipt.write_text(json.dumps(result, indent=2) + '\n')
    return result


def validate_compression_receipt(before, after, receipt):
    before, after, receipt = (Path(x).resolve() for x in (before, after, receipt))
    proof = json.loads(receipt.read_text())
    expected = compare(parse(before.read_bytes()), parse(after.read_bytes()))
    require(proof.get('schema') == 'valence-new-debug-compression-v1' and
            proof.get('tool_sha256') == sha(Path(__file__).read_bytes()), 'compression schema/helper drift')
    require(proof.get('before_path') == str(before) and proof.get('after_path') == str(after), 'compression path drift')
    for key, value in expected.items():
        require(proof.get(key) == value, 'compression equivalence proof drift: ' + key)
    tools = installed_tools()
    require(proof.get('tools') == tools, 'compression installed tool binding drift')
    symbols, commands = symbol_proof(before, after, tools)
    require(proof.get('symbolization') == symbols, 'compression symbolization proof drift')
    compression = {'command': [tools['objcopy']['path'], '--compress-debug-sections=zlib-gabi', str(before), str(after)],
                   'exit': 0, 'output': ''}
    require(proof.get('commands') == [compression, *commands], 'compression command evidence drift')
    require(set(proof) == set(expected) | {'schema', 'tool_sha256', 'before_path', 'after_path', 'tools',
                                         'symbolization', 'commands'}, 'compression receipt inventory drift')
    return proof


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before', required=True, type=Path)
    ap.add_argument('--after', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    require(not args.out.exists(), 'refusing existing receipt')
    result = compare(parse(args.before.read_bytes()), parse(args.after.read_bytes()))
    result['tool_sha256'] = sha(Path(__file__).read_bytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'])


if __name__ == '__main__':
    main()
