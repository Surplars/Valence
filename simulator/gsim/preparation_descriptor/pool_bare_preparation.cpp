#define main retained_ready_main
#include "bare_backend.cpp"
#undef main
int main(int argc,char**argv)try {
 const bool mutate=argc>1&&std::string(argv[1])=="--mutate-bare-address";
 unsigned cases=0;uint64_t coverage=0;
 for(unsigned viaSatp=0;viaSatp<2;++viaSatp){
  Bench b;b.expectedQuery=true;b.configure();b.warm();
  // Explicitly completed CSR writes drive the independent address interpretation.
  // This virtual-only adapter fixture must not launch bare buffered stores.
  if(viaSatp)b.csr(0x180,0);else b.csr(0x300,0);
  b.independentBare=true;
  if(viaSatp)b.csr(0x180,satp);else b.csr(0x300,(1ULL<<17)|(1ULL<<11));
  b.independentBare=false;b.warm();
  if(viaSatp)b.csr(0x180,0);else b.csr(0x300,0);
  b.independentBare=true;
  b.constant(10,ram);b.constant(11,ram+4096);b.constant(12,ram+8192);
  const auto beforePhysical=b.physicalCount;
  b.commitEnable=false;
  auto ts=b.submit({divu(29,25,26),st(10,30),st(10,30,8)});
  uint64_t observed=0;
  for(unsigned n=0;n<100;++n){b.tick();
   if(b.dut.get_io$$poolBare()&&!b.dut.get_io$$poolOriginalMask()&&b.dut.get_io$$poolStageValid()){
    Token t{unsigned(b.dut.get_io$$poolStageToken$$index()),uint64_t(b.dut.get_io$$poolStageToken$$tag())};
    b.check(t==ts[1],"bare fallback resident violated oldest prepared-store owner");
    const uint64_t address=b.dut.get_io$$poolStageAddress()^(mutate?8ULL:0ULL);
    b.check(address==ram,"independent bare resident address mismatch");++observed;
   }
  }
  b.check(observed>20,"bare fallback/resident coverage missing");coverage+=observed;
  b.check(!b.entries.at(ts[1]).started&&!b.entries.at(ts[2]).started&&b.physicalCount==beforePhysical,
    "held preparation produced an actual younger store launch or memory request");
  // Intentionally end before releasing the blocked head: preparation/payload
  // coverage only; no claim about bare posted retirement in this fixture.
  std::cout<<"POOL_BARE_PREPARATION_CASE via_satp="<<viaSatp<<" fallback_cycles="<<observed<<'\n';++cases;
 }
 std::cout<<"POOL_BARE_PREPARATION_PASS cases="<<cases<<" fallback_cycles="<<coverage
  <<" bare_store_launches=0 preparation_only=true\n";return 0;
}catch(const std::exception&e){std::cerr<<"POOL_BARE_PREPARATION_FAIL "<<e.what()<<'\n';return 1;}
