#!/usr/bin/env python3
"""Execute real CLI parsing/preflight only; never invoke a compiler or simulator."""
import argparse
import ast
import contextlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[4]
FLAG = '--prepared-store-lookahead'
KEY = 'prepared_store_lookahead'


def board_plan(arguments):
    path = ROOT / 'simulator/gsim/fpga_next_board.py'
    source = ast.parse(path.read_text())
    body = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    stop = next(i for i, n in enumerate(body.body) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'plan' for t in n.targets))
    fn = ast.FunctionDef(name='plan', args=body.args, body=body.body[:stop+1]
                        + [ast.Return(ast.Name('plan', ast.Load()))], decorator_list=[])
    with tempfile.TemporaryDirectory() as tmp:
        env = {'argparse': argparse, 're': re, 'common': types.SimpleNamespace(BUILD=Path(tmp)),
               'source_inventory': lambda: {}}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(path), 'exec'), env)
        old = sys.argv
        try:
            sys.argv = [str(path), '--tag', 'host-only', *arguments]
            return env['plan']()
        finally:
            sys.argv = old


def native_plan(arguments, expect=0):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'never-created'
        result = subprocess.run([sys.executable, '-B', str(ROOT/'fpga/next/export.py'),
                                 '--output', str(out), *arguments], cwd=ROOT, capture_output=True,
                                text=True, timeout=30)
        assert result.returncode == expect, result.stdout + result.stderr
        assert not out.exists(), 'native preflight created outputs'
        return json.loads(result.stdout) if expect == 0 else result.stderr


class Selection(unittest.TestCase):
    def test_defaults_remain_off_for_every_existing_variant(self):
        for variant in ('reference', 'candidate', 'selected'):
            plan = board_plan(['--variant', variant])
            self.assertIs(plan[KEY], False)
            self.assertNotIn(FLAG, plan['parameters'])
        for flags in ([], ['--reference'], ['--storage-candidate']):
            self.assertIs(native_plan(flags)[KEY], False)

    def test_exact_board_delta_and_unchanged_read_profile(self):
        for capacity in (2, 4):
            fixed = ['--variant', 'selected', '--lsu-entries', str(capacity),
                     '--physical-load-ingress-flow', '--fetch-previous-packet',
                     '--load-order-older-retire', '--dma-line-transfers', '--dma-line-entries', '4']
            off, on = board_plan(fixed), board_plan(fixed + [FLAG])
            self.assertIs(off.pop(KEY), False)
            self.assertIs(on.pop(KEY), True)
            self.assertEqual(on['parameters'].count(FLAG), 1)
            on['parameters'].remove(FLAG)
            self.assertEqual(off, on)

    def test_exact_native_metadata_delta(self):
        off, on = native_plan([]), native_plan([FLAG])
        self.assertIs(off.pop(KEY), False)
        self.assertIs(on.pop(KEY), True)
        self.assertEqual(on.pop('profile'), off.pop('profile') + '-prepared-store-lookahead')
        off.pop('output'); on.pop('output')
        self.assertEqual(off, on)

    def test_nonboolean_and_unsupported_capacity_rejected(self):
        for flags in ([FLAG+'=false'], [FLAG+'=1'], ['--lsu-entries', '1', FLAG]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                board_plan(flags)
            native_plan(flags, expect=2)

    def test_scala_option_is_explicit_and_default_off(self):
        for name in ('OooParams.scala', 'FpgaNextConfig.scala', 'BoardSocTop.scala'):
            self.assertIn('preparedStoreLookahead: Boolean = false',
                          (ROOT/'src/main/scala/core/ooo'/name).read_text())
        for name in ('FpgaNextMain.scala', 'FpgaNextBoardGsimMain.scala'):
            text = (ROOT/'src/test/scala/ooo'/name).read_text()
            self.assertIn('"'+FLAG+'"', text)
            self.assertIn('['+FLAG+']', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
