"""Strict emitted FIR capacity proof, independent of profile-name receipts."""
import re


def module(fir, name):
    found = re.search(r"^  module " + re.escape(name) + r"\s*:.*?(?=^  (?:module|extmodule) |\Z)", fir, re.M | re.S)
    if not found:
        raise RuntimeError("Missing emitted module: " + name)
    return found[0]


def child(fir, body, instance):
    found = re.search(r"^    inst " + re.escape(instance) + r" of (\w+) ", body, re.M)
    if not found:
        raise RuntimeError("Missing emitted instance: " + instance)
    return module(fir, found[1])


def ram(body, depth, scalar_width=None):
    found = re.search(r"^    [cs]mem ram : (.+)\[(\d+)\] ", body, re.M)
    if not found or int(found[2]) != depth or (scalar_width is not None and found[1] != f"UInt<{scalar_width}>"):
        raise RuntimeError(f"Emitted queue RAM differs: depth={depth}, width={scalar_width}")
    return found[0].strip()


def verify_store_geometry(fir, slots):
    body = module(fir, "StoreBuffer")
    entries = re.search(r"^    reg entries : (.+)\[(\d+)\], clock", body, re.M)
    if not entries or int(entries[2]) != 2:
        raise RuntimeError("StoreBuffer must retain two write entries")
    owners = ram(child(fir, body, "owners"), slots + 1, 1)
    return {"write_entries": 2, "physical_owner_credits": slots + 1, "owner_ram": owners}


def verify_memory_geometry(fir, slots):
    if slots not in (2, 4):
        raise ValueError("Experiment geometry must explicitly be two or four slots")
    backend = module(fir, "IntegerBackend")
    lsu = child(fir, backend, "lsu")
    instances = re.findall(r"^    inst slots_(\d+) of LoadStoreUnit(?:_\d+)? ", lsu, re.M)
    if sorted(map(int, instances)) != list(range(slots)):
        raise RuntimeError("Emitted LSU slots differ from expected geometry")
    requests = ram(child(fir, backend, "requests"), slots)
    owners = ram(child(fir, lsu, "owners"), slots, 1 if slots == 2 else 2)
    return {"status": "PASS_EMITTED_MEMORY_GEOMETRY", "lsu_slots": slots,
            "request_fifo": requests, "lsu_owner_fifo": owners,
            "store_buffer": verify_store_geometry(fir, slots)}
