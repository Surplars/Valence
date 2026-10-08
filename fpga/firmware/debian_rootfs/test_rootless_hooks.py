#!/usr/bin/env python3
"""Opt-in host-runner argument checks; no rootfs, QEMU or package execution."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from build_rootfs import rootless_runner, pack


class RootlessHookTests(unittest.TestCase):
    def test_default_path_needs_no_rootless_environment(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(rootless_runner(SimpleNamespace(rootless_chroot=None), True))

    def test_missing_metadata_fails_before_rootfs_read_or_write(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {}, clear=True):
            output = Path(directory) / 'untouched'
            with self.assertRaisesRegex(RuntimeError, 'fakeroot metadata'):
                pack(SimpleNamespace(rootless_chroot='/bin/true', qemu_user='/bin/true'), output)
            self.assertFalse(output.exists())

    def test_missing_qemu_fails_before_rootfs_read_or_write(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'FAKEROOTKEY': 'test-only'}):
            output = Path(directory) / 'untouched'
            with self.assertRaisesRegex(RuntimeError, '--qemu-user'):
                pack(SimpleNamespace(rootless_chroot='/bin/true', qemu_user=None), output)
            self.assertFalse(output.exists())

    def test_nonexecutable_runner_rejected(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'FAKEROOTKEY': 'test-only'}):
            path = Path(directory) / 'not-executable'; path.write_text('fixture')
            with self.assertRaisesRegex(RuntimeError, 'existing executable'):
                rootless_runner(SimpleNamespace(rootless_chroot=path))

    def test_explicit_executables_validate_without_running(self):
        with mock.patch.dict(os.environ, {'FAKEROOTKEY': 'test-only'}):
            self.assertEqual(rootless_runner(SimpleNamespace(rootless_chroot='/bin/true',
                             qemu_user='/bin/true'), True), str(Path('/bin/true').resolve()))


if __name__ == '__main__':
    unittest.main()
