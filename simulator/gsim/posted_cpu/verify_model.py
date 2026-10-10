"""Census actual emitted board hardware before accepting any posted ON/OFF label."""
import re


def _module(fir, name):
    found = re.search(r"^  (?:public )?module " + re.escape(name) + r"\s*:.*?(?=^  (?:public )?(?:module|extmodule) |\Z)",
                      fir, re.M | re.S)
    if not found:
        raise RuntimeError("missing actual emitted module: " + name)
    return found[0]


def verify_posted_model(fir, enabled, rob_entries=16):
    if rob_entries not in (16, 32, 64):
        raise ValueError("unsupported explicit ROB capacity")
    index_bits = (rob_entries - 1).bit_length()
    backend = _module(fir, "IntegerBackend")
    cache = _module(fir, "NonBlockingCoherentLineCache")
    stores = _module(fir, "StoreBuffer")
    def io(body):
        return next(line for line in body.splitlines() if line.startswith("    output io :"))
    for actual, expected, message in [
        ("posted :" in io(backend), enabled, "CPU optional posted port"),
        ("posted :" in io(cache), enabled, "cache optional posted port"),
        ("upstreamProof :" in io(stores), enabled, "StoreBuffer optional proof port"),
        (bool(re.search(r"^  module PostedStoreMerge\s*:", fir, re.M)), enabled, "actual merge owner"),
    ]:
        if actual != expected:
            raise RuntimeError(message + " disagrees with explicit posted selector")
    for field in ("valid : UInt<1>[512]", "replacement : UInt<1>[256]",
                  "responseOwned : UInt<1>[2]", "wbLive : UInt<1>[2]"):
        if field not in cache:
            raise RuntimeError("actual cache geometry differs: " + field)
    if enabled:
        owner = _module(fir, "PostedStoreMerge")
        for field in (f"index : UInt<{index_bits}>, tag : UInt<64>", "generation : UInt<64>", "epoch : UInt<32>",
                      "set : UInt<8>", "responseTicket : UInt<1>"):
            if field not in owner:
                raise RuntimeError("actual owner width differs: " + field)
        if "headAuthorized" not in backend or "finalChecked" not in cache or "proofs :" not in stores:
            raise RuntimeError("actual CPU-to-cache proof lineage absent")
    elif "postedContext :" in cache or "proofs :" in stores or "requestProof :" in backend:
        raise RuntimeError("OFF hardware retained optional posted storage")
    return {"status": "PASS_EMITTED_POSTED_CENSUS", "enabled": enabled, "owner_generation_bits": 64 if enabled else 0,
            "cpu_token_bits": {"index": index_bits, "tag": 64} if enabled else None,
            "cache_lines": 512, "cache_sets": 256, "response_entries": 2, "writeback_entries": 2}
