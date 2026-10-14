#include "FpConvertGsim.h"
#include <fstream>
#include <iostream>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <type_traits>
static void check(bool v,const char*msg){if(!v)throw std::runtime_error(msg);}
int main(int argc,char**argv){try{
 check(argc==2,"usage: convert VECTORS");std::ifstream f(argv[1]);check(bool(f),"open vectors");SFpConvertGsim d;static_assert(std::is_trivially_copyable_v<SFpConvertGsim>);std::memset(&d,0,sizeof(d));d.activateAll();d.set_reset(1);d.step();d.set_reset(0);
 unsigned fmt,sign,rm,nf,wf;uint64_t bits,narrow,wide,count=0;
 while(f>>std::dec>>fmt>>sign>>rm>>std::hex>>bits>>narrow>>nf>>wide>>wf){
 d.set_io$$bits(bits);d.set_io$$double(fmt);d.set_io$$signed(sign);d.set_io$$rm(rm);d.step();
 if(d.get_io$$referenceNarrow()!=narrow||d.get_io$$referenceWide()!=wide||d.get_io$$rnf()!=nf||d.get_io$$rwf()!=wf){std::cerr<<"row="<<std::dec<<count<<" bits="<<std::hex<<bits<<'\n';throw std::runtime_error("ORACLE_BASELINE_MISMATCH");}
 if(d.get_io$$narrow()!=narrow||d.get_io$$wide()!=wide||d.get_io$$nf()!=nf||d.get_io$$wf()!=wf){std::cerr<<"row="<<std::dec<<count<<" bits="<<std::hex<<bits<<'\n';throw std::runtime_error("CANDIDATE_MISMATCH");}++count;
 }check(f.eof(),"vector parse");check(count==122840,"vector coverage");std::cout<<"GSIM_CONVERT_PASS vectors="<<count<<" independent_integer_oracle=1 original_hardfloat=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
