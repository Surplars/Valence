#include "BoundHeadStoreOverlapGsim.h"
#include "pending_store_proof_reference.h"
#include <cstring>
#include <deque>
#include <iostream>
#include <optional>
#include <set>
#include <tuple>
#include <type_traits>
#ifndef BOUND_HEAD_STORE_OVERLAP
#define BOUND_HEAD_STORE_OVERLAP 0
#endif
using namespace pending_store_reference;
struct Op {
    Token token{0,0}; uint64_t va=::pending_store_reference::va,pa=ram,data=0x123456789abcdef0ULL;
    uint32_t epoch=0xf1234567;unsigned size=3;
    bool store=false,prechecked=true,virtualized=true,parallel=true,atomic=false,forward=false,denied=false;
    bool frozen=false,canonical=false;
};
struct State {Op op;uint64_t start=0,request=0,response=0,complete=0,release=0;bool cancelled=false;};
struct Reply {Token token;uint64_t due,data;bool error=false;};
struct Snapshot {bool ready=false,available=false,accepted=false,complete=false;unsigned live=0,phases=0,chosen=0,compatible=0;};
struct Bench {
    SBoundHeadStoreOverlapGsim dut;
    uint64_t cycle=1;unsigned requests=0,responses=0,completions=0,corruptions=0;
    bool memoryReady=true,completionReady=false,allowResponse=false,qualified=true;
    unsigned cancel=0;uint64_t latency=3;
    bool mutateOwner=false,mutateSlot=false,mutatePa=false,mutateDrop=false;
    std::optional<Token> relax;
    Bytes actual,expected;
    std::map<Token,State> states;std::deque<Reply> replies;std::set<Token> previousOwners;
    using Payload=std::tuple<Token,uint64_t,uint64_t,unsigned,unsigned,bool,uint32_t,bool,uint64_t>;
    std::optional<Payload> held;
    Bench(){std::memset(&dut,0,sizeof(dut));dut.LOG_START=1;dut.activateAll();tick({},false,true);tick({},false,true);tick();tick();}
    void check(bool ok,const std::string&why){require(ok,"cycle="+std::to_string(cycle)+" "+why);}
    void drive(const Op&o,bool valid){
        dut.set_io$$start$$valid(valid);dut.set_io$$parallel(o.parallel);dut.set_io$$qualified(qualified);
        dut.set_io$$start$$bits$$token$$index(o.token.index);dut.set_io$$start$$bits$$token$$tag(o.token.tag);
        dut.set_io$$start$$bits$$pc(0x1000+o.token.index*4);dut.set_io$$start$$bits$$address(o.va);
        dut.set_io$$start$$bits$$physicalAddress(o.pa);dut.set_io$$start$$bits$$data(o.data);
        dut.set_io$$start$$bits$$store(o.store);dut.set_io$$start$$bits$$size(o.size);
        dut.set_io$$start$$bits$$unsigned(true);dut.set_io$$start$$bits$$atomic(o.atomic);dut.set_io$$start$$bits$$atomicOp(0);
        dut.set_io$$start$$bits$$forward$$valid(o.forward);dut.set_io$$start$$bits$$forward$$bits(0xdecafbad);
        dut.set_io$$start$$bits$$accessDenied(o.denied);dut.set_io$$start$$bits$$virtualized(o.virtualized);
        dut.set_io$$start$$bits$$precheckedLoad(o.prechecked);dut.set_io$$start$$bits$$translationEpoch(o.epoch);
        dut.set_io$$start$$bits$$canonicalStoreEpoch$$valid(o.canonical);dut.set_io$$start$$bits$$canonicalStoreEpoch$$bits(o.epoch);
        dut.set_io$$start$$bits$$frozenStoreProof$$valid(o.frozen);
        dut.set_io$$start$$bits$$frozenStoreProof$$bits$$address(o.va);
        dut.set_io$$start$$bits$$frozenStoreProof$$bits$$physicalAddress(o.pa);
        dut.set_io$$start$$bits$$frozenStoreProof$$bits$$size(o.size);
        dut.set_io$$start$$bits$$frozenStoreProof$$bits$$mask(lanes(o.pa,o.size));
    }
    Snapshot tick(Op op={},bool valid=false,bool reset=false){
        drive(op,valid);dut.set_reset(reset);dut.set_io$$cancel(cancel);
        dut.set_io$$relax$$valid(relax.has_value());dut.set_io$$relax$$bits$$index(relax?relax->index:0);
        dut.set_io$$relax$$bits$$tag(relax?relax->tag:0);
        dut.set_io$$memory$$request$$ready(memoryReady);dut.set_io$$complete$$ready(completionReady);
        const bool response=allowResponse&&!replies.empty()&&replies.front().due<=cycle;
        dut.set_io$$memory$$response$$valid(response);dut.set_io$$memory$$response$$bits$$data(response?replies.front().data:0);
        dut.set_io$$memory$$response$$bits$$error(response&&replies.front().error);dut.set_io$$memory$$response$$bits$$pageFault(false);
        dut.step();Snapshot s{bool(dut.get_io$$start$$ready()),bool(dut.get_io$$available()),bool(dut.get_io$$accepted()),
            bool(dut.get_io$$complete$$valid()),unsigned(dut.get_io$$live()),unsigned(dut.get_io$$phase()),
            unsigned(dut.get_io$$chosen()),unsigned(dut.get_io$$compatible())};
        if(reset){dut.resetAll();++cycle;return s;}
        if(valid&&s.ready){
            check(!states.count(op.token),"duplicate full-token start");states.emplace(op.token,State{op,cycle});
            if(op.store)expected.write(op.pa,op.data,op.size);
            if(s.accepted){unsigned observed=s.chosen;if(mutateSlot){observed=0;++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
                check(BOUND_HEAD_STORE_OVERLAP&&!op.parallel&&op.store&&!(s.live&(1u<<observed)),"accepted overlap selected a completing or busy slot");}
        }
        std::set<Token> owners;
#define OWNER(N) if(s.live&(1u<<N)){Token t{unsigned(dut.get_io$$owner##N##$$index()),uint64_t(dut.get_io$$owner##N##$$tag())}; \
            check(states.count(t),"live slot changed full owner token");owners.insert(t);if(cancel&(1u<<N))states.at(t).cancelled=true;}
        OWNER(0);OWNER(1);OWNER(2);OWNER(3);
#undef OWNER
        for(auto t:previousOwners)if(!owners.count(t)){auto&e=states.at(t);e.release=cycle;
            check(e.response||!e.request,"live owner released before accepted response drain");}
        previousOwners=owners;
        if(response&&dut.get_io$$memory$$response$$ready()){
            const auto r=replies.front();replies.pop_front();auto&e=states.at(r.token);e.response=cycle;++responses;
            if(e.op.store&&!r.error)actual.write(e.op.pa,e.op.data,e.op.size);
        }
        const bool request=dut.get_io$$memory$$request$$valid();
        if(request){
            check(dut.get_io$$requestOwner$$valid(),"request lacks full owner");
            Token t{unsigned(dut.get_io$$requestOwner$$bits$$index()),uint64_t(dut.get_io$$requestOwner$$bits$$tag())};
            if(mutateOwner){t.tag^=1ULL<<48;++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
            check(states.count(t),"request owner full-tag corruption");auto&e=states.at(t);const auto&o=e.op;
            uint64_t proofPa=dut.get_io$$frozen$$bits$$physicalAddress();if(mutatePa&&o.frozen){proofPa^=1ULL<<32;++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
            Payload payload{t,uint64_t(dut.get_io$$memory$$request$$bits$$address()),uint64_t(dut.get_io$$memory$$request$$bits$$data()),
                unsigned(dut.get_io$$memory$$request$$bits$$size()),unsigned(dut.get_io$$memory$$request$$bits$$mask()),
                bool(dut.get_io$$memory$$request$$bits$$write()),uint32_t(dut.get_io$$memory$$request$$bits$$translationEpoch()),
                bool(dut.get_io$$frozen$$valid()),proofPa};
            if(held)check(*held==payload,"held request/origin/frozen payload changed");held=memoryReady?std::nullopt:std::optional{payload};
            check(std::get<1>(payload)==(o.prechecked?o.pa:o.va)&&std::get<3>(payload)==o.size&&
                std::get<4>(payload)==lanes(o.va,o.size)&&std::get<5>(payload)==o.store,"request differs from independent byte/class oracle");
            if(o.frozen)check(std::get<7>(payload)&&proofPa==o.pa&&dut.get_io$$origin$$valid()&&
                dut.get_io$$origin$$bits$$token$$index()==t.index&&dut.get_io$$origin$$bits$$token$$tag()==t.tag&&
                dut.get_io$$origin$$bits$$epoch()==o.epoch,"frozen PA/full-token origin corruption");
            if(memoryReady){check(!e.request,"duplicate accepted request");e.request=cycle;++requests;
                replies.push_back({t,cycle+latency,o.store?0:actual.read(o.pa&~7ULL,3),false});}
        }else check(!held,"held request withdrawn");
        if(s.complete&&completionReady){Token t{unsigned(dut.get_io$$complete$$bits$$token$$index()),uint64_t(dut.get_io$$complete$$bits$$token$$tag())};
            check(states.count(t),"completion changed full owner token");auto&e=states.at(t);
            check(!e.complete&&!e.cancelled,"duplicate or cancelled completion");
            const uint64_t value=e.op.store?0:(e.op.forward?0xdecafbad:expected.read(e.op.pa,e.op.size));
            check(bool(dut.get_io$$complete$$bits$$exception())==e.op.denied&&(e.op.denied||dut.get_io$$complete$$bits$$data()==value),"completion lost byte data or fault state");
            check(e.response||e.op.forward||e.op.denied,"local completion preceded actual ACK");e.complete=cycle;++completions;}
        ++cycle;return s;
    }
    void start(Op op){auto s=tick(op,true);check(s.ready,"fixture start was not admitted");}
    void drain(){memoryReady=completionReady=allowResponse=true;cancel=0;
        for(unsigned n=0;n<128;++n){auto s=tick();if(!s.live&&replies.empty()&&!held)break;}
        auto s=tick();check(!s.live&&replies.empty()&&requests==responses,"final request/response/owner drain mismatch");
        for(auto [address,byte]:expected.changed)check(actual.changed[address]==byte,"final byte memory mismatch");}
};
static Op load(unsigned index=0,uint64_t pa=ram+4096,unsigned size=3){Op o;o.token={index,0xfedcba9876543210ULL+index};o.pa=pa;o.va=va+4096+(pa&4095);o.size=size;return o;}
static Op store(unsigned index=15,uint64_t pa=ram,unsigned size=3){Op o;o.token={index,0x8edcba9876543200ULL+index};o.va=va+(pa&4095);o.pa=pa;o.size=size;o.store=o.frozen=o.canonical=true;o.prechecked=o.parallel=false;return o;}
int main(int argc,char**argv){try{
    std::cout.setf(std::ios::unitbuf);const std::string mode=argc>1?argv[1]:"";
    // The same complete byte/token oracle checks both models. Responses are kept
    // ordered and finite; holding completion tests real idle-vs-done selection.
    for(unsigned phase=1;phase<=3;++phase){Bench b;b.memoryReady=phase!=1;b.start(load());
        if(phase==3){b.allowResponse=true;for(unsigned n=0;n<8&&!b.dut.get_io$$complete$$valid();++n)b.tick();b.allowResponse=false;}
        auto before=b.tick(store());require((before.phases&3)==phase,"requested saved-load phase absent");
        b.mutateOwner=mode=="--mutate-owner";b.mutateSlot=mode=="--mutate-slot";b.mutatePa=mode=="--mutate-pa";
        if(BOUND_HEAD_STORE_OVERLAP){if(mode=="--assert-same-edge-cancel")b.cancel=1;auto s=b.tick(store(),true);require(s.ready&&s.accepted,"NEW failed legal disjoint overlap");
            require(s.chosen==1,"NEW replaced completing load instead of choosing idle slot");
            b.tick();require((b.dut.get_io$$live()&3)==3,"overlap failed to retain both actual owners");}
        else {require(!before.accepted&&(phase==3||!before.ready),"OLD incorrectly used new overlap route");
            b.drain();b.start(store());}
        b.drain();std::cout<<"BOUND_OVERLAP_SLOTS_CASE phase="<<phase<<" requests="<<b.requests<<" responses="<<b.responses<<'\n';}
    // Two/three legal saved owners are component capacity vectors, not extra
    // pending-store early-load credits in the integrated backend.
    for(unsigned count=1;count<=4;++count){Bench b;for(unsigned i=0;i<count;++i)b.start(load(i,ram+4096+8*i));
        auto s=b.tick(store());const bool expected=BOUND_HEAD_STORE_OVERLAP&&count<4;
        require(s.accepted==false&&s.ready==expected,"idle capacity/conjunction qualification mismatch");
        if(expected)b.start(store());b.drain();std::cout<<"BOUND_OVERLAP_SLOTS_CASE coowners="<<count<<'\n';}
    {Bench b;for(unsigned i=0;i<4;++i)b.start(load(i,ram+4096+8*i));
      b.allowResponse=true;b.tick();b.allowResponse=false;
      for(unsigned n=0;n<4&&!(b.dut.get_io$$phase()&3);++n)b.tick();
      const auto s=b.tick(store());require(s.live==15&&!s.ready&&!s.accepted,"full capacity anticipated a completing slot as idle");
      require((s.phases&3)==3,"full-capacity fixture lacked completing owner");b.drain();
      std::cout<<"BOUND_OVERLAP_SLOTS_CASE full_capacity_with_done\n";}
    {Bench b;b.start(load(0));Op bad=load(1,ram+4104);bad.epoch^=1;b.start(bad);b.start(load(2,ram+4112));
      const auto s=b.tick(store());require(s.live==7&&!s.ready&&!s.accepted,"one incompatible co-owner was omitted from conjunction");b.drain();
      std::cout<<"BOUND_OVERLAP_SLOTS_CASE mixed_valid_invalid_coowners\n";}
    for(unsigned which=0;which<13;++which){Bench b;Op l=load();Op st=store();bool expected=false;
        if(which==0){l.pa=ram;l.va=va+8192;} // distinct VA, identical physical interval
        if(which==1){l.pa=ram+2;l.va=va+2;l.size=1;st=store(15,ram,2);} // one overlapping halfword
        if(which==2){l.pa=ram+4;l.va=va+4;l.size=2;st=store(15,ram,2);expected=true;}
        if(which==3){l.pa=ram+1;l.va=va+1;l.size=0;st=store(15,ram,0);expected=true;}
        if(which==4){l.epoch^=1;}
        if(which==5){l.prechecked=false;}
        if(which==6){l.parallel=false;}
        if(which==7){l.token.index=st.token.index;l.token.tag^=1ULL<<48;} // same index cannot be a younger current owner
        if(which==8){expected=true;st=store(15,ram+8,3);}
        if(which==9){l.prechecked=false;l.forward=true;}
        if(which==10){l.prechecked=false;l.atomic=true;}
        if(which==11){l.prechecked=false;l.virtualized=false;l.va=l.pa;}
        if(which==12){l.prechecked=false;l.denied=true;} // same cache line, different beats
        b.start(l);auto s=b.tick(st);require(s.ready==(BOUND_HEAD_STORE_OVERLAP&&expected),"independent PA-byte/epoch/class/index rejection mismatch");
        if(BOUND_HEAD_STORE_OVERLAP&&expected)b.start(st);b.drain();std::cout<<"BOUND_OVERLAP_SLOTS_CASE interval_class="<<which<<'\n';}
    {Bench b;b.start(load());b.cancel=1;b.tick();b.cancel=0;auto s=b.tick(store());
      require(!s.ready&&!s.accepted,"registered cancelled owner authorized overlap");b.drain();
      Op again=load(0);again.token.tag^=1ULL<<52;b.start(again);auto reuse=b.tick(store());require(reuse.ready==bool(BOUND_HEAD_STORE_OVERLAP),"drained index reallocation lost legal qualification");
      b.drain();std::cout<<"BOUND_OVERLAP_SLOTS_CASE registered_cancel_drain_reuse\n";}
    {Bench b;b.memoryReady=false;b.start(load());b.cancel=1;b.tick();b.cancel=0;
      require(!b.tick(store()).ready&&b.held.has_value(),"held cancelled request lost owner or authorized store");
      b.drain();std::cout<<"BOUND_OVERLAP_SLOTS_CASE held_cancel_must_drain\n";}
    {Bench b;b.start(load());b.qualified=false;require(!b.tick(store()).ready,"absent exact-bound-head authority admitted overlap");b.drain();}
    // Existing actual-checked exemption is a separate unchanged authority. An
    // origin/preproof alone grants no exemption; a wrong full tag grants none.
    {Bench b;b.start(store());Op l=load();require(!b.tick(l).ready,"frozen preproof granted unchecked canonical exemption");
      b.relax=Token{15,store().token.tag^(1ULL<<48)};require(!b.tick(l).ready,"truncated canonical owner tag authorized younger load");
      b.relax=store().token;require(b.tick(l).ready,"existing exact checked-owner exemption was disabled");b.start(l);b.relax.reset();b.drain();
      std::cout<<"BOUND_OVERLAP_SLOTS_CASE unchanged_exact_checked_exemption\n";}
    std::cout<<"BOUND_OVERLAP_SLOTS_PASS coowner="<<BOUND_HEAD_STORE_OVERLAP<<'\n';return 0;
}catch(const std::exception&e){std::cerr<<"BOUND_OVERLAP_SLOTS_FAIL "<<e.what()<<'\n';return 1;}}
