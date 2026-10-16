#!/usr/bin/env python3
"""Host-only shell tests; the real sysfs path is redirected in a temporary copy."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

class DmaBenchErrors(unittest.TestCase):
    def run_wrapper(self, args=(), failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node = root / 'device' / 'benchmark'
            node.parent.mkdir()
            if failure:
                node.symlink_to('/dev/full')
            else:
                node.write_text('')
            fakebin = root / 'bin'
            fakebin.mkdir()
            (fakebin / 'id').write_text('#!/bin/sh\necho 0\n')
            (fakebin / 'id').chmod(0o755)
            marker = root / 'cat_called'
            (fakebin / 'cat').write_text(f'#!/bin/sh\ntouch "{marker}"\n/bin/cat "$@"\n')
            (fakebin / 'cat').chmod(0o755)
            script = root / 'dma-bench'
            text = (HERE / 'dma-bench').read_text()
            self.assertIn('/usr/bin/printf', text)
            text = text.replace('/sys/bus/platform/drivers/valence-dma-bench/*/benchmark', str(node))
            script.write_text(text)
            env = {**os.environ, 'PATH': str(fakebin) + ':' + os.environ['PATH'], 'LC_ALL': 'C'}
            result = subprocess.run(['/bin/dash', str(script), *args], env=env, text=True, capture_output=True)
            return result, None if failure else node.read_text(), marker.exists()

    def test_default_one_mib_unchanged(self):
        p, content, read = self.run_wrapper()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(content, '1048576 4\n')
        self.assertTrue(read)

    def test_explicit_eight_mib_not_clipped_or_chunked(self):
        p, content, read = self.run_wrapper(['8388608', '4'])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(content, '8388608 4\n')
        self.assertTrue(read)

    def test_comparison_size_unchanged(self):
        p, content, _ = self.run_wrapper(['131072', '1'])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(content, '131072 1\n')

    def test_write_errno_message_preserved_no_false_report(self):
        p, _, read = self.run_wrapper(['8388608', '4'], failure=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('No space left on device', p.stderr)
        self.assertFalse(read)
        self.assertEqual(p.stdout, '')

    def test_recommendations_and_pack_dependency(self):
        for name in ('README.md', 'boot-diagnose', 'valence-ready', 'dinit/ready', 'dinit/boot-diagnose'):
            self.assertNotIn('dma-bench 8388608 4', (HERE / name).read_text())
        builder = (HERE / 'build_rootfs.py').read_text()
        self.assertIn("PACKAGES = ('coreutils',", builder)
        self.assertIn("rootfs / 'usr/bin/printf'", builder)
        self.assertIn('requires executable Debian coreutils', builder)

if __name__ == '__main__':
    unittest.main()
