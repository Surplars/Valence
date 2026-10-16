#include "AtomicRequestProofGsim.h"
#include <cstring>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>
#include <cstdint>
static void check(bool b,const char*s){if(!b)throw std::runtime_error(s);}
struct Entry {uint64_t id;bool proof;unsigned flags;};
int main(int argc,char**argv)try{
 const std::string mutation=argc>1?argv[1]:"";
 SAtomicRequestProofGsim d;std::memset(&d,0,sizeof d);d.LOG_START=1;d.activateAll();
 std::deque<Entry> expected;unsigned cycles=0,accepted=0,consumed=0,invalidProof=0,full=0,simultaneous=0,stalled=0,flushLive=0,quiesceLive=0;
 auto tick=[&](bool valid,bool ready,uint64_t id,bool proof,unsigned flags,bool flush=false,bool quiesce=false,bool reset=false){
  d.set_reset(reset);d.set_io$$valid(valid);d.set_io$$ready(ready);d.set_io$$id(id);
  d.set_io$$proofValid(proof);d.set_io$$flags(flags);d.set_io$$flush(flush);d.set_io$$quiesce(quiesce);d.step();++cycles;
  if(reset){expected.clear();return;}
  const bool inReady=expected.size()<4,outValid=!expected.empty();
  check(d.get_io$$enqReady()==inReady,"independent non-pipe capacity/ready mismatch");
  check(d.get_io$$deqValid()==outValid,"independent non-flow publish mismatch");
  check(d.get_io$$count()==expected.size(),"independent occupancy mismatch");
  check(!d.get_io$$outProofValid() || outValid,"permission published while empty");
  check(!d.get_io$$outOriginValid() || outValid,"canonical published while empty");
  check(!d.get_io$$outFrozenValid() || outValid,"frozen published while empty");
  if(outValid){
   auto e=expected.front();uint64_t tag=d.get_io$$outTag();unsigned f=d.get_io$$outFlags();
   if(mutation=="stale-token")tag^=1;
   if(mutation=="permission")f^=2;
   check(d.get_io$$outId()==e.id,"independent request payload/order mismatch");
   check(d.get_io$$outHandle()==(e.id & HANDLE_MASK),"tagged return owner lost");
   check(d.get_io$$outProofValid()==e.proof,"false-proof load skipped or permission changed");
   check(tag==(e.id^0xdecaf123456789abULL),"independent stale token oracle mismatch");
   check(f==e.flags,"independent permission oracle mismatch");
   uint64_t origin=d.get_io$$outOrigin(),frozen=d.get_io$$outFrozen();
   if(mutation=="canonical")origin^=1;
   if(mutation=="frozen")frozen^=1;
   check(origin==e.id,"independent canonical oracle mismatch");
   check(frozen==~e.id,"independent frozen oracle mismatch");
   check(d.get_io$$outOriginValid()==bool(e.id&4),"independent canonical valid mismatch");
   check(d.get_io$$outFrozenValid()==bool(e.id&8),"independent frozen valid mismatch");
  }
  full+=!inReady;stalled+=outValid&&!ready;simultaneous+=valid&&inReady&&ready&&outValid;
  flushLive+=flush&&outValid;quiesceLive+=quiesce&&outValid;
  if(ready&&outValid){expected.pop_front();++consumed;}
  if(valid&&inReady){expected.push_back({id,proof,flags});++accepted;invalidProof+=!proof;}
 };
 tick(false,false,0,false,0,false,false,true);tick(false,false,0,false,0,false,false,true);
 tick(false,false,0,false,0);
 // Fill every slot, mixing loads and proofs. Full pop still rejects the offer.
 for(unsigned i=1;i<=4;++i)tick(true,false,i,i%2,15);
 for(unsigned i=0;i<8;++i)tick(true,false,5,false,0,true,true);
 tick(true,true,5,false,0,true,true);tick(true,true,5,false,0);
 // Interior occupancy sustains one enqueue/dequeue per cycle without a bubble.
 const auto a=accepted,b=consumed;
 for(unsigned i=6;i<70;++i)tick(true,true,i,i%3==0,(i*7)&63);
 check(accepted-a==64&&consumed-b==64,"one transfer per cycle duty changed");
 for(unsigned i=0;i<7;++i)tick(false,true,0,false,0);
 // Reset with live owners is global reset only, distinct from flush/quiesce.
 tick(true,false,100,true,15);tick(false,false,0,false,0,false,false,true);
 tick(false,true,0,false,0);
 uint64_t rng=0x5a171e;uint64_t id=1000;bool pending=false;Entry offer{};
 for(unsigned n=0;n<16000;++n){
  rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;
  if(!pending&&(rng&3)!=0){pending=true;offer={id++,(rng&4)!=0,unsigned((rng>>8)&63)};}
  const bool beforeReady=expected.size()<4;
  tick(pending,(rng&24)!=0,offer.id,offer.proof,offer.flags,n%23==0,n%17==0);
  if(pending&&beforeReady)pending=false;
 }
 if(pending){while(expected.size()==4)tick(true,true,offer.id,offer.proof,offer.flags);tick(true,true,offer.id,offer.proof,offer.flags);}
 while(!expected.empty())tick(false,true,0,false,0);
 tick(false,true,0,false,0);
 check(full&&stalled&&simultaneous&&flushLive&&quiesceLive&&invalidProof,"required coverage absent");
 std::cout<<"ATOMIC_FIFO_PASS cycles="<<cycles<<" accepted="<<accepted<<" consumed="<<consumed
 <<" invalid_proof="<<invalidProof<<" full="<<full<<" simultaneous="<<simultaneous<<" stalled="<<stalled
 <<" flush_live="<<flushLive<<" quiesce_live="<<quiesceLive<<'\n';return 0;
}catch(const std::exception&e){std::cerr<<"ATOMIC_FIFO_FAIL "<<e.what()<<'\n';return 1;}
