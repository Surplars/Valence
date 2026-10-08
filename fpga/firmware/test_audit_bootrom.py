"""Both ROM profiles retain exact MIF comparison and profile-specific identity."""
from pathlib import Path
import tempfile
import unittest
from audit_bootrom import audit, ROM_BYTES


class AuditBootromTest(unittest.TestCase):
    def fixture(self, directory, menu=False):
        data = b"Valence Bootrom V0.1\r\n\0"
        data += (b"monitor> \0locked> \0EXTERNAL STATE LOCKED; BOARD RESET REQUIRED\r\n\0"
                 if menu else b"download mode (UART)\r\n\0")
        binary, mif, dcp = (directory / n for n in ("bootrom.bin", "bootrom.mif", "bootrom.dcp"))
        binary.write_bytes(data)
        padded = data.ljust(ROM_BYTES, b"\0")
        mif.write_text("\n".join(format(int.from_bytes(padded[i:i+4], "little"), "032b")
                                  for i in range(0, ROM_BYTES, 4)) + "\n")
        dcp.write_bytes(b"fixture, not a real FPGA checkpoint")
        return binary, mif, dcp

    def test_minimal_default(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(audit(*self.fixture(Path(folder)))["profile"], "minimal")

    def test_menu_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            files = self.fixture(Path(folder), menu=True)
            self.assertEqual(audit(*files, profile="menu")["mifWordsMatched"], 32768)
            with self.assertRaisesRegex(ValueError, "minimal.*missing"):
                audit(*files)

    def test_no_profile_bypass(self):
        with tempfile.TemporaryDirectory() as folder:
            files = self.fixture(Path(folder))
            with self.assertRaisesRegex(ValueError, "menu.*missing"):
                audit(*files, profile="menu")
            with self.assertRaisesRegex(ValueError, "unknown"):
                audit(*files, profile="anything")

    def test_corrupt_padding_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            binary, mif, dcp = self.fixture(Path(folder), menu=True)
            text = mif.read_text()
            mif.write_text(text[:-2] + "1\n")
            # mtime check is downstream of exact image identity.
            with self.assertRaisesRegex(ValueError, "MIF differs"):
                audit(binary, mif, dcp, profile="menu")


if __name__ == "__main__":
    unittest.main()
