#!/usr/bin/env python3
"""Exact interval-partition proof of fixed-aperture arithmetic, not an RTL proof.

For each fixed size the oracle and candidate are conjunctions of interval
predicates. Their truth can change only at the listed endpoints. Testing one
representative of every partition cell therefore covers every 64-bit address.
A deliberate exclusive-end error must be rejected by the same checker.
"""
import json

LIMIT = 1 << 64
CASES = [
    (0x80200000, 1 << 31), (0x80000000, 1 << 31), (0x80010000, 8192),
    (0, 64), (3, 19), (0x123456000, 192), (LIMIT - 64, 64),
    (LIMIT - 71, 64), (0, LIMIT), (7, 1), (LIMIT - 64, 128),
]


def check(base, length, mutant=False):
    bits = max(3, (base ^ (base + length - 1)).bit_length())
    eligible = length >= 8 and base + length <= LIMIT and bits < 64
    count = 0
    for size in range(4):
        transfer = 1 << size
        oracle_low, oracle_end = base, base + length - transfer + 1
        if eligible:
            mask = (1 << bits) - 1
            prefix = (base >> bits) << bits
            low = base & mask
            upper = (base + length - transfer) & mask
            bounds = [prefix, prefix + (1 << bits), prefix + low, prefix + upper + 1]
        else:
            bounds = [oracle_low, oracle_end]
        # Include the mutant's additional transition; it removes the final
        # legal byte rather than changing the input-domain assumptions.
        boundary = base + length - 1
        edges = sorted({0, LIMIT, *[x for x in
            bounds + [oracle_low, oracle_end, boundary, boundary + 1] if 0 <= x <= LIMIT]})
        for address, end in zip(edges, edges[1:]):
            assert address < end
            expected = address >= base and address + transfer <= base + length
            actual = ((address >> bits) == (base >> bits) and
                      low <= (address & mask) <= upper) if eligible else expected
            if mutant:
                actual = actual and address != boundary
            if expected != actual:
                return False, {"address": hex(address), "size": size}
            count += 1
    return True, {"partition_cells": count, "split_bits": bits if eligible else None}


if __name__ == "__main__":
    results = []
    for base, length in CASES:
        passed, details = check(base, length)
        assert passed, (base, length, details)
        results.append({"base": hex(base), "bytes": length, **details})
    passed, counterexample = check(*CASES[0], mutant=True)
    assert not passed, "Boundary mutant escaped the checker"
    print(json.dumps({"status": "PASS_ALGORITHM_INTERVAL_PARTITION_ONLY",
                      "scope": "all 64-bit addresses and all four size values per fixed aperture",
                      "rtl_equivalence": "not established by this script",
                      "cases": results, "boundary_mutant_counterexample": counterexample}, indent=2))
