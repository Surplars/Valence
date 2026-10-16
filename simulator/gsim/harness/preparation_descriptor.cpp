#include "PreparationDescriptorGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
struct Result {int fresh; bool capture, transfer, keepS, keepQ;};
int main(int argc,char**argv)try{
 SPreparationDescriptorGsim dut;dut.set_reset(0);uint64_t checks=0,refills=0,preempts=0;
 bool mutate=argc>1&&std::string(argv[1])=="--mutate-control";
 bool omitQ=argc>1&&std::string(argv[1])=="--omit-q-reservation";
 auto check=[&](unsigned mask,unsigned head,int s,int q,bool issued,bool enabled){
  dut.set_io$$eligible(mask);dut.set_io$$enabled(enabled);dut.set_io$$head(head);
  dut.set_io$$headMask((0xffffu<<head)&0xffffu);
  dut.set_io$$resident$$valid(s>=0);dut.set_io$$resident$$bits(s<0?0:s);
  dut.set_io$$descriptor$$valid(q>=0&&!omitQ);dut.set_io$$descriptor$$bits(q<0?0:q);
  dut.set_io$$issued(issued);dut.step();
  std::vector<int> ordered;
  if(enabled)for(unsigned n=0;n<16;n++){int i=(head+n)%16;if(mask&(1u<<i))ordered.push_back(i);}
  int c=-1,ps=-1,pq=-1,pc=-1;
  for(unsigned n=0;n<ordered.size();n++){int i=ordered[n];if(i==s)ps=n;if(i==q)pq=n;if(c<0&&i!=s&&i!=q){c=i;pc=n;}}
  bool newerWins=c>=0&&(pq<0||pc<pq);
  bool transfer=pq>=0&&!newerWins&&(ps<0||issued||pq<ps);
  Result r{c,c>=0&&(newerWins||transfer),transfer,ps>=0&&!issued&&!transfer,pq>=0&&!transfer&&!(c>=0&&(newerWins||transfer))};
  bool got=bool(dut.get_io$$capture());if(mutate&&checks==0)got=!got;
  if(got!=r.capture||bool(dut.get_io$$transfer())!=r.transfer||bool(dut.get_io$$keepResident())!=r.keepS||
     bool(dut.get_io$$keepDescriptor())!=r.keepQ||bool(dut.get_io$$freshValid())!=(c>=0)||
     dut.get_io$$freshIndex()!=unsigned(c<0?0:c)||dut.get_io$$freshOwner()!=(c<0?0u:1u<<c))
   throw std::runtime_error("independent descriptor reservation mismatch");
  checks++;refills+=r.capture&&r.transfer;preempts+=r.capture&&pq>=0&&pc<pq;return r;
 };
 if(omitQ)check(3,0,-1,0,false,true);
 for(unsigned head=0;head<16;head++)for(unsigned mask=0;mask<65536;mask++){
  int s=int((mask>>5)%17)-1,q=int((mask>>9)%17)-1;if(s>=0&&q==s)q=-1;
  check(mask,head,s,q,mask&1,mask&2);
 }
 std::mt19937 rng(0x276c1);
 for(unsigned n=0;n<100000;n++){int s=int(rng()%17)-1,q=int(rng()%17)-1;if(s>=0&&s==q)q=-1;check(rng()&65535,rng()%16,s,q,rng()&1,rng()&1);}
 // Stateful independent expected stream: two fill cycles, then exactly one issue each cycle.
 uint64_t launches=0;
 for(unsigned start=0;start<16;start++){
  unsigned mask=0xffff;int s=-1,q=-1;unsigned head=start;
  for(unsigned cycle=0;cycle<18;cycle++){
   bool issue=s>=0;auto r=check(mask,head,s,q,issue,true);
   if(cycle>=2&&cycle<18&&!issue)throw std::runtime_error("descriptor stable stream lost II=1");
   if(issue){if(s!=int(head))throw std::runtime_error("descriptor stream violated oldest order");mask&=~(1u<<s);head=(head+1)%16;launches++;}
   int nextS=r.transfer?q:(r.keepS?s:-1),nextQ=r.capture?r.fresh:(r.keepQ?q:-1);
   if(nextS>=0&&nextS==nextQ)throw std::runtime_error("duplicate reservation after transfer/refill");s=nextS;q=nextQ;
  }
 }
 // Stalled younger resident must not prevent newly older owner from being prepared and replacing it.
 auto a=check((1<<2)|(1<<7)|(1<<9),0,7,9,false,true);
 if(!a.capture||a.fresh!=2||a.transfer)throw std::runtime_error("older descriptor preemption missing");
 auto b=check((1<<2)|(1<<7)|(1<<9),0,7,2,false,true);
 if(!b.transfer||b.keepS)throw std::runtime_error("older resident replacement missing");
 if(!refills||!preempts||launches!=256)throw std::runtime_error("descriptor coverage missing");
 std::cout<<"DESCRIPTOR_SELECTOR_PASS checks="<<checks<<" transfer_refills="<<refills<<" preemptions="<<preempts<<" launches="<<launches<<" stream_II=1\n";
}catch(const std::exception&e){std::cerr<<"DESCRIPTOR_SELECTOR_FAIL "<<e.what()<<'\n';return 1;}
