"""Synthetic parser regressions, not evidence that a hardware model ran."""
import unittest

from memory_capacity_geometry import verify_memory_geometry


REQUEST = ("{ request : { atomic : UInt<1>, atomicOp : UInt<5>, address : UInt<64>, "
           "write : UInt<1>, size : UInt<2>, data : UInt<64>, mask : UInt<8>, "
           "virtualized : UInt<1>, precheckedLoad : UInt<1>, translationEpoch : UInt<32>, "
           "prefetchNextAllowed : UInt<1>, uncached : UInt<1>}}")


def fixture(slots, wrapped):
    request_module = "RegisteredRequestQueue" if wrapped else "DirectRequestQueue"
    lines = ["circuit Test :", "  module IntegerBackend :",
             "    inst lsu of ParallelLoadStoreUnit @[fixture]",
             f"    inst requests of {request_module} @[fixture]",
             "  module ParallelLoadStoreUnit :"]
    lines += [f"    inst slots_{i} of LoadStoreUnit @[fixture]" for i in range(slots)]
    lines += ["    inst owners of ResponseOwnerQueue @[fixture]", "  module LoadStoreUnit :"]
    if wrapped:
        lines += ["  module RegisteredRequestQueue :",
                  f"    inst entries of Queue{slots}_RegisteredRequestEntry @[fixture]",
                  f"  module Queue{slots}_RegisteredRequestEntry :"]
    else:
        lines += ["  module DirectRequestQueue :"]
    lines += [f"    cmem ram : {REQUEST}[{slots}] @[fixture]",
              "  module ResponseOwnerQueue :",
              f"    cmem ram : UInt<{1 if slots == 2 else 2}>[{slots}] @[fixture]",
              "  module StoreBuffer :", "    reg entries : UInt<64>[2], clock @[fixture]",
              "    inst owners of StoreOwnerQueue @[fixture]", "  module StoreOwnerQueue :",
              f"    cmem ram : UInt<1>[{slots + 1}] @[fixture]"]
    return "\n".join(lines) + "\n"


class MemoryCapacityGeometryTest(unittest.TestCase):
    def test_direct_and_wrapped_two_and_four_slot_queues(self):
        for slots in (2, 4):
            for wrapped in (False, True):
                with self.subTest(slots=slots, wrapped=wrapped):
                    actual = verify_memory_geometry(fixture(slots, wrapped), slots)
                    self.assertEqual(actual["lsu_slots"], slots)
                    self.assertEqual(actual["store_buffer"]["physical_owner_credits"], slots + 1)

    def test_request_depth_mismatch_is_rejected(self):
        source = fixture(4, True).replace(f"{REQUEST}[4]", f"{REQUEST}[2]")
        with self.assertRaisesRegex(RuntimeError, "queue RAM differs"):
            verify_memory_geometry(source, 4)

    def test_missing_nested_request_queue_is_rejected(self):
        source = fixture(2, True).replace("inst entries of", "inst unrelated of")
        with self.assertRaisesRegex(RuntimeError, "Missing emitted instance: entries"):
            verify_memory_geometry(source, 2)

    def test_wrong_nested_module_is_rejected(self):
        source = fixture(2, True).replace("Queue2_RegisteredRequestEntry", "UnrelatedQueue")
        with self.assertRaisesRegex(RuntimeError, "request-entry Queue"):
            verify_memory_geometry(source, 2)

    def test_nested_queue_requires_the_actual_request_payload(self):
        source = fixture(2, True).replace(REQUEST, "UInt<1>")
        with self.assertRaisesRegex(RuntimeError, "actual request payload"):
            verify_memory_geometry(source, 2)

    def test_response_owner_width_mismatch_is_rejected(self):
        source = fixture(4, True).replace("UInt<2>[4]", "UInt<1>[4]")
        with self.assertRaisesRegex(RuntimeError, "queue RAM differs"):
            verify_memory_geometry(source, 4)

    def test_store_owner_credit_depth_mismatch_is_rejected(self):
        source = fixture(4, True).replace("UInt<1>[5]", "UInt<1>[3]")
        with self.assertRaisesRegex(RuntimeError, "queue RAM differs"):
            verify_memory_geometry(source, 4)


if __name__ == "__main__":
    unittest.main()
