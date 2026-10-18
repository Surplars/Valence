import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import export_board_cpu as export
from check_bootrom_boot import simulation_flags


class BootromProofTest(unittest.TestCase):
    def test_model_scope_preserves_cpu_flags(self):
        flags = ["--icache=32768", "--dcache=32768", "--soc-clock-hz=300000000", "--f", "--d",
                 "--soc-managed-uart", "--soc-jtag", "--soc-user-chain=2", "--soc-jtag-scan-bits=65"]
        self.assertEqual(simulation_flags(flags), flags[:5] + ["--soc-jtag"])

    def test_source_artifact_and_negative_controls_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rom = root / "src/main/resources/inorder/bootrom.hex"
            rom.parent.mkdir(parents=True); rom.write_text("0000000030401073\n" * 512)
            artifact = root / "boot.log"; artifact.write_text("I1_BOOTROM_UART_PASS\n")
            flags = ["--icache=32768", "--soc-jtag", "--soc-managed-uart", "--soc-user-chain=2"]
            original = {"status": "PASS_I1_BOOTROM_UART_SHORT", "board_flags": flags,
                "simulation_flags": simulation_flags(flags), "rom_sha256": export.sha(rom),
                "checks": {"real_cpu_uart": artifact.read_text(), "wrong-banner": "PASS_EXPECTED_REJECTION",
                           "empty-rom": "PASS_EXPECTED_REJECTION"},
                "source_sha256": {str(rom.relative_to(root)): export.sha(rom)},
                "artifact_sha256": {"boot.log": export.sha(artifact)}, "scope": "unit-test fixture only"}
            receipt = root / "receipt.json"
            with patch.object(export, "ROOT", root):
                receipt.write_text(json.dumps(original))
                self.assertTrue(export.validate_bootrom_proof(receipt, flags)["actual_netlist_init_gate_required"])
                for key, value in (("status", "FAIL"), ("board_flags", []), ("simulation_flags", []),
                                   ("rom_sha256", "0" * 64), ("checks", {}),
                                   ("source_sha256", {str(rom.relative_to(root)): "0" * 64}),
                                   ("artifact_sha256", {"boot.log": "0" * 64})):
                    changed = copy.deepcopy(original); changed[key] = value
                    receipt.write_text(json.dumps(changed))
                    with self.subTest(key=key), self.assertRaises(RuntimeError):
                        export.validate_bootrom_proof(receipt, flags)
                for name in ("empty-rom", "wrong-banner"):
                    changed = copy.deepcopy(original); changed["checks"][name] = "PASS"
                    receipt.write_text(json.dumps(changed))
                    with self.subTest(name=name), self.assertRaises(RuntimeError):
                        export.validate_bootrom_proof(receipt, flags)


if __name__ == "__main__":
    unittest.main()
