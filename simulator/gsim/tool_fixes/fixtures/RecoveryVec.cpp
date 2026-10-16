#include "RecoveryVec.h"
#include <cassert>
#include <type_traits>
#include <cstring>
int main() {
  SRecoveryVec d;
  const SRecoveryVec &cd=d;
  static_assert(std::is_same_v<decltype(cd.get_copied()),const uint8_t (&)[4]>);
  static_assert(std::is_same_v<decltype(cd.get_copiedMatrix()),const uint8_t (&)[4][4]>);
  static_assert(std::is_same_v<decltype(cd.get_constants()),const uint8_t (&)[4][4]>);
  uint8_t values[4]={23,129,255,199};
  uint8_t matrix[4][4]={{1,2,3,199},{4,5,6,199},{7,8,9,199},{199,199,199,199}};
  d.set_values(values); d.set_matrix(matrix);
  assert(d.values[3]==0);
  for(unsigned i=0;i<4;++i) { assert(d.matrix[3][i]==0); assert(d.matrix[i][3]==0); }
  for(unsigned i=0;i<3;++i) {
    d.set_index(i); d.step();
    assert(d.get_selected()==values[i]); assert(d.get_selectedMatrix()==matrix[i][i]);
    assert(cd.get_copied()[i]==values[i]);
    for(unsigned j=0;j<3;++j) assert(cd.get_copiedMatrix()[i][j]==matrix[i][j]);
  }
  memset(d.activeFlags,0,sizeof(d.activeFlags));
  values[3]=17; matrix[3][0]=17; matrix[0][3]=17;
  d.set_values(values); d.set_matrix(matrix);
  for(auto flag:d.activeFlags) assert(flag==0);
  values[2]=12; d.set_values(values);
  bool activated=false; for(auto flag:d.activeFlags) activated|=flag!=0; assert(activated);
  d.step(); assert(cd.get_copied()[2]==12);
  auto &constants=cd.get_constants();
  assert(&constants==&cd.get_constants());
  for(unsigned i=0;i<4;++i) for(unsigned j=0;j<4;++j)
    assert(constants[i][j]==(i<3&&j<3?42:0));
}
