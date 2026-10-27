"""Synthetic structural-reader tests only, not generated candidate proof."""
import unittest
from factored_pmp_structure import WidthAudit, review_text, widths
from registered_raw_certified_cones import Module, Uncertain


def fixture():
    return '''FIRRTL version 6.0.0
circuit PmpGenericRangeComparisons :
  public module PmpGenericRangeComparisons :
    input clock : Clock
    input reset : Reset
    output io : { flip address : UInt<64>, flip size : UInt<3>, flip regionLow : UInt<65>[1], flip regionEnd : UInt<65>[1], flip regionActive : UInt<1>[1], overlap : UInt<1>[1], covers : UInt<1>[1]}
    node firstHigh = cat(UInt<1>(0h0), bits(io.address, 63, 7))
    node lowSum = add(bits(io.address, 6, 0), pad(io.size, 7))
    node lowerSub = sub(bits(io.regionLow[0], 64, 7), UInt<58>(0h1))
    node lowerPredecessor = tail(lowerSub, 1)
    node upperPredecessor = tail(sub(bits(io.regionEnd[0], 64, 7), UInt<58>(0h1)), 1)
    node lower = and(eq(firstHigh, lowerPredecessor), geq(lowSum, bits(io.regionLow[0], 6, 0)))
    node upper = and(eq(firstHigh, upperPredecessor), leq(lowSum, bits(io.regionEnd[0], 6, 0)))
    node predicate = and(lower, upper)
    connect io.overlap[0], and(io.regionActive[0], predicate)
    connect io.covers[0], predicate
'''


class FactoredStructureTests(unittest.TestCase):
    def test_toy_shape_pass_not_functional_claim(self):
        result = review_text(fixture())
        self.assertEqual(result['modules']['PmpGenericRangeComparisons']['entries'], 1)
        self.assertEqual(len(result['instances']), 1)

    def test_parent_direct_endpoint_arithmetic_rejected(self):
        original = fixture()
        body = original.split('  public module PmpGenericRangeComparisons :\n',1)[1]
        parent = ('FIRRTL version 6.0.0\ncircuit PmpChecker :\n' +
                  '  module PmpGenericRangeComparisons :\n' + body +
                  '  public module PmpChecker :\n' +
                  '    input address : UInt<64>\n' +
                  '    inst ranges of PmpGenericRangeComparisons\n')
        self.assertEqual(review_text(parent)['factoredParents']['PmpChecker']['directArithmetic'],0)
        with self.assertRaises(Uncertain):
            review_text(parent + '    node extra = add(address, UInt<7>(0h7f))\n')

    def test_nested_unsigned_widths(self):
        self.assertEqual(widths('{ flip a : UInt<65>[2], b : { x : UInt<3>}}', 'io'),
                         {'io.a[0]':65,'io.a[1]':65,'io.b.x':3})

    def test_unknown_and_uninferred_width_rejected(self):
        for typ in ('UInt', 'SInt<58>', 'UInt<0>', 'UInt<1>[17]'):
            with self.subTest(typ=typ), self.assertRaises(Uncertain): widths(typ, 'x')

    def reject(self, old, new):
        self.assertIn(old, fixture())
        with self.assertRaises(Uncertain): review_text(fixture().replace(old,new))

    def test_wide_request_add_rejected(self):
        self.reject('add(bits(io.address, 6, 0), pad(io.size, 7))',
                    'add(cat(UInt<1>(0h0), io.address), pad(io.size, 65))')

    def test_duplicate_add_rejected(self):
        self.reject('    node lowerSub', '    node extra = add(io.size, io.size)\n    node lowerSub')

    def test_request_dependent_predecessor_rejected(self):
        self.reject('sub(bits(io.regionLow[0], 64, 7), UInt<58>(0h1))',
                    'sub(firstHigh, UInt<58>(0h1))')

    def test_missing_predecessor_truncation_rejected(self):
        self.reject('tail(lowerSub, 1)', 'lowerSub')

    def test_extra_state_rejected(self):
        self.reject('    node firstHigh', '    reg saved : UInt<1>, clock\n    node firstHigh')

    def test_unsupported_primitive_rejected(self):
        self.reject('pad(io.size, 7)', 'dshl(io.size, UInt<3>(0h1))')

    def test_bypass_output_rejected(self):
        self.reject('connect io.covers[0], predicate', 'connect io.covers[0], eq(io.address, UInt<64>(0h0))')

    def test_wrong_active_policy_rejected(self):
        self.reject('connect io.covers[0], predicate', 'connect io.covers[0], and(io.regionActive[0], predicate)')

    def test_decoy_mutant_identity_not_production(self):
        with self.assertRaises(Uncertain): review_text(fixture().replace('PmpGenericRangeComparisons','PmpGenericRangeMutant0'))

    def test_hidden_extra_port_rejected(self):
        self.reject('flip address : UInt<64>', 'flip other : UInt<64>, flip address : UInt<64>')

    def test_malformed_bits_rejected(self):
        self.reject('bits(io.address, 6, 0)', 'bits(io.address, 64, 0)')


if __name__ == '__main__': unittest.main()
