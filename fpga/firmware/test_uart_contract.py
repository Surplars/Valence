import json
from pathlib import Path
import subprocess
import sys
import unittest

from audit_uart_contract import audit


class CompiledUartContractTest(unittest.TestCase):
    repo = Path(__file__).resolve().parents[2]
    rom = repo / "build/fpga/bootrom-uart-margin-20261006-r6"

    def setUp(self):
        if self._testMethodName.startswith("test_actual") or self._testMethodName == "test_wrong_expected_baud_is_rejected":
            if not (self.rom / "bootrom.elf").exists():
                self.skipTest("Compiled r6 ROM evidence absent; build that candidate before artifact tests")
        if self._testMethodName == "test_actual_historical_divisor_seven_is_rejected" and not (
                self.repo / "build/fpga/bootrom-vl100-2g-20261006-r5/bootrom.bin").exists():
            self.skipTest("Historical r5 ROM evidence absent; not a candidate acceptance result")

    def test_actual_rom_divisor_one_fifo_seven(self):
        proof = audit(self.rom / "bootrom.bin", self.rom / "bootrom.elf", 7372800, 460800)
        self.assertEqual((proof["divisor"], proof["lcr"], proof["ier"], proof["fcr"]), (1, 3, 0, 7))
        with (self.rom / "uart-machine-code-audit-r2.json").open() as stream:
            self.assertEqual(proof, json.load(stream))

    def test_actual_historical_divisor_seven_is_rejected(self):
        # uart_init has the same entry address in both builds. Execute the OLD
        # binary, not a substituted divisor metadata field or a patched image.
        old = self.repo / "build/fpga/bootrom-vl100-2g-20261006-r5/bootrom.bin"
        with self.assertRaisesRegex(ValueError, "divisor=7"):
            audit(old, self.rom / "bootrom.elf", 7372800, 460800)

    def test_wrong_expected_baud_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Compiled UART baud mismatch"):
            audit(self.rom / "bootrom.bin", self.rom / "bootrom.elf", 7372800, 115200)

    def test_build_contract_rejects_divisor_seven_before_compilation(self):
        result = subprocess.run([sys.executable, str(self.repo / "fpga/firmware/build.py"),
                                 "--uart-divisor", "7", "--uart-reference-hz", "7372800",
                                 "--uart-baud", "460800"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("UART contract mismatch", result.stderr)

    def test_build_contract_requires_both_clock_and_baud(self):
        result = subprocess.run([sys.executable, str(self.repo / "fpga/firmware/build.py"),
                                 "--uart-baud", "460800"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be specified together", result.stderr)


if __name__ == "__main__":
    unittest.main()
