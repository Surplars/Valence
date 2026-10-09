#include "PhysicalIngressFlowGsim.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
#ifndef PHYSICAL_PREFETCH_AUTH
#define PHYSICAL_PREFETCH_AUTH 1
#endif
#ifndef PHYSICAL_INGRESS_FLOW
#define PHYSICAL_INGRESS_FLOW 0
#endif
static void check(bool p,const char *m){if(!p)throw std::runtime_error(m);}
static constexpr uint64_t ram=0x80200000ULL;
// Separate software request, PMP and ordered-response oracles. No DUT fault/hint verdict is reused.
static bool injectData=false,injectContext=false,injectPermission=false,injectOrder=false;
static constexpr uint64_t ramBytes=0x80000000ULL, allPmpAddress=(1ULL<<54)-1;
struct Request {
 uint64_t address=0,physical=0,data=0,satp=0;
 unsigned privilege=3,size=3,mask=255,atomicOp=0,pbmt=0,tlbDelay=3;
 bool write=false,atomic=false,virt=false,uncached=false,sum=false,mxr=false,page=false,access=false,physicalError=false,cancelled=false,prechecked=false;
};
static Request request(unsigned n,bool virt=false,unsigned delay=3){
 Request r;r.address=ram+64*n;r.physical=ram+0x10000+64*n;r.data=0x9876543210abcdefULL^n;
 r.virt=virt;r.privilege=virt?1:3;r.satp=(uint64_t(virt?8:0)<<60)|(uint64_t(n+1)<<44)|(0x1234+n);
 r.sum=n&1;r.mxr=!(n&1);r.tlbDelay=delay;return r;
}
static unsigned access(const Request&r){return r.atomic?(r.atomicOp==2?0:r.atomicOp==3?1:3):r.write?1:0;}
static bool inRam(uint64_t address,unsigned size){
 return address>=ram && __uint128_t(address)+(uint64_t(1)<<size)<=__uint128_t(ram)+ramBytes;
}
static bool pmpAllowed(uint64_t address,unsigned size,unsigned privilege,unsigned cfg,uint64_t pmpAddress,unsigned permissions){
 // Independent single-entry PMP oracle: TOR, NA4 and NAPOT, first overlap and whole access coverage.
 using Wide=__uint128_t; const Wide start=address,end=start+(Wide(1)<<size)-1;
 Wide lo=0,hi=0; const unsigned mode=(cfg>>3)&3;bool active=mode!=0;
 if(mode==1){hi=Wide(pmpAddress)*4;active=hi!=0;if(active)--hi;}
 if(mode==2){lo=Wide(pmpAddress)*4;hi=lo+3;}
 if(mode==3){unsigned trailing=0;while(trailing<54&&((pmpAddress>>trailing)&1))++trailing;
  const Wide length=Wide(1)<<(trailing+3);lo=(Wide(pmpAddress)*4)&~(length-1);hi=lo+length-1;}
 const bool overlaps=active&&start<=hi&&end>=lo;
 if(!overlaps)return privilege==3;
 const bool permission=(privilege==3&&!(cfg&128))||(cfg&permissions)==permissions;
 return start>=lo&&end<=hi&&permission;
}
static bool fault(const Request&r,unsigned cfg,uint64_t pmpAddress){
 if(r.prechecked)return true; // Fixture disables virtual certificates: hostile metadata must use the fault path.
 const unsigned perm=access(r)==0?1:access(r)==1?2:3;
 return r.virt&&(r.page||r.access||!pmpAllowed(r.physical,r.size,r.privilege,cfg,pmpAddress,perm)||
                  (r.atomic&&!inRam(r.physical,r.size)));
}
static bool eligible(const Request&r){
 return !r.virt&&!r.prechecked&&!r.write&&!r.atomic&&!r.uncached&&
        !(r.address&((1ULL<<r.size)-1))&&inRam(r.address,r.size);
}
static bool permission(const Request&r,unsigned cfg,uint64_t pmpAddress){
 const uint64_t pa=r.virt?r.physical:r.address,next=(pa&~63ULL)+64;
 return PHYSICAL_PREFETCH_AUTH&&!r.write&&!r.atomic&&!r.uncached&&!(r.virt&&r.pbmt)&&
        inRam(pa,r.size)&&inRam(next,6)&&(pa>>12)==(next>>12)&&
        pmpAllowed(next,6,r.privilege,cfg,pmpAddress,1);
}
static uint64_t value(const Request&r){return r.write?0:0x123456789abcdef0ULL^((r.virt?r.physical:r.address)*0x100100101ULL);}
struct Options {
 unsigned memoryLatency=1,blockPhysical=0,blockReply=0,pmpCfg=0x1f,pmpSwitch=0;
 bool stalls=false,dependent=false,resetHeld=false;
 uint64_t pmpAddress=allPmpAddress;
};
struct Stats {
 uint64_t cycles=0,physicalLatency=0,responseLatency=0,trace=1469598103934665603ULL;
 unsigned accepted=0,returned=0,physical=0,translations=0,upstreamStalls=0,physicalHolds=0,responseHolds=0,cancelled=0;
 uint64_t physicalTrace=1469598103934665603ULL,responseTrace=1469598103934665603ULL;
 uint64_t minPhysicalLatency=UINT64_MAX,maxPhysicalLatency=0,firstPhysical=UINT64_MAX,lastPhysical=0;
 unsigned shortcuts=0,eligibleSpills=0,checkedFullPops=0,checkedTurnovers=0,fullPopThenPush=0;
 unsigned olderTranslatedIngress=0,walkerBlockedIngress=0,permissionAllowed=0,permissionDenied=0,faults=0;
};
struct Test {
 SPhysicalIngressFlowGsim d;
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
  bool requestHeld=false,pmpSwitched=false,previousFullPop=false;unsigned cfg=opt.pmpCfg;uint64_t pmpAddress=opt.pmpAddress;
  auto hash=[&](uint64_t x){s.trace^=x;s.trace*=1099511628211ULL;};
  auto semanticHash=[](uint64_t &h,uint64_t x){h^=x;h*=1099511628211ULL;};
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
   d.set_io$$upstream$$request$$bits$$precheckedLoad(up.prechecked);
   d.set_io$$upstream$$request$$bits$$translationEpoch(up.prechecked?0x12345678:0);
   d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(1); // adapter must overwrite hostile ingress metadata
   d.set_io$$context$$satp(up.satp);d.set_io$$context$$dataPrivilege(up.privilege);d.set_io$$context$$sum(up.sum);d.set_io$$context$$mxr(up.mxr);
   d.set_pmpCfg0(cfg);d.set_pmpAddr0(pmpAddress);d.set_immediateTranslation(immediate);
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
   if(!pmpSwitched&&(((opt.pmpSwitch==1||opt.pmpSwitch==3)&&pv&&!pr)||(opt.pmpSwitch==2&&rv&&!vr))){
    cfg=opt.pmpSwitch==1?0x18:0x1f;pmpAddress=allPmpAddress;pmpSwitched=true;
   }
   const bool accepted=offer&&d.get_io$$upstream$$request$$ready();
   const bool checkedPush=d.get_io$$checkedPush(),checkedPop=d.get_io$$checkedPop();
   const bool checkedFull=d.get_io$$checkedCount()==2;
   if(checkedFull)check(!checkedPush,"full checked queue borrowed same-cycle pop credit");
   s.checkedFullPops+=checkedFull&&checkedPop;s.checkedTurnovers+=checkedPush&&checkedPop;
   s.fullPopThenPush+=previousFullPop&&checkedPush;previousFullPop=checkedFull&&checkedPop;
   if(d.get_io$$shortcut()){
    check(PHYSICAL_INGRESS_FLOW&&accepted&&eligible(up)&&!d.get_io$$ingressCount()&&
          !d.get_io$$translatedValid()&&!d.get_io$$waiting()&&!d.get_io$$ingressPush()&&checkedPush,
          "ineligible or older-owned ingress used shortcut");++s.shortcuts;
   }
   if(accepted&&eligible(up)){
    s.eligibleSpills+=checkedFull&&!d.get_io$$ingressCount()&&!d.get_io$$translatedValid()&&
                      !d.get_io$$waiting()&&d.get_io$$ingressPush();
    s.olderTranslatedIngress+=bool(d.get_io$$translatedValid());
    s.walkerBlockedIngress+=bool(d.get_io$$waiting());
   }
   if(offer&&d.get_io$$upstream$$request$$ready()){
    acceptedAt[next]=s.cycles;owners.push_back(next);if(up.virt)translate.push_back(next);if(!fault(up,opt.pmpCfg,opt.pmpAddress))physical.push_back(next);
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
    check(std::get<0>(pb)==((r.virt?r.physical:r.address)^(injectOrder?64ULL:0ULL))&&std::get<1>(pb)==r.data&&std::get<2>(pb)==r.size&&std::get<3>(pb)==r.mask&&std::get<4>(pb)==r.write&&std::get<5>(pb)==r.atomic&&std::get<6>(pb)==r.atomicOp&&std::get<7>(pb)==(r.uncached||(r.virt&&r.pbmt))&&!d.get_io$$physical$$request$$bits$$virtualized()&&!d.get_io$$physical$$request$$bits$$precheckedLoad()&&!d.get_io$$physical$$request$$bits$$translationEpoch(),"independent physical request/order mismatch");
    const bool expectedPermission=permission(r,opt.pmpCfg,opt.pmpAddress);
    s.permissionAllowed+=expectedPermission;s.permissionDenied+=!expectedPermission;
    const uint64_t latency=s.cycles-acceptedAt[id];
    check(latency>=1,"mandatory checked register boundary collapsed");
    s.minPhysicalLatency=std::min(s.minPhysicalLatency,latency);s.maxPhysicalLatency=std::max(s.maxPhysicalLatency,latency);
    if(s.firstPhysical==UINT64_MAX)s.firstPhysical=s.cycles;s.lastPhysical=s.cycles;
    for(uint64_t x:{uint64_t(id),uint64_t(std::get<0>(pb)),uint64_t(std::get<1>(pb)),uint64_t(r.size),uint64_t(r.mask),
                   uint64_t(r.write),uint64_t(r.atomic),uint64_t(r.atomicOp),uint64_t(r.uncached||(r.virt&&r.pbmt)),uint64_t(expectedPermission)})
      semanticHash(s.physicalTrace,x);
    check(bool(d.get_io$$physical$$request$$bits$$prefetchNextAllowed())==(expectedPermission^injectPermission),
      "independent captured prefetch permission mismatch");
    physicalAt[id]=s.cycles;s.physicalLatency+=s.cycles-acceptedAt[id];memory.push_back({id,s.cycles+opt.memoryLatency});++s.physical;hash(0x300000+id);hash(s.cycles);
   }
   if(rv&&vr){
    check(!owners.empty(),"unowned virtual response");unsigned id=owners.front();owners.pop_front();const auto&r=rs[id];const bool f=fault(r,opt.pmpCfg,opt.pmpAddress);
    check(std::get<0>(rb)==((f?0:value(r))^(injectData?1ULL:0ULL))&&std::get<1>(rb)==(f||r.physicalError)&&std::get<2>(rb)==(r.virt&&r.page),"independent response data/fault/order mismatch");
    for(uint64_t x:{uint64_t(id),uint64_t(std::get<0>(rb)),uint64_t(std::get<1>(rb)),uint64_t(std::get<2>(rb))})semanticHash(s.responseTrace,x);
    s.faults+=std::get<1>(rb);s.responseLatency+=s.cycles-acceptedAt[id];++s.returned;s.cancelled+=r.cancelled;hash(0x400000+id);hash(s.cycles);
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
static void report(const char*name,const Stats&s){
 std::cout<<"PHYSICAL_INGRESS_CASE name="<<name<<" cycles="<<s.cycles<<" accepted="<<s.accepted
 <<" returned="<<s.returned<<" physical="<<s.physical<<" translations="<<s.translations
 <<" physical_latency="<<s.physicalLatency<<" response_latency="<<s.responseLatency<<" trace="<<s.trace
 <<" physical_trace="<<s.physicalTrace<<" response_trace="<<s.responseTrace<<" cancelled="<<s.cancelled
 <<" stalls="<<s.upstreamStalls<<" physical_holds="<<s.physicalHolds<<" response_holds="<<s.responseHolds
 <<" min_latency="<<(s.physical?s.minPhysicalLatency:0)<<" max_latency="<<s.maxPhysicalLatency
 <<" physical_span="<<(s.physical?s.lastPhysical-s.firstPhysical:0)<<" shortcuts="<<s.shortcuts
 <<" eligible_spills="<<s.eligibleSpills<<" checked_full_pops="<<s.checkedFullPops
 <<" checked_turnovers="<<s.checkedTurnovers<<" full_pop_then_push="<<s.fullPopThenPush
 <<" older_translated_ingress="<<s.olderTranslatedIngress<<" walker_blocked_ingress="<<s.walkerBlockedIngress
 <<" permission_allowed="<<s.permissionAllowed<<" permission_denied="<<s.permissionDenied<<" faults="<<s.faults<<"\n";
}
int main(int argc,char**argv){try{
 const std::string arg=argc>1?argv[1]:"";injectData=arg=="--inject-data";injectContext=arg=="--inject-context";injectPermission=arg=="--inject-prefetch";injectOrder=arg=="--inject-order";
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
 // Additional ingress-only cases. The old sixteen identity/context cases above remain independently exercised.
 {std::vector<Request> v;for(unsigned n=0;n<48;++n){auto r=request(n);r.size=n%4;r.address+=(n%8)&~((1U<<r.size)-1);r.mask=((1U<<(1U<<r.size))-1)<<(r.address&7);v.push_back(r);}
  Test t;const auto s=t.run(v);check(s.physical==48&&s.lastPhysical-s.firstPhysical==47,"physical stream did not sustain II=1");report("physical_shapes_stream48",s);}
 {std::vector<Request> v;for(unsigned n=0;n<48;++n)v.push_back(request(n));Test t;auto s=t.run(v,slow);
  check(s.upstreamStalls&&s.physicalHolds&&s.responseHolds&&s.checkedFullPops&&s.checkedTurnovers&&s.fullPopThenPush,"checked spill/full-pop/turnover coverage missing");
  if(PHYSICAL_INGRESS_FLOW)check(s.eligibleSpills,"empty-ingress checked-full spill not exercised");report("checked_spill_full_turnover",s);}
 {std::vector<Request> v;for(unsigned n=0;n<24;++n){auto r=request(n,n==0,0);v.push_back(r);}Test t;Options o;o.blockPhysical=35;
  auto s=t.run(v,o);check(s.olderTranslatedIngress,"older translated priority was not exercised");report("older_translated_priority",s);}
 {std::vector<Request> v;v.push_back(request(0,true,12));for(unsigned n=1;n<16;++n)v.push_back(request(n));Test t;
  auto s=t.run(v);check(s.walkerBlockedIngress,"pending external translation priority was not exercised");report("older_walker_priority",s);}
 for(unsigned kind=0;kind<12;++kind){auto r=request(20);const char*name="";
  switch(kind){
   case 0:r.address=0x10000000;name="fallback_mmio";break;
   case 1:r.uncached=true;name="fallback_uncached";break;
   case 2:r.write=true;name="fallback_store";break;
   case 3:r.atomic=true;r.atomicOp=2;name="fallback_atomic_lr";break;
   case 4:r.atomic=true;r.atomicOp=3;r.write=true;name="fallback_atomic_sc";break;
   case 5:r.atomic=true;r.atomicOp=0;name="fallback_atomic_amo";break;
   case 6:r.address=ram+1;name="fallback_misaligned";break;
   case 7:r.address=ram-8;name="fallback_outside_low";break;
   case 8:r.address=ram+ramBytes;name="fallback_outside_high";break;
   case 9:r.address=ram+ramBytes-4;name="fallback_partial_range";break;
   case 10:r.address=UINT64_MAX-3;name="fallback_wrap";break;
   case 11:r.prechecked=true;name="fallback_prechecked";break;
  }
  Test t;const auto s=t.run({r});check(s.shortcuts==0,"excluded request used ingress shortcut");
  if(!r.prechecked)check(s.minPhysicalLatency==2,"fallback path latency was shortened");report(name,s);
 }
 {auto r=request(22);r.physicalError=true;Test t;report("physical_response_error",t.run({r}));}
 {auto r=request(23,true,0);r.page=true;Test t;auto s=t.run({r});check(s.physical==0&&s.faults==1,"page fault escaped physically");report("virtual_page_fault",s);}
 {auto r=request(24);r.address=ram+56;r.privilege=1;Options o;o.pmpCfg=9;o.pmpAddress=(ram+64)>>2;
  check(pmpAllowed(r.address,r.size,r.privilege,o.pmpCfg,o.pmpAddress,1),"TOR current access setup must be allowed");
  Test t;auto s=t.run({r},o);check(s.permissionDenied==1,"TOR next-line denial was not exercised");report("pmp_current_allowed_next_denied_s",s);}
 {auto r=request(25);r.privilege=1;Options o;o.blockPhysical=20;o.pmpSwitch=1;Test t;
  auto s=t.run({r},o);check(s.permissionAllowed==1&&s.physicalHolds,"held allowed prefetch snapshot missing");report("physical_prefetch_allow_snapshot",s);}
 {auto r=request(26);r.address=ram+56;r.privilege=1;Options o;o.pmpCfg=9;o.pmpAddress=(ram+64)>>2;o.pmpSwitch=3;o.blockPhysical=20;Test t;
  auto s=t.run({r},o);check(s.permissionDenied==1&&s.physicalHolds,"held denied prefetch snapshot missing");report("physical_prefetch_deny_snapshot",s);}
 for(unsigned kind=0;kind<2;++kind){auto r=request(27);r.address=kind?ram+ramBytes-8:ram+4096-8;Test t;
  auto s=t.run({r});check(s.permissionDenied==1,"last page/RAM line incorrectly authorized prefetch");report(kind?"ram_last_line_no_prefetch":"page_last_line_no_prefetch",s);}
 {auto r=request(28,true,0);r.pbmt=1;Test t;auto s=t.run({r});check(s.permissionDenied==1,"PBMT prefetch restriction missing");report("virtual_pbmt_no_prefetch",s);}
 std::cout<<"PHYSICAL_INGRESS_FLOW_PASS flag="<<PHYSICAL_INGRESS_FLOW<<" accepted_tokens_drained=1 vm_pmp_context=1 prefetch_enabled=1 external_dtlb_model_not_real_walker=1\n";return 0;
}catch(const std::exception&e){std::cerr<<"PHYSICAL_INGRESS_FLOW_FAIL "<<e.what()<<"\n";return 1;}}
