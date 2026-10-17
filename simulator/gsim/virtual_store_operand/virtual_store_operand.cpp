#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main(int argc,char**argv)try {
 const std::string mutation=argc>1?argv[1]:"";
 Bench b;b.expectedQuery=true;b.configure();b.warm();
 const auto before=b.physicalCount;b.commitEnable=false;
 auto ts=b.submit({divu(29,25,26),st(10,30),st(10,30,8)});
 unsigned q=0,s=0;
 for(unsigned n=0;n<90;n++){
  b.tick();
  const bool qs=b.dut.get_io$$descriptorValid()&&b.dut.get_io$$descriptorToken$$index()==ts[1].index&&
   b.dut.get_io$$descriptorToken$$tag()==ts[1].tag;
  if(qs){b.check(b.dut.get_io$$descriptorSaved(),"virtual fallback used fresh PRF operands");q++;}
  if(b.dut.get_io$$poolStageValid()&&!b.dut.get_io$$poolOriginalMask()){
   Token t{unsigned(b.dut.get_io$$poolStageToken$$index()),uint64_t(b.dut.get_io$$poolStageToken$$tag())};
   if(mutation=="--wrong-full-token")t.tag^=1ULL<<63;
   b.check(t==ts[1],"virtual fallback full-token mismatch");
   b.check(b.dut.get_io$$poolStageAddress()==va&&b.dut.get_io$$poolStageData()==b.entries.at(ts[1]).data,
    "virtual fallback saved VA/data mismatch");
   b.check(!b.dut.get_io$$poolBare(),"virtual test accidentally ran Bare");s++;
  }
  const bool allegedStart=b.entries.at(ts[1]).started||(mutation=="--early-start"&&s>0);
  b.check(!allegedStart&&!b.entries.at(ts[2]).started&&b.physicalCount==before,
   "virtual fallback produced nonhead launch or physical effect");
 }
 b.check(q>0&&s>50,"virtual operand idle-window preparation NOT_REACHED");
 // A new original younger load preempts speculative fallback reservations, retaining normal hazard rules.
 auto load=b.submit({ld(20,11)})[0];unsigned selected=0;
 for(unsigned n=0;n<40;n++){
  b.tick();
  if(b.dut.get_io$$poolStageValid()&&b.dut.get_io$$poolStageToken$$index()==load.index&&
   b.dut.get_io$$poolStageToken$$tag()==load.tag)selected++;
 }
 b.check(selected>10&&!b.entries.at(load).started,"original load priority/commit gate not preserved");
 b.commitEnable=true;b.drain();
 b.check(b.entries.at(ts[1]).retired&&b.entries.at(ts[2]).retired&&b.entries.at(load).retired,
  "prefilled store/load failed exact response retirement");
 std::cout<<"VIRTUAL_STORE_OPERAND_PASS q_saved="<<q<<" s_idle="<<s<<" original_load_selected="<<selected
  <<" virtual_va_outside_physical_range=1 prehead_requests=0\n";
}catch(const std::exception&e){std::cerr<<"VIRTUAL_STORE_OPERAND_FAIL "<<e.what()<<'\n';return 1;}
