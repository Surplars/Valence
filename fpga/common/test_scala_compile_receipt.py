"""Synthetic receipt admission tests, never Scala, hardware, or timing evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import scala_compile_receipt as receipt


class CompileReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.head = 'a' * 40
        self.calls = []
        self.compile_status = 0
        self.classpath_status = 0
        self.compile_mutation = None
        self.inputs = {
            'build.mill': '// Synthetic fixture, not an executable build.\n',
            '.mill-version': '1.1.7\n',
            '.mill-jvm-opts': '-Dsynthetic.fixture=true\n',
            'src/main/scala/Main.scala': '// Synthetic production source.\n',
            'src/test/scala/Test.scala': '// Synthetic test source.\n',
            'third_party/berkeley-hardfloat/src/main/scala/Float.scala':
                '// Synthetic dependency source.\n',
            'src/main/resources/main.bin': 'main resource',
            'src/test/resources/test.bin': 'test resource',
            'compile-resources/compile.bin': 'compile resource',
            'third_party/berkeley-hardfloat/src/main/resources/float.bin': 'dependency resource',
            'third_party/berkeley-hardfloat/compile-resources/compile.bin': 'dependency compile resource',
        }
        for relative, content in self.inputs.items():
            self.write(relative, content)
        self.classes = self.root / 'out/synthetic/classes'
        self.write('out/synthetic/classes/Main.class', 'synthetic class bytes')
        self.jar = self.write('cache/synthetic.jar', 'synthetic jar bytes')
        self.classpath = [self.classes, self.jar]
        self.write_classpath(self.classpath)
        self.out = Path(self.temp.name) / 'receipt'
        self.run = mock.patch.object(receipt.subprocess, 'run', side_effect=self.fake_run).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(receipt.subprocess, 'check_output', side_effect=self.fake_head).start()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def write_classpath(self, paths):
        self.write('out/IonSoC/test/runClasspath.json', json.dumps({
            'value': ['qref:v1:deadbeef:' + str(path) for path in paths],
        }))

    def fake_head(self, command, **kwargs):
        self.assertIn('rev-parse', command)
        self.assertIn('HEAD', command)
        value = self.head + '\n'
        return value if kwargs.get('text') or kwargs.get('encoding') else value.encode()

    def fake_run(self, command, **kwargs):
        self.calls.append(command)
        compiling = any(str(part).endswith('.compile') for part in command)
        if compiling and self.compile_mutation:
            self.compile_mutation()
        status = self.compile_status if compiling else self.classpath_status
        output = 'Synthetic compile fixture\n' if compiling else 'Synthetic classpath fixture\n'
        stream = kwargs.get('stdout')
        if hasattr(stream, 'write'):
            try:
                stream.write(output)
            except TypeError:
                stream.write(output.encode())
        return subprocess.CompletedProcess(command, status, stdout=output, stderr='')

    def produce(self):
        # A real, hashable executable path is required, but fake_run never runs it.
        return receipt.produce(self.root, self.out, mill=sys.executable)

    def read(self, path):
        return json.loads(path.read_text(encoding='utf-8'))

    def save(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def assert_failed_attempt(self):
        self.assertFalse((self.out / 'compile-receipt.json').exists())
        attempt = self.read(self.out / 'attempt.json')
        self.assertEqual(attempt['status'], 'FAIL')
        self.assertNotEqual(attempt['exit'], 0)
        self.assertTrue(list(self.out.glob('*.log')))
        return attempt

    def test_source_manifest_covers_active_roots_resources_and_build_inputs(self):
        self.write('legacy/hardware/src/main/scala/Legacy.scala', 'not an active input')
        self.write('difftest/src/main/scala/Difftest.scala', 'not an active input')
        self.write('src/main/scala/README.txt', 'not a Scala input')
        paths = receipt.compile_source_paths(self.root)
        self.assertEqual(paths, sorted(self.root / name for name in self.inputs))

    def test_success_binds_sources_manifest_commit_and_ordered_classpath(self):
        path = self.produce()
        self.assertEqual(path, self.out / 'compile-receipt.json')
        record = self.read(path)
        self.assertEqual(record['schema'], 'valence-scala-compile-v1')
        self.assertEqual(record['exit'], 0)
        self.assertEqual(record['sourceRoot'], str(self.root.resolve()))
        self.assertEqual(record['sourceCommit'], self.head)
        sources = {str((self.root / name).resolve()): hashlib.sha256(content.encode()).hexdigest()
                   for name, content in self.inputs.items()}
        self.assertEqual(record['sourceInputs'], sources)
        manifest = Path(record['sourceManifest']['path'])
        self.assertEqual(self.read(manifest), sources)
        self.assertEqual(record['sourceManifest']['sha256'], hashlib.sha256(manifest.read_bytes()).hexdigest())
        self.assertEqual(record['runClasspathEntries'], [str(p.resolve()) for p in self.classpath])
        self.assertEqual(record['compiledClasspath'], {
            str((self.classes / 'Main.class').resolve()): hashlib.sha256(b'synthetic class bytes').hexdigest(),
            str(self.jar.resolve()): hashlib.sha256(b'synthetic jar bytes').hexdigest(),
        })
        executable = str(Path(sys.executable).resolve())
        self.assertEqual(self.calls, [
            [executable, '-i', 'IonSoC.test.compile'],
            [executable, '-i', 'show', 'IonSoC.test.runClasspath'],
        ])
        self.assertEqual([command['exit'] for command in record['commands']], [0, 0])
        for command in record['commands']:
            log = Path(command['log'])
            self.assertTrue(log.read_text().startswith('Synthetic'))
            self.assertEqual(command['log_sha256'], hashlib.sha256(log.read_bytes()).hexdigest())
        actual = os.pathsep.join(str(p) for p in self.classpath)
        self.assertEqual(receipt.verify_receipt(path, self.root, actual), record)
        with self.assertRaisesRegex(ValueError, 'actual Java classpath'):
            receipt.verify_receipt(path, self.root, os.pathsep.join(str(p) for p in reversed(self.classpath)))
        self.assertEqual(len(self.calls), 2, 'verification must not invoke compilation')
        self.assertEqual(self.read(self.out / 'attempt.json')['exit'], 0)

    def test_compile_failure_retains_attempt_and_log_without_success_receipt(self):
        self.compile_status = 7
        with self.assertRaisesRegex(ValueError, 'compile failed'):
            self.produce()
        attempt = self.assert_failed_attempt()
        self.assertEqual(attempt['exit'], 7)
        self.assertEqual([command['exit'] for command in attempt['commands']], [7])
        self.assertEqual(len(self.calls), 1)

    def test_classpath_failure_after_successful_compile_never_publishes_receipt(self):
        self.classpath_status = 9
        with self.assertRaisesRegex(ValueError, 'classpath failed'):
            self.produce()
        attempt = self.assert_failed_attempt()
        self.assertEqual(attempt['exit'], 9)
        self.assertEqual([command['exit'] for command in attempt['commands']], [0, 9])
        self.assertEqual(len(self.calls), 2)

    def test_source_mutation_during_compile_rejects_successful_exit(self):
        self.compile_mutation = lambda: self.write('src/main/scala/Main.scala', '// changed during compile')
        with self.assertRaisesRegex(ValueError, 'source/commit drift'):
            self.produce()
        attempt = self.assert_failed_attempt()
        self.assertEqual([command['exit'] for command in attempt['commands']], [0])
        self.assertEqual(len(self.calls), 1)

    def test_stale_or_added_source_and_class_files_are_rejected(self):
        path = self.produce()
        for relative in ('src/main/scala/Main.scala', 'src/test/resources/test.bin',
                         'out/synthetic/classes/Main.class', 'cache/synthetic.jar'):
            original = (self.root / relative).read_bytes()
            with self.subTest(changed=relative):
                self.write(relative, 'changed after receipt')
                with self.assertRaisesRegex(ValueError, 'set/hash mismatch'):
                    receipt.verify_receipt(path, self.root)
            (self.root / relative).write_bytes(original)
        for relative in ('src/test/scala/Added.scala', 'out/synthetic/classes/Added.class'):
            with self.subTest(added=relative):
                added = self.write(relative, 'added after receipt')
                with self.assertRaisesRegex(ValueError, 'set/hash mismatch'):
                    receipt.verify_receipt(path, self.root)
            added.unlink()
        receipt.verify_receipt(path, self.root)

    def test_stale_manifest_commit_and_classpath_order_are_rejected(self):
        path = self.produce()
        record = self.read(path)
        manifest = Path(record['sourceManifest']['path'])
        original = manifest.read_bytes()
        self.save(manifest, {})
        with self.assertRaisesRegex(ValueError, 'manifest mismatch'):
            receipt.verify_receipt(path, self.root)
        manifest.write_bytes(original)
        self.head = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'commit mismatch'):
            receipt.verify_receipt(path, self.root)
        self.head = record['sourceCommit']
        self.write_classpath(reversed(self.classpath))
        with self.assertRaisesRegex(ValueError, 'classpath set/hash mismatch'):
            receipt.verify_receipt(path, self.root)
        self.write_classpath(self.classpath)
        receipt.verify_receipt(path, self.root)

    def test_legacy_and_tampered_receipt_fields_are_rejected(self):
        path = self.produce()
        valid = self.read(path)
        invalid = [
            {'exit': 0},
            dict(valid, schema='legacy'),
            dict(valid, exit=False),
            dict(valid, exit=1),
            dict(valid, sourceRoot=str(self.root.parent)),
            dict(valid, sourceInputs={}),
            dict(valid, sourceManifest={}),
            dict(valid, runClasspathEntries=list(reversed(valid['runClasspathEntries']))),
        ]
        altered_manifest = copy.deepcopy(valid)
        altered_manifest['sourceManifest']['sha256'] = '0' * 64
        invalid.append(altered_manifest)
        for index, record in enumerate(invalid):
            with self.subTest(case=index), self.assertRaises(ValueError):
                self.save(path, record)
                receipt.verify_receipt(path, self.root)
        self.save(path, valid)
        receipt.verify_receipt(path, self.root)

    def test_existing_output_is_preserved_without_subprocess_calls(self):
        self.out.mkdir()
        marker = self.out / 'compile-receipt.json'
        marker.write_bytes(b'preexisting evidence, including invalid evidence, is preserved')
        original = marker.read_bytes()
        with self.assertRaisesRegex(ValueError, 'fresh output directory'):
            self.produce()
        self.assertEqual(marker.read_bytes(), original)
        self.assertEqual(list(self.out.iterdir()), [marker])
        self.run.assert_not_called()

    def test_current_classpath_preserves_order_duplicates_and_hashes_all_files(self):
        resource = self.write('out/synthetic/classes/assets/config.bin', 'classpath resource')
        missing = self.root / 'optional-resource-directory'
        entries = [self.jar, self.classes, self.jar, missing]
        self.write_classpath(entries)
        ordered, files = receipt.current_classpath(self.root)
        self.assertEqual(ordered, [str(p.resolve()) for p in entries])
        self.assertEqual(set(files), {str(self.jar), str(self.classes / 'Main.class'), str(resource)})
        self.assertEqual(files[str(resource)], hashlib.sha256(b'classpath resource').hexdigest())

    def test_pathref_preserves_windows_drive_and_path_colons(self):
        windows = r'C:\work tree\classes'
        self.assertEqual(receipt.parse_pathref('qref:v1:abcdef01:' + windows), windows)
        self.assertEqual(receipt.parse_pathref('ref:v0:abcdef01:/tmp/a:b/classes'),
                         '/tmp/a:b/classes')

    def test_java_classpath_uses_platform_or_explicit_separator(self):
        self.assertEqual(receipt.split_java_classpath(os.pathsep.join(['first', 'second'])),
                         ['first', 'second'])
        windows = [r'C:\work tree\classes', r'D:\cache\library.jar']
        self.assertEqual(receipt.split_java_classpath(';'.join(windows), separator=';'), windows)


if __name__ == '__main__':
    unittest.main()
