#include "BoundedEarlyLoadCreditGsim.h"
#include "pending_store_proof_reference.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <iostream>
#include <optional>
#include <set>
#include <type_traits>
#ifndef EARLY_LOAD_CREDITS
#define EARLY_LOAD_CREDITS 1
#endif
using namespace pending_store_reference;
struct Input {
    std::optional<Token> reserve, consume, cancel;
    std::array<std::optional<Token>,4> live{};
};
// Reference is an obligation set, not a copy of the RTL slot/state implementation.
// A reservation is a promise even with no accepted owner. Only accepted obligations
// follow full-token physical-owner disappearance, observed strictly before this edge.
struct Oracle {
    std::set<Token> reserved, accepted;
    void advance(const Input &in) {
        const auto beforeReserved=reserved, beforeAccepted=accepted;
        std::set<Token> live;
        for(auto t:in.live)if(t)require(live.insert(*t).second,"oracle duplicate physical owner");
        if(in.reserve) {
            require(beforeReserved.size()+beforeAccepted.size()<EARLY_LOAD_CREDITS,"oracle no pre-edge free credit");
            require(!beforeReserved.count(*in.reserve)&&!beforeAccepted.count(*in.reserve),"oracle duplicate reserve");
        }
        if(in.consume)require(beforeReserved.count(*in.consume)||(in.reserve&&*in.reserve==*in.consume),"oracle wrong consume");
        if(in.cancel)require(!in.consume&&beforeReserved.count(*in.cancel),"oracle wrong cancellation");
        for(auto t:beforeAccepted)if(!live.count(t))accepted.erase(t);
        if(in.reserve)reserved.insert(*in.reserve);
        if(in.consume){reserved.erase(*in.consume);accepted.insert(*in.consume);}
        if(in.cancel)reserved.erase(*in.cancel);
        require(reserved.size()+accepted.size()<=EARLY_LOAD_CREDITS,"oracle capacity overflow");
    }
};
struct Bench {
    SBoundedEarlyLoadCreditGsim dut;
    Oracle oracle;
    unsigned cycle=0,checks=0,peak=0,corruptions=0;
    bool mutateTag=false,mutateFree=false;
    Bench(){static_assert(std::is_trivially_copyable_v<SBoundedEarlyLoadCreditGsim>);std::memset(&dut,0,sizeof(dut));dut.LOG_START=1;dut.activateAll();tick({},true);tick({},true);tick();}
    void tick(const Input &in={},bool reset=false) {
        dut.set_reset(reset);
#define TOKEN(PORT,OPT) \
        dut.set_io$$##PORT##$$valid((OPT).has_value()); \
        dut.set_io$$##PORT##$$bits$$index((OPT)?(OPT)->index:15); \
        dut.set_io$$##PORT##$$bits$$tag((OPT)?(OPT)->tag:UINT64_MAX)
        TOKEN(reserve,in.reserve);TOKEN(consume,in.consume);TOKEN(cancel,in.cancel);
        TOKEN(live0,in.live[0]);TOKEN(live1,in.live[1]);TOKEN(live2,in.live[2]);TOKEN(live3,in.live[3]);
#undef TOKEN
        dut.step();++cycle;
        if(reset){dut.resetAll();oracle={};return;}
        std::set<Token> reserved,accepted;
        const unsigned r=dut.get_io$$reserved(),a=dut.get_io$$active();
        require(!(r&a)&&!(unsigned(r|a)>>EARLY_LOAD_CREDITS),"nonexclusive or excess credit slot state");
        for(unsigned n=0;n<EARLY_LOAD_CREDITS;++n)if((r|a)&(1u<<n)){
            // Invalid and nonexistent slot payloads are deliberately never read.
            Token t=n==0?Token{unsigned(dut.get_io$$owner0$$index()),uint64_t(dut.get_io$$owner0$$tag())}:
                Token{unsigned(dut.get_io$$owner1$$index()),uint64_t(dut.get_io$$owner1$$tag())};
            if(mutateTag){t.tag^=1ULL<<63;++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
            auto &set=(r&(1u<<n))?reserved:accepted;
            require(set.insert(t).second,"duplicate same-phase full-token owner");
        }
        bool available=dut.get_io$$available();
        if(mutateFree&&!accepted.empty()){available=true;++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
        require(reserved==oracle.reserved&&accepted==oracle.accepted,"independent full-token obligation mismatch");
        for(auto t:reserved)require(!accepted.count(t),"same token reserved and active");
        require(available==(oracle.reserved.size()+oracle.accepted.size()<EARLY_LOAD_CREDITS),"pre-edge free capacity mismatch");
        peak=std::max(peak,unsigned(reserved.size()+accepted.size()));++checks;
        oracle.advance(in);
    }
    void hold(const Input&in,unsigned n=4){while(n--)tick(in);}
};
static void negative(const std::string &mode) {
    Bench b;const Token a{3,0x8000000000000101ULL},btoken{3,0x0000000000000101ULL},c{7,0xe000000000000701ULL};
    Input in;in.reserve=a;b.tick(in);in={};
    if(mode=="--wrong-consume")in.consume=btoken;
    else if(mode=="--wrong-cancel")in.cancel=btoken;
    else if(mode=="--duplicate-reserve")in.reserve=a;
    else if(mode=="--consume-and-cancel"){in.consume=a;in.cancel=a;}
    else if(mode=="--duplicate-consume"){
        in.consume=a;in.live[0]=a;b.tick(in);in.consume=a;
    }else if(mode=="--duplicate-live"){
        in.consume=a;in.live[0]=a;b.tick(in);in.consume.reset();in.live[1]=a;
    }else if(mode=="--turnover-reserve"){
        in.consume=a;in.live[0]=a;b.tick(in);in.consume.reset();
#if EARLY_LOAD_CREDITS == 2
        in.reserve=btoken;in.consume=btoken;in.live[1]=btoken;b.tick(in);
#endif
        in={};in.reserve=c; // All active owners disappear on this edge: still no pre-edge free entry.
    }else if(mode=="--capacity-overflow"){
#if EARLY_LOAD_CREDITS == 2
        in.reserve=btoken;b.tick(in);
#endif
        in={};in.reserve=c;
    }else throw std::runtime_error("unknown negative mode");
    std::cerr<<"ACTUAL_CORRUPTION count=1 event="<<mode<<'\n';
    // Invalid IO is delivered to hardware before reference validation. A runner must
    // require the hardware assertion text, not accept this host's fallback failure.
    b.tick(in);throw std::runtime_error("DUT failed to reject invalid event");
}
int main(int argc,char**argv){try{
    const std::string mode=argc>1?argv[1]:"";
    if(!mode.empty()&&mode!="--mutate-tag"&&mode!="--mutate-free"){negative(mode);return 2;}
    const Token a{3,0x8000000000000101ULL},b{3,0x0000000000000101ULL},c{15,0xfedcba9876543210ULL},d{0,0x123456789abcdef0ULL};
    unsigned checks=0;
    {Bench x;Input in;in.reserve=a;x.tick(in);in={};x.hold(in,7);
      x.mutateTag=mode=="--mutate-tag";x.tick(in);x.mutateTag=false;
      in.cancel=a;x.tick(in);x.tick();
      in={};in.reserve=a;in.consume=a;in.live[0]=a;x.tick(in);in.reserve.reset();in.consume.reset();x.hold(in);
      // A high-generation alias with identical low index cannot retain the old owner.
      in.live[0]=b;x.tick(in);x.tick(in);in.reserve=b;x.tick(in);in.reserve.reset();x.hold(in,3);
      in.consume=b;x.tick(in);in.consume.reset();x.hold(in);in={};x.tick(in);x.tick();
      checks+=x.checks;std::cout<<"EARLY_CREDIT_CASE held_exact_cancel_same_index_generation_reuse\n";}
    {Bench x;Input in;in.reserve=a;in.consume=a;in.live[0]=a;x.tick(in);in.reserve.reset();in.consume.reset();
#if EARLY_LOAD_CREDITS == 2
      in.reserve=b;x.tick(in);in.reserve.reset();x.hold(in,5); // Active + reserved fills capacity two.
      in.cancel=b;x.tick(in);in.cancel.reset();x.tick(in);
      in.reserve=b;in.consume=b;in.live[1]=b;x.tick(in);in.reserve.reset();in.consume.reset();x.hold(in);
#endif
      x.mutateFree=mode=="--mutate-free";x.tick(in);x.mutateFree=false;
      // Physical slot replacement changes its full token. Neither the completion
      // nor cancel event itself frees a credit; only the next observed owner set does.
      in.live[0]=c;x.tick(in);x.tick(in);
      in.reserve=d;in.consume=d;in.live[2]=d;x.tick(in);in.reserve.reset();in.consume.reset();x.hold(in);
      in={};x.tick(in);x.tick();checks+=x.checks;
      require(x.peak==EARLY_LOAD_CREDITS,"capacity witness did not fill configured credits");
      std::cout<<"EARLY_CREDIT_CASE active_reserved_capacity_slot_replacement peak="<<x.peak<<'\n';}
#if EARLY_LOAD_CREDITS == 2
    {Bench x;Input in;in.reserve=a;in.consume=a;in.live[0]=a;x.tick(in);
      in.reserve=b;in.consume=b;in.live[1]=b;x.tick(in);in.reserve.reset();in.consume.reset();
      in.live[1].reset();x.tick(in);x.tick(in); // Reverse completion: B disappears while A survives.
      in.reserve=c;in.consume=c;in.live[1]=c;x.tick(in);in.reserve.reset();in.consume.reset();x.hold(in);
      in.live[0].reset();x.tick(in);x.tick(in);in.reserve=d;x.tick(in);in.reserve.reset();x.hold(in);
      in.cancel=d;in.live[1].reset();x.tick(in);x.tick();checks+=x.checks;
      std::cout<<"EARLY_CREDIT_CASE reverse_completion_order_exact_survivor\n";}
    {Bench x;Input in;in.reserve=a;in.consume=a;in.live[0]=a;x.tick(in);
      in.reserve=b;in.consume=b;in.live[1]=b;x.tick(in);in={};x.tick(in); // Both old owners disappear together.
      in.reserve=c;x.tick(in);in={};x.tick(in); // Only one scalar new reservation after free becomes visible.
      in.consume=c;in.live[0]=c;x.tick(in);in={};in.reserve=d; // One old drain + a distinct pre-edge-free reserve.
      x.tick(in);in={};x.hold(in,4);in.cancel=d;x.tick(in);x.tick();checks+=x.checks;
      std::cout<<"EARLY_CREDIT_CASE simultaneous_two_drains_conservative_free_boundary\n";}
#endif
    std::cout<<"EARLY_CREDIT_PASS capacity="<<EARLY_LOAD_CREDITS<<" checks="<<checks<<'\n';return 0;
}catch(const std::exception&e){std::cerr<<"EARLY_CREDIT_FAIL "<<e.what()<<'\n';return 1;}}
