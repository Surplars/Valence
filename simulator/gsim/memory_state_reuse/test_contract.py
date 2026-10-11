#!/usr/bin/env python3
"""Small source/host algebra gates only, never DUT qualification."""
import itertools
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]


def decode_owner(slot, tag, stored_index, reconstructed, entries=64):
    if not 0 <= slot < entries or not 0 <= tag < 1 << 64:
        raise ValueError("invalid bound queue layout")
    return (slot if reconstructed else stored_index, tag)


def accepted(owner, completion, live):
    return live and owner == completion


class Contract(unittest.TestCase):
    def test_fixed_index_two_lane_wrap_and_full_tags(self):
        tags = (0, 1, (1 << 32) + 7, (1 << 63) + 7, (1 << 64) - 1)
        for head, lane, tag in itertools.product(range(64), range(2), tags):
            slot = (head + lane) % 64
            before = decode_owner(slot, tag, slot, False)
            after = decode_owner(slot, tag, 0, True)
            self.assertEqual(before, after)
            for live in (False, True):
                self.assertEqual(accepted(before, (slot, tag), live), live)
                self.assertEqual(accepted(after, (slot, tag), live), live)
                self.assertFalse(accepted(after, (slot, tag ^ (1 << 63)), live))
                self.assertFalse(accepted(after, ((slot + 1) % 64, tag), live))

    def test_store_load_slot_reuse_does_not_reuse_generation(self):
        for slot in range(64):
            old = decode_owner(slot, 17, 0, True)
            for tag in (18, (1 << 63) + 17):
                new = decode_owner(slot, tag, 0, True)
                self.assertFalse(accepted(new, old, True))
                self.assertFalse(accepted(new, new, False))
                self.assertTrue(accepted(new, new, True))

    def test_no_raw_queue_reads_remain(self):
        source = (ROOT / 'src/main/scala/core/ooo/IntegerBackend.scala').read_text()
        references = [line.strip() for line in source.splitlines()
                      if not line.lstrip().startswith('//') and re.search(r'\bqueue[.(]', line)]
        self.assertEqual(references, [
            'queue(renamed.bits.token.index).renamed := renamed.bits',
            'queue(renamed.bits.token.index).renamed.token.index := 0.U',
            'queue(renamed.bits.token.index).request := io.allocate(lane).bits',
            'ImmutableIssuePayload.insert(queue(renamed.bits.token.index).request,'])
        self.assertIn('entries(slot).renamed.token.index := slot.U(p.robBits.W)', source)
        self.assertIn('} else queue', source)
        self.assertIn('CircularIssueSelector.selectPayload(mask, issueEntries.map(_.asUInt).toSeq)', source)
        self.assertIn('issueEntries(ownerIndex).renamed.token.asUInt =/= entry.renamed.token.asUInt', source)
        self.assertIn('issueEntries(slot).renamed.token.asUInt === operand.token.asUInt', source)
        probe = (ROOT / 'src/test/scala/ooo/PostedPreparationPriorityGsim.scala').read_text()
        self.assertIn('backend.issueEntries(i).renamed.token', probe)
        self.assertNotIn('backend.queue(i).renamed.token', probe)


if __name__ == '__main__':
    unittest.main(verbosity=2)
