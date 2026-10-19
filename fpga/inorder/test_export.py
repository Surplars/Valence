import unittest
from export import stamp_ram_attribute


class RamAnnotationTest(unittest.TestCase):
    def test_attribute_only_and_both_implementations(self):
        original = "module bank_32x64(\n);\n  reg [63:0] Memory[0:31];\nendmodule\n"
        for style in ("block", "distributed"):
            emitted = stamp_ram_attribute(original, style)
            self.assertEqual(emitted.replace(f'(* ram_style = "{style}" *)\n', ""), original)

    def test_reject_shape_or_attribute_drift(self):
        original = "module bank_32x64(\n);\n  reg [63:0] Memory[0:31];\nendmodule\n"
        for changed in (original.replace("[63:0]", "[31:0]"), original + original,
                        original.replace("bank_32x64", "another_memory"),
                        '(* ram_style = "block" *)\n' + original):
            with self.assertRaises(RuntimeError):
                stamp_ram_attribute(changed, "block")
        with self.assertRaises(ValueError):
            stamp_ram_attribute(original, "registers")


if __name__ == "__main__":
    unittest.main()
