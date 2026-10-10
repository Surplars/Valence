"""Full typed profile negatives, source-only preparation; execution pending."""
import copy
from contract import *
def test_profiles():
 for side in PROFILES:profile(expected_profile(side),side)
 pair_profiles(expected_profile('off'),expected_profile('on'))
 for field,bad in [('memoryProofRows',24),('memoryProofCacheSets',128),('memoryProofFrontier',1),('postedPreparationPriority',False),('tagBits',32),('physicalRegs',48),('robEntries',16)]:
  p=expected_profile('on');p['core'][field]=bad
  try:profile(p,'on')
  except RuntimeError:pass
  else:raise AssertionError('profile mutation accepted '+field)
if __name__=='__main__':test_profiles()
