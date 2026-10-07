"""Fast capacity provenance tests with deliberately corrupted emitted geometry."""
import unittest
from memory_capacity_geometry import verify_memory_geometry


def fixture(slots):
    width = 1 if slots == 2 else 2
    return ("  module IntegerBackend :\n    inst lsu of ParallelLoadStoreUnit \n"
            "    inst requests of Requests \n  module ParallelLoadStoreUnit :\n" +
            "".join(f"    inst slots_{i} of LoadStoreUnit_{i} \n" for i in range(slots)) +
            "    inst owners of Owners \n  module Requests :\n" +
            f"    cmem ram : {{ address : UInt<64>}}[{slots}] \n  module Owners :\n" +
            f"    cmem ram : UInt<{width}>[{slots}] \n  module StoreBuffer :\n" +
            "    reg entries : { write : UInt<1>}[2], clock\n    inst owners of StoreOwners \n" +
            f"  module StoreOwners :\n    cmem ram : UInt<1>[{slots + 1}] \n")


class GeometryTest(unittest.TestCase):
    def test_two_and_four_explicit(self):
        for slots in (2, 4):
            self.assertEqual(verify_memory_geometry(fixture(slots), slots)["lsu_slots"], slots)
            with self.assertRaises(RuntimeError):
                verify_memory_geometry(fixture(slots), 6 - slots)

    def test_each_coupled_capacity_rejects_corruption(self):
        text = fixture(4)
        for old, new in (("slots_3", "slots_4"), ("UInt<64>}[4]", "UInt<64>}[2]"),
                         ("UInt<2>[4]", "UInt<1>[4]"), ("UInt<1>[5]", "UInt<1>[3]"),
                         ("UInt<1>}[2], clock", "UInt<1>}[4], clock")):
            self.assertIn(old, text)
            with self.assertRaises(RuntimeError):
                verify_memory_geometry(text.replace(old, new), 4)


if __name__ == "__main__":
    unittest.main()
