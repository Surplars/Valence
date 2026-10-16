#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main()try{
 Bench b;b.expectedQuery=true;b.configure();b.warm();b.constant(25,(va+4096)*7);b.constant(26,7);
 std::map<unsigned,uint64_t> tags;unsigned reused=0,waiting=0;
 for(unsigned n=0;n<24;n++){
  auto owners=b.submit({divu(29,25,26),ld(20,29)});auto producer=owners[0],load=owners[1];
  auto old=tags.find(load.index);if(old!=tags.end()){b.check(old->second!=load.tag,"waiting Q reused stale ROB token");reused++;}tags[load.index]=load.tag;
  bool seen=false;
  for(unsigned k=0;k<150&&!b.entries.at(load).retired;k++){
   if(b.dut.get_io$$descriptorValid()&&b.dut.get_io$$descriptorToken$$index()==load.index&&
      b.dut.get_io$$descriptorToken$$tag()==load.tag&&!b.entries.at(producer).completed){seen=true;waiting++;}
   b.tick();
  }
  b.check(seen,"reused waiting source did not reserve early");b.drain();
 }
 b.check(reused>=16&&waiting>=24,"waiting reuse coverage absent");
 std::cout<<"EARLY_WAITING_REUSE_PASS owners=24 reused_slots="<<reused<<" waiting_cycles="<<waiting<<"\n";
}catch(const std::exception&e){std::cerr<<"EARLY_WAITING_REUSE_FAIL "<<e.what()<<'\n';return 1;}
