#include "EarlyLoadDescriptorGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
struct Result { int fresh; bool capture, transfer, keepS, keepQ; };
int main(int argc,char**argv)try {
 SEarlyLoadDescriptorGsim dut; dut.set_reset(0);
 std::string mutation=argc>1?argv[1]:"";
 uint64_t checks=0,refills=0,preempts=0,waits=0,readyWins=0;
 auto check=[&](unsigned ready,unsigned waiting,unsigned head,int s,int q,bool issued,bool enabled) {
  if(ready&waiting)throw std::runtime_error("oracle masks overlap");
  dut.set_io$$eligible(ready);dut.set_io$$waitingLoads(waiting);dut.set_io$$enabled(enabled);
  dut.set_io$$head(head);dut.set_io$$headMask((0xffffu<<head)&0xffffu);
  dut.set_io$$resident$$valid(s>=0);dut.set_io$$resident$$bits(s<0?0:s);
  dut.set_io$$descriptor$$valid(q>=0&&mutation!="--omit-q-reservation");dut.set_io$$descriptor$$bits(q<0?0:q);
  dut.set_io$$issued(issued);dut.step();
  unsigned active=enabled?ready:0;
  auto readyAt=[&](int x){return x>=0&&bool(active&(1u<<x));};
  auto waitAt=[&](int x){return x>=0&&bool(waiting&(1u<<x));};
  auto age=[&](int x){return (unsigned(x)-head)&15u;};
  int fresh=-1;
  for(unsigned n=0;n<16;n++){int x=(head+n)%16;if(x!=s&&x!=q&&readyAt(x)){fresh=x;break;}}
  bool freshReady=fresh>=0;
  if(fresh<0)for(unsigned n=0;n<16;n++){int x=(head+n)%16;if(x!=s&&x!=q&&waitAt(x)){fresh=x;break;}}
  bool replace=false;
  if(fresh>=0){
   if(readyAt(q))replace=freshReady&&age(fresh)<age(q);
   else if(waitAt(q))replace=freshReady||age(fresh)<age(q);
   else replace=true;
  }
  bool transfer=readyAt(q)&&!replace&&(!readyAt(s)||issued||age(q)<age(s));
  Result r{fresh,fresh>=0&&(replace||transfer),transfer,readyAt(s)&&!issued&&!transfer,
   (readyAt(q)||waitAt(q))&&!transfer&&!(fresh>=0&&(replace||transfer))};
  bool gotTransfer=dut.get_io$$transfer();
  bool gotCapture=dut.get_io$$capture();
  if(mutation=="--unready-transfer"&&waitAt(q))gotTransfer=true;
  if(mutation=="--waiting-over-ready"&&readyAt(q)&&fresh>=0&&!freshReady)gotCapture=true;
  if(gotCapture!=r.capture||gotTransfer!=r.transfer||bool(dut.get_io$$keepResident())!=r.keepS||
     bool(dut.get_io$$keepDescriptor())!=r.keepQ||bool(dut.get_io$$nextDescriptorValid())!=(r.capture||r.keepQ)||bool(dut.get_io$$freshValid())!=(fresh>=0)||
     dut.get_io$$freshIndex()!=unsigned(fresh<0?0:fresh)||dut.get_io$$freshOwner()!=(fresh<0?0u:1u<<fresh))
   throw std::runtime_error("independent early-load descriptor mismatch");
  checks++;refills+=r.capture&&r.transfer;preempts+=r.capture&&q>=0&&!r.transfer;waits+=r.keepQ&&waitAt(q);
  readyWins+=r.capture&&waitAt(q)&&freshReady;return r;
 };
 // Directed mutation witnesses, readiness transition, ready-priority and virtual idle retention.
 check(0,3,0,-1,0,false,true);
 check(2,1,0,-1,1,false,true);
 // Ready Q blocked behind older ready S: older waiting fresh must not replace Q.
 check((1<<1)|(1<<4),1<<0,0,1,4,false,true);
 auto a=check(1<<9,1<<2,0,9,2,false,true);
 if(!a.keepQ||!a.keepS||a.transfer)throw std::runtime_error("waiting Q blocked ready S");
 auto b=check(1<<9,1<<2,0,-1,2,false,true);
 if(!b.capture||b.fresh!=9||b.transfer)throw std::runtime_error("ready fresh did not evict waiting Q");
 auto c=check(1<<9,1<<2,0,-1,9,false,true);
 if(!c.transfer||!c.capture||c.fresh!=2)throw std::runtime_error("ready transfer plus waiting refill failed");
 auto d=check(0,1<<2,0,-1,2,false,false);
 if(!d.keepQ||d.transfer)throw std::runtime_error("virtual idle dropped waiting Q");
 auto e=check(1<<2,0,0,-1,2,false,true);
 if(!e.transfer)throw std::runtime_error("registered wake did not enable transfer");
 // All heads / every ready mask; waiting mask varied independently, disjoint by construction.
 std::mt19937 rng(0xe4111);
 for(unsigned head=0;head<16;head++)for(unsigned ready=0;ready<65536;ready++){
  unsigned waiting=(rng()&65535u)&~ready;
  int s=int(rng()%17)-1,q=int(rng()%17)-1;if(s>=0&&s==q)q=-1;
  check(ready,waiting,head,s,q,rng()&1,rng()&1);
 }
 uint64_t launches=0;
 for(unsigned head=0;head<16;head++){
  unsigned mask=65535;int s=-1,q=-1;unsigned h=head;
  for(unsigned cycle=0;cycle<18;cycle++){
   bool issue=s>=0;auto r=check(mask,0,h,s,q,issue,true);
   if(cycle>=2&&!issue)throw std::runtime_error("ready-only II=1 lost");
   if(issue){if(s!=int(h))throw std::runtime_error("oldest issue lost");mask&=~(1u<<s);h=(h+1)%16;launches++;}
   int ns=r.transfer?q:(r.keepS?s:-1),nq=r.capture?r.fresh:(r.keepQ?q:-1);
   if(ns>=0&&ns==nq)throw std::runtime_error("duplicate Q/S owner");s=ns;q=nq;
  }
 }
 if(!waits||!readyWins||!refills||!preempts||launches!=256)throw std::runtime_error("missing coverage");
 std::cout<<"EARLY_LOAD_SELECTOR_PASS checks="<<checks<<" waiting="<<waits<<" ready_preempts="<<readyWins
  <<" refills="<<refills<<" preempts="<<preempts<<" launches="<<launches<<"\n";
}catch(const std::exception&e){std::cerr<<"EARLY_LOAD_SELECTOR_FAIL "<<e.what()<<'\n';return 1;}
