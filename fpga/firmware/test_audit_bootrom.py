import os
from pathlib import Path
import tempfile
import unittest
from audit_bootrom import ROM_BYTES, audit


class BootromAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.binary, self.mif, self.dcp = (root / name for name in ("bootrom.bin", "rom.mif", "rom.dcp"))
        self.data = b"Valence Bootrom V0.1\r\n\0download mode (UART)\r\n\0"
        self.binary.write_bytes(self.data)
        padded = self.data.ljust(ROM_BYTES, b"\0")
        self.words = [f"{int.from_bytes(padded[n:n + 4], 'little'):032b}" for n in range(0, ROM_BYTES, 4)]
        self.mif.write_text("\n".join(self.words) + "\n", encoding="ascii")
        self.dcp.write_bytes(b"test checkpoint provenance, not a Vivado INIT oracle")
        os.utime(self.dcp, ns=(self.mif.stat().st_mtime_ns + 1000000,) * 2)

    def test_exact_image_and_padding(self):
        self.assertEqual(audit(self.binary, self.mif, self.dcp)["mifWordsMatched"], 32768)

    def test_stale_payload(self):
        self.binary.write_bytes(self.data + b"changed firmware")
        with self.assertRaisesRegex(ValueError, "differs"):
            audit(self.binary, self.mif, self.dcp)

    def test_nonzero_padding(self):
        self.words[-1] = "1" + "0" * 31
        self.mif.write_text("\n".join(self.words) + "\n", encoding="ascii")
        os.utime(self.dcp, ns=(self.mif.stat().st_mtime_ns + 1000000,) * 2)
        with self.assertRaisesRegex(ValueError, "differs"):
            audit(self.binary, self.mif, self.dcp)

    def test_old_checkpoint(self):
        os.utime(self.dcp, ns=(self.mif.stat().st_mtime_ns - 1000000,) * 2)
        with self.assertRaisesRegex(ValueError, "predates"):
            audit(self.binary, self.mif, self.dcp)

    def test_short_mif(self):
        self.mif.write_text("\n".join(self.words[:-1]), encoding="ascii")
        with self.assertRaisesRegex(ValueError, "32768"):
            audit(self.binary, self.mif, self.dcp)

    def test_old_menu(self):
        self.binary.write_bytes(self.data + b"CPU OK r:RAM")
        with self.assertRaisesRegex(ValueError, "retired"):
            audit(self.binary, self.mif, self.dcp)


if __name__ == "__main__":
    unittest.main()
