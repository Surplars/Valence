"""Mechanical driver transport preflight with a scalar stub, never an RTL model."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import ports


class TransportTests(unittest.TestCase):
    def test_port_names_unique_and_scalar_word_abi(self):
        self.assertEqual(len(ports.INPUTS), len(set(ports.INPUTS)))
        self.assertEqual(len(ports.OUTPUTS), len(set(ports.OUTPUTS)))
        self.assertEqual(len([p for p in ports.OUTPUTS if p.startswith('refillWord')]), 8)
        self.assertEqual(len([p for p in ports.OUTPUTS if p.startswith('installWord')]), 8)
        self.assertIn('posted.requestProof.valid', ports.INPUTS)

    def test_generated_cpp_transport_retains_full_uint64(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler, 'installed host C++ compiler required for mechanical transport check')
        with tempfile.TemporaryDirectory(prefix='posted-scalar-transport-') as temp:
            path = Path(temp)
            ports.emit_driver(path / 'driver.cpp')
            methods = ['#include <cstdint>', 'struct SPostedStoreCacheGsim { uint64_t data=0; void step() {}']
            for name in ports.INPUTS:
                body = 'data=v;' if name == 'upstream.request.bits.data' else '(void)v;'
                methods.append('void ' + ports.method('set_', name) + '(uint64_t v) {' + body + '}')
            for name in ports.OUTPUTS:
                value = 'data' if name == 'upstream.response.bits.data' else '0'
                methods.append('uint64_t ' + ports.method('get_', name) + '() const { return ' + value + '; }')
            methods.append('};')
            (path / 'PostedStoreCacheGsim.h').write_text('\n'.join(methods) + '\n')
            subprocess.run([compiler, '-std=c++20', '-Wall', '-Wextra', '-Werror', '-I' + str(path),
                            str(path / 'driver.cpp'), '-o', str(path / 'driver')], check=True, capture_output=True, text=True)
            value = (1 << 64) - 1
            result = subprocess.run([str(path / 'driver')], input=f'upstream.request.bits.data={value}\nquit\n',
                                    capture_output=True, text=True, check=True)
            record = json.loads(result.stdout)
            self.assertEqual(record['upstream.response.bits.data'], value)
            self.assertEqual(set(record), set(ports.OUTPUTS) | {'cycle'})
            bad = subprocess.run([str(path / 'driver')], input='unknownPort=1\n', capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1)
            self.assertIn('unknown input', bad.stderr)

    def test_fixture_and_runner_python_syntax(self):
        root = Path(__file__).parent
        for name in ['fixture.py', 'ports.py', 'run_component.py']:
            compile((root / name).read_text(), str(root / name), 'exec')


if __name__ == '__main__':
    unittest.main(verbosity=2)
