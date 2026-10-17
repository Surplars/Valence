import unittest
from check_directory_writer import inspect_leaf


class DirectoryWriterTests(unittest.TestCase):
    def setUp(self):
        self.leaf = """module directoryBanks_256x20 (
input [7:0] W0_addr, input W0_en, output [19:0] R0_data);
reg [19:0] Memory[0:255];
always @(posedge W0_clk) if (W0_en) Memory[W0_addr] <= W0_data;
assign R0_data = Memory[R0_addr]; endmodule"""

    def test_single_writer(self):
        self.assertEqual(inspect_leaf(self.leaf),
            {"width": 20, "depth": 256, "write_ports": 1, "read_ports": 1})

    def test_second_writer_rejected(self):
        with self.assertRaises(ValueError):
            inspect_leaf(self.leaf + "\nif (W1_en) Memory[W1_addr] <= W1_data;")

    def test_capacity_change_rejected(self):
        with self.assertRaises(ValueError):
            inspect_leaf(self.leaf.replace("[0:255]", "[0:511]"))
