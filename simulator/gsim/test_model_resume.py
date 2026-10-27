#!/usr/bin/env python3
"""Pure tempfile/mock tests. Never executes compiler, Mill, GSIM, or a DUT."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import model_resume as resume


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, sort_keys=True))


class ModelResumeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.model = self.root / 'build/prior/model'
        self.parent = self.model.parent / 'receipt.json'
        self.compile = self.root / 'build/compile/compile-receipt.json'
        self.host = self.root / 'simulator/gsim/harness/host.cpp'
        self.compiler = self.root / 'tool/clang++'
        self.runner = self.root / 'simulator/gsim/runner.py'
        for name in ('build.mill', '.mill-version', '.mill-jvm-opts', 'src/main/scala/Test.scala',
                     'src/main/resources/data.bin', 'simulator/gsim/harness/helper.h'):
            write(self.root / name, 'original ' + name)
        write(self.host, '#include "helper.h"\nint main(){return 0;}')
        write(self.runner, '# original runner')
        write(self.compiler, 'mock compiler bytes; NOT executable')
        self.tools = {'compiler': {'command': str(self.compiler), 'path': str(self.compiler),
                                  'sha256': sha(self.compiler), 'version': 'mock'},
                      'gsim': {'sha256': 'a' * 64}, 'mill': {'sha256': 'b' * 64}, 'java': {'sha256': 'c' * 64}}
        for name, data in [('TestGsim.fir', 'circuit TestGsim:'), ('TestGsim.h', '#pragma once'),
                           ('TestGsim0.cpp', '// mock generated DUT'), ('run', 'old binary')]:
            write(self.model / name, data)
        self.flags = ['-std=c++20', '-O1', '-g', '-I' + str(self.model)]
        headers = {str(self.model / 'TestGsim.h'): sha(self.model / 'TestGsim.h')}
        self.build = {'schema': 'real-gsim-header-gate-v1', 'syntax_pass': True,
                      'host': str(self.host), 'host_sha256': sha(self.host), 'compiler': str(self.compiler),
                      'flags': self.flags, 'headers': headers, 'binary_sha256': sha(self.model / 'run'), 'objects': []}
        for source in (self.model / 'TestGsim0.cpp', self.host):
            key = hashlib.sha256(json.dumps({'source': sha(source), 'headers': headers,
                'flags': self.flags, 'compiler': sha(self.compiler)}, sort_keys=True).encode()).hexdigest()
            obj = self.model / (source.stem + '-' + key[:16] + '.o')
            write(obj, 'object for ' + source.name)
            self.build['objects'].append({'source': str(source), 'source_sha256': sha(source),
                'object': str(obj), 'object_sha256': sha(obj), 'key': key, 'reused': False})
        write(self.model / 'run-compile-receipt.json', self.build)
        sources = {str(p): sha(p) for p in resume.scala.compile_source_paths(self.root)}
        manifest = self.compile.parent / 'sources.json'; write(manifest, sources)
        self.compile_record = {'schema': resume.scala.SCHEMA, 'status': 'PASS_SCALA_COMPILE', 'exit': 0,
            'sourceRoot': str(self.root), 'sourceCommit': '1' * 40, 'sourceInputs': sources,
            'sourceManifest': {'path': str(manifest), 'sha256': sha(manifest)},
            'compiledClasspath': {'historical.class': 'd' * 64}, 'runClasspathEntries': ['historical classes']}
        write(self.compile, self.compile_record)
        self.prior = {'status': 'PASS_BOUNDED_TEST', 'source_revision': '1' * 40,
            'inputs_before': self.current_sources(), 'inputs_after': self.current_sources(),
            'inputs_unchanged': True, 'tools_before': self.tools, 'tools_after': self.tools,
            'tools_unchanged': True, 'artifacts_sha256': {str(p.relative_to(self.parent.parent)): sha(p)
                for p in self.model.rglob('*') if p.is_file()}}
        write(self.parent, self.prior)
        self.arguments = dict(prior_path=self.parent, prior_sha=sha(self.parent),
            compile_path=self.compile, compile_sha=sha(self.compile), model_name='model', top='TestGsim', host=self.host)
        self.initial_old = {str(p): sha(p) for p in self.parent.parent.rglob('*') if p.is_file()}
        self.calls = []
        self.stack = []
        for patcher in (mock.patch.object(resume, 'ROOT', self.root),
                        mock.patch.object(resume.base, 'source_inputs', self.current_sources),
                        mock.patch.object(resume.base, 'tool_binding', lambda hardware: self.tools),
                        mock.patch.object(resume.base, 'git', lambda *args: '2' * 40 + '\n'),
                        mock.patch.object(resume, 'execute', self.fake_execute)):
            patcher.start(); self.addCleanup(patcher.stop)

    def current_sources(self):
        paths = set(resume.scala.compile_source_paths(self.root))
        paths.update((self.root / 'simulator/gsim/harness').rglob('*.h'))
        paths.update([self.host, self.runner])
        return {str(p.relative_to(self.root)): sha(p) for p in sorted(paths)}

    def fake_execute(self, command, log):
        command = list(map(str, command)); self.calls.append(command)
        write(log, 'MOCK ONLY; no software executed\n')
        if '-MF' in command:
            write(Path(command[command.index('-MF') + 1]), 'host.o: ' + command[-1] + '\n')
        if '-o' in command:
            write(Path(command[command.index('-o') + 1]), 'new mock output ' + str(len(self.calls)))

    def old_unchanged(self):
        self.assertEqual(self.initial_old, {str(p): sha(p) for p in self.parent.parent.rglob('*') if p.is_file()})

    def reject(self, text=None):
        with self.assertRaises(resume.ReuseRejected) as caught:
            resume.inspect(**self.arguments)
        if text: self.assertIn(text, str(caught.exception))
        self.assertEqual(self.calls, [])

    def repin(self):
        # Tests may simulate an internally inconsistent but SHA-pinned old record;
        # all independent object-key and schema checks must still reject it.
        write(self.parent, self.prior); self.arguments['prior_sha'] = sha(self.parent)

    def test_host_only_relink_never_runs_model_or_inherits_pass(self):
        write(self.host, '#include "helper.h"\nint main(){return 1;} // changed oracle')
        out = self.root / 'build/new-host'
        receipt = resume.build_host(self.arguments, out)
        data = json.loads(receipt.read_text())
        self.assertEqual(data['status'], 'RELINKED_NOT_RUN')
        self.assertFalse(data['simulation_executed']); self.assertFalse(data['inherited_functional_pass'])
        self.assertEqual(len(self.calls), 3)
        self.assertIn('-fsyntax-only', self.calls[0]); self.assertIn('-c', self.calls[1])
        self.assertNotIn('-c', self.calls[2])
        self.assertTrue(all('TestGsim0.cpp' not in ' '.join(command) for command in self.calls))
        self.assertTrue(all(command[0] == str(self.compiler) for command in self.calls))
        self.assertEqual(data['binding']['host_sha256'], sha(self.host))
        self.assertEqual(data['binary_sha256'], sha(out / 'run'))
        self.assertEqual(data['binding']['dut_recipe']['flags'], self.flags)
        self.assertNotEqual(data['host_recipe']['flags'], self.flags)
        self.old_unchanged()

    def test_functional_failure_with_complete_model_is_not_transferred(self):
        self.prior['status'] = 'FAIL'; self.repin()
        write(self.host, 'fixed host')
        result = resume.build_host(self.arguments, self.root / 'build/from-failed-run')
        self.assertEqual(json.loads(result.read_text())['status'], 'RELINKED_NOT_RUN')

    def test_new_private_host_allowed_but_other_source_change_rejected(self):
        host = self.host.with_name('new_private_host.cpp'); write(host, 'new observer')
        args = {**self.arguments, 'host': host}
        self.assertEqual(resume.inspect(**args)['host_sha256'], sha(host))
        write(self.runner, 'modified test runner')
        with self.assertRaisesRegex(resume.ReuseRejected, 'non-host'):resume.inspect(**args)

    def test_non_host_input_changes_and_additions_are_rejected(self):
        choices = ('src/main/scala/Test.scala', 'src/main/resources/data.bin', 'build.mill',
                   'simulator/gsim/harness/helper.h', 'simulator/gsim/runner.py')
        for name in choices:
            with self.subTest(name=name):
                p = self.root / name; old = p.read_bytes(); p.write_text('changed')
                self.reject('non-host'); p.write_bytes(old)
        for name in ('src/main/scala/Added.scala', 'src/main/resources/new.bin', 'simulator/gsim/harness/new.h'):
            with self.subTest(added=name):
                p=self.root/name;write(p,'added');self.reject('non-host');p.unlink()
        p=self.root/'src/main/resources/data.bin';old=p.read_bytes();p.unlink();self.reject();p.write_bytes(old)

    def test_each_model_artifact_change_or_added_member_is_rejected(self):
        names=['TestGsim.fir','TestGsim.h','TestGsim0.cpp',Path(self.build['objects'][0]['object']).name]
        for name in names:
            with self.subTest(name=name):
                p=self.model/name;old=p.read_bytes();p.write_text('corrupt but same filename');self.reject('artifact');p.write_bytes(old)
        p=self.model/'TestGsim1.cpp';write(p,'stale extra TU');self.reject('artifact');p.unlink()
        p=self.model/'TestGsim.h';old=p.read_bytes();p.unlink();self.reject('artifact');p.write_bytes(old)

    def test_tools_flags_and_full_key_are_checked(self):
        self.tools['gsim']['sha256']='f'*64;self.reject('tool');self.tools['gsim']['sha256']='a'*64
        old=self.compiler.read_bytes();self.compiler.write_text('different compiler');self.reject('compiler');self.compiler.write_bytes(old)
        for change in ('key','flags','unsafe_flags'):
            with self.subTest(change=change):
                build=json.loads(json.dumps(self.build))
                if change=='key':build['objects'][0]['key']='0'*64
                elif change=='flags':build['flags']=list(reversed(build['flags']))
                else:build['flags']+=['-include','/unbound/header.h']
                write(self.model/'run-compile-receipt.json',build)
                self.prior['artifacts_sha256']['model/run-compile-receipt.json']=sha(self.model/'run-compile-receipt.json');self.repin()
                self.reject('flags' if change=='unsafe_flags' else 'key')
        write(self.model/'run-compile-receipt.json',self.build)

    def test_prior_proof_missing_fields_or_hash_cannot_be_laundered(self):
        wrong={**self.arguments,'prior_sha':'0'*64}
        with self.assertRaisesRegex(resume.ReuseRejected,'receipt SHA'):resume.inspect(**wrong)
        for change in ('schema','guard','key'):
            prior=json.loads(json.dumps(self.prior))
            if change=='guard':prior['inputs_unchanged']=False
            elif change=='schema':
                build=json.loads(json.dumps(self.build));build['schema']='exit-only';write(self.model/'run-compile-receipt.json',build)
                prior['artifacts_sha256']['model/run-compile-receipt.json']=sha(self.model/'run-compile-receipt.json')
            else:
                prior['artifacts_sha256'].pop('model/run-compile-receipt.json')
            write(self.parent,prior);args={**self.arguments,'prior_sha':sha(self.parent)}
            with self.subTest(change=change),self.assertRaises(resume.ReuseRejected):resume.inspect(**args)

    def test_stage_failures_never_publish_success_and_preserve_old_evidence(self):
        for fail_at in (1,2,3):
            self.calls=[]
            def failing(command,log):
                self.fake_execute(command,log)
                if len(self.calls)==fail_at:raise RuntimeError('mock stage failure')
            out=self.root/f'build/failure-{fail_at}'
            with mock.patch.object(resume,'execute',failing),self.assertRaises(RuntimeError):
                resume.build_host(self.arguments,out)
            record=json.loads((out/'resume-receipt.json').read_text())
            self.assertEqual(record['status'],'BUILD_FAILED');self.assertNotIn('binary_sha256',record)
            self.old_unchanged()

    def test_mid_build_drift_is_rejected(self):
        def changing(command,log):
            self.fake_execute(command,log)
            if len(self.calls)==1:write(self.root/'src/main/scala/Unexpected.scala','added mid-build')
        out=self.root/'build/drift'
        with mock.patch.object(resume,'execute',changing),self.assertRaises(resume.ReuseRejected):
            resume.build_host(self.arguments,out)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(json.loads((out/'resume-receipt.json').read_text())['status'],'REJECTED')
        self.old_unchanged()

    def test_later_compile_cannot_supply_missing_historical_resource_proof(self):
        resource = self.root / 'src/main/resources/data.bin'
        self.prior['inputs_before'].pop(str(resource.relative_to(self.root)))
        self.prior['inputs_after'].pop(str(resource.relative_to(self.root)))
        self.repin()
        write(resource, 'later resource B under same HEAD')
        self.compile_record['sourceInputs'][str(resource)] = sha(resource)
        manifest = Path(self.compile_record['sourceManifest']['path'])
        write(manifest, self.compile_record['sourceInputs'])
        self.compile_record['sourceManifest']['sha256'] = sha(manifest)
        write(self.compile, self.compile_record); self.arguments['compile_sha'] = sha(self.compile)
        self.reject('historical binding')

    def test_direct_compile_link_is_required_when_history_incomplete(self):
        resource = 'src/main/resources/data.bin'
        self.prior['inputs_before'].pop(resource); self.prior['inputs_after'].pop(resource)
        self.prior['scala_compile_receipt'] = {'path': str(self.compile), 'sha256': sha(self.compile)}
        self.repin(); resume.inspect(**self.arguments)
        self.prior['scala_compile_receipt']['sha256'] = '0' * 64; self.repin(); self.reject('different compile')
        self.prior.pop('scala_compile_receipt'); self.repin(); self.reject('historical binding')

    def test_unrelated_copied_header_does_not_block_actual_include_graph(self):
        extra = self.root / 'simulator/gsim/harness/unrelated_other_model.h'
        write(extra, '#include "OtherGsim.h"\n')
        self.prior['inputs_before'] = self.current_sources()
        self.prior['inputs_after'] = self.current_sources()
        self.repin()
        result = resume.build_host(self.arguments, self.root / 'build/unused-header')
        data = json.loads(result.read_text())
        self.assertEqual(data['status'], 'RELINKED_NOT_RUN')
        self.assertTrue(any('unrelated_other_model.h' in name for name in data['host_recipe']['frozen_inputs']))
        self.assertFalse(any('unrelated_other_model.h' in name for name in data['host_recipe']['literal_project_dependencies']))

    def test_external_include_environment_and_actual_dependencies_are_rejected(self):
        with mock.patch.dict(os.environ, {'CPLUS_INCLUDE_PATH': '/tmp/unbound'}): self.reject('environment')
        for include in ('#include "/tmp/live-oracle.h"', '#include "../../../../live.h"', '#include HEADER_MACRO'):
            write(self.host, include + '\nint main(){return 0;}')
            out = self.root / ('build/include-' + str(len(list((self.root / 'build').glob('include-*')))))
            with self.subTest(include=include), self.assertRaises(resume.ReuseRejected): resume.build_host(self.arguments, out)
            self.assertEqual(self.calls, [])
        write(self.host, '#include "helper.h"\nint main(){return 0;}')
        def external_dependency(command, log):
            self.fake_execute(command, log)
            command = list(map(str, command))
            if '-MF' in command:
                write(Path(command[command.index('-MF') + 1]), 'host.o: /tmp/live-oracle.h\n')
        out = self.root / 'build/external-dependency'
        with mock.patch.object(resume, 'execute', external_dependency), self.assertRaisesRegex(resume.ReuseRejected, 'non-system'):
            resume.build_host(self.arguments, out)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(json.loads((out / 'resume-receipt.json').read_text())['status'], 'REJECTED')

    def test_existing_or_historical_output_is_never_overwritten(self):
        existing=self.root/'build/exists';existing.mkdir();write(existing/'keep','unchanged')
        for out in (existing,self.model/'new-host'):
            with self.subTest(out=str(out)),self.assertRaises(resume.ReuseRejected):resume.build_host(self.arguments,out)
        self.assertEqual((existing/'keep').read_text(),'unchanged');self.assertEqual(self.calls,[]);self.old_unchanged()


if __name__=='__main__':
    unittest.main()
