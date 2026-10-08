#!/usr/bin/env python3
"""Synthetic fixture gates; never access the user's inputs or launch Vivado."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from verify_dev_sources import verify_dev_sources

HERE = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / 'existing-repo'
        self.repo.mkdir()
        self.path = self.repo / 'src/main/scala/Fixture.scala'
        self.path.parent.mkdir(parents=True)
        self.path.write_text('class Fixture\n')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        self.commit = self.git('rev-parse', 'HEAD').strip()
        self.manifest = self.root / 'sources.json'
        self.manifest.write_text(json.dumps({'src/main/scala/Fixture.scala': sha(self.path)}))

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True)

    def check(self):
        return verify_dev_sources(self.repo, self.commit, self.manifest)

    def test_source_exact(self):
        self.assertEqual(self.check()['status'], 'PASS')

    def test_dirty_source_rejected(self):
        self.path.write_text('changed\n')
        with self.assertRaisesRegex(RuntimeError, 'working source'):
            self.check()

    def test_extra_source_rejected(self):
        self.path.with_name('Unexpected.scala').write_text('class Unexpected\n')
        with self.assertRaisesRegex(RuntimeError, 'inventory'):
            self.check()

    def test_wrong_commit_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'HEAD'):
            verify_dev_sources(self.repo, '0' * 40, self.manifest)

    def test_committed_blob_drift_rejected(self):
        old = self.path.read_bytes()
        self.path.write_text('different committed source\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'changed')
        self.commit = self.git('rev-parse', 'HEAD').strip()
        self.path.write_bytes(old)
        with self.assertRaisesRegex(RuntimeError, 'committed source'):
            self.check()

    def packet(self):
        packet = self.root / 'packet'; packet.mkdir()
        for name in ('stage_local_candidate.py', 'verify_local_inputs.py', 'verify_dev_sources.py'):
            shutil.copyfile(HERE / name, packet / name)
        source_map = {}
        for name in ('board', 'scripts'):
            source = self.repo / 'fpga' / name / 'fixture.txt'
            source.parent.mkdir(parents=True); source.write_text(name)
            source_map[name + '/fixture.txt'] = {'repo_path': source.relative_to(self.repo).as_posix(), 'sha256': sha(source)}
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'board fixture')
        self.commit = self.git('rev-parse', 'HEAD').strip()
        existing = self.root / 'immutable'; existing.mkdir()
        (existing / 'firmware').mkdir(); (existing / 'firmware/rom.bin').write_bytes(b'rom')
        (existing / 'inputs.json').write_text('manifest')
        expected = {'expected_inputs_json_sha256': sha(existing / 'inputs.json'), 'directories': ['firmware'],
                    'sha256': {'firmware/rom.bin': sha(existing / 'firmware/rom.bin')}}
        (packet / 'expected-local-inputs.json').write_text(json.dumps(expected))
        shutil.copyfile(self.manifest, packet / 'integrated-source-sha256.json')
        variants = {}
        for name, flag in [('integrated-off', False), ('integrated-on', True)]:
            rtl = packet / 'variants' / name / 'rtl'; rtl.mkdir(parents=True)
            (rtl / 'Fixture.sv').write_text('module Fixture; endmodule\n')
            variants[name] = {'cpu_precheck': flag, 'rtl_sha256': {'Fixture.sv': sha(rtl / 'Fixture.sv')}}
        (packet / 'EXPORT-RECEIPT.json').write_text(json.dumps({
            'status': 'PASS_EXPORT_IDENTITY_FUNCTIONAL_SCOPE_ONLY', 'variants': variants, 'source_map': source_map}))
        self.hash_packet(packet)
        return packet, existing

    def hash_packet(self, packet):
        hashes = {p.relative_to(packet).as_posix(): sha(p) for p in packet.rglob('*')
                  if p.is_file() and p.name != 'PACKAGE-SHA256.json' and '__pycache__' not in p.parts}
        (packet / 'PACKAGE-SHA256.json').write_text(json.dumps(hashes))

    def stage(self, packet, existing, variant='integrated-on', bind=True):
        command = ['python3', str(packet / 'stage_local_candidate.py'), '--existing', str(existing),
                   '--output', str(self.repo / 'build/fresh'), '--variant', variant,
                   '--rtl', str(packet / 'variants' / variant / 'rtl')]
        if bind: command += ['--repo', str(self.repo), '--commit', self.commit]
        return subprocess.run(command, capture_output=True, text=True)

    def test_stages_inside_existing_repo_and_retains_flag(self):
        packet, existing = self.packet()
        result = self.stage(packet, existing)
        self.assertEqual(result.returncode, 0, result.stderr)
        staged = json.loads((self.repo / 'build/fresh/staged-inputs.json').read_text())
        self.assertTrue(staged['cpu_precheck'])
        self.assertEqual(staged['source_binding']['commit'], self.commit)
        self.assertFalse(staged['bitstream_generated'])

    def test_unbound_candidate_rejected(self):
        packet, existing = self.packet()
        self.assertNotEqual(self.stage(packet, existing, bind=False).returncode, 0)
        self.assertFalse((self.repo / 'build/fresh').exists())

    def test_modified_ip_rejected_before_staging(self):
        packet, existing = self.packet()
        (existing / 'firmware/rom.bin').write_bytes(b'wrong')
        self.assertNotEqual(self.stage(packet, existing).returncode, 0)
        self.assertFalse((self.repo / 'build/fresh').exists())

    def test_modified_board_source_rejected_before_staging(self):
        packet, existing = self.packet()
        (self.repo / 'fpga/board/fixture.txt').write_text('changed')
        self.assertNotEqual(self.stage(packet, existing).returncode, 0)
        self.assertFalse((self.repo / 'build/fresh').exists())

    def test_existing_output_rejected(self):
        packet, existing = self.packet()
        dest = self.repo / 'build/fresh'; dest.mkdir(parents=True)
        (dest / 'preserve').write_text('keep')
        self.assertNotEqual(self.stage(packet, existing).returncode, 0)
        self.assertEqual((dest / 'preserve').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
