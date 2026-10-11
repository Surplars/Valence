#!/usr/bin/env python3
import tempfile
import unittest
import test_ddr_write_collection_cli as collection_cli


class LatencyBandwidthCliTests(unittest.TestCase):
    call = collection_cli.WriteCollectionCliTests.call

    def test_forwarding_and_explicit_capacity_metadata(self):
        with tempfile.TemporaryDirectory(prefix="latency-cli-") as tmp:
            options = ["--dma-line-transfers", "--dma-line-entries", "8", "--ddr-outstanding", "8",
                       "--ddr-write-credits", "4", "--dtlb-write-read-reuse", "--line-read-channel"]
            native = self.call("fpga/next/export.py", ["--output", tmp + "/absent", *options])
            board = self.call("simulator/gsim/fpga_next_board.py",
                ["--tag", "latency-cli", "--preflight-only", "--variant", "selected", *options])
            self.assertEqual(native["command"][5:], board["plan"]["parameters"])
            for flag in ("--dma-line-entries=8", "--ddr-outstanding=8", "--ddr-write-credits=4", "--dtlb-write-read-reuse"):
                self.assertEqual(native["command"].count(flag), 1)
            config = native["configuration"]
            self.assertEqual(config["ddr_shared_slots"], 8)
            self.assertEqual(config["ddr_write_slots"], 4)
            self.assertIs(config["data_tlb_write_read_reuse"], True)
            default = self.call("fpga/next/performance.py", ["--output", tmp + "/absent"])
            self.assertEqual(default["configuration"]["ddr_shared_slots"], 4)
            self.assertEqual(default["configuration"]["ddr_write_slots"], 2)
            self.assertNotIn("data_tlb_write_read_reuse", default["configuration"])

    def test_invalid_or_duplicate_forms_rejected(self):
        with tempfile.TemporaryDirectory(prefix="latency-bad-") as tmp:
            for bad in (["--ddr-outstanding", "16"], ["--ddr-write-credits", "8"],
                        ["--ddr-outstanding", "4", "--ddr-outstanding", "8"],
                        ["--ddr-write-credits", "2", "--ddr-write-credits", "4"],
                        ["--dtlb-write-read-reuse", "--dtlb-write-read-reuse"],
                        ["--dtlb-write-read-reuse=false"], ["--dma-line-entries", "8"]):
                self.call("fpga/next/export.py", ["--output", tmp + "/absent", *bad], False)
                self.call("simulator/gsim/fpga_next_board.py", ["--tag", "latency-bad", "--preflight-only", *bad], False)


if __name__ == "__main__":
    unittest.main()
