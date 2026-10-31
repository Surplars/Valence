#!/usr/bin/env python3
"""Small source-generation checks, not hardware behavioral tests."""
import json
from pathlib import Path
import tempfile
import unittest
from prepare import HERE, apply_exact, prepare


class PreparationTest(unittest.TestCase):
    def test_exact_patch_and_context_rejection(self):
        patch = '--- old\n+++ new\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n'
        self.assertEqual(apply_exact('a\nb\n', patch), 'a\nc\n')
        with self.assertRaises(ValueError):
            apply_exact('a\nx\n', patch)

    def test_sealed_outputs_and_rejections(self):
        repo = HERE.parents[3]
        identities = json.loads((HERE / 'base_hashes.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            fake = Path(temporary)
            for name in identities['base_sources']:
                target = fake / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((repo / name).read_bytes())
            outputs = prepare(fake, fake / 'build/valid')
            self.assertEqual(len(outputs), 4)
            with self.assertRaises(ValueError):
                prepare(fake, fake / 'build/valid')
            with self.assertRaises(ValueError):
                prepare(fake, fake / 'src/forbidden')
            name = next(iter(identities['base_sources']))
            with (fake / name).open('a') as stream:
                stream.write('// drift\n')
            with self.assertRaisesRegex(ValueError, 'source drift'):
                prepare(fake, fake / 'build/drift')
            self.assertFalse((fake / 'build/drift').exists())


if __name__ == '__main__':
    unittest.main()
