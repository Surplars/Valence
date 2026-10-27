#!/usr/bin/env python3
"""Pure arithmetic contract check, NOT a DUT/GSIM or CPU correctness result.
The oracle stores original 64-bit addresses; candidate stores tag/boundary high.
Mutation checks validate this model's sensitivity, not production RTL coverage.
"""
import json
import random

MASK = (1 << 64) - 1
TAG_MASK = (1 << 57) - 1


class Keys:
    def __init__(self, mutant=None):
        self.tag = [[0, 0] for _ in range(16)]
        self.borrow = [[0, 0] for _ in range(2)]
        self.mutant = mutant

    def write(self, address, way, minus_two_high, enabled=True):
        if not enabled:
            return
        assert address & 7 == 0
        row = (address >> 3) & 15
        self.tag[row][way] = address >> 7
        if self.mutant == 'truncate_high':
            self.tag[row][way] &= (1 << 25) - 1
        if row < 2:
            self.borrow[row][way] = minus_two_high

    def read(self, row, way, offset):
        borrowed = row < offset
        if self.mutant == 'wrong_borrow':
            borrowed = False
        high = self.borrow[row][way] if borrowed else self.tag[row][way]
        return (high << 7) | (((row - offset) & 15) << 3)


def check(mutant=None):
    rng = random.Random(0x43414E4F4E494341)
    candidate = Keys(mutant)
    original = {}
    checks = 0
    roots = [0, 1 << 32, 1 << 54, 1 << 56, 1 << 63, MASK & ~127]
    addresses = [(root + row * 8, way) for root in roots for row in range(16) for way in range(2)]
    addresses += [(rng.getrandbits(64) & ~7, rng.randrange(2)) for _ in range(1000)]
    for address, way in addresses:
        slot = ((address >> 3) & 15, way)
        candidate.write(address, way, ((address - 16) & MASK) >> 7)
        original[slot] = address
        # Inactive payload noise cannot alter keys, including boundary rows.
        candidate.write(rng.getrandbits(64) & ~7, 1 - way, rng.getrandbits(57), False)
        for (row, stored_way), base in original.items():
            for offset in range(3):
                expected = (base - 8 * offset) & MASK
                observed = candidate.read(row, stored_way, offset)
                assert observed == expected, (mutant, hex(base), row, stored_way, offset)
                checks += 1
    return checks


def main():
    checks = check()
    rejected = []
    for mutant in ['wrong_borrow', 'truncate_high']:
        try:
            check(mutant)
        except AssertionError:
            rejected.append(mutant)
        else:
            raise AssertionError('undetected mutation: ' + mutant)
    # Boundary borrow is modulo 57, including base zero and top-of-XLEN values.
    for high in [0, 1, TAG_MASK - 1, TAG_MASK]:
        for row in [0, 1]:
            address = (high << 7) | (row << 3)
            assert (((address - 16) & MASK) >> 7) == ((high - 1) & TAG_MASK)
    print(json.dumps({'status': 'PASS', 'kind': 'pure arithmetic model only',
                      'checks': checks, 'mutants_rejected': rejected,
                      'all_sets_ways_offsets': True, 'uint64_wrap': True,
                      'inactive_write_noise': True, 'DUT_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
