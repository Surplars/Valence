"""Current complete constructors require one new strictly-false field."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import board_profile as profile
import board_release as release
import board_timing_cdc as timing
import board_pmp_publication as pmp
import board_bound_store_prefetch as bound
import board_durable_read_prefetch as durable
import board_dual_proof_credit as dual


def original_expected(mode):
    expected=json.loads((profile.HERE/'board-performance-constructors.json').read_text())[mode]
    for section in ('profile','core'):
        for field in ('registeredPmpRegions','publishedPmpChanges','frozenStoreProofTransport',
                      'pendingVirtualStoreProof','boundHeadStoreOverlap','pendingReadyStoreBypass','taggedStoreReturns'):
            expected[section][field]=False
        expected[section]['pendingVirtualStoreProofSlots']=1
        expected[section]['pendingStoreEarlyLoadCredits']=1
    for section in ('profile','cache'):
        for field in ('readPrefetchDirtyRetry','readPrefetchDemandAdoption','readPrefetchStoreHold',
                      'durableReadPrefetchCandidate','readPrefetchBehindStore','internalLineGrant','concurrentReadStorePrefetch','memoryScheduleOverlap'):
            expected[section][field]=False
    return expected

class TaggedProfileSchemaTests(unittest.TestCase):
    def test_every_rollback_current_constructor_requires_actual_false(self):
        cases=[('profile-'+m,original_expected(m),lambda x,m=m:profile.compare_constructor(m,x)) for m in ('A','B')]
        rel=original_expected('B');rel['profile']['experimentalTriSpeedEthernet']=True
        cases.append(('release',rel,release.compare_constructor))
        cases += [(module.__name__,module.expected_constructor(),module.compare_constructor)
                  for module in (timing,pmp,bound,durable,dual)]
        cases.append(('dual-fabric',dual.expected_fabric(),dual.compare_fabric))
        for name,expected,compare in cases:
            sections=('cpu',) if name=='dual-fabric' else ('profile','core')
            compare(expected)
            for section in sections:
                self.assertIs(expected[section]['taggedStoreReturns'],False)
                for value in (None,True,0,1,False):
                    actual=copy.deepcopy(expected)
                    if value is None:del actual[section]['taggedStoreReturns']
                    elif value is False:actual[section]['unrequestedFutureField']=False
                    else:actual[section]['taggedStoreReturns']=value
                    with self.subTest(profile=name,section=section,value=value),self.assertRaises(RuntimeError):compare(actual)

if __name__=='__main__':unittest.main()
