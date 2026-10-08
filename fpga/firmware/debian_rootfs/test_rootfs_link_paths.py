import os
from pathlib import Path
import tempfile
import unittest
from rootfs_link_paths import normalize_build_links


class LinkPathTests(unittest.TestCase):
    def test_only_explicit_origin_is_normalized(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'root'
            (root / 'etc/alternatives').mkdir(parents=True)
            (root / 'usr/bin').mkdir(parents=True)
            origin = '/workspace/test/old-root'
            (root / 'etc/alternatives/awk').symlink_to(origin + '/usr/bin/mawk')
            (root / 'usr/bin/relative').symlink_to('../bin/mawk')
            (root / 'usr/bin/absolute').symlink_to('/usr/bin/mawk')
            state = root / 'var/lib/dpkg/alternatives/awk'
            state.parent.mkdir(parents=True)
            state.write_text('auto\n' + origin + '/usr/bin/mawk\n')
            receipt = normalize_build_links(root, [origin])
            self.assertEqual(len(receipt['links']), 1)
            self.assertEqual(os.readlink(root / 'etc/alternatives/awk'), '/usr/bin/mawk')
            self.assertEqual(os.readlink(root / 'usr/bin/relative'), '../bin/mawk')
            self.assertEqual(os.readlink(root / 'usr/bin/absolute'), '/usr/bin/mawk')
            self.assertEqual(state.read_text(), 'auto\n/usr/bin/mawk\n')

    def test_unknown_host_prefix_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'bad').symlink_to('/workspace/other/private')
            with self.assertRaises(RuntimeError):
                normalize_build_links(root, ['/workspace/approved/root'])

    def test_escape_rejected(self):
        for target in ('../outside', '/workspace/approved/root/../outside'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / 'bad').symlink_to(target)
                with self.assertRaises(RuntimeError):
                    normalize_build_links(root, ['/workspace/approved/root'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
