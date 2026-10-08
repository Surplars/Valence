"""Host checks for the actual vector files passed to the selected FP replay."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[2] / 'simulator/gsim'
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('selected_fp_cpu', HERE / 'selected_fp_cpu.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ExecutedVectorBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.proof = {'vectors': {}}
        for name in ('vectors.txt', 'memory-vectors.txt'):
            path = self.root / name
            path.write_text('independent ' + name)
            self.proof['vectors']['/unavailable/archive/' + name] = hashlib.sha256(path.read_bytes()).hexdigest()

    def test_relocated_files_are_bound_without_reading_old_absolute_paths(self):
        actual = runner.bind_executed_vectors(self.proof, self.root)
        self.assertEqual(set(actual), {str(self.root / name) for name in ('vectors.txt', 'memory-vectors.txt')})

    def test_corrupted_executed_file_rejected(self):
        (self.root / 'vectors.txt').write_text('corrupt active input')
        with self.assertRaisesRegex(RuntimeError, 'executed qualified vector changed'):
            runner.bind_executed_vectors(self.proof, self.root)

    def test_missing_executed_file_rejected(self):
        (self.root / 'memory-vectors.txt').unlink()
        with self.assertRaisesRegex(RuntimeError, 'executed qualified vector changed or missing'):
            runner.bind_executed_vectors(self.proof, self.root)

    def test_duplicate_and_unexpected_identities_rejected(self):
        self.proof['vectors']['/different/archive/vectors.txt'] = self.proof['vectors']['/unavailable/archive/vectors.txt']
        with self.assertRaisesRegex(RuntimeError, 'ambiguous or unexpected'):
            runner.bind_executed_vectors(self.proof, self.root)
        self.proof['vectors'] = {'/other/not-a-vector.txt': '0' * 64}
        with self.assertRaisesRegex(RuntimeError, 'ambiguous or unexpected'):
            runner.bind_executed_vectors(self.proof, self.root)

    def test_incomplete_inventory_rejected(self):
        self.proof['vectors'].pop('/unavailable/archive/memory-vectors.txt')
        with self.assertRaisesRegex(RuntimeError, 'inventory is incomplete'):
            runner.bind_executed_vectors(self.proof, self.root)


if __name__ == '__main__':
    unittest.main()
