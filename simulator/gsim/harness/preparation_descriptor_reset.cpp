#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main()try{
 Bench b;b.expectedQuery=true;b.configure();b.warm();b.commitEnable=false;
 b.submit({ld(20,11),ld(21,11,16),ld(22,11,32)});
 for(unsigned n=0;n<100&&!b.dut.get_io$$descriptorValid();n++)b.tick();
 b.check(b.dut.get_io$$descriptorValid(),"active descriptor reset witness missing");
 b.dut.set_reset(1);b.dut.step();
 b.check(!b.dut.get_io$$descriptorValid()&&!b.dut.get_io$$poolStageValid()&&
   !b.dut.get_io$$poolStageToken$$index()&&!b.dut.get_io$$poolStageToken$$tag()&&
   !b.dut.get_io$$poolStageAddress()&&!b.dut.get_io$$poolStageData()&&!b.dut.get_io$$poolStageSize(),
   "active descriptor reset left an invalid nonzero stage");
 std::cout<<"DESCRIPTOR_ACTIVE_RESET_PASS abandoned_speculative_only=true\n";
}catch(const std::exception&e){std::cerr<<"DESCRIPTOR_ACTIVE_RESET_FAIL "<<e.what()<<'\n';return 1;}
