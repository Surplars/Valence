import unittest
import struct
from repack_linux import board_dts, fdt_u32, HERE


class BoardClockTests(unittest.TestCase):
    def test_100mhz_460800(self):
        text = board_dts((HERE / "linux-ddr50.dts").read_text(), 100000000, 460800)
        for field in ("timebase-frequency = <100000000>;", "clock-frequency = <7372800>;",
                      "current-speed = <460800>;", 'stdout-path = "serial0:460800n8";'):
            self.assertIn(field, text)
        self.assertIn('riscv,isa = "rv64imac_zicsr_zifencei";', text)
        self.assertIn("0x80200000 0x0 0x20000000", text)
        self.assertIn('model = "Valence ZU15EG PL DDR100 single-hart";', text)

    def test_dtb_cell_that_dtc_may_render_as_string(self):
        words = lambda *values: struct.pack(">" + "I" * len(values), *values)
        tree = (words(1) + bytes(4) + words(1) + b"cpus" + bytes(4) +
                words(3, 4, 0, 460800) + words(2, 2, 9))
        strings = b"current-speed\0"
        blob = words(0xd00dfeed, 40 + len(tree) + len(strings),
                     40, 40 + len(tree), 0, 17, 16, 0, len(strings), len(tree)) + tree + strings
        self.assertEqual(fdt_u32(blob, "/cpus", "current-speed"), 460800)
        with self.assertRaises(RuntimeError):
            fdt_u32(blob, "/cpus", "missing-clock")

    def test_bad_clock_or_baud(self):
        for hz, baud in ((99999999, 460800), (50000000, 123456), (6000000, 460800)):
            with self.assertRaises(ValueError):
                board_dts("", hz, baud)

    def test_changed_template_rejected(self):
        with self.assertRaises(RuntimeError):
            board_dts("", 100000000, 460800)


if __name__ == "__main__":
    unittest.main()
