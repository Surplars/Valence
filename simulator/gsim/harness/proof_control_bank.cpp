#include "ProofControlBankGsim.h"
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
static void require(bool b,const char*s){if(!b)throw std::runtime_error(s);}
struct B {
 SProofControlBankGsim d; unsigned collisions=0,stales=0,evictions=0;
 B(){std::memset(&d,0,sizeof d);d.LOG_START=1;d.activateAll();d.set_io$$overrideIndex(15);
  d.set_io$$loadAddress(0x80200080ULL);d.set_io$$stable(1);d.set_io$$replyValid(1);
  d.set_reset(1);tick();tick();d.set_reset(0);tick();tick();}
 void tick(){d.step();collisions+=d.get_io$$oldNewCollision();stales+=d.get_io$$staleIncoming();evictions+=d.get_io$$evict();}
 void wait(unsigned n){while(n--)tick();}
 void load(unsigned i,uint64_t a){d.set_io$$loadIndex(i);d.set_io$$loadAddress(a);d.set_io$$loadCandidate(1);tick();d.set_io$$loadCandidate(0);}
 void expectLoad(unsigned i,uint64_t a,bool mutation=false,bool waitForCollision=false){
  bool seen=false;
  for(unsigned n=0;n<8;++n){tick();
   // The old A certificate legally remains valid until the incoming-B collision.
   // Validate it too; require exact B only from that independently witnessed edge.
   const bool before=waitForCollision&&collisions==0;
   const unsigned expectedIndex=before?8:i;const uint64_t expectedAddress=before?0x80200080ULL:a;
   const bool observedValid=d.get_io$$load$$valid() && !(mutation&&!before);
   if(observedValid){require(d.get_io$$load$$bits$$token$$index()==expectedIndex &&
     d.get_io$$load$$bits$$token$$tag()==expectedIndex+1 && d.get_io$$load$$bits$$address()==expectedAddress &&
     d.get_io$$load$$bits$$physicalAddress()==expectedAddress+4096 && d.get_io$$load$$bits$$allowed(),
     "independent load certificate payload mismatch");if(!before)seen=true;}
  }
  require(seen,"fresh different live owner result lost or stale result overwrote retained load");
 }
 void fill(){d.set_io$$storeMask(0xe0);d.set_io$$queryMask(0xe0);wait(20);
  require(d.get_io$$proof0$$valid()&&d.get_io$$proof1$$valid()&&d.get_io$$proof2$$valid(),"three real store rows did not fill");
  require(d.get_io$$proof0$$bits$$token$$index()==5&&d.get_io$$proof1$$bits$$token$$index()==6&&
   d.get_io$$proof2$$bits$$token$$index()==7,"independent oldest-owner row ordering mismatch");d.set_io$$queryMask(0);}
};
int main(int argc,char**argv)try{
 const std::string mode=argc>1?argv[1]:"";
 if(mode=="--bind-evict") {B b;b.fill();b.d.set_io$$storeMask(0xe1);b.d.set_io$$queryMask(1);b.d.set_io$$bind(4);b.wait(3);
   throw std::runtime_error("missing bind/query/evict exclusion assertion");}
 if(mode=="--bound-epoch") {B b;b.fill();b.d.set_io$$bind(1);b.tick();b.d.set_io$$bind(0);b.d.set_io$$epoch(1);b.wait(3);
   throw std::runtime_error("missing surviving bound epoch assertion");}
 {B b;b.d.set_io$$loadMask((1u<<8)|(1u<<9));b.load(8,0x80200080);b.expectLoad(8,0x80200080);
  b.d.set_io$$dropIndex(8);b.d.set_io$$dropOldOnIncoming(1);b.load(9,0x80200088);
  b.expectLoad(9,0x80200088,mode=="--mutate-load",true);require(b.collisions,"old/new load collision was not exercised");
  std::cout<<"C1_BANK_FRESH_WINS_OLD_INVALID_PASS collisions="<<b.collisions<<'\n';}
 {B b;b.d.set_io$$loadMask((1u<<8)|(1u<<9));b.load(8,0x80200080);b.expectLoad(8,0x80200080);
  b.d.set_io$$dropIncomingOwner(1);b.load(9,0x80200088);b.expectLoad(8,0x80200080);
  require(b.stales,"stale incoming load was not exercised");std::cout<<"C1_BANK_STALE_INCOMING_RETAINS_CURRENT_PASS\n";}
 {B b;b.d.set_io$$loadMask((1u<<8)|(1u<<9));b.load(8,0x80200080);b.expectLoad(8,0x80200080);
  b.d.set_io$$flushOnIncoming(1);b.load(9,0x80200088);b.wait(7);
  require(!b.d.get_io$$load$$valid(),"context cancellation did not dominate fresh result");std::cout<<"C1_BANK_CONTEXT_DOMINATES_PASS\n";}
 for(unsigned mask=1;mask<8;++mask){B b;b.fill();b.d.set_io$$bind(mask);b.tick();b.d.set_io$$bind(0);b.wait(2);
  require(b.d.get_io$$bound()==mask && !b.evictions,"bank failed legal full row-subset binding");}
 {B b;b.fill();b.d.set_io$$storeMask(0xe1);b.d.set_io$$queryMask(1);b.wait(12);
  require(b.evictions==1 && b.d.get_io$$proof2$$valid() && b.d.get_io$$proof2$$bits$$token$$index()==0,
    "independent eviction/admission oldest replacement failed");std::cout<<"C1_BANK_EVICTION_PASS\n";}
 {B b;b.fill();b.d.set_io$$queryMask(1u<<5);b.d.set_io$$overrideIndex(5);b.d.set_io$$overrideTag((1ULL<<63)|6);b.tick();
  require(!b.d.get_io$$proof0$$valid(),"old full-tag owner retained proof authority");b.wait(12);
  require(b.d.get_io$$proof0$$valid()&&b.d.get_io$$proof0$$bits$$token$$tag()==((1ULL<<63)|6),
    "new highest-tag-bit owner failed safe reclamation/requery");std::cout<<"C1_BANK_FULL_TAG_REUSE_PASS\n";}
 std::cout<<"C1_BANK_COMPONENT_PASS masks=7\n";return 0;
}catch(const std::exception&e){std::cerr<<"C1_BANK_COMPONENT_FAIL "<<e.what()<<'\n';return 1;}
