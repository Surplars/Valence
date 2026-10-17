#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main()try {
 Bench b;b.expectedQuery=true;b.configure();b.warm();
 std::map<unsigned,uint64_t> tags;unsigned reuse=0,stores=0;
 for(unsigned n=0;n<24;++n) {
  b.constant(25,1000+n*101);b.constant(26,3+n%5);
  b.commitEnable=false;
  auto tokens=b.submit({divu(30,25,26),st(10,30),st(10,30,8)});
  for(unsigned k=1;k<=2;++k){auto t=tokens[k];
   if(tags.count(t.index)){b.check(tags[t.index]!=t.tag,"store payload ROB reuse retained old full token");++reuse;}
   tags[t.index]=t.tag;++stores;
  }
  b.wait(100);b.commitEnable=true;
  b.drain();b.one(ld(20,10));b.one(ld(21,10,8));
 }
 b.check(reuse>=16,"store payload real allocator reuse coverage missing");
 b.check(b.bankWrites>=48,"store payload qualified RAM write coverage missing");
 b.check(b.bankDualWrites>0,"store payload two preparation-rank write coverage missing");
 std::cout<<"BANKED_STORE_PAYLOAD_REUSE_PASS stores="<<stores<<" reused_rows="<<reuse
          <<" writes="<<b.bankWrites<<" dual="<<b.bankDualWrites<<"\n";
}catch(const std::exception&e){std::cerr<<"BANKED_STORE_PAYLOAD_REUSE_FAIL "<<e.what()<<'\n';return 1;}
