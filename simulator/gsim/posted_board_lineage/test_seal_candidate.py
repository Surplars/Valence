"""Host truth-table contract only; actual CPU/cache regression is separate."""
import unittest


def candidate_seals(*, choice_valid=True, eligible=False, lookahead=True,
                    younger=True, prepared=True, token_index_matches=True,
                    store=True, atomic=False, virtual=False, ram=True,
                    pmp_denied=False, aligned=True, boundary=False):
    harmless_preparation = (lookahead and choice_valid and younger and prepared
                            and token_index_matches and store and not atomic
                            and not virtual and ram and not pmp_denied and aligned)
    return boundary or (choice_valid and not eligible and not harmless_preparation)


class SealCandidateContract(unittest.TestCase):
    def test_only_prepared_young_physical_store_exempt(self):
        self.assertFalse(candidate_seals())
        # These are explicit boundary cases, including a full-token-invalid
        # selection whose existing valid bit must already be false.
        cases = [dict(lookahead=False), dict(younger=False), dict(prepared=False),
                 dict(token_index_matches=False), dict(store=False), dict(atomic=True),
                 dict(virtual=True), dict(ram=False), dict(pmp_denied=True), dict(aligned=False)]
        for inputs in cases:
            with self.subTest(inputs=inputs):
                self.assertTrue(candidate_seals(**inputs))
        self.assertFalse(candidate_seals(choice_valid=False))
        self.assertFalse(candidate_seals(younger=False, eligible=True))

    def test_all_external_boundaries_still_seal(self):
        for name in ('recovery', 'recovering', 'interrupt', 'system', 'context', 'head_system'):
            with self.subTest(boundary=name):
                self.assertTrue(candidate_seals(boundary=True))
                self.assertTrue(candidate_seals(boundary=True, eligible=True, younger=False))
                self.assertTrue(candidate_seals(boundary=True, choice_valid=False))


if __name__ == '__main__':
    unittest.main()
