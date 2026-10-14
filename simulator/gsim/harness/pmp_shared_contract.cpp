#include "PmpSharedBoundsContract.h"
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <type_traits>
#ifndef LINE_MODE
#define LINE_MODE 0
#endif
int main(int argc,char**argv){try{
 SPmpSharedBoundsContract d;static_assert(std::is_trivially_copyable_v<SPmpSharedBoundsContract>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();d.set_io$$size(LINE_MODE?6:3);d.set_io$$address(0);d.set_reset(1);d.step();d.step();d.set_reset(0);
 std::string flag=argc>1?argv[1]:"";if(!flag.empty()){
  if(flag=="--size")d.set_io$$size(LINE_MODE?5:4);else if(flag=="--alignment")d.set_io$$address(1);else throw std::runtime_error("unknown flag");
  std::cout<<"REACHED contract "<<(LINE_MODE?"line":"natural")<<" "<<flag<<std::endl;d.step();throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
 }
 for(unsigned i=0;i<16;i++){d.set_io$$address(~uint64_t(LINE_MODE?63:7)-uint64_t(i)*(LINE_MODE?64:8));d.step();if(!d.get_io$$denied())throw std::runtime_error("inactive S-mode access must deny");}
 std::cout<<"PMP_SHARED_SINGLE_CONTRACT_PASS line="<<LINE_MODE<<"\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
