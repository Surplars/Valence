#!/usr/bin/env python3
"""Small independent negative fixtures for packed path and ELF closure checks."""
import stat
import struct
import unittest

from audit_runtime_closure import resolve, elf_dependencies


def entry(mode, data=b''):
    return ([0, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, 0, 0], data)


def sample_elf():
    strings = b'\0libc.so.6\0'
    blob = bytearray(240 + len(strings))
    blob[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HH', blob, 16, 3, 243)
    struct.pack_into('<Q', blob, 32, 64)
    struct.pack_into('<I', blob, 48, 5)
    struct.pack_into('<HHH', blob, 52, 64, 56, 2)
    struct.pack_into('<IIQQQQQQ', blob, 64, 1, 4, 0, 0x10000, 0x10000, len(blob), len(blob), 4096)
    struct.pack_into('<IIQQQQQQ', blob, 120, 2, 4, 176, 0x100b0, 0x100b0, 64, 64, 8)
    for pos, tag, value in ((176, 1, 1), (192, 5, 0x100f0), (208, 10, len(strings)), (224, 0, 0)):
        struct.pack_into('<QQ', blob, pos, tag, value)
    blob[240:] = strings
    return blob


class ClosureTests(unittest.TestCase):
    def test_absolute_and_relative_links_and_runtime_exception(self):
        entries = {'usr': entry(stat.S_IFDIR), 'usr/bin': entry(stat.S_IFDIR),
            'usr/bin/sh': entry(stat.S_IFREG), 'bin': entry(stat.S_IFLNK, b'usr/bin'),
            'usr/bin/shell': entry(stat.S_IFLNK, b'../../bin/sh'),
            'usr/bin/abs': entry(stat.S_IFLNK, b'/bin/sh'), 'dev': entry(stat.S_IFDIR),
            'dev/stdin': entry(stat.S_IFLNK, b'/proc/self/fd/0')}
        for name in ('/bin/sh', '/usr/bin/shell', '/usr/bin/abs'):
            self.assertEqual(resolve(entries, name), 'usr/bin/sh')
        with self.assertRaises(RuntimeError):
            resolve(entries, 'dev/stdin')
        self.assertEqual(resolve(entries, 'dev/stdin', allow_runtime=True), 'proc/self/fd/0')

    def test_missing_cycle_host_path_and_escape_rejected(self):
        for target in (b'/missing', b'/bad', b'/workspace/host', b'../../outside'):
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                resolve({'bad': entry(stat.S_IFLNK, target)}, 'bad')

    def test_dynamic_elf_and_rejected_header_or_string_map(self):
        sample = sample_elf()
        self.assertEqual(elf_dependencies(sample)['needed'], ['libc.so.6'])
        for offset, kind, value in ((18, '<H', 62), (48, '<I', 1), (32, '<Q', 999999),
                                     (200, '<Q', 0xffffffffffff)):
            mutated = bytearray(sample)
            struct.pack_into(kind, mutated, offset, value)
            with self.subTest(offset=offset), self.assertRaises(RuntimeError):
                elf_dependencies(mutated)


if __name__ == '__main__':
    unittest.main(verbosity=2)
