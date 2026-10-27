import unittest
from guarded_natural_pmp_structure import parse, evaluate, refs, Expressions, negative, conjuncts
from registered_raw_certified_cones import Module, Uncertain

class GuardedShapeParserTests(unittest.TestCase):
    def test_size_masks_and_low_normalization(self):
        mask=parse('mux(eq(s, UInt<2>(0h0)), UInt<3>(0h0), mux(eq(s, UInt<2>(0h1)), UInt<3>(0h1), mux(eq(s, UInt<2>(0h2)), UInt<3>(0h3), UInt<3>(0h7))))')
        for s in range(4):
            self.assertEqual(evaluate(mask,{'s':(s,2)}),((1<<s)-1,3))
            for x in range(8):
                e=('and',('ref','a'),('not',mask))
                self.assertEqual(evaluate(e,{'a':(x,3),'s':(s,2)}),(x & ~((1<<s)-1),3))
    def test_mux_width_is_max_of_both_branches(self):
        for c in (0,1):
            self.assertEqual(evaluate(parse("mux(c, UInt<1>(0h0), UInt<3>(0h7))"),{'c':(c,1)}), (0 if c else 7,3))
    def test_complement_has_finite_width(self):
        self.assertEqual(evaluate(parse('not(UInt<3>(0h2))'),{}),(5,3))
    def test_concat_preserves_upper_bits(self):
        e=parse('cat(bits(a, 63, 3), bits(a, 2, 0))')
        for a in (0,1,7,8,0xffffffffffffffff,1<<63):
            self.assertEqual(evaluate(e,{'a':(a,64)}),(a,64))
    def test_exact_final_driver_overrides(self):
        m=Module('M',[(4,'connect x, UInt<1>(0h0)',1),(4,'connect x, UInt<1>(0h1)',2)],False)
        self.assertEqual(Expressions(m).final('x'),('lit',1,1))
    def test_conditional_final_driver_rejected(self):
        m=Module('M',[(4,'connect x, UInt<1>(0h0)',1),(6,'connect x, UInt<1>(0h1)',2)],False)
        with self.assertRaises(Uncertain):Expressions(m).final('x')
    def test_cycles_rejected(self):
        m=Module('M',[(4,'node a = b',1),(4,'node b = a',2)],False)
        with self.assertRaises(Uncertain):Expressions(m).expand(('ref','a'))
    def test_unsupported_primitive_rejected(self):
        with self.assertRaises(Uncertain):evaluate(parse('foo(UInt<1>(0h0))'),{})
    def test_missing_proof_variable_rejected(self):
        with self.assertRaises(Uncertain):evaluate(parse('hidden'),{})
    def test_reference_and_conjunction_identity(self):
        x=parse('or(a, b)'); self.assertEqual(refs(x),{'a','b'})
        self.assertIn(negative(x),conjuncts(('and',('ref','ready'),negative(x))))

if __name__=='__main__':unittest.main()
