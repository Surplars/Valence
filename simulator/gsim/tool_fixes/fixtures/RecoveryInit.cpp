#include "RecoveryInit.h"
#include <cassert>
#include <cstring>
#include <type_traits>
int main() {
  SRecoveryInit d;
  static_assert(sizeof(d.narrow) == 1);
  constexpr size_t start = offsetof(SRecoveryInit, _var_start);
  constexpr size_t end = offsetof(SRecoveryInit, _var_end);
  auto *bytes = reinterpret_cast<unsigned char *>(&d);
  auto verifyZero = [&] { for(size_t i=start;i<end;++i) assert(bytes[i]==0); };
  verifyZero();
  d.cycles=123; d.LOG_START=456; d.LOG_END=789; d._var_end=0xdeadbeef;
  memset(bytes+start, 0xa5, end-start);
  d.init(); verifyZero();
  assert(d.cycles==123 && d.LOG_START==456 && d.LOG_END==789 && d._var_end==0xdeadbeef);
  for (auto flag : d.activeFlags) assert(flag==0xff);
  for (unsigned n=0;n<256;++n) {
    d.set_narrow(n); assert(d.narrow==n);
    d.step(); assert(d.get_low()==(n&7));
  }
  d.set_wide((static_cast<unsigned _BitInt(129)>(1)<<128)|123);
  d.step(); d.step(); assert(d.get_saved()!=0);
  d.init(); assert(d.get_saved()==0);
}
