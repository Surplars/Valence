"""Fail-closed capacity census of actual emitted state, independent of labels.

This checks declared async memories and register geometry. It makes no claim
about FPGA RAM inference, mapped area, timing or behavioral correctness.
"""
import re

from memory_capacity_geometry import module, child


def verify_backend_capacity(fir, rob_entries, physical_regs):
    if rob_entries not in (16, 32, 64) or physical_regs not in (48, 64):
        raise ValueError("unsupported explicit backend geometry")
    index_bits = (rob_entries - 1).bit_length()
    count_bits = rob_entries.bit_length()
    physical_bits = (physical_regs - 1).bit_length()
    backend = module(fir, "IntegerBackend")
    ledger = child(fir, backend, "ledger")

    def expect(body, pattern, label):
        matches = re.findall(pattern, body, re.M)
        if len(matches) != 1:
            raise ValueError("backend capacity: missing or ambiguous " + label)

    expect(ledger, rf"^    reg entries : [^\n]+\[{rob_entries}\], clock", "ROB entries")
    for pointer in ("head", "tail"):
        expect(ledger, rf"^    regreset {pointer} : UInt<{index_bits}>,", "ROB " + pointer)
    expect(ledger, rf"^    regreset count : UInt<{count_bits}>,", "ROB occupancy")
    expect(ledger, rf"^    regreset free : UInt<1>\[{physical_regs}\],", "physical free map")
    expect(backend, rf"^    regreset ready : UInt<1>\[{physical_regs}\],", "physical ready map")
    if f"index : UInt<{index_bits}>, tag : UInt<64>" not in ledger:
        raise ValueError("backend capacity: full ROB token width differs")
    if f"destination : UInt<{physical_bits}>" not in ledger:
        raise ValueError("backend capacity: physical destination width differs")

    payload = child(fir, ledger, "allocationPayload")
    banks = re.findall(r"^    cmem (memory(?:_\d+)?) : UInt<(\d+)>\[(\d+)\] ", payload, re.M)
    if sorted((int(width), int(depth)) for _, width, depth in banks) != [(96, rob_entries // 2)] * 2:
        raise ValueError("backend capacity: ROB parity payload banks differ")
    prf = child(fir, backend, "physicalFile")
    banks = re.findall(r"^    cmem (banks_\d+) : UInt<(\d+)>\[(\d+)\] ", prf, re.M)
    if sorted((int(width), int(depth)) for _, width, depth in banks) != [(64, physical_regs)] * 2:
        raise ValueError("backend capacity: PRF owner data banks differ")
    for field in ("initialized", "owner"):
        expect(prf, rf"^    regreset {field} : UInt<1>\[{physical_regs}\],", "PRF " + field)
    owner_ready = child(fir, backend, "ownerReady")
    for field in ("ready1", "ready2"):
        expect(owner_ready, rf"^    regreset {field} : UInt<1>\[{rob_entries}\],", "owner " + field)
    return {"status": "PASS_EMITTED_BACKEND_GEOMETRY", "rob_entries": rob_entries,
            "physical_regs": physical_regs, "rob_index_bits": index_bits, "rob_count_bits": count_bits,
            "physical_index_bits": physical_bits, "token_tag_bits": 64,
            "token_total_bits": index_bits + 64, "rob_payload_banks": 2,
            "rob_payload_bank_depth": rob_entries // 2, "prf_data_banks": 2,
            "storage_layout_changed": False, "mapped_ram_inference": "UNVERIFIED"}
