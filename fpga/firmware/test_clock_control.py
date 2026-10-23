"""Short host ABI/console tests; no hardware simulator or network dependency."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class ClockControlTests(unittest.TestCase):
    def test_host_contracts(self):
        with tempfile.TemporaryDirectory(prefix="valence-clock-") as temporary:
            for stem in ("test_valence_clock", "test_valence_perf", "test_boot_clock_console"):
                with self.subTest(contract=stem):
                    binary = Path(temporary) / stem
                    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O2",
                                    "-Wall", "-Wextra", "-Werror", str(HERE / (stem + ".c")),
                                    "-o", str(binary)], check=True)
                    subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
