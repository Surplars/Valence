#!/usr/bin/env python3
"""Host-only external-module source closure; no kernel, downloads or hardware."""
import ast
from pathlib import Path
import re
import shutil
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
NET = HERE.parent / 'linux_net'
ASSIGNMENTS = {
    node.targets[0].id: ast.literal_eval(node.value)
    for node in ast.parse((HERE / 'build_image.py').read_text()).body
    if isinstance(node, ast.Assign) and len(node.targets) == 1
    and isinstance(node.targets[0], ast.Name)
    and node.targets[0].id in ('MODULE_SOURCES', 'MODULES')
}


def stage_and_check(names, destination):
    for name in names:
        shutil.copyfile(NET / name, destination / name)
    # virt-dma.h is the one quoted upstream header, supplied by Kbuild's
    # explicit srctree include path. Every project-local include must be staged.
    external = {'virt-dma.h'}
    assert '-I$(srctree)/drivers/dma' in (destination / 'Makefile').read_text()
    for path in destination.iterdir():
        if path.suffix not in ('.c', '.h'):
            continue
        for name in re.findall(r'^\s*#\s*include\s*"([^"]+)"', path.read_text(), re.M):
            assert name in external or (destination / name).is_file(), (path.name, name)


class ModuleSourceTests(unittest.TestCase):
    def test_five_driver_sources_and_recursive_headers_are_staged(self):
        names = ASSIGNMENTS['MODULE_SOURCES']
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(ASSIGNMENTS['MODULES']), {
            'valence_aia.ko', 'valence_gmac.ko', 'valence_soc.ko',
            'valence_cmu.ko', 'valence_dma.ko',
        })
        for module in ASSIGNMENTS['MODULES']:
            self.assertIn(module.removesuffix('.ko') + '.c', names)
        with tempfile.TemporaryDirectory() as directory:
            stage_and_check(names, Path(directory))

    def test_missing_posted_queue_header_is_rejected(self):
        for omitted in ('valence_rx_queue.h', 'valence_tx_queue.h'):
            with self.subTest(header=omitted), tempfile.TemporaryDirectory() as directory:
                names = tuple(n for n in ASSIGNMENTS['MODULE_SOURCES'] if n != omitted)
                with self.assertRaises(AssertionError):
                    stage_and_check(names, Path(directory))

    def test_staged_bytes_match_declared_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            stage_and_check(ASSIGNMENTS['MODULE_SOURCES'], destination)
            for name in ASSIGNMENTS['MODULE_SOURCES']:
                self.assertEqual((destination / name).read_bytes(), (NET / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
