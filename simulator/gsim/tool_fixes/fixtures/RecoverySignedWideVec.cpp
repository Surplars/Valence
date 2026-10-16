#include "RecoverySignedWideVec.h"
#include <cassert>
#include <type_traits>
#include <cstring>
int main() {
  SRecoverySignedWideVec d;
  const SRecoverySignedWideVec &cd=d;
  using Wide = unsigned _BitInt(192); // GSIM rounds >64-bit physical storage to 64-bit words
  static_assert(std::is_same_v<decltype(cd.get_signedCopied()),const uint16_t (&)[4]>);
  static_assert(std::is_same_v<decltype(cd.get_wideCopied()),const Wide (&)[4]>);
  static_assert(std::is_same_v<decltype(cd.get_signedConstants()),const uint16_t (&)[4]>);
  const int expected[3]={-256,-3,255};
  uint16_t signedValues[4]={256,509,255,0xffff};
  Wide wideValues[4]={Wide(1)<<128,(Wide(1)<<127)|255,(Wide(1)<<129)-1,Wide(-1)};
  d.set_signedValues(signedValues); d.set_wideValues(wideValues);
  assert(d.signedValues[3]==0 && d.wideValues[3]==0);
  for(unsigned i=0;i<3;++i) {
    d.set_index(i); d.step();
    assert(static_cast<signed _BitInt(9)>(d.get_signedSelected())==expected[i]);
    assert(static_cast<signed _BitInt(9)>(cd.get_signedCopied()[i])==expected[i]);
    assert(d.get_wideSelected()==wideValues[i]);
    assert(cd.get_wideCopied()[i]==wideValues[i]);
    assert(static_cast<signed _BitInt(9)>(cd.get_signedConstants()[i])==-3);
  }
  assert(cd.get_signedConstants()[3]==0);
  memset(d.activeFlags,0,sizeof(d.activeFlags));
  signedValues[3]=0; wideValues[3]=0;
  d.set_signedValues(signedValues); d.set_wideValues(wideValues);
  for(auto flag:d.activeFlags) assert(flag==0);
  wideValues[1]^=Wide(1)<<128; d.set_wideValues(wideValues);
  bool activated=false; for(auto flag:d.activeFlags) activated|=flag!=0; assert(activated);
  d.set_index(1); d.step(); assert(d.get_wideSelected()==wideValues[1]);
}
