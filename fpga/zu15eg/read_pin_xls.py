#!/usr/bin/env python3
"""Read BIFF8 pin tables without Excel or an installed legacy-XLS dependency.

Read-only, intentionally limited to plain BIFF8 cell values. Reject mini-stream
workbooks, formulas and unsupported SST flags rather than silently guessing.
Output includes worksheet/cell addresses and the original file hash.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path


def u32(data, offset=0):
    return struct.unpack_from('<I', data, offset)[0]


def workbook_stream(data):
    assert data[:8] == bytes.fromhex('d0cf11e0a1b11ae1'), 'Not an OLE XLS'
    sector_size = 1 << struct.unpack_from('<H', data, 30)[0]
    assert sector_size in (512, 4096)
    def sector(index):
        start = (index + 1) * sector_size
        assert start + sector_size <= len(data), 'Invalid sector'
        return data[start:start + sector_size]
    difat = list(struct.unpack_from('<109I', data, 76))
    next_difat, count = u32(data, 68), u32(data, 72)
    for _ in range(count):
        block = sector(next_difat)
        entries = struct.unpack('<%dI' % (sector_size // 4), block)
        difat.extend(entries[:-1])
        next_difat = entries[-1]
    fat = []
    for index in [v for v in difat if v < 0xfffffffa][:u32(data, 44)]:
        fat.extend(struct.unpack('<%dI' % (sector_size // 4), sector(index)))
    def chain(index):
        blocks, visited = [], set()
        while index != 0xfffffffe:
            assert index < len(fat) and index not in visited, 'Invalid/cyclic FAT'
            visited.add(index)
            blocks.append(sector(index))
            index = fat[index]
        return b''.join(blocks)
    directory = chain(u32(data, 48))
    for offset in range(0, len(directory), 128):
        entry = directory[offset:offset + 128]
        size = struct.unpack_from('<H', entry, 64)[0]
        if not size:
            continue
        name = entry[:size - 2].decode('utf-16le')
        if name in ('Workbook', 'Book'):
            length = struct.unpack_from('<Q', entry, 120)[0]
            assert length >= u32(data, 56), 'Mini-stream workbook unsupported'
            return chain(u32(entry, 116))[:length]
    raise ValueError('Workbook stream missing')


def records(data):
    offset = 0
    while offset + 4 <= len(data):
        kind, length = struct.unpack_from('<HH', data, offset)
        yield offset, kind, data[offset + 4:offset + 4 + length]
        offset += 4 + length


class SstCursor:
    def __init__(self, parts):
        self.parts, self.part, self.offset = parts, 0, 0

    def advance(self):
        self.part += 1
        self.offset = 0
        assert self.part < len(self.parts), 'Truncated SST'

    def take(self, count):
        result = b''
        while count:
            if self.offset == len(self.parts[self.part]):
                self.advance()
            amount = min(count, len(self.parts[self.part]) - self.offset)
            result += self.parts[self.part][self.offset:self.offset + amount]
            self.offset += amount
            count -= amount
        return result

    def text(self):
        count, flags = struct.unpack('<HB', self.take(3))
        assert flags & ~0x0d == 0, 'Unsupported SST flags'
        rich = struct.unpack('<H', self.take(2))[0] if flags & 8 else 0
        extended = u32(self.take(4)) if flags & 4 else 0
        wide, result = bool(flags & 1), ''
        while count:
            if self.offset == len(self.parts[self.part]):
                self.advance()
                continuation = self.take(1)[0]
                assert continuation in (0, 1)
                wide = bool(continuation)
            width = 2 if wide else 1
            amount = min(count, (len(self.parts[self.part]) - self.offset) // width)
            assert amount, 'Split UTF16 character unsupported'
            result += self.take(amount * width).decode('utf-16le' if wide else 'latin1')
            count -= amount
        self.take(rich * 4 + extended)
        return result


def cell_name(row, col):
    column = ''
    col += 1
    while col:
        col, tail = divmod(col - 1, 26)
        column = chr(65 + tail) + column
    return '%s%d' % (column, row + 1)


def extract(path):
    original = path.read_bytes()
    stream = workbook_stream(original)
    rows = list(records(stream))
    sheets, strings = [], []
    for n, (_, kind, value) in enumerate(rows):
        if kind == 0x85:
            count, wide = value[6], value[7] & 1
            name = value[8:8 + count * (2 if wide else 1)].decode('utf-16le' if wide else 'latin1')
            sheets.append((u32(value), name))
        elif kind == 0xfc:
            parts = [value]
            while n + 1 < len(rows) and rows[n + 1][1] == 0x3c:
                n += 1
                parts.append(rows[n][2])
            cursor = SstCursor(parts)
            _, unique = struct.unpack('<II', cursor.take(8))
            strings = [cursor.text() for _ in range(unique)]
    output = []
    for start, name in sheets:
        cells = {}
        for _, kind, value in records(stream[start:]):
            if kind == 0x0a:
                break
            if kind == 0xfd:
                row, col = struct.unpack_from('<HH', value)
                cells[cell_name(row, col)] = strings[u32(value, 6)]
            elif kind == 0x203:
                row, col = struct.unpack_from('<HH', value)
                cells[cell_name(row, col)] = struct.unpack_from('<d', value, 6)[0]
            elif kind == 0x06:
                raise ValueError('Formula in pin table requires a full XLS reader')
        output.append({'sheet': name, 'cells': cells})
    return {'source': str(path), 'sha256': hashlib.sha256(original).hexdigest(), 'sheets': output}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('xls', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = extract(args.xls)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for sheet in result['sheets']:
        print(sheet['sheet'], len(sheet['cells']), 'cells')
        selected_rows = {int(''.join(c for c in addr if c.isdigit())) for addr, value in sheet['cells'].items()
                         if any(word in str(value).upper() for word in ('PHY2', 'RGMII', 'B66_L5', 'B66_L6', 'B66_L22'))}
        for row in sorted(selected_rows):
            print({addr: value for addr, value in sheet['cells'].items()
                   if int(''.join(c for c in addr if c.isdigit())) == row})
