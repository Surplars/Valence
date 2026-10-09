#!/usr/bin/env python3
"""Independent host policy checks only. This does not execute Scala or RTL."""
from dataclasses import dataclass, replace
import itertools
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[4]
PUBLIC = '926ea18ecab93364a1a7b1ae745fc674c275c2b1'


def mask_select(ordinary, prepared, count, head, issued, enabled=True):
    pool = ordinary if ordinary else prepared if enabled else 0
    ranked = sorted((i for i in range(count) if pool & (1 << i)), key=lambda i: (i - head) % count)
    first = ranked[0] if ranked else None
    if first == issued:
        return ranked[1] if len(ranked) > 1 else None
    return first


def reference(ordinary, prepared, count, head, issued, enabled=True):
    # The original ready work reserves priority even when its sole owner issues.
    permitted = {i for i in range(count) if ordinary & (1 << i)}
    if not permitted and enabled:
        permitted = {i for i in range(count) if prepared & (1 << i)}
    for offset in range(count):
        index = (head + offset) % count
        if index in permitted and index != issued:
            return index
    return None


@dataclass(frozen=True)
class Entry:
    index: int = 1
    token_index: int = 1
    pending: bool = True
    memory_live: bool = True
    memory: bool = True
    store: bool = True
    atomic: bool = False
    system: bool = False
    muldiv: bool = False
    control: bool = False
    operation_add: bool = True
    fetch_fault: bool = False
    fetch_page_fault: bool = False
    prepared: bool = True
    address_known: bool = True
    safe_range: bool = True
    virtualized: bool = False


def admissible(e, head):
    return (e.pending and e.memory_live and e.index != head and e.token_index == e.index
            and e.memory and e.store and not e.atomic and not e.system and not e.muldiv
            and not e.control and e.operation_add and not e.fetch_fault and not e.fetch_page_fault
            and e.prepared and e.address_known and e.safe_range and not e.virtualized)


class Policy(unittest.TestCase):
    def test_exhaustive_original_pool_priority_and_wrap(self):
        for n in (2, 4):
            for ordinary, prepared, head, issued, enabled in itertools.product(
                    range(1 << n), range(1 << n), range(n), [None] + list(range(n)), (False, True)):
                self.assertEqual(mask_select(ordinary, prepared, n, head, issued, enabled),
                                 reference(ordinary, prepared, n, head, issued, enabled))

    def test_sole_issued_original_does_not_expose_fallback(self):
        for original, younger in itertools.permutations(range(4), 2):
            for head in range(4):
                self.assertIsNone(mask_select(1 << original, 1 << younger, 4, head, original))
                # This is the forbidden after-exclusion variant, and is observably different.
                self.assertEqual(mask_select(0, 1 << younger, 4, head, original), younger)

    def test_disabled_selection_matches_original_for_all_masks(self):
        for ordinary, head, issued in itertools.product(range(16), range(4), [None, 0, 1, 2, 3]):
            self.assertEqual(mask_select(ordinary, 15, 4, head, issued, False),
                             reference(ordinary, 0, 4, head, issued, False))

    def test_each_nonordinary_or_unprepared_class_is_rejected(self):
        e = Entry()
        self.assertTrue(admissible(e, 0))
        excluded = dict(pending=False, memory_live=False, memory=False, store=False, atomic=True,
                        system=True, muldiv=True, control=True, operation_add=False, fetch_fault=True,
                        fetch_page_fault=True, prepared=False, address_known=False, safe_range=False,
                        virtualized=True, token_index=2)
        for field, value in excluded.items():
            with self.subTest(field=field):
                self.assertFalse(admissible(replace(e, **{field: value}), 0))
        self.assertFalse(admissible(e, 1))

    def test_new_original_load_preempts_existing_store_prefill(self):
        self.assertEqual(mask_select(0, 1 << 1, 4, 0, None), 1)
        self.assertEqual(mask_select(1 << 3, 1 << 1, 4, 0, None), 3)
        # When that saved store becomes the actual head, it joins the original pool.
        self.assertEqual(mask_select((1 << 1) | (1 << 3), 0, 4, 1, None), 1)

    def test_original_launch_and_recovery_source_is_byte_identical(self):
        relative = 'src/main/scala/core/ooo/IntegerBackend.scala'
        base = subprocess.check_output(['git', 'show', PUBLIC + ':' + relative], cwd=ROOT, text=True)
        current = (ROOT / relative).read_text()
        # Only planner input preparation may change. Everything after candidate
        # payload capture, including full-token, PMP, launch and recovery, is exact.
        self.assertEqual(base.split('            planner.io.head := head', 1)[1],
                         current.split('            planner.io.head := head', 1)[1])
        self.assertEqual(base.split('            planner.io.eligible :=', 1)[0],
                         current.split('            val originalMemoryMask =', 1)[0])
        for token in ('queue(stagedMemoryIndex.get).renamed.token.asUInt === stagedMemoryToken.get.asUInt',
                      '(memoryChoice.index === head || (speculative && !blockedByStore))',
                      'lsu.io.start.bits.accessDenied  := pmpCheck.io.denied && !virtualized'):
            self.assertIn(token, current)


if __name__ == '__main__':
    unittest.main(verbosity=2)
