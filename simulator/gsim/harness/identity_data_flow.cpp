#include "TranslationContextGsim.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
#ifndef PREFETCH_AUTH
#define PREFETCH_AUTH 0
#endif
#ifndef IDENTITY_FLOW
#define IDENTITY_FLOW 0
#endif
static void check(bool p,const char *m){if(!p)throw std::runtime_error(m);}
static constexpr uint64_t ram=0x80200000ULL;
static bool injectData=false,injectContext=false,injectPermission=false;
struct Request {
 uint64_t address=0,physical=0,data=0,satp=0;
 unsigned privilege=3,size=3,mask=255,atomicOp=0,pbmt=0,tlbDelay=3;
 bool write=false,atomic=false,virt=false,uncached=false,sum=false,mxr=false,page=false,access=false,physicalError=false,cancelled=false;
};
static Request request(unsigned n,bool virt=false,unsigned delay=3){
 Request r;r.address=ram+64*n;r.physical=ram+0x10000+64*n;r.data=0x9876543210abcdefULL^n;
 r.virt=virt;r.privilege=virt?1:3;r.satp=(uint64_t(virt?8:0)<<60)|(uint64_t(n+1)<<44)|(0x1234+n);
 r.sum=n&1;r.mxr=!(n&1);r.tlbDelay=delay;return r;
}
static unsigned access(const Request&r){return r.atomic?(r.atomicOp==2?0:r.atomicOp==3?1:3):r.write?1:0;}
static bool fault(const Request&r,unsigned cfg){
 const unsigned perm=access(r)==0?1:access(r)==1?2:3;
 const bool pmp=(r.privilege!=3||(cfg&128))&&((cfg&perm)!=perm);
 return r.virt&&(r.page||r.access||pmp||(r.atomic&&(r.physical<ram||r.physical>=ram+0x80000000ULL)));
}
static uint64_t value(const Request&r){return r.write?0:0x123456789abcdef0ULL^((r.virt?r.physical:r.address)*0x100100101ULL);}
struct Options {
 unsigned memoryLatency=1,blockPhysical=0,blockReply=0,pmpCfg=0x1f,pmpSwitch=0;
 bool stalls=false,dependent=false,resetHeld=false;
};
struct Stats {
 uint64_t cycles=0,physicalLatency=0,responseLatency=0,trace=1469598103934665603ULL;
 unsigned accepted=0,returned=0,physical=0,translations=0,upstreamStalls=0,physicalHolds=0,responseHolds=0,cancelled=0;
};
struct Test {
 STranslationContextGsim d;
 Test(){
  d.set_io$$upstream$$request$$valid(0);d.set_io$$upstream$$response$$ready(0);
  d.set_io$$physical$$request$$ready(0);d.set_io$$physical$$response$$valid(0);
  d.set_io$$translation$$request$$ready(0);d.set_io$$translation$$response$$valid(0);
  d.set_immediateTranslation(0);d.set_pmpCfg0(0x1f);d.set_pmpAddr0((1ULL<<54)-1);
  d.set_reset(1);d.step();d.step();d.set_reset(0);
 }
 Stats run(const std::vector<Request>&rs,Options opt={}){
  Stats s;std::deque<unsigned> owners,translate,physical;
  struct Pending{unsigned id;uint64_t due;};std::deque<Pending> memory;std::optional<Pending> tlb;
  std::vector<uint64_t> acceptedAt(rs.size()),physicalAt(rs.size());
  std::optional<std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool,bool,unsigned,bool>> heldPhysical;
  std::optional<std::tuple<uint64_t,bool,bool>> heldResponse;
  std::optional<bool> heldPermission;
  bool requestHeld=false,pmpSwitched=false;unsigned cfg=opt.pmpCfg;
  auto hash=[&](uint64_t x){s.trace^=x;s.trace*=1099511628211ULL;};
  for(;s.cycles<20000&&s.returned<rs.size();++s.cycles){
   const unsigned next=s.accepted;
   const bool offer=next<rs.size()&&(!opt.dependent||owners.empty())&&(!opt.stalls||s.cycles%7!=3||requestHeld);
   const Request poison=request(100,false);const Request &up=next<rs.size()?rs[next]:poison;
   const bool pr=s.cycles>=opt.blockPhysical&&(!opt.stalls||s.cycles%7<4);
   const bool vr=s.cycles>=opt.blockReply&&(!opt.stalls||s.cycles%11<6);
   const bool tr=!opt.stalls||s.cycles%5!=2;
   const bool immediate=!tlb&&!translate.empty()&&rs[translate.front()].tlbDelay==0;
   const bool tv=tlb&&s.cycles>=tlb->due;
   const Request &reply=tlb?rs[tlb->id]:!translate.empty()?rs[translate.front()]:poison;
   const bool mv=!memory.empty()&&s.cycles>=memory.front().due;
   d.set_io$$upstream$$request$$valid(offer);d.set_io$$upstream$$response$$ready(vr);
   d.set_io$$upstream$$request$$bits$$address(up.address);d.set_io$$upstream$$request$$bits$$data(up.data);
   d.set_io$$upstream$$request$$bits$$size(up.size);d.set_io$$upstream$$request$$bits$$mask(up.mask);
   d.set_io$$upstream$$request$$bits$$write(up.write);d.set_io$$upstream$$request$$bits$$atomic(up.atomic);
   d.set_io$$upstream$$request$$bits$$atomicOp(up.atomicOp);d.set_io$$upstream$$request$$bits$$virtualized(up.virt);
   d.set_io$$upstream$$request$$bits$$uncached(up.uncached);
   d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(1); // adapter must overwrite hostile ingress metadata
   d.set_io$$context$$satp(up.satp);d.set_io$$context$$dataPrivilege(up.privilege);d.set_io$$context$$sum(up.sum);d.set_io$$context$$mxr(up.mxr);
   d.set_pmpCfg0(cfg);d.set_pmpAddr0((1ULL<<54)-1);d.set_immediateTranslation(immediate);
   d.set_io$$translation$$request$$ready(tr);d.set_io$$translation$$response$$valid(tv);
   d.set_io$$translation$$response$$bits$$physicalAddress(reply.physical);d.set_io$$translation$$response$$bits$$pageFault(reply.page);
   d.set_io$$translation$$response$$bits$$accessFault(reply.access);d.set_io$$translation$$response$$bits$$pbmt(reply.pbmt);
   d.set_io$$physical$$request$$ready(pr);d.set_io$$physical$$response$$valid(mv);
   d.set_io$$physical$$response$$bits$$data(mv?value(rs[memory.front().id]):0);
   d.set_io$$physical$$response$$bits$$error(mv&&rs[memory.front().id].physicalError);d.set_io$$physical$$response$$bits$$pageFault(0);
   d.step();
   auto pb=std::make_tuple(uint64_t(d.get_io$$physical$$request$$bits$$address()),uint64_t(d.get_io$$physical$$request$$bits$$data()),unsigned(d.get_io$$physical$$request$$bits$$size()),unsigned(d.get_io$$physical$$request$$bits$$mask()),bool(d.get_io$$physical$$request$$bits$$write()),bool(d.get_io$$physical$$request$$bits$$atomic()),unsigned(d.get_io$$physical$$request$$bits$$atomicOp()),bool(d.get_io$$physical$$request$$bits$$uncached()));
   auto rb=std::make_tuple(uint64_t(d.get_io$$upstream$$response$$bits$$data()),bool(d.get_io$$upstream$$response$$bits$$error()),bool(d.get_io$$upstream$$response$$bits$$pageFault()));
   const bool pv=d.get_io$$physical$$request$$valid(),rv=d.get_io$$upstream$$response$$valid();
   if(heldPhysical)check(pv&&pb==*heldPhysical,"held physical request changed");
   if(heldResponse)check(rv&&rb==*heldResponse,"held virtual response changed");
   if(heldPermission)check(pv&&bool(d.get_io$$physical$$request$$bits$$prefetchNextAllowed())==*heldPermission,"held prefetch permission changed");
   heldPermission=pv&&!pr?std::optional<bool>{bool(d.get_io$$physical$$request$$bits$$prefetchNextAllowed())}:std::nullopt;
   heldPhysical=pv&&!pr?std::optional{pb}:std::nullopt;heldResponse=rv&&!vr?std::optional{rb}:std::nullopt;
   s.physicalHolds+=pv&&!pr;s.responseHolds+=rv&&!vr;
   if(!pmpSwitched&&((opt.pmpSwitch==1&&pv&&!pr)||(opt.pmpSwitch==2&&rv&&!vr))){cfg=opt.pmpSwitch==1?0x18:0x1f;pmpSwitched=true;}
   if(offer&&d.get_io$$upstream$$request$$ready()){
    acceptedAt[next]=s.cycles;owners.push_back(next);if(up.virt)translate.push_back(next);if(!fault(up,opt.pmpCfg))physical.push_back(next);
    hash(0x100000+next);hash(s.cycles);++s.accepted;
   }else if(offer)++s.upstreamStalls;
   requestHeld=offer&&!d.get_io$$upstream$$request$$ready();
   if(d.get_io$$translation$$request$$valid()&&tr){
    check(!tlb&&!translate.empty(),"translation request lacked FIFO owner");const auto id=translate.front();translate.pop_front();const auto&r=rs[id];
    check(d.get_io$$translation$$request$$bits$$virtualAddress()==r.address&&d.get_io$$translation$$request$$bits$$rootPpn()==(r.satp&((1ULL<<44)-1))&&d.get_io$$translation$$request$$bits$$asid()==(((r.satp>>44)&65535)^(injectContext?1:0))&&d.get_io$$translation$$request$$bits$$mode()==(r.satp>>60)&&d.get_io$$translation$$request$$bits$$privilege()==r.privilege&&bool(d.get_io$$translation$$request$$bits$$sum())==r.sum&&bool(d.get_io$$translation$$request$$bits$$mxr())==r.mxr&&d.get_io$$translation$$request$$bits$$access()==access(r),"independent captured VM context mismatch");
    check(immediate==(r.tlbDelay==0),"immediate TLB mode ownership mismatch");
    if(immediate)check(d.get_io$$translation$$response$$ready(),"immediate TLB reply was not accepted");else tlb=Pending{id,s.cycles+r.tlbDelay};
    hash(0x200000+id);hash(s.cycles);++s.translations;
   }
   if(tv&&d.get_io$$translation$$response$$ready()){check(bool(tlb),"late TLB reply lacked owner");tlb.reset();}
   if(pv&&pr){
    check(!physical.empty(),"fault or unowned request escaped physically");unsigned id=physical.front();physical.pop_front();const auto&r=rs[id];
    check(std::get<0>(pb)==(r.virt?r.physical:r.address)&&std::get<1>(pb)==r.data&&std::get<2>(pb)==r.size&&std::get<3>(pb)==r.mask&&std::get<4>(pb)==r.write&&std::get<5>(pb)==r.atomic&&std::get<6>(pb)==r.atomicOp&&std::get<7>(pb)==(r.uncached||(r.virt&&r.pbmt))&&!d.get_io$$physical$$request$$bits$$virtualized(),"independent physical request/order mismatch");
    const uint64_t physicalAddress=r.virt?r.physical:r.address;
    const uint64_t nextLine=(physicalAddress&~63ULL)+64;
    const bool wholePermission=(r.privilege==3&&!(opt.pmpCfg&128))||(opt.pmpCfg&1);
    const bool expectedPermission=PREFETCH_AUTH && !r.write&&!r.atomic&&!r.uncached&&!(r.virt&&r.pbmt)&&
      physicalAddress>=ram&&physicalAddress+(1ULL<<r.size)<=ram+0x80000000ULL&&
      nextLine>=ram&&nextLine+64<=ram+0x80000000ULL&&
      (physicalAddress>>12)==(nextLine>>12)&&wholePermission;
    check(bool(d.get_io$$physical$$request$$bits$$prefetchNextAllowed())==(expectedPermission^injectPermission),
      "independent captured prefetch permission mismatch");
    physicalAt[id]=s.cycles;s.physicalLatency+=s.cycles-acceptedAt[id];memory.push_back({id,s.cycles+opt.memoryLatency});++s.physical;hash(0x300000+id);hash(s.cycles);
   }
   if(rv&&vr){
    check(!owners.empty(),"unowned virtual response");unsigned id=owners.front();owners.pop_front();const auto&r=rs[id];const bool f=fault(r,opt.pmpCfg);
    check(std::get<0>(rb)==((f?0:value(r))^(injectData?1ULL:0ULL))&&std::get<1>(rb)==(f||r.physicalError)&&std::get<2>(rb)==(r.virt&&r.page),"independent response data/fault/order mismatch");
    s.responseLatency+=s.cycles-acceptedAt[id];++s.returned;s.cancelled+=r.cancelled;hash(0x400000+id);hash(s.cycles);
   }
   if(mv&&d.get_io$$physical$$response$$ready()){check(!memory.empty(),"unowned memory response");memory.pop_front();}
   if(d.get_io$$idle()&&!(offer&&d.get_io$$upstream$$request$$ready()))check(owners.empty()&&translate.empty()&&physical.empty()&&memory.empty()&&!tlb,"idle omitted an accepted owner");
   if(opt.resetHeld&&s.accepted>=2&&s.cycles>8){
    check(!d.get_io$$idle(),"reset setup lost held owners");
    d.set_io$$upstream$$request$$valid(0);d.set_io$$physical$$response$$valid(0);d.set_io$$translation$$response$$valid(0);d.set_immediateTranslation(0);
    d.set_reset(1);d.step();d.step();d.set_reset(0);d.step();check(d.get_io$$idle(),"coordinated reset did not clear adapter");return s;
   }
  }
  check(s.returned==rs.size()&&s.accepted==rs.size()&&owners.empty()&&translate.empty()&&physical.empty()&&memory.empty()&&!tlb,"adapter lost token or deadlocked");
  if(opt.pmpSwitch)check(pmpSwitched,"PMP snapshot switch not exercised");
  d.set_io$$upstream$$request$$valid(0);d.set_io$$physical$$response$$valid(0);d.set_io$$translation$$response$$valid(0);d.set_immediateTranslation(0);d.step();
  check(d.get_io$$idle(),"adapter did not become idle after every owner drained");
  return s;
 }
};
static void report(const char*name,const Stats&s){std::cout<<"IDENTITY_CASE name="<<name<<" cycles="<<s.cycles<<" accepted="<<s.accepted<<" physical="<<s.physical<<" translations="<<s.translations<<" physical_latency="<<s.physicalLatency<<" response_latency="<<s.responseLatency<<" trace="<<s.trace<<" cancelled="<<s.cancelled<<" stalls="<<s.upstreamStalls<<" physical_holds="<<s.physicalHolds<<" response_holds="<<s.responseHolds<<"\n";}
int main(int argc,char**argv){try{
 const std::string arg=argc>1?argv[1]:"";injectData=arg=="--inject-data";injectContext=arg=="--inject-context";injectPermission=arg=="--inject-permission";
 for(unsigned latency:{1U,5U}){Test t;report(latency==1?"bare_single_l1":"bare_single_l5",t.run({request(0)},Options{latency}));}
 for(unsigned kind=0;kind<3;++kind){auto r=request(1,false);r.privilege=kind==2?3:kind;r.satp=kind==2?(8ULL<<60):0;Test t;report(kind==0?"u_bare":kind==1?"s_bare":"m_satp_bypass",t.run({r}));}
 {Test t;auto r=request(2,true,0);r.privilege=1;report("mprv_effective_s",t.run({r}));}
 std::vector<Request> chain;for(unsigned n=0;n<64;++n)chain.push_back(request(n));Test dependent;Options dep;dep.dependent=true;report("bare_dependent64",dependent.run(chain,dep));
 for(unsigned delay:{0U,7U}){std::vector<Request> v;for(unsigned n=0;n<24;++n){auto r=request(n,true,delay);r.write=n%3==1;r.uncached=n%5==1;r.pbmt=n%7==2?1:0;r.privilege=n%2;r.atomic=n%8==3;r.atomicOp=r.atomic?2:0;v.push_back(r);}Test t;report(delay?"vm_delayed":"vm_immediate",t.run(v));}
 std::vector<Request> mixed;for(unsigned n=0;n<48;++n){auto r=request(n,n%3!=1,n%2?7:0);r.write=n%4==1;r.atomic=n%9==0;r.atomicOp=n%2?3:2;r.page=r.virt&&n%11==3;r.access=r.virt&&n%13==7;r.physicalError=n%17==2;r.pbmt=n%5==1?2:0;r.uncached=n%7==0;r.cancelled=n%6==4;mixed.push_back(r);}Test mix;Options slow;slow.stalls=true;slow.blockPhysical=45;slow.blockReply=90;auto ms=mix.run(mixed,slow);check(ms.physicalHolds&&ms.responseHolds&&ms.cancelled,"mixed holds/cancellation coverage missing");report("mixed_held",ms);
 std::vector<Request> spill;for(unsigned n=0;n<32;++n){auto r=request(n);r.size=n%4;r.mask=((1U<<(1U<<r.size))-1);r.write=n%3==1;r.atomic=n%5==2;r.atomicOp=2;spill.push_back(r);}Test blocked;auto bs=blocked.run(spill,slow);check(bs.upstreamStalls&&bs.physicalHolds&&bs.responseHolds,"identity spill backpressure not exercised");report("identity_spill",bs);
 {Test t;Options o;o.blockPhysical=20;o.pmpSwitch=1;report("vm_pmp_allow_snapshot",t.run({request(4,true,0)},o));}
 {Test t;Options o;o.blockReply=20;o.pmpCfg=0x18;o.pmpSwitch=2;report("vm_pmp_deny_snapshot",t.run({request(5,true,0)},o));}
 {Test t;Options o;o.pmpCfg=0x98;auto r=request(6,true,3);r.privilege=3;report("vm_locked_machine_pmp",t.run({r},o));}
 {Test t;auto r=request(7,true,0);r.atomic=true;r.atomicOp=0;r.physical=0x1000;report("vm_atomic_outside",t.run({r}));}
 {Test t;Options o;o.resetHeld=true;o.blockPhysical=100;o.blockReply=100;auto r=request(0,true,7);t.run({r,request(1)},o);report("reset_recovery",t.run({request(9)}));}
 std::cout<<"IDENTITY_DATA_FLOW_PASS flag="<<IDENTITY_FLOW<<" accepted_tokens_drained=1 vm_pmp_context=1\n";return 0;
}catch(const std::exception&e){std::cerr<<"IDENTITY_DATA_FLOW_FAIL "<<e.what()<<"\n";return 1;}}
