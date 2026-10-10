#include "canonical_observer.hpp"
#include <vector>
#include <iostream>
#include <sstream>
#include <unistd.h>
using namespace canonical_overlap;
static std::vector<Sample> fixture(){
 std::vector<Sample> v(10);v[0].reset=true;
 Token st{3,0xfedcba9876543210ULL},ld{4,0x8000000000000001ULL};
 Request sv;sv.valid=sv.ready=sv.write=sv.virtualized=true;sv.address=0x4010;sv.size=3;sv.mask=255;
 Request sp=sv;sp.address=0x80200010;sp.virtualized=false;
 Request lp;lp.valid=lp.ready=lp.prechecked=true;lp.address=0x80200020;lp.size=3;lp.mask=255;lp.epoch=7;
 Certificate c;c.valid=true;c.token=st;c.epoch=7;c.va=sv.address;c.pa=sp.address;c.size=3;c.mask=255;
 for(auto&s:v){s.enabled=true;s.stable=true;s.epoch=7;}
 auto&s=v[1];s.startValid=s.startReady=s.startStore=s.startVirtual=true;s.start=st;s.startVa=sv.address;s.startSize=3;s.request=sv;s.requestOwnerValid=true;s.requestOwner=st;
 v[2].dequeue=sv;v[2].upstream=sv;v[2].direct=true;
 v[3].checked=sp;v[3].capture=c;
 for(unsigned i=4;i<=8;++i){auto&t=v[i];t.record=c;t.headValid=t.protectedValid=t.tracked=t.ownerLive=true;t.head=t.protectedToken=st;t.slots[0].live=t.slots[0].serial=t.slots[0].acceptedKnown=t.slots[0].accepted=t.slots[0].storeClass=true;t.slots[0].token=st;}
 auto&t=v[4];t.startValid=t.startReady=t.startVirtual=t.startPrechecked=true;t.start=ld;t.startVa=0x4020;t.startPa=lp.address;t.startSize=3;t.startEpoch=7;t.request=lp;t.requestOwnerValid=true;t.requestOwner=ld;t.ownerPush=true;t.checkedDequeue=sp;t.physical=sp;
 v[5].dequeue=lp;v[5].upstream=lp;v[5].direct=true;
 v[6].checked=lp;v[7].ownerPush=true;v[7].checkedDequeue=lp;v[7].physical=lp;
 v[8].physicalResponse.valid=v[8].physicalResponse.ready=v[8].upstreamResponse.valid=v[8].upstreamResponse.ready=true;
 v[9].physicalResponse.valid=v[9].physicalResponse.ready=v[9].upstreamResponse.valid=v[9].upstreamResponse.ready=true;
 return v;
}
static std::vector<Sample> cacheFixture(bool miss){auto v=fixture();for(auto&s:v)s.cacheObserved=true;
 v[4].cache=v[4].physical;v[4].cacheFound=v[4].cacheWriteHit=!miss;v[4].cacheBarrierRequest=miss;
 if(!miss){v[7].cache=v[7].physical;v[7].cacheFound=v[7].cacheReadHit=true;v[8].cacheResponse=v[8].physicalResponse;v[9].cacheResponse=v[9].physicalResponse;}
 else{v.resize(11);for(auto&s:v)s.cacheObserved=true;for(unsigned i=5;i<=8;++i)v[i].cacheBarrier=true;
  v[7].physical={};v[7].checkedDequeue={};v[7].ownerPush=false;v[8].cacheResponse=v[8].physicalResponse;
  v[9].physicalResponse={};v[9].upstreamResponse={};v[9].ownerPush=true;v[9].checkedDequeue=v[6].checked;v[9].physical=v[6].checked;v[9].cache=v[9].physical;v[9].cacheFound=v[9].cacheReadHit=true;
  v[10].physicalResponse.valid=v[10].physicalResponse.ready=v[10].upstreamResponse.valid=v[10].upstreamResponse.ready=true;v[10].cacheResponse=v[10].physicalResponse;
 }return v;}
static void run(std::vector<Sample>v,bool positive){
 char path[]="/tmp/canonical-observer-XXXXXX";int fd=mkstemp(path);need(fd>=0,"temporary test trace");close(fd);setenv("CANONICAL_OVERLAP_TRACE",path,1);
 try{Observer o;for(unsigned i=0;i<v.size();++i)o.sample(v[i],i,i>=4&&i<=7);std::ostringstream summary;o.finish(summary);if(positive)need(o.startsOverlap==1&&o.upstreamOverlap==1&&o.physicalOverlap==1&&o.captures==1,"three causal boundaries not observed");unlink(path);}catch(...){unlink(path);throw;}
}
int main(){try{run(fixture(),true);run(cacheFixture(false),true);run(cacheFixture(true),false);unsigned rejected=0;
 for(unsigned k=0;k<5;++k){auto v=fixture();if(k==0)v[3].capture.token.tag^=(1ULL<<63);if(k==1)v[2].direct=false;if(k==2)v[7].physical.address+=8;if(k==3)v[8].physicalResponse.ready=false;if(k==4)v[3].capture.mask=15;try{run(v,false);}catch(const std::runtime_error&){++rejected;}}
 need(rejected==5,"canonical negative mutation escaped");
 {auto v=fixture();for(auto&s:v)if(s.record.valid)s.record.epoch=8;bool rejectedEpoch=false;try{run(v,false);}catch(const std::runtime_error&){rejectedEpoch=true;}need(rejectedEpoch,"record epoch mismatch escaped");}
 {auto v=cacheFixture(false);v[7].cache.address+=8;bool caught=false;try{run(v,false);}catch(const std::runtime_error&){caught=true;}need(caught,"cache full owner/address mismatch escaped");}
 {auto v=cacheFixture(true);v[7].cache=v[6].checked;bool caught=false;try{run(v,false);}catch(const std::runtime_error&){caught=true;}need(caught,"cache acceptance across miss barrier escaped");}
 std::cout<<"PASS canonical passive ledger full64token=1 three_boundaries=1 unknown_cannot_certify=1 physical_owner_poison=1 response_poison=1 mask_poison=1 epoch_poison=1\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
