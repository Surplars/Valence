#include "AtomicMemory.h"
#include <array>
#include <bit>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
static constexpr uint64_t base=0x80010000;
#ifndef RAM_BYTES
#define RAM_BYTES 4096
#endif
static constexpr unsigned ramBytes=RAM_BYTES;
static_assert(ramBytes==4096||ramBytes==8192);
static void check(bool b,const char*m){if(!b)throw std::runtime_error(m);}
struct Request {
 uint64_t address=base,data=0;unsigned size=3,mask=255;bool write=false,atomic=false;unsigned op=0;
 bool operator==(const Request&)const=default;
};
struct Reply {uint64_t data=0;bool error=false;unsigned due=0;bool atomic=false;};
struct Bus {Request request;bool error;};
using Memory=std::array<uint8_t,ramBytes>;
static bool legal(const Request&r){return r.address>=base&&r.address<=base+ramBytes-(1U<<r.size)&&!(r.address&((1U<<r.size)-1))&&r.mask==(((1U<<(1U<<r.size))-1)<<(r.address&7));}
static uint64_t beat(const Memory&m,uint64_t address){uint64_t v=0;for(unsigned i=0;i<8;++i)v|=uint64_t(m[((address-base)&~7ULL)+i])<<(8*i);return v;}
static void write(Memory&m,const Request&r){for(unsigned i=0;i<8;++i)if(r.mask&(1U<<i))m[((r.address-base)&~7ULL)+i]=r.data>>(8*i);}
static uint64_t narrow(uint64_t v,unsigned size){return size==2?uint32_t(v):v;}
static uint64_t extendWord(uint64_t v,unsigned size){return size==2?uint64_t(int64_t(std::bit_cast<int32_t>(uint32_t(v)))):v;}
static uint64_t calculate(unsigned op,uint64_t a,uint64_t b,unsigned size){
 a=narrow(a,size);b=narrow(b,size);auto sa=std::bit_cast<int64_t>(extendWord(a,size)),sb=std::bit_cast<int64_t>(extendWord(b,size));
 switch(op){case 0:return a+b;case 1:return b;case 4:return a^b;case 8:return a|b;case 12:return a&b;
 case 16:return sa<sb?a:b;case 20:return sa>sb?a:b;case 24:return std::min(a,b);case 28:return std::max(a,b);default:throw std::runtime_error("oracle operation");}
}
static Request atomic(unsigned op,uint64_t address,uint64_t value=0,unsigned size=3){return {address,value,size,unsigned(((1U<<(1U<<size))-1)<<(address&7)),false,true,op};}
struct Test {
 SAtomicMemory d;std::mt19937_64 rng;Memory actual{},expected{};
 std::array<Request,2> request{};std::array<bool,2> offer{};
 std::array<std::deque<Reply>,2> replies;std::deque<Reply> memory;std::deque<Bus> plan;
 std::array<std::optional<Reply>,2> heldResponse;std::optional<Request> heldRequest;
 bool random=false,zero=false,active=false,reserved=false,inject=false,clearNext=false,clearRead=false,clearMid=false;
 uint64_t reservation=0;unsigned reservationSize=0,currentOp=0,latency=1,errorStage=0;
 unsigned cycle=0,busCount=0,atomics=0,successfulSc=0,failedSc=0,peak=0,stream=0,maxStream=0,fair=0,turn=0;
 std::array<unsigned,2> accepted{},completed{};
 Test(unsigned seed,bool immediate=false,bool corrupt=false):rng(seed),zero(immediate),inject(corrupt){
  for(auto&b:actual)b=rng();expected=actual;d.set_reset(1);tick();tick();d.set_reset(0);
 }
 void tick(){
  bool mr=zero?bool(heldRequest)&&memory.empty():(!random||rng()%4!=0);
  bool rv=!memory.empty()&&memory.front().due<=cycle;
  Reply response=rv?memory.front():Reply{};
  bool direct=zero&&heldRequest&&mr;
  if(direct){rv=true;bool error=!legal(*heldRequest)||(active&&!plan.empty()&&plan.front().error);
   response={error||heldRequest->write?0:beat(actual,heldRequest->address),error,cycle};}
  bool clear=clearNext||(clearMid&&active)||(clearRead&&active&&currentOp==2&&rv);
  if(clear){clearNext=clearMid=clearRead=false;}
  std::array<bool,2> ready{!random||rng()%3!=0,!random||rng()%3!=0};
  d.set_io$$clearReservation(clear);
#define INPUT(C,I) d.set_io$$##C##$$request$$valid(offer[I]);d.set_io$$##C##$$request$$bits$$address(request[I].address);d.set_io$$##C##$$request$$bits$$data(request[I].data);d.set_io$$##C##$$request$$bits$$size(request[I].size);d.set_io$$##C##$$request$$bits$$mask(request[I].mask);d.set_io$$##C##$$request$$bits$$write(request[I].write);d.set_io$$##C##$$response$$ready(ready[I]);
  INPUT(cpu,0);INPUT(dma,1);
#undef INPUT
  d.set_io$$cpu$$request$$bits$$atomic(request[0].atomic);d.set_io$$cpu$$request$$bits$$operation(request[0].op);
  d.set_io$$memory$$request$$ready(mr);d.set_io$$memory$$response$$valid(rv);
  d.set_io$$memory$$response$$bits$$data(response.data);d.set_io$$memory$$response$$bits$$error(response.error);d.step();
  std::array<bool,2> take{offer[0]&&bool(d.get_io$$cpu$$request$$ready()),offer[1]&&bool(d.get_io$$dma$$request$$ready())};
  check(!(take[0]&&take[1]),"two requests accepted");if(active)check(!take[0]&&!take[1],"request interleaved inside atomic lock");
  bool start=take[0]&&request[0].atomic;
  if(clear)reserved=false;
  if(start){
   check(memory.empty()&&replies[0].empty()&&replies[1].empty(),"atomic before ordinary drain");
   active=true;currentOp=request[0].op;++atomics;auto r=request[0];
   bool known=r.op==0||r.op==1||r.op==2||r.op==3||r.op==4||r.op==8||r.op==12||r.op==16||r.op==20||r.op==24||r.op==28;
   bool valid=known&&r.size>=2&&legal(r);uint64_t value=0;bool error=!valid;
   if(valid){
    if(r.op==3){
     bool success=reserved&&r.address==reservation&&r.size==reservationSize;
     value=success?0:1;success?++successfulSc:++failedSc;
     if(success){Request wr=r;wr.atomic=false;wr.op=0;wr.write=true;wr.data=r.data<<((r.address&7)*8);
      error=errorStage==2;plan.push_back({wr,error});if(!error)write(expected,wr);}
    }else{
     Request rd=r;rd.atomic=false;rd.op=0;rd.write=false;rd.data=0;bool readError=errorStage==1;plan.push_back({rd,readError});
     value=extendWord(beat(expected,r.address)>>((r.address&7)*8),r.size);error=readError;
     if(!readError&&r.op!=2){Request wr=rd;wr.write=true;wr.data=calculate(r.op,value,r.data,r.size)<<((r.address&7)*8);
      error=errorStage==2;plan.push_back({wr,error});if(!error)write(expected,wr);}
    }
   }
   if(r.op==2||r.op==3||(r.address>>6)==(reservation>>6))reserved=false;
   if(valid&&r.op==2&&errorStage!=1&&!clear){reserved=true;reservation=r.address;reservationSize=r.size;}
   replies[0].push_back({value,error,0,true});errorStage=0;turn=1;
  }else for(unsigned i=0;i<2;++i)if(take[i]){
   auto r=request[i];bool error=!legal(r);uint64_t value=error||r.write?0:beat(expected,r.address);
   if(!error&&r.write)write(expected,r);
   if(r.write&&(r.address>>6)==(reservation>>6))reserved=false;
   replies[i].push_back({value,error});
   if(offer[0]&&offer[1]){check(i==turn,"normal arbitration fairness");++fair;}turn=!i;
  }
  Request bus{d.get_io$$memory$$request$$bits$$address(),d.get_io$$memory$$request$$bits$$data(),d.get_io$$memory$$request$$bits$$size(),d.get_io$$memory$$request$$bits$$mask(),bool(d.get_io$$memory$$request$$bits$$write())};
  bool bv=d.get_io$$memory$$request$$valid(),fire=bv&&mr;
  if(heldRequest)check(bv&&bus==*heldRequest,"stalled memory request changed");
  if(fire){
   bool error=!legal(bus);
   if(active){check(!start&&!plan.empty(),"unexpected atomic memory transaction");auto wanted=plan.front();plan.pop_front();
    uint64_t enabledBytes=0;for(unsigned b=0;b<8;++b)if(bus.mask&(1U<<b))enabledBytes|=UINT64_C(255)<<(8*b);
    bool matches=bus.address==wanted.request.address&&bus.size==wanted.request.size&&bus.mask==wanted.request.mask&&bus.write==wanted.request.write&&(!bus.write||(bus.data&enabledBytes)==(wanted.request.data&enabledBytes));
    if(!matches)std::cerr<<"cycle="<<cycle<<" op="<<currentOp<<" address="<<std::hex<<bus.address<<"/"<<wanted.request.address<<" data="<<bus.data<<"/"<<wanted.request.data<<std::dec<<" write="<<bus.write<<"/"<<wanted.request.write<<" size="<<bus.size<<"/"<<wanted.request.size<<" mask="<<bus.mask<<"/"<<wanted.request.mask<<"\n";
    check(matches,"atomic bus sequence mismatch");error=wanted.error;
   }else {unsigned i=take[1]?1:0;check(take[i]&&bus==request[i],"ordinary request mapping");}
   Reply out{error||bus.write?0:beat(actual,bus.address),error,direct?cycle:cycle+latency};
   if(!error&&bus.write)write(actual,bus);
   if(!direct||!d.get_io$$memory$$response$$ready())memory.push_back(out);
   if(direct)check(rv&&out.data==response.data&&out.error==response.error,"zero-cycle response model");
   ++busCount;maxStream=std::max(maxStream,++stream);
  }else stream=0;
  if(!active)check(fire==(take[0]||take[1]),"ordinary handshake");
  heldRequest=bv&&!mr?std::optional<Request>(bus):std::nullopt;
  if(rv&&d.get_io$$memory$$response$$ready()){if(!direct){check(!memory.empty(),"memory response missing");memory.pop_front();}}
  std::array<bool,2> valid{bool(d.get_io$$cpu$$response$$valid()),bool(d.get_io$$dma$$response$$valid())};
  std::array<Reply,2> output{{{d.get_io$$cpu$$response$$bits$$data(),bool(d.get_io$$cpu$$response$$bits$$error())},{d.get_io$$dma$$response$$bits$$data(),bool(d.get_io$$dma$$response$$bits$$error())}}};
  for(unsigned i=0;i<2;++i){
   if(heldResponse[i])check(valid[i]&&output[i].data==heldResponse[i]->data&&output[i].error==heldResponse[i]->error,"held response changed");
   if(valid[i]){
    check(!replies[i].empty(),"unsolicited client response");auto wanted=replies[i].front();auto value=output[i].data;
    if(inject&&!wanted.error){value^=1;inject=false;}
    check(output[i].error==wanted.error&&(wanted.error||value==wanted.data),"atomic response mismatch");
    if(wanted.atomic)check(plan.empty()&&memory.empty(),"atomic completed before final response");
    if(ready[i]){if(wanted.atomic){active=false;check(actual==expected,"atomic memory mismatch");}replies[i].pop_front();++completed[i];}
   }
   heldResponse[i]=valid[i]&&!ready[i]?std::optional<Reply>(output[i]):std::nullopt;
   if(take[i]){offer[i]=false;++accepted[i];}
  }
  peak=std::max(peak,unsigned(memory.size()));check(memory.size()<=8,"credit overflow");++cycle;
 }
 void access(Request r,unsigned client=0){unsigned goal=completed[client]+1,limit=cycle+10000;check(!offer[client],"overwritten offer");request[client]=r;offer[client]=true;
  while(completed[client]<goal){tick();check(cycle<limit,"access timeout");}}
 void drain(){unsigned limit=cycle+10000;while(offer[0]||offer[1]||active||!memory.empty()||!replies[0].empty()||!replies[1].empty()){tick();check(cycle<limit,"drain timeout");}check(actual==expected,"final memory mismatch");}
};
int main(int argc,char**){try{
 for(bool zero:{false,true})for(unsigned latency:{1U,12U}){
  Test t(415,zero,argc>1);t.latency=latency;t.random=true;
  std::array<uint64_t,8> values{0,1,~UINT64_C(0),UINT64_C(0x8000000000000000),UINT64_C(0x7fffffffffffffff),0x80000000,0x7fffffff,0x123456789abcdef0};
  for(unsigned op:{0U,1U,4U,8U,12U,16U,20U,24U,28U})for(unsigned pos:{0U,4U,8U})for(unsigned k=0;k<values.size();++k){
   t.access({base+(pos&~7U),values[k],3,255,true});t.access(atomic(op,base+pos,values[(k+3)%values.size()],pos==8?3:2));
  }
  // Most recent LR, same/different granule writes, failed SC consumes reservation, exact width/address.
  for(unsigned size:{2U,3U}){
   t.access(atomic(3,base,19,size));t.access(atomic(2,base,0,size));t.access(atomic(3,base,23,size));t.access(atomic(3,base,24,size));
   t.access(atomic(2,base,0,size));t.access({base+64,7,3,255,true},1);t.access(atomic(3,base,29,size));
   t.access(atomic(2,base,0,size));t.access({base+8,7,3,255,true},1);t.access(atomic(3,base,31,size));
   t.access(atomic(2,base,0,size));t.access({base,7,3,255,true},1);t.access(atomic(3,base,37,size));
   t.access(atomic(2,base,0,size));t.access(atomic(3,base+64,41,size));t.access(atomic(3,base,43,size));
   t.access(atomic(2,base,0,size));t.access(atomic(2,base+64,0,size));t.access(atomic(3,base,47,size));
   t.access(atomic(2,base,0,size));t.access({base,7,3,255,true});t.access(atomic(3,base,49,size));
   t.access(atomic(2,base,0,size));t.access(atomic(3,base,51,size==2?3:2));t.access(atomic(3,base,52,size));
   t.access(atomic(2,base,0,size));t.clearNext=true;t.tick();t.access(atomic(3,base,53,size));
   t.clearMid=true;t.access(atomic(2,base,0,size));t.access(atomic(3,base,59,size));
   t.clearRead=true;t.access(atomic(2,base,0,size));t.access(atomic(3,base,61,size));
  }
  for(unsigned stage:{1U,2U}){t.errorStage=stage;t.access(atomic(0,base,71));}
  t.errorStage=1;t.access(atomic(2,base));t.access(atomic(3,base,73));
  t.access(atomic(2,base));t.clearMid=true;t.access(atomic(3,base,77));
  t.access(atomic(2,base));t.errorStage=2;t.access(atomic(3,base,79));t.access(atomic(3,base,83));
  for(auto r:{atomic(31,base),atomic(0,base+1),atomic(0,base+ramBytes),atomic(0,~UINT64_C(0)-7),atomic(2,base,0,1)})t.access(r);
  auto badMask=atomic(0,base);badMask.mask=1;t.access(badMask);
  if constexpr(ramBytes==8192){
   const auto upper=base+4096,last=base+ramBytes-8;
   t.access({upper,UINT64_C(0x123456789abcdef0),3,255,true});
   t.access(atomic(0,upper,7));t.access(atomic(2,upper));t.access(atomic(3,upper,23));
   t.access(atomic(2,upper));t.access({upper,31,3,255,true},1);t.access(atomic(3,upper,37));
   t.access({last,UINT64_C(0xfedcba9876543210),3,255,true});
   t.access(atomic(4,last+4,UINT64_C(0x12345678),2));
   t.access(atomic(2,last));t.access(atomic(3,last,UINT64_C(0x98765432)));
   t.access(atomic(0,base+ramBytes));
  }
  for(unsigned cycle=0;cycle<16000;++cycle){
   for(unsigned i=0;i<2;++i)if(!t.offer[i]){
    unsigned offset=(t.rng()%512)*8;t.request[i]={base+offset,t.rng(),3,255,bool(t.rng()%2)};
    if(i==0&&cycle>=500&&t.rng()%4){unsigned op=std::array<unsigned,11>{0,1,2,3,4,8,12,16,20,24,28}[t.rng()%11];t.request[i]=atomic(op,base+offset,t.rng(),t.rng()%2?2:3);}
    t.offer[i]=true;
   }
   t.random=cycle>=500;t.tick();
  }
  t.drain();check(t.successfulSc>=4&&t.failedSc>=15&&t.atomics>200&&t.fair>100,"atomic coverage");
  if(!zero&&latency==1)check(t.maxStream>400,"ordinary stream throughput");
  if(!zero&&latency==12)check(t.peak==8,"ordinary outstanding capacity");
  std::cout<<"GSIM AtomicMemory: PASS bytes="<<ramBytes<<" zero="<<zero<<" latency="<<latency<<" atomics="<<t.atomics<<" SC="<<t.successfulSc<<"/"<<t.failedSc<<" normal="<<t.accepted[0]+t.accepted[1]-t.atomics<<" bus="<<t.busCount<<" capacity="<<t.peak<<" stream="<<t.maxStream<<" fair="<<t.fair<<" cycles="<<t.cycle<<"\n";
 }
 for(unsigned latency:{1U,12U}){
  Test t(1);t.latency=latency;
  unsigned start=t.cycle;t.access(atomic(2,base));unsigned lr=t.cycle-start;
  start=t.cycle;t.access(atomic(3,base,1));unsigned sc=t.cycle-start;
  start=t.cycle;t.access(atomic(3,base,2));unsigned fail=t.cycle-start;
  start=t.cycle;t.access(atomic(0,base,3));unsigned amo=t.cycle-start;
  check(lr==latency+3&&sc==latency+3&&fail==2&&amo==2*latency+4,"isolated atomic latency");
  std::cout<<"GSIM AtomicMemory latency: memory="<<latency<<" LR="<<lr<<" SC="<<sc<<" SC-fail="<<fail<<" AMO="<<amo<<" cycles (request through response handshake inclusive)\n";
 }
}catch(const std::exception&e){std::cerr<<"GSIM AtomicMemory: FAIL "<<e.what()<<"\n";return 1;}}
