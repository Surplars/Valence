#include "InitByteSpan.h"
#include <cstddef>
#include <cstdio>
#include <type_traits>
int main() {
  static_assert(std::is_standard_layout<SInitByteSpan>::value);
  SInitByteSpan d;
  constexpr auto begin = offsetof(SInitByteSpan, _var_start);
  constexpr auto end = offsetof(SInitByteSpan, _var_end);
  auto *bytes = reinterpret_cast<unsigned char *>(&d);
  d.cycles=123; d.LOG_START=456; d.LOG_END=789; d._var_end=0xdeadbeef;
  memset(bytes + begin, 0xa5, end-begin);
  d.init();
  size_t uncleared=0;
  for (size_t i=begin;i<end;++i) uncleared += bytes[i]!=0;
  if (d.cycles!=123 || d.LOG_START!=456 || d.LOG_END!=789 || d._var_end!=0xdeadbeef) return 3;
  for(auto flag:d.activeFlags) if(flag!=0xff) return 4;
  printf("span=%zu uncleared=%zu tail=%u\n", end-begin, uncleared, bytes[end-1]);
  return uncleared ? 2 : 0;
}
