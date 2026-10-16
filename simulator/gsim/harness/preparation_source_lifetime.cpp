#include "PreparationSourceLifetimeGsim.h"
#include <iostream>
#include <string>
int main(int argc,char**argv){
 SPreparationSourceLifetimeGsim dut;dut.set_reset(0);
 std::string mode=argc>1?argv[1]:"";
 // Independent hostile events: a delayed consumer still owns a ready source,
 // but an external allocator/write source illegally reuses it.
 dut.set_io$$active(1);dut.set_io$$mappingMatches(1);dut.set_io$$inRange(1);dut.set_io$$ready(1);
 dut.set_io$$reserved(mode=="--reserve");dut.set_io$$written(mode=="--write");dut.step();
 for(unsigned mask=0;mask<32;mask++){
  dut.set_io$$active(0);dut.set_io$$mappingMatches(mask&1);dut.set_io$$inRange(mask&2);
  dut.set_io$$ready(mask&4);dut.set_io$$reserved(mask&8);dut.set_io$$written(mask&16);dut.step();
 }
 std::cout<<"SOURCE_LIFETIME_CHECK_PASS active_positive=1 inactive_cases=32\n";
}
