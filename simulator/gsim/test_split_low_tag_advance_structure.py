#!/usr/bin/env python3
import unittest
from split_low_tag_advance_structure import review
from registered_raw_certified_cones import Uncertain

CONTROL = '''FIRRTL version 6.0.0
circuit RenameRob :
  module RenameRob :
    input clock : Clock
    input reset : UInt<1>
    input request : UInt<2>
    regreset nextTag : UInt<64>, clock, reset, UInt<64>(0h0)
    regreset exhausted : UInt<1>, clock, reset, UInt<1>(0h0)
    node allocatedCount = request
    node advancedTag = add(nextTag, allocatedCount)
    node lane1 = add(nextTag, UInt<1>(0h1))
    when neq(allocatedCount, UInt<1>(0h0)) :
      connect nextTag, advancedTag
      connect exhausted, bits(advancedTag, 64, 64)
'''
HELPER = '''node low = add(bits(nextTag, 1, 0), allocatedCount)
    node high = bits(nextTag, 63, 2)
    node highIncremented = add(high, UInt<1>(0h1))
    node selectedHigh = mux(bits(low, 2, 2), highIncremented, cat(UInt<1>(0h0), high))
    node advancedTag = cat(selectedHigh, bits(low, 1, 0))'''
CANDIDATE=CONTROL.replace('node advancedTag = add(nextTag, allocatedCount)',HELPER)


class StructureTests(unittest.TestCase):
    def test_exact_delta(self):
        self.assertEqual(review(CONTROL,CANDIDATE)['state_delta'],0)

    def reject(self, text):
        with self.assertRaises(Uncertain): review(CONTROL,text)

    def test_unrelated_dynamic_index_is_preserved_exactly(self):
        extra='    connect lane1, entries[head].tag\n'
        self.assertEqual(review(CONTROL+extra,CANDIDATE+extra)['state_delta'],0)
        with self.assertRaises(Uncertain):
            review(CONTROL+extra,CANDIDATE+extra.replace('head','tail'))

    def test_wrong_carry(self):
        self.reject(CANDIDATE.replace('bits(low, 2, 2)','bits(low, 1, 1)'))

    def test_count_in_high(self):
        self.reject(CANDIDATE.replace('add(high, UInt<1>(0h1))','add(high, allocatedCount)'))

    def test_lost_overflow(self):
        self.reject(CANDIDATE.replace('bits(advancedTag, 64, 64)','UInt<1>(0h0)'))

    def test_sticky_or(self):
        self.reject(CANDIDATE.replace('connect exhausted, bits(advancedTag, 64, 64)',
            'connect exhausted, or(exhausted, bits(advancedTag, 64, 64))'))

    def test_extra_state(self):
        self.reject(CANDIDATE+'    regreset stage : UInt<64>, clock, reset, UInt<64>(0h0)\n')

    def test_lost_enable(self):
        self.reject(CANDIDATE.replace('when neq(allocatedCount, UInt<1>(0h0)) :','when UInt<1>(0h1) :'))

    def test_lane_change(self):
        self.reject(CANDIDATE.replace('node lane1 = add(nextTag, UInt<1>(0h1))','node lane1 = advancedTag'))

    def test_unexpected_helper_reference(self):
        self.reject(CANDIDATE.replace('bits(nextTag, 63, 2)','bits(other, 63, 2)'))

    def test_duplicate_helper_node(self):
        self.reject(CANDIDATE+'    node high = UInt<62>(0h0)\n')

    def test_extra_module(self):
        self.reject(CANDIDATE+'  module Extra :\n    input clock : Clock\n')

if __name__=='__main__': unittest.main()
