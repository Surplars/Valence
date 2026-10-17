#include "VirtualStoreOperandPoolGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
struct State {
 unsigned original=0, prepared=0, head=0, flags=0x183b, operation=0, control=0;
 int s=-1,q=-1; bool issued=false, sp=true,qp=true, sk=false,qk=false,fk=false,clear=false;
 bool si=true,qi=true,st=true,qt=true;
};
int main(int argc,char**argv)try {
 SVirtualStoreOperandPoolGsim dut;dut.set_reset(0);
 std::string mutation=argc>1?argv[1]:""; uint64_t checks=0,virtualCaptures=0,bareChecks=0,originalWins=0,staleChecks=0;
 auto oracle=[&](const State&x,bool enabled){
  bool ordinary=(x.flags&0x1fff)==0x183b && x.operation==0 && x.control==0;
  bool virt=x.flags&(1<<14),safe=x.flags&(1<<13);
  bool qualified=ordinary&&(virt?enabled:safe);
  unsigned pool=x.original?x.original:(qualified?x.prepared:0);
  int s=x.s>=0&&x.sp&&x.si&&x.st?x.s:-1, q=x.q>=0&&x.qp&&x.qi&&x.qt?x.q:-1;
  std::vector<int> order;
  for(unsigned age=0;age<16;age++){int i=(x.head+age)%16;if(pool&(1u<<i))order.push_back(i);}
  int c=-1,ps=-1,pq=-1,pc=-1;
  for(unsigned n=0;n<order.size();n++){int i=order[n];if(i==s)ps=n;if(i==q)pq=n;if(c<0&&i!=s&&i!=q){c=i;pc=n;}}
  bool replace=c>=0&&(pq<0||pc<pq);
  bool transfer=pq>=0&&!replace&&(ps<0||x.issued||pq<ps);
  bool capture=c>=0&&(replace||transfer),ks=ps>=0&&!x.issued&&!transfer,kq=pq>=0&&!transfer&&!capture;
  return (uint32_t(kq&&!x.clear&&!x.qk)<<24)|(uint32_t(ks&&!x.clear&&!x.sk)<<23)|
   (uint32_t(transfer&&!x.clear&&!x.qk)<<22)|(uint32_t(capture&&!x.clear&&!x.fk)<<21)|
   (c<0?0u:(1u<<20)|(unsigned(c)<<16)|(1u<<c));
 };
 auto check=[&](State x){
  constexpr uint64_t fullTag=0x8000000000000007ULL;
  dut.set_io$$flags(x.flags);dut.set_io$$operation(x.operation);dut.set_io$$control(x.control);
  dut.set_io$$original(mutation=="--expose-issued-fallback"&&x.issued?0:x.original);
  dut.set_io$$prepared(x.prepared);dut.set_io$$head(x.head);
  dut.set_io$$resident(x.s<0?0:x.s);dut.set_io$$descriptor(x.q<0?0:x.q);
  dut.set_io$$residentPresent(x.s>=0);dut.set_io$$descriptorPresent(x.q>=0);
  dut.set_io$$residentPending(x.sp);dut.set_io$$descriptorPending(x.qp);
  dut.set_io$$residentSavedIndex(x.s<0?0:(x.s+(x.si?0:1))%16);
  dut.set_io$$descriptorSavedIndex(x.q<0?0:(x.q+(x.qi?0:1))%16);
  dut.set_io$$residentSavedTag(fullTag);dut.set_io$$descriptorSavedTag(fullTag);
  dut.set_io$$residentRowTag(fullTag^(x.st?0:1ULL<<63));
  dut.set_io$$descriptorRowTag(fullTag^((x.qt||mutation=="--truncate-tag")?0:1ULL<<63));
  dut.set_io$$residentKilled(x.sk);dut.set_io$$descriptorKilled(x.qk);dut.set_io$$freshKilled(x.fk);
  dut.set_io$$clear(x.clear);dut.set_io$$issued(x.issued);dut.step();
  bool ordinary=(x.flags&0x1fff)==0x183b&&x.operation==0&&x.control==0;
  bool virt=x.flags&(1<<14),safe=x.flags&(1<<13);
  unsigned qualification=(ordinary&&virt?1:0)|(ordinary&&safe&&!virt?2:0)|(ordinary&&(virt||safe)?4:0);
  unsigned got=dut.get_io$$qualification();if(mutation=="--trust-va-range"&&virt&&!safe)got&=~5u;
  if(got!=qualification||dut.get_io$$off()!=oracle(x,false)||dut.get_io$$on()!=oracle(x,true))
   throw std::runtime_error("independent virtual operand pool mismatch");
  checks++;virtualCaptures+=virt&&!x.original&&bool(dut.get_io$$on()&(1u<<21));
  bareChecks+=!virt;originalWins+=bool(x.original)&&x.issued;staleChecks+=x.q>=0&&!x.qt;
 };
 // Positive outside-RAM-looking VA classification: safeRange=false still prepares virtual operands.
 State x;x.flags|=1<<14;x.prepared=1<<4;check(x);
 // Original already-issued S suppresses fallback BEFORE issued owner exclusion.
 x.original=1<<2;x.s=2;x.issued=true;check(x);
 // Same slot, differing high tag must be fresh-captured, never transferred from stale Q.
 x.original=0;x.s=-1;x.issued=false;x.q=4;x.qt=false;check(x);
 // Complete qualification truth table, then all actual operation/control encodings.
 for(unsigned f=0;f<(1<<15);f++){State a;a.flags=f;a.prepared=0xaaaa;check(a);}
 for(unsigned op=0;op<64;op++)for(unsigned cf=0;cf<16;cf++)for(unsigned mode=0;mode<4;mode++){
  State a;a.flags=0x183b|(mode<<13);a.operation=op;a.control=cf;a.prepared=0xffff;check(a);
 }
 std::mt19937 rng(0x0f50cb);
 for(unsigned head=0;head<16;head++)for(unsigned mask=0;mask<65536;mask++){
  State a;a.head=head;a.prepared=mask;a.original=(rng()&1)?rng()&65535:0;a.flags=0x183b|((rng()&3)<<13);
  a.s=int(rng()%17)-1;a.q=int(rng()%17)-1;if(a.q==a.s)a.q=-1;
  a.issued=rng()&1;a.sp=rng()%5;a.qp=rng()%5;a.si=rng()%5;a.qi=rng()%5;a.st=rng()%5;a.qt=rng()%5;
  a.sk=!(rng()%7);a.qk=!(rng()%7);a.fk=!(rng()%7);a.clear=!(rng()%11);check(a);
 }
 if(!virtualCaptures||!bareChecks||!originalWins||!staleChecks)throw std::runtime_error("coverage missing");
 std::cout<<"VIRTUAL_OPERAND_POOL_PASS checks="<<checks<<" virtual_captures="<<virtualCaptures
  <<" bare_checks="<<bareChecks<<" original_issued_suppression="<<originalWins<<" stale_high_tag="<<staleChecks<<'\n';
}catch(const std::exception&e){std::cerr<<"VIRTUAL_OPERAND_POOL_FAIL "<<e.what()<<'\n';return 1;}
