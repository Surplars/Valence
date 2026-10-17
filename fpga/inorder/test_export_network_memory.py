import unittest

from export_network import memory_style, parallel_instruction_bindings


def cache_source(leaf="mem_256x64"):
    return "\n".join(f"  {leaf} dataWays_{bank}_{way}_ext ("
                     for bank in range(8) for way in range(2))


class NetworkMemoryBindingTests(unittest.TestCase):
    def test_real_instances_bind_a_deduplicated_leaf(self):
        binding = parallel_instruction_bindings({"I1CoherentLineCache.sv": cache_source()})
        self.assertEqual(set(binding), {"mem_256x64.sv"})
        self.assertEqual(len(binding["mem_256x64.sv"]), 16)
        self.assertEqual(memory_style("mem_256x64.sv", 64, 256, binding), "block")

    def test_missing_or_duplicate_way_is_rejected(self):
        source = cache_source()
        for broken in (source.rsplit("\n", 1)[0],
                       source.replace("dataWays_7_1_ext", "dataWays_7_0_ext")):
            with self.assertRaisesRegex(RuntimeError, "geometry"):
                parallel_instruction_bindings({"I1CoherentLineCache.sv": broken})

    def test_unrelated_memory_name_does_not_qualify(self):
        with self.assertRaisesRegex(RuntimeError, "instances missing"):
            parallel_instruction_bindings({"I1CoherentLineCache.sv": "mem_256x64 buffer ("})
        self.assertIsNone(memory_style("mem_256x64.sv", 64, 256, {}))

    def test_binding_requires_actual_width_and_depth(self):
        binding = parallel_instruction_bindings({"I1CoherentLineCache.sv": cache_source()})
        for width, depth in ((32, 256), (64, 128), (64, 512)):
            self.assertIsNone(memory_style("mem_256x64.sv", width, depth, binding))

    def test_existing_data_rf_and_tag_policies_are_preserved(self):
        self.assertEqual(memory_style("data_512x64.sv", 64, 512, {}), "block")
        self.assertEqual(memory_style("mem_32x64.sv", 64, 32, {}), "block")
        self.assertEqual(memory_style("tagBanks_256x19.sv", 19, 256, {}), "distributed")
        self.assertEqual(memory_style("directoryBanks_256x20.sv", 20, 256, {}), "distributed")


if __name__ == "__main__":
    unittest.main()
