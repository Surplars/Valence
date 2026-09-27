#include "SharedReadCache.h"
#include <algorithm>
#include <array>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <vector>
static constexpr uint64_t base=0x80010000;
static void check(bool x,const char*s){if(!x)throw std::runtime_error(s);}
struct Request {uint64_t address=base,data=0;unsigned size=3,mask=255;bool write=false;bool operator==(const Request&)const=default;};
struct Reply {uint64_t data=0;bool error=false;unsigned due=0;uint64_t address=0;bool fill=false;};
struct Test {
 SSharedReadCache d;std::mt19937_64 rng{715};std::array<uint8_t,4096> mem{};
 std::array<uint64_t,16> tags{};std::array<unsigned,16> valid{};
 unsigned cycle=0,latency=1,hits=0,misses=0,bus=0,accesses=0,stalls=0;bool random=false,zero=false,inject=false;
 Test(){for(auto&b:mem)b=rng();d.set_reset(1);d.set_io$$upstream$$request$$valid(0);d.set_io$$upstream$$response$$ready(0);
 d.set_io$$memory$$request$$ready(0);d.set_io$$memory$$response$$valid(0);d.step();d.step();d.set_reset(0);}
 uint64_t beat(uint64_t a){uint64_t v=0;for(unsigned b=0;b<8;++b)v|=uint64_t(mem[((a-base)&~7ULL)+b])<<(8*b);return v;}
 unsigned access(Request r,bool fail=false){
  bool range=r.address>=base&&r.address<=base+4096-(1U<<r.size),aligned=!(r.address&((1U<<r.size)-1));
  bool eligible=range&&aligned&&r.mask==(((1U<<(1U<<r.size))-1)<<(r.address&7));
  unsigned line=(r.address/64)%16,sector=(r.address%64)/8;uint64_t tag=r.address/1024;
  bool hit=eligible&&!r.write&&tags[line]==tag&&(valid[line]&(1U<<sector));
  bool error=!hit&&(fail||!eligible);uint64_t expected=error||r.write?0:beat(r.address);
  if(r.write&&tags[line]==tag)valid[line]=eligible?(valid[line]&~(1U<<sector)):0;
  if(!hit&&eligible&&!r.write&&!error){if(tags[line]!=tag)valid[line]=0;tags[line]=tag;valid[line]|=1U<<sector;}
  unsigned begin=cycle,transactions=0,hitPulses=0,missPulses=0;bool sent=false,present=false,done=false;
  Reply response;std::optional<Request> held;std::optional<Reply> heldUp;
  for(;cycle<begin+1000;++cycle){
   bool ready=!random||rng()%4,accept=!random||rng()%3;
   bool rv=present&&response.due<=cycle;
   // Zero-cycle lower slave first stalls request to capture its stable payload.
   if(zero){ready=held.has_value();rv=ready;response={expected,error,cycle};}
   d.set_io$$upstream$$request$$valid(!sent);d.set_io$$upstream$$request$$bits$$address(r.address);d.set_io$$upstream$$request$$bits$$data(r.data);
   d.set_io$$upstream$$request$$bits$$size(r.size);d.set_io$$upstream$$request$$bits$$mask(r.mask);d.set_io$$upstream$$request$$bits$$write(r.write);
   d.set_io$$upstream$$response$$ready(accept);d.set_io$$memory$$request$$ready(ready);d.set_io$$memory$$response$$valid(rv);
   d.set_io$$memory$$response$$bits$$data(response.data);d.set_io$$memory$$response$$bits$$error(response.error);d.step();
   if(!sent&&d.get_io$$upstream$$request$$ready())sent=true;
   Request got{d.get_io$$memory$$request$$bits$$address(),d.get_io$$memory$$request$$bits$$data(),d.get_io$$memory$$request$$bits$$size(),d.get_io$$memory$$request$$bits$$mask(),bool(d.get_io$$memory$$request$$bits$$write())};
   bool bv=d.get_io$$memory$$request$$valid();if(held)check(bv&&got==*held,"held cache request changed");
   held=bv&&!ready?std::optional<Request>(got):std::nullopt;
   if(bv&&ready){check(!hit&&got==r&&transactions++==0,"cache lower transaction");++bus;
    response={expected,error,cycle+latency};present=!zero;
    if(r.write&&!error)for(unsigned b=0;b<8;++b)if(r.mask&(1U<<b))mem[((r.address-base)&~7ULL)+b]=r.data>>(8*b);
   }
   if(rv&&d.get_io$$memory$$response$$ready()){check(!zero||transactions==1,"zero response before request");present=false;}
   hitPulses+=d.get_io$$hit();missPulses+=d.get_io$$miss();
   bool uv=d.get_io$$upstream$$response$$valid();Reply up{d.get_io$$upstream$$response$$bits$$data(),bool(d.get_io$$upstream$$response$$bits$$error())};
   if(heldUp)check(uv&&up.data==heldUp->data&&up.error==heldUp->error,"held cache response changed");
   heldUp=uv&&!accept?std::optional<Reply>(up):std::nullopt;stalls+=uv&&!accept;
   if(uv){auto value=up.data;if(inject){value^=1;inject=false;}
    check(up.error==error&&(error||value==expected),"cache response mismatch");if(accept){done=true;++cycle;break;}}
  }
  check(done&&sent&&!present,"cache timeout/drain");check(transactions==unsigned(!hit),"cache hit/miss routing");
  check(hitPulses==unsigned(hit)&&missPulses==unsigned(eligible&&!r.write&&!hit),"cache event accounting");
  hits+=hitPulses;misses+=missPulses;++accesses;return cycle-begin;
 }
 // Multiple accepted requests: a byte-addressed architectural oracle is updated
 // in request order, independently of the downstream slave and cache hit state.
 void stream(const std::vector<Request>& requests,bool backpressure,bool allHits,int expectedLower=-1,
             unsigned expectedPeak=0,bool requireWriteOverlap=false,bool requireWriteBurst=false){
  struct Expected {Request request;Reply reply;bool issued=false;};
  std::deque<Expected> expected;auto reference=mem;
  std::deque<Reply> lower;std::optional<Reply> heldUp;std::optional<Request> heldBus;
  unsigned sent=0,received=0,start=cycle,lowerCount=0,maxPending=0,blocked=0,hitCount=0,peakLower=0;
  unsigned fillOverlap=0,fillStalls=0,writeOverlap=0,writeBurstOverlap=0,uncachedBarrier=0;
  unsigned firstAccept=0,lastAccept=0,firstReply=0,lastReply=0;
  auto bad=[](Request r){
   unsigned bytes=1U<<r.size;
   return r.address<base||r.address>base+4096-bytes||(r.address&(bytes-1))||
    r.mask!=(((1U<<bytes)-1)<<(r.address&7))||r.address==base+4088||
    (r.write&&r.data==UINT64_C(0xbadbad));
  };
  auto execute=[&](auto& bytes,Request r){
   Reply answer{0,bad(r)};if(answer.error)return answer;
   unsigned offset=(r.address-base)&~7ULL;
   if(r.write){for(unsigned b=0;b<8;++b)if(r.mask&(1U<<b))bytes[offset+b]=r.data>>(8*b);}
   else for(unsigned b=0;b<8;++b)answer.data|=uint64_t(bytes[offset+b])<<(8*b);
   return answer;
  };
  while(received<requests.size()&&cycle<start+requests.size()*100+1000){
   bool offer=sent<requests.size();Request r=offer?requests[sent]:Request{};
   // Long deterministic stalls force a full queue, followed by randomized stalls.
   bool accept=!backpressure||((cycle-start)%47>=17&&rng()%4);
   bool ready=!backpressure||rng()%3;
   bool rv=!lower.empty()&&lower.front().due<=cycle;
   d.set_io$$upstream$$request$$valid(offer);d.set_io$$upstream$$request$$bits$$address(r.address);
   d.set_io$$upstream$$request$$bits$$data(r.data);d.set_io$$upstream$$request$$bits$$size(r.size);
   d.set_io$$upstream$$request$$bits$$mask(r.mask);d.set_io$$upstream$$request$$bits$$write(r.write);
   d.set_io$$upstream$$response$$ready(accept);d.set_io$$memory$$request$$ready(ready);
   d.set_io$$memory$$response$$valid(rv);d.set_io$$memory$$response$$bits$$data(lower.empty()?0:lower.front().data);
   d.set_io$$memory$$response$$bits$$error(!lower.empty()&&lower.front().error);d.step();
   if(requireWriteOverlap&&offer&&r.address==base+4096&&
    std::any_of(expected.begin(),expected.end(),[](const Expected& e){return e.request.write;})){
    check(!d.get_io$$upstream$$request$$ready(),"uncached read crossed pending write");++uncachedBarrier;
   }
   if(offer&&d.get_io$$upstream$$request$$ready()){
    bool pendingWrite=std::any_of(expected.begin(),expected.end(),[&](const Expected& e){
     return e.request.write&&(!e.issued||std::any_of(lower.begin(),lower.end(),[&](const Reply& reply){
      return !reply.fill&&reply.address==e.request.address&&reply.due>cycle;
     }));
    });
    if(pendingWrite){if(r.write)++writeBurstOverlap;else ++writeOverlap;}
    expected.push_back({r,execute(reference,r)});if(!sent)firstAccept=cycle;lastAccept=cycle;++sent;
   }
   blocked+=offer&&!d.get_io$$upstream$$request$$ready();
   fillStalls+=d.get_io$$stalls$$fill();
   bool fillCycle=rv&&d.get_io$$memory$$response$$ready()&&!lower.empty()&&lower.front().fill;
   if(fillCycle&&offer&&!r.write&&!bad(r)){
    bool sameWord=((r.address>>3)&127)==((lower.front().address>>3)&127);
    if(sameWord)check(!d.get_io$$upstream$$request$$ready(),"read/write same SRAM word overlap");
    else if(d.get_io$$upstream$$request$$ready())++fillOverlap;
   }
   Request got{d.get_io$$memory$$request$$bits$$address(),d.get_io$$memory$$request$$bits$$data(),
    d.get_io$$memory$$request$$bits$$size(),d.get_io$$memory$$request$$bits$$mask(),bool(d.get_io$$memory$$request$$bits$$write())};
   bool bv=d.get_io$$memory$$request$$valid();
   if(heldBus)check(bv&&got==*heldBus,"stream held lower request changed");
   heldBus=bv&&!ready?std::optional<Request>(got):std::nullopt;
   if(rv&&d.get_io$$memory$$response$$ready())lower.pop_front();
   if(bv&&ready){
    auto match=std::find_if(expected.begin(),expected.end(),[&](auto& e){return !e.issued&&e.request==got;});
    check(match!=expected.end(),"stream lower request was not accepted");match->issued=true;
    lower.push_back(execute(mem,got));lower.back().due=cycle+latency;
    lower.back().address=got.address;lower.back().fill=!got.write&&!lower.back().error;++lowerCount;
    peakLower=std::max(peakLower,unsigned(lower.size()));
    check(lower.size()<=4,"stream lower outstanding exceeds four");
   }
   bool uv=d.get_io$$upstream$$response$$valid();
   Reply up{d.get_io$$upstream$$response$$bits$$data(),bool(d.get_io$$upstream$$response$$bits$$error())};
   if(heldUp)check(uv&&up.data==heldUp->data&&up.error==heldUp->error,"stream stalled response changed");
   heldUp=uv&&!accept?std::optional<Reply>(up):std::nullopt;
   if(uv){
    check(!expected.empty(),"stream unsolicited response");auto want=expected.front().reply;
    check(up.error==want.error&&(want.error||up.data==want.data),"stream ordered response mismatch");
    if(accept){expected.pop_front();if(!received)firstReply=cycle;lastReply=cycle;++received;}
   }
   maxPending=std::max(maxPending,unsigned(expected.size()));check(expected.size()<=8,"stream capacity overflow");
   hitCount+=d.get_io$$hit();++cycle;
  }
  check(received==requests.size()&&sent==received&&lower.empty()&&expected.empty(),"stream timeout/drain");
  check(mem==reference,"stream memory side effects");
  if(allHits){
   check(lowerCount==0&&hitCount==requests.size(),"warm stream went downstream");
   if(!backpressure)check(lastAccept-firstAccept==requests.size()-1&&firstReply-firstAccept==1&&
    lastReply-firstReply==requests.size()-1,"cache hit throughput must be one per cycle");
  }
  if(backpressure)check(maxPending>=3&&blocked>0,"stream full queue coverage");
  if(expectedLower>=0)check(lowerCount==unsigned(expectedLower),"stream physical read count");
  if(expectedPeak)check(peakLower>=expectedPeak,"stream parallel miss coverage");
  if(requireWriteOverlap)check(writeOverlap>0,"cacheable reads did not overlap pending writes");
  if(requireWriteBurst)check(writeBurstOverlap>0,"cacheable writes did not overlap pending writes");
  if(requireWriteOverlap&&latency==12)check(uncachedBarrier>0,"uncached write barrier was not exercised");
  if(!backpressure&&!allHits&&requests.size()==128&&latency==12)
   check(fillOverlap>0,"independent cache reads did not overlap fills");
  std::cout<<"GSIM cache stream: PASS hot="<<allHits<<" backpressure="<<backpressure<<" latency="<<latency
   <<" requests="<<requests.size()<<" cycles="<<cycle-start<<" lower="<<lowerCount<<" peakLower="<<peakLower
   <<" maxPending="<<maxPending<<" fillOverlap="<<fillOverlap<<" fillStalls="<<fillStalls
   <<" writeOverlap="<<writeOverlap<<" writeBurstOverlap="<<writeBurstOverlap
   <<" uncachedBarrier="<<uncachedBarrier<<"\n";
 }

};
int main(int argc,char**){try{
 for(bool zero:{false,true})for(unsigned latency:{1U,12U}){
  Test t;t.zero=zero;t.latency=latency;t.inject=argc>1;
  auto miss=t.access({base}),hit=t.access({base}),wr=t.access({base,19,3,255,true});
  if(!zero)check(miss==latency+2&&hit==2&&wr==latency+2,"cache latency target");
  t.access({base+8});t.access({base,23,3,255,true});
  check(t.access({base+8})==2,"same-line write must preserve other cached sector");
  t.random=true;
  for(unsigned round=0;round<12;++round)for(unsigned sector=0;sector<8;++sector){
   auto a=base+(round%4)*1024+sector*8;t.access({a});t.access({a+4,0,2,240,false});
  }
  // Read errors must not fill; write errors invalidate but do not modify memory.
  t.access({base+512,0,3,255,true});t.access({base+512},true);t.access({base+512});
  t.access({base+512,5,3,255,true},true);t.access({base+512});
  for(auto r:{Request{base+1},Request{base+4096},Request{~UINT64_C(7)},Request{base,0,3,1}})t.access(r);
  for(unsigned n=0;n<4000;++n){unsigned size=t.rng()%4;uint64_t a=base+((t.rng()%256)*8)+(t.rng()%(8>>size))*(1U<<size);
   Request r{a,t.rng(),size,unsigned(((1U<<(1U<<size))-1)<<(a&7)),bool(t.rng()%4==0)};
   t.access(r,t.rng()%19==0);if(n%4==0)t.access({a,0,size,r.mask,false});
  }
  check(t.hits>1000&&t.misses>1000&&t.stalls>100,"cache coverage");
  std::cout<<"GSIM SharedReadCache: PASS zero="<<zero<<" latency="<<latency<<" requests="<<t.accesses<<" hits="<<t.hits<<" misses="<<t.misses<<" lower="<<t.bus<<" stalls="<<t.stalls<<" cycles="<<t.cycle<<"\n";
 }
 for(unsigned latency:{1U,12U}){
  Test t;t.latency=latency;
  std::vector<Request> cold,repeated;
  for(unsigned n=0;n<128;++n)cold.push_back({base+n*8});
  for(unsigned n=0;n<64;++n)repeated.push_back({base+2048});
  t.stream(cold,false,false,128,latency==12?4:0);
  t.stream(repeated,false,false,1);
  std::vector<Request> conflicts;
  for(unsigned n=0;n<256;++n)conflicts.push_back({base+((n&1)?1024:0)+((n/2)%8)*8});
  t.stream(conflicts,true,false);
 }
 for(unsigned latency:{1U,12U}){
  Test t;t.latency=latency;
  std::vector<Request> writesAndReads;
  for(unsigned n=0;n<64;++n){
   uint64_t a=base+(n%16)*16,b=base+512+(n%16)*8;
   writesAndReads.insert(writesAndReads.end(),{{a,n+1,3,255,true},{a},{a+8},{b},{base+4096}});
  }
  t.stream(writesAndReads,false,false,-1,0,true);
 }
 for(unsigned latency:{1U,12U})for(bool stalls:{false,true}){
  Test t;t.latency=latency;
  std::vector<Request> writeBurst;
  for(unsigned n=0;n<128;++n)writeBurst.push_back({base+n*8,UINT64_C(0x100000000)+n,3,255,true});
  for(unsigned n=0;n<128;++n)writeBurst.push_back({base+n*8});
  t.stream(writeBurst,stalls,false,256,latency==12?4:0,false,true);
 }
 for(unsigned latency:{1U,12U})for(bool stalls:{false,true}){
  Test t;t.latency=latency;
  for(unsigned n=0;n<64;++n)t.access({base+n*8});
  std::vector<Request> hot,mixed;
  for(unsigned n=0;n<512;++n)hot.push_back({base+(n%64)*8});
  t.stream(hot,stalls,true);
  // Old hit / younger same-line write, replacement, failed write, failed fill,
  // narrow reads/writes and uncached illegal requests all share one ordered stream.
  for(unsigned n=0;n<128;++n){
   uint64_t a=base+(n%64)*8;
   mixed.insert(mixed.end(),{{a},{a,t.rng(),3,255,true},{a},{a+1024},{a},
    {a,UINT64_C(0xbadbad),3,255,true},{a},{base+4088},{base+4088},
    {a+4,t.rng(),2,240,true},{a+4,0,2,240},{base+4096},{base+1}});
  }
  t.stream(mixed,stalls,false);
 }

}catch(const std::exception&e){std::cerr<<"GSIM cache: FAIL "<<e.what()<<"\n";return 1;}}
