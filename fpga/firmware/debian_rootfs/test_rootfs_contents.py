#!/usr/bin/env python3
"""Small rootfs fixtures verify source-only packaging and old-seed filtering."""
import inspect
from pathlib import Path
import tempfile
import unittest

import build_rootfs as rootfs
import build_dinit_rootfs as dinit
import build_systemd_rootfs as systemd
import audit_dinit_delivery as audit


class RootfsContentsTests(unittest.TestCase):
    def test_all_profiles_use_the_same_archive_filter(self):
        for function in (rootfs.pack, dinit.rootfs, systemd.pack):
            with self.subTest(profile=function.__module__):
                source = inspect.getsource(function)
                self.assertIn('paths = archive_paths(', source)
                self.assertIn("input=b'\\0'.join(p.encode() for p in paths)", source)
        self.assertIs(dinit.archive_paths, rootfs.archive_paths)
        self.assertIs(systemd.archive_paths, rootfs.archive_paths)

    def test_old_seed_custom_payload_is_omitted_but_source_tree_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            kept = ('init', 'usr/bin/bash', 'usr/bin/fastfetch', 'usr/share/doc/fastfetch/copyright',
                    'usr/local/bin/coremark', 'usr/local/bin/fpu-test', 'usr/local/bin/net-bench',
                    'usr/local/bin/mem-bench', 'usr/local/sbin/dma-bench', 'etc/inittab')
            excluded = ('usr/local/bin/fastfetch', 'usr/share/doc/valence/fastfetch/LICENSE',
                        'var/cache/apt/archives/package.deb', 'var/lib/apt/lists/index', 'debootstrap/log')
            for relative in (*kept, *excluded):
                path = tree / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture: ' + relative)
            paths = rootfs.archive_paths(tree)
            self.assertEqual(paths, sorted(set(paths)))
            self.assertEqual(paths[0], '.')
            for relative in kept:
                self.assertIn('./' + relative, paths)
            for relative in excluded:
                self.assertNotIn('./' + relative, paths)
                self.assertEqual((tree / relative).read_text(), 'fixture: ' + relative)
            dinit_paths = dinit.archive_paths(tree, extra_excluded=('etc/inittab',))
            self.assertNotIn('./etc/inittab', dinit_paths)
            audit.require_no_retired_tools(path.removeprefix('./') for path in dinit_paths)

    def test_original_flat_license_and_dangling_custom_binary_are_filtered(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            binary = tree / 'usr/local/bin/fastfetch'
            binary.parent.mkdir(parents=True)
            binary.symlink_to('/missing-old-custom-binary')
            license = tree / 'usr/share/doc/valence/fastfetch'
            license.parent.mkdir(parents=True)
            license.write_text('old license')
            paths = rootfs.archive_paths(tree)
            self.assertNotIn('./usr/local/bin/fastfetch', paths)
            self.assertNotIn('./usr/share/doc/valence/fastfetch', paths)
            self.assertTrue(binary.is_symlink())
            self.assertTrue(license.is_file())

    def test_audit_rejects_each_retired_payload_independently(self):
        for path in ('usr/local/bin/fastfetch', 'usr/share/doc/valence/fastfetch',
                     'usr/share/doc/valence/fastfetch/LICENSE'):
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'retired custom utility'):
                audit.require_no_retired_tools(['init', 'usr/bin/bash', path])
        audit.require_no_retired_tools(['init', 'usr/bin/fastfetch', 'usr/share/doc/fastfetch/copyright'])

    def test_no_custom_build_or_new_debian_package_dependency(self):
        self.assertNotIn('fastfetch', rootfs.PACKAGES)
        self.assertNotIn('fastfetch', systemd.PACKAGES)
        self.assertNotIn('build/fpga/linux-userland', inspect.getsource(rootfs.pack))
        self.assertNotIn('fastfetch', inspect.getsource(rootfs.pack))


if __name__ == '__main__':
    unittest.main(verbosity=2)
