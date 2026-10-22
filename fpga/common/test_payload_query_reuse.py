"""Pure Tcl query-reuse equivalence; not Vivado/native CDC qualification.

The oracle is extracted by its fixed pre-change Git blob when no private local
baseline file exists. Blob identity survives an aggregated delivery commit; the
cloud-only commit ID need not be present. It is never regenerated from the candidate.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


BASELINE_BLOB = "5a1a0ba012cae678d0562101251d53d4907ab529"
# Reviewed in cloud commit ff06eeb76cd8bdf5f9d2e303d1266d35257c728b.
BASELINE_SHA256 = "7da9f0426195377447a5918af7432ffd4e32f45be04e0c2a8677ad65b31d89a7"


@unittest.skipUnless(shutil.which("tclsh"), "Tcl unavailable")
class PayloadQueryReuseTests(unittest.TestCase):
    def test_frozen_oracle_graphs_and_query_counts(self):
        script = Path(__file__).with_suffix(".tcl")
        root = script.parents[2]
        local_baseline = root / "common_cdc.baseline.tcl"
        with tempfile.TemporaryDirectory(prefix="payload-query-oracle-") as temp:
            baseline = local_baseline
            if not baseline.exists():
                oracle = subprocess.run(
                    ["git", "cat-file", "blob", BASELINE_BLOB],
                    cwd=root,
                    capture_output=True,
                    check=True,
                )
                baseline = Path(temp) / "common_cdc.baseline.tcl"
                baseline.write_bytes(oracle.stdout)
            self.assertEqual(
                hashlib.sha256(baseline.read_bytes()).hexdigest(),
                BASELINE_SHA256,
                "Frozen payload oracle differs from the reviewed revision",
            )
            result = subprocess.run(
                ["tclsh", str(script), str(baseline)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PAYLOAD_QUERY_EQUIVALENCE_PASS", result.stdout)
        self.assertIn("NOT_NATIVE_QUALIFIED", result.stdout)
        self.assertIn("all_fanin baseline=520 candidate=520", result.stdout)


if __name__ == "__main__":
    unittest.main()
