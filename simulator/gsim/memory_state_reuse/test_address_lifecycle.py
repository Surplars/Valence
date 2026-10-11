#!/usr/bin/env python3
"""Independent reference/compact host state models; this is not a DUT test."""
from copy import deepcopy
import itertools
import unittest


def lanes(address, size):
    return (((1 << (1 << size)) - 1) << (address & 7)) & 255


def fresh():
    return dict(token=None, live=False, pending=False, store=False, atomic=False,
                canonical=False, known=False, address=0, lanes=0, beat=0,
                load_lanes=0, shared_address=0, shared_lanes=0)


class Models:
    def __init__(self, rows=64):
        self.rows = [fresh() for _ in range(rows)]

    def tick(self, allocate=(), starts=(), prepare=(), killed=(), retired=(), poison=False):
        old = deepcopy(self.rows)
        for slot in set(killed) | set(retired):
            self.rows[slot].update(live=False, pending=False, canonical=False, known=False)
        load_writes = set()
        for slot, token, address, size, canonical in starts:
            owner, row = old[slot], self.rows[slot]
            assert owner['live'] and owner['pending'] and owner['token'] == token and slot not in killed
            row.update(pending=False, canonical=canonical, beat=address >> 3, load_lanes=lanes(address, size))
            if poison or not (owner['store'] or owner['atomic']):
                row.update(shared_address=address & ~7, shared_lanes=lanes(address, size))
                load_writes.add(slot)
        store_writes = set()
        for slot, token, address, size in prepare:
            owner, row = old[slot], self.rows[slot]
            # Independent captured full-token ownership is revalidated at write time.
            if owner['live'] and owner['pending'] and slot not in killed and owner['token'] == token:
                assert owner['store']
                assert slot not in store_writes and slot not in load_writes
                store_writes.add(slot)
                row.update(known=True, address=address, lanes=lanes(address, size),
                           shared_address=address, shared_lanes=lanes(address, size))
        # Accepted allocation has the original final validity/class priority.
        for slot, token, store, atomic in allocate:
            assert token[0] == slot
            self.rows[slot].update(token=token, live=True, pending=True, store=store,
                                   atomic=atomic, canonical=False, known=False)
        self.check()
        return load_writes, store_writes

    def check(self):
        for row in self.rows:
            if row['live'] and row['store'] and row['known']:
                assert (row['address'], row['lanes']) == (row['shared_address'], row['shared_lanes'])
            if row['live'] and not row['pending'] and not row['store'] and not row['atomic'] and row['canonical']:
                assert (row['beat'], row['load_lanes']) == (row['shared_address'] >> 3, row['shared_lanes'])


class Lifecycle(unittest.TestCase):
    def test_two_preparations_and_one_load_preserve_all_ports(self):
        for size in range(4):
            m = Models()
            m.tick(allocate=[(s, (s, (1 << 63) + s), s != 2, False) for s in (0, 1, 2)])
            writes = m.tick(starts=[(2, (2, (1 << 63) + 2), 0x80001000 + (1 << size), size, True)],
                            prepare=[(s, (s, (1 << 63) + s), 0x12345000 + (s << 3), size) for s in (0, 1)])
            self.assertEqual(writes, ({2}, {0, 1}))

    def test_store_start_preserves_virtual_address_and_negative_rejects(self):
        for size, low in itertools.product(range(4), range(8)):
            m = Models()
            m.tick(allocate=[(63, (63, 7), True, False)])
            m.tick(prepare=[(63, (63, 7), 0x10001000 + low, size)])
            poisoned = deepcopy(m)
            m.tick(starts=[(63, (63, 7), 0x80003000 + low, size, False)])
            self.assertEqual(m.rows[63]['shared_address'], 0x10001000 + low)
            with self.assertRaises(AssertionError):
                poisoned.tick(starts=[(63, (63, 7), 0x80003000 + low, size, False)], poison=True)

    def test_store_start_and_prior_cycle_capture_same_row(self):
        m = Models()
        m.tick(allocate=[(4, (4, 10), True, False)])
        loads, stores = m.tick(starts=[(4, (4, 10), 0x9000, 3, True)],
                               prepare=[(4, (4, 10), 0x5000, 3)])
        self.assertEqual((loads, stores), (set(), {4}))
        self.assertEqual(m.rows[4]['shared_address'], 0x5000)

    def test_atomic_start_never_becomes_replay_payload(self):
        for store in (False, True):
            m = Models()
            m.rows[3].update(shared_address=0x1005, shared_lanes=32)
            m.tick(allocate=[(3, (3, 11), store, True)])
            loads, _ = m.tick(starts=[(3, (3, 11), 0x9000, 3, True)])
            self.assertEqual(loads, set())
            self.assertEqual((m.rows[3]['shared_address'], m.rows[3]['shared_lanes']), (0x1005, 32))

    def test_all_rows_wrap_store_load_store_reuse_and_stale_captures(self):
        for slot in range(64):
            m = Models()
            previous, current, following = (slot, 7), (slot, (1 << 63) + 7), (slot, (1 << 63) + 8)
            m.tick(allocate=[(slot, previous, True, False)])
            m.tick(prepare=[(slot, previous, 0x7003, 0)])
            # Kill and new allocation share an edge with the old delayed capture.
            m.tick(killed=[slot], prepare=[(slot, previous, 0xDEAD, 0)],
                   allocate=[(slot, current, False, False)])
            m.tick(starts=[(slot, current, 0x80001000, 3, True)],
                   prepare=[(slot, previous, 0xDEAD, 0)])
            self.assertEqual(m.rows[slot]['shared_address'], 0x80001000)
            m.tick(retired=[slot], allocate=[(slot, following, True, False)])
            self.assertFalse(m.rows[slot]['known'])
            m.tick(prepare=[(slot, following, 0x1006, 1), (slot, previous, 0xDEAD, 0)])
            self.assertEqual(m.rows[slot]['shared_address'], 0x1006)

    def test_uncanonical_fault_widths_and_held_replay_payload(self):
        for size, low, canonical in itertools.product(range(4), range(8), (False, True)):
            m = Models()
            m.tick(allocate=[(0, (0, 99), False, False)])
            m.tick(starts=[(0, (0, 99), 0x80000000 + low, size, canonical)])
            saved = deepcopy(m.rows[0])
            for _ in range(3):
                m.tick()
                self.assertEqual(m.rows[0], saved)
            m.tick(killed=[0])
            self.assertFalse(m.rows[0]['live'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
