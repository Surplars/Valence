#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main()try{
 Bench b;b.expectedQuery=true;b.configure();b.warm();
 std::map<unsigned,uint64_t> tags;unsigned reuse=0;
 for(unsigned n=0;n<24;n++){
  auto owners=b.submit({ld(20,11),ld(21,11,16)});
  for(auto t:owners){auto i=tags.find(t.index);if(i!=tags.end()){b.check(i->second!=t.tag,"ROB reuse retained old full token");reuse++;}tags[t.index]=t.tag;}
  b.drain();
 }
 b.check(reuse>=32,"bounded real allocator did not wrap memory-owner slots");
 std::cout<<"DESCRIPTOR_OWNER_REUSE_PASS owners=48 reused_slots="<<reuse<<"\n";
}catch(const std::exception&e){std::cerr<<"DESCRIPTOR_OWNER_REUSE_FAIL "<<e.what()<<'\n';return 1;}
