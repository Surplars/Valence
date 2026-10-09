#!/usr/bin/env python3
import stat
import unittest
from repack_dinit_overlay import overlay
from audit_dinit_delivery import decode_newc


def archive(link_count=1, mode=stat.S_IFREG | 0o755):
    out = bytearray()
    for index, (name, data, kind, links) in enumerate((('helper', b'old\n', mode, link_count),
                ('other', b'untouched\0bytes', stat.S_IFREG | 0o644, 1),
                ('link', b'other', stat.S_IFLNK | 0o777, 1), ('TRAILER!!!', b'', 0, 1))):
        encoded = name.encode() + b'\0'
        fields = [index + 1, kind, 0, 42, links, 123, len(data), 0, 0, 0, 0, len(encoded), 0]
        out.extend(b'070701' + b''.join(f'{v:08x}'.encode() for v in fields))
        out.extend(encoded); out.extend(bytes((-len(out)) % 4))
        out.extend(data); out.extend(bytes((-len(out)) % 4))
    out.extend(bytes((-len(out)) % 512))
    return bytes(out)


class OverlayTests(unittest.TestCase):
    def test_content_resize_preserves_every_other_byte_and_metadata(self):
        before = archive()
        for replacement in (b'x', b'new helper' * 1001):
            changed, delta = overlay(before, {'helper': replacement})
            entries, _ = decode_newc(changed)
            old, _ = decode_newc(before)
            self.assertEqual(entries['helper'][1], replacement)
            self.assertEqual(entries['other'], old['other'])
            self.assertEqual(entries['link'], old['link'])
            self.assertEqual(delta, len(replacement) - 4)
            self.assertEqual(len(changed) % 512, 0)

    def test_missing_target_rejected(self):
        with self.assertRaises(RuntimeError):
            overlay(archive(), {'absent': b'new'})

    def test_hardlink_target_rejected(self):
        with self.assertRaises(RuntimeError):
            overlay(archive(link_count=2), {'helper': b'new'})

    def test_non_regular_target_rejected(self):
        with self.assertRaises(RuntimeError):
            overlay(archive(mode=stat.S_IFLNK | 0o777), {'helper': b'new'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
