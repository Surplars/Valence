"""Independent negatives for the metadata-only graph/profile correspondence gate."""
import copy
import unittest
import official_entry_gate as gate


class OfficialEntryGate(unittest.TestCase):
    def test_graph_only_ignores_exact_source_locator_metadata(self):
        source = '  module Backend : @[original.scala 42:3]\n    node x = and(a, b) @[a.scala 2:1]\n'
        moved = source.replace('original.scala 42:3', 'new.scala 99:5')
        self.assertEqual(gate.normalized_fir(source), gate.normalized_fir(moved))
        for mutation in (source.replace('and(a, b)', 'or(a, b)'), source + '    node extra = a\n',
                         source.replace('Backend', 'Other'), source.replace('a, b', 'a, a')):
            self.assertNotEqual(gate.normalized_fir(source), gate.normalized_fir(mutation))

    def test_full_profile_adds_only_explicit_new_config_field(self):
        old = {'profile': {str(i): False for i in range(26)},
               'core': {str(i): False for i in range(135)},
               'developmentTreatment': {'canonicalVirtualStoreOverlap': True,
                                        'productionCliSupportsTreatment': False}}
        old['core']['canonicalVirtualStoreOverlap'] = True
        new = copy.deepcopy(old)
        del new['developmentTreatment']
        new['profile']['canonicalVirtualStoreOverlap'] = True
        gate.compare_profile(new, old, 'on')
        for group in ('profile', 'core'):
            for value in (False, 1):
                bad = copy.deepcopy(new)
                bad[group]['canonicalVirtualStoreOverlap'] = value
                with self.assertRaises(ValueError):
                    gate.compare_profile(bad, old, 'on')
        bad = copy.deepcopy(new)
        bad['core']['0'] = True
        with self.assertRaises(ValueError):
            gate.compare_profile(bad, old, 'on')

    def test_actual_audit_rejects_one_drifted_or_missing_instance(self):
        value = {'allActualParametersEqualExpected': True, 'hardwareMutation': False,
                 'expectedCore': {'canonicalVirtualStoreOverlap': True}}
        for key, count in [('coreParameters', 6), ('ddrParameters', 2), ('cacheConcurrency', 3),
                           ('cacheTileLinkParameters', 1)]:
            value[key] = [{'instancePath': str(i), 'values': {'canonical': True}} for i in range(count)]
        gate.compare_actual(value, value, 'on')
        for key in ('coreParameters', 'ddrParameters', 'cacheConcurrency', 'cacheTileLinkParameters'):
            bad = copy.deepcopy(value)
            bad[key][0]['values']['canonical'] = 1
            with self.assertRaises(ValueError):
                gate.compare_actual(bad, value, 'on')
            bad = copy.deepcopy(value)
            bad[key].pop()
            with self.assertRaises(ValueError):
                gate.compare_actual(bad, value, 'on')


if __name__ == '__main__':
    unittest.main()
