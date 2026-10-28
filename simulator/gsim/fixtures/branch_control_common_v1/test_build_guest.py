#!/usr/bin/env python3
"""Pure Python recipe guards; no compiler, linker or CPU is launched."""
from pathlib import Path
import tempfile
import unittest
from build_guest import checked_hash, check_body, invocation_path


class RecipeGuards(unittest.TestCase):
    def test_ld_lld_invocation_keeps_symlink_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "lld").write_bytes(b"not executed")
            (root / "ld.lld-19").symlink_to("lld")
            self.assertEqual(invocation_path(str(root / "ld.lld-19")), root / "ld.lld-19")
            self.assertNotEqual(invocation_path(str(root / "ld.lld-19")), (root / "lld").resolve())

    def test_unrecognized_tool_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tool"
            path.write_bytes(b"unrecognized")
            with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
                checked_hash(path, "0" * 64, "tool")

    def test_body_preservation_requires_exact_prefix(self):
        check_body(b"body", b"bodytail")
        for result in (b"badytail", b"body", b"bod"):
            with self.subTest(result=result), self.assertRaisesRegex(RuntimeError, "body bytes changed"):
                check_body(b"body", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
